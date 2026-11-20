"""Synthetic telematics for a European truck fleet.

What a real fleet's systems would give you, and nothing more:

* GPS pings from each truck: every 10 minutes while driving, hourly while parked, with
  position noise, the odd lost ping and the odd duplicate.
* Cargo events from the transport management system: one ``load`` when a shipment is on
  board, one ``unload`` when it is delivered.

Nothing in that data says "this trip was empty". That has to be derived (see the dbt
project). What the simulator actually drove is written separately as ground truth, so the
detection can be checked against it.

The operating model is deliberately simple and stated here so it can be argued with:

* Full truckloads: a truck carries one shipment at a time.
* Driving happens Monday to Friday, 05:00-19:00, at most 9 hours a day (in the spirit of the
  EU driving-time rules, not an implementation of them). Times are UTC.
* After delivering, the next shipment is usually picked up in the same city (a short empty
  run across town) and otherwise in a nearby city, so the truck repositions empty.
* About every two to three weeks a truck goes back to its home depot and loads there.
* Roads are not straight: each route bends through two offset waypoints.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from empty_trips.geo import Point, haversine_km, interpolate, offset_km, polyline_km

CITIES: dict[str, Point] = {
    "Rotterdam": (51.92, 4.48),
    "Antwerp": (51.22, 4.40),
    "Brussels": (50.85, 4.35),
    "Lille": (50.63, 3.06),
    "Paris": (48.86, 2.35),
    "Lyon": (45.76, 4.84),
    "Barcelona": (41.39, 2.17),
    "Madrid": (40.42, -3.70),
    "Duisburg": (51.43, 6.76),
    "Cologne": (50.94, 6.96),
    "Frankfurt": (50.11, 8.68),
    "Stuttgart": (48.78, 9.18),
    "Munich": (48.14, 11.58),
    "Hamburg": (53.55, 9.99),
    "Berlin": (52.52, 13.40),
    "Leipzig": (51.34, 12.37),
    "Zurich": (47.38, 8.54),
    "Milan": (45.46, 9.19),
    "Turin": (45.07, 7.69),
    "Verona": (45.44, 10.99),
    "Ljubljana": (46.06, 14.51),
    "Vienna": (48.21, 16.37),
    "Prague": (50.08, 14.44),
    "Poznan": (52.41, 16.93),
    "Warsaw": (52.23, 21.01),
    "Budapest": (47.50, 19.04),
    "Bucharest": (44.43, 26.10),
    "Sofia": (42.70, 23.32),
}

DEPOTS = ("Duisburg", "Munich", "Poznan", "Verona")

MOVING_PING = timedelta(minutes=10)
PARKED_PING = timedelta(hours=1)
DAY_START_HOUR = 5
DAY_END_HOUR = 19
MAX_DRIVE_PER_DAY = timedelta(hours=9)


@dataclass(frozen=True)
class Params:
    """Knobs of the operating model. Defaults give roughly a fifth of all km run empty."""

    p_same_city_pickup: float = 0.55
    nearby_decay_km: float = 150.0
    loaded_typical_km: float = 700.0
    loaded_spread_km: float = 400.0
    home_return_after_days: tuple[int, int] = (12, 21)
    moving_jitter_m: float = 10.0
    parked_jitter_m: float = 15.0
    p_drop_ping: float = 0.01
    p_duplicate_ping: float = 0.005


@dataclass
class Ping:
    truck_id: str
    recorded_at: datetime
    lat: float
    lon: float


@dataclass
class CargoEvent:
    truck_id: str
    event_type: str  # "load" | "unload"
    occurred_at: datetime
    lat: float
    lon: float
    shipment_id: str


@dataclass
class TruthLeg:
    """What was really driven between two consecutive cargo events of one truck."""

    truck_id: str
    start_at: datetime
    end_at: datetime
    kind: str  # "empty" (after an unload) | "loaded" (after a load)
    km: float


@dataclass
class FleetData:
    trucks: list[tuple[str, str]] = field(default_factory=list)  # (truck_id, home depot)
    pings: list[Ping] = field(default_factory=list)
    events: list[CargoEvent] = field(default_factory=list)
    truth: list[TruthLeg] = field(default_factory=list)


class _Truck:
    def __init__(
        self,
        truck_id: str,
        home: str,
        start: datetime,
        end: datetime,
        rng: random.Random,
        p: Params,
    ):
        self.id, self.home, self.end, self.rng, self.p = truck_id, home, end, rng, p
        self.city = home
        self.pos: Point = offset_km(CITIES[home], rng.uniform(-3, 3), rng.uniform(-3, 3))
        self.t = start + timedelta(hours=rng.uniform(5, 8))
        self.drive_day = self.t.date()
        self.driven_today = timedelta()
        self.last_home = self.t
        self.home_after = timedelta(days=rng.randint(*p.home_return_after_days))
        self.shipments = 0
        self.pings: list[Ping] = []
        self.events: list[CargoEvent] = []
        self.truth: list[TruthLeg] = []
        self._last_event: CargoEvent | None = None
        self._km_since_event = 0.0

    # --- pings -------------------------------------------------------------------------
    def _ping(self, jitter_m: float) -> None:
        if self.rng.random() < self.p.p_drop_ping:
            return
        noisy = offset_km(
            self.pos, self.rng.gauss(0, jitter_m / 1000), self.rng.gauss(0, jitter_m / 1000)
        )
        ping = Ping(self.id, self.t, round(noisy[0], 6), round(noisy[1], 6))
        self.pings.append(ping)
        if self.rng.random() < self.p.p_duplicate_ping:
            self.pings.append(Ping(ping.truck_id, ping.recorded_at, ping.lat, ping.lon))

    def _park_until(self, until: datetime) -> None:
        """Stand still until ``until``, pinging hourly. Leaves ``self.t == until``."""
        while self.t + PARKED_PING < until:
            self.t += PARKED_PING
            self._ping(self.p.parked_jitter_m)
        self.t = until
        self._ping(self.p.parked_jitter_m)

    # --- driving-time rules ------------------------------------------------------------
    def _reset_day(self) -> None:
        if self.t.date() != self.drive_day:
            self.drive_day = self.t.date()
            self.driven_today = timedelta()

    def _drive_window_left(self) -> timedelta:
        self._reset_day()
        if self.t.weekday() >= 5 or not DAY_START_HOUR <= self.t.hour < DAY_END_HOUR:
            return timedelta()
        day_end = self.t.replace(hour=DAY_END_HOUR, minute=0, second=0, microsecond=0)
        return min(day_end - self.t, MAX_DRIVE_PER_DAY - self.driven_today)

    def _next_window_start(self) -> datetime:
        t = self.t
        candidate = t.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
        if candidate <= t:
            candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate

    # --- movement ----------------------------------------------------------------------
    def _route(self, a: Point, b: Point) -> list[Point]:
        d = haversine_km(a, b)
        if d < 1:
            return [a, b]
        # Two waypoints pushed sideways make the road longer than the straight line.
        north = (b[0] - a[0]) * 111.32
        east = (b[1] - a[1]) * 111.32 * math.cos(math.radians(a[0]))
        norm = math.hypot(north, east) or 1.0
        perp_n, perp_e = -east / norm, north / norm
        waypoints = []
        for f in (1 / 3, 2 / 3):
            s = d * self.rng.uniform(-0.25, 0.25)
            waypoints.append(offset_km(interpolate(a, b, f), perp_n * s, perp_e * s))
        return [a, *waypoints, b]

    def _drive(self, dest: Point) -> None:
        route = self._route(self.pos, dest)
        self._km_since_event += polyline_km(route)
        speed_kmh = (
            self.rng.uniform(58, 72) if polyline_km(route) > 30 else self.rng.uniform(25, 40)
        )
        for a, b in itertools.pairwise(route):
            seg_km = haversine_km(a, b)
            done_km = 0.0
            while seg_km - done_km > 1e-9:
                window = self._drive_window_left()
                if window <= timedelta():
                    self._park_until(self._next_window_start())
                    continue
                # Whole seconds: timedelta rounds to microseconds, and a tick that rounds to
                # zero would never finish the segment.
                need = timedelta(seconds=max(1, math.ceil((seg_km - done_km) / speed_kmh * 3600)))
                tick = min(MOVING_PING, window, need)
                done_km = (
                    seg_km
                    if tick == need
                    else min(seg_km, done_km + speed_kmh * tick.total_seconds() / 3600)
                )
                self.t += tick
                self.driven_today += tick
                self.pos = interpolate(a, b, done_km / seg_km)
                self._ping(self.p.moving_jitter_m)
        self.pos = dest

    def _event(self, event_type: str, shipment_id: str) -> None:
        ev = CargoEvent(
            self.id, event_type, self.t, round(self.pos[0], 6), round(self.pos[1], 6), shipment_id
        )
        if self._last_event is not None:
            kind = "empty" if self._last_event.event_type == "unload" else "loaded"
            self.truth.append(
                TruthLeg(
                    self.id,
                    self._last_event.occurred_at,
                    ev.occurred_at,
                    kind,
                    self._km_since_event,
                )
            )
        self.events.append(ev)
        self._last_event = ev
        self._km_since_event = 0.0

    # --- dispatching -------------------------------------------------------------------
    def _choose_pickup(self) -> str:
        if self.t - self.last_home > self.home_after:
            return self.home
        if self.rng.random() < self.p.p_same_city_pickup:
            return self.city
        here = CITIES[self.city]
        others = [c for c in CITIES if c != self.city]
        weights = [
            math.exp(-haversine_km(here, CITIES[c]) / self.p.nearby_decay_km) for c in others
        ]
        return self.rng.choices(others, weights)[0]

    def _choose_delivery(self, pickup: str) -> str:
        here = CITIES[pickup]
        others = [c for c in CITIES if c != pickup and haversine_km(here, CITIES[c]) > 150]
        weights = [
            math.exp(
                -(
                    (
                        (haversine_km(here, CITIES[c]) - self.p.loaded_typical_km)
                        / self.p.loaded_spread_km
                    )
                    ** 2
                )
            )
            for c in others
        ]
        return self.rng.choices(others, weights)[0]

    def run(self) -> None:
        self._ping(self.p.parked_jitter_m)
        while self.t < self.end:
            pickup = self._choose_pickup()
            if pickup == self.home:
                self.last_home = self.t
                self.home_after = timedelta(days=self.rng.randint(*self.p.home_return_after_days))
            pickup_at = offset_km(
                CITIES[pickup], self.rng.uniform(-10, 10), self.rng.uniform(-10, 10)
            )
            self._drive(pickup_at)
            self._park_until(self.t + timedelta(minutes=self.rng.randint(45, 180)))
            self.shipments += 1
            shipment_id = f"{self.id}-S{self.shipments:04d}"
            self._event("load", shipment_id)

            delivery = self._choose_delivery(pickup)
            self._drive(
                offset_km(CITIES[delivery], self.rng.uniform(-8, 8), self.rng.uniform(-8, 8))
            )
            self._park_until(self.t + timedelta(minutes=self.rng.randint(45, 150)))
            self._event("unload", shipment_id)
            self.city = delivery


def generate(
    trucks: int = 120,
    days: int = 365,
    start: datetime = datetime(2025, 1, 1),
    seed: int = 7,
    params: Params | None = None,
) -> FleetData:
    """Simulate the fleet. Deterministic for a given seed; each truck has its own stream,
    so truck T003 is the same whether the fleet has 10 or 120 trucks."""
    p = params or Params()
    end = start + timedelta(days=days)
    out = FleetData()
    for i in range(1, trucks + 1):
        truck_id = f"T{i:03d}"
        home = DEPOTS[(i - 1) % len(DEPOTS)]
        truck = _Truck(truck_id, home, start, end, random.Random(f"{seed}-{truck_id}"), p)
        truck.run()
        out.trucks.append((truck_id, home))
        out.pings.extend(x for x in truck.pings if x.recorded_at < end)
        out.events.extend(x for x in truck.events if x.occurred_at < end)
        out.truth.extend(x for x in truck.truth if x.end_at < end)
    return out
