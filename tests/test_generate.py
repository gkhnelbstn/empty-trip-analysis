from __future__ import annotations

import itertools
from datetime import datetime, timedelta

import pytest

from empty_trips.generate import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    MAX_DRIVE_PER_DAY,
    generate,
)
from empty_trips.geo import haversine_km

START = datetime(2025, 1, 6)


@pytest.fixture(scope="module")
def fleet():
    return generate(trucks=6, days=90, start=START, seed=11)


def test_same_seed_same_data(fleet):
    again = generate(trucks=6, days=90, start=START, seed=11)
    assert again.pings == fleet.pings
    assert again.events == fleet.events


def test_a_truck_does_not_depend_on_fleet_size(fleet):
    small = generate(trucks=2, days=90, start=START, seed=11)
    assert [e for e in fleet.events if e.truck_id == "T002"] == [
        e for e in small.events if e.truck_id == "T002"
    ]


def test_cargo_events_alternate_load_unload(fleet):
    for truck_id, _ in fleet.trucks:
        types = [e.event_type for e in fleet.events if e.truck_id == truck_id]
        assert types[0] == "load"
        assert all(a != b for a, b in itertools.pairwise(types))


def test_truth_legs_chain_event_to_event(fleet):
    for truck_id, _ in fleet.trucks:
        events = [e for e in fleet.events if e.truck_id == truck_id]
        legs = [x for x in fleet.truth if x.truck_id == truck_id]
        assert [x.start_at for x in legs] == [e.occurred_at for e in events[:-1]]
        assert [x.end_at for x in legs] == [e.occurred_at for e in events[1:]]
        assert [x.kind for x in legs] == [
            "empty" if e.event_type == "unload" else "loaded" for e in events[:-1]
        ]


def test_trucks_only_drive_inside_the_driving_window(fleet):
    for b in _driving_steps(fleet):
        # a driving step ends on a weekday, inside the window (or exactly at its end)
        assert b.recorded_at.weekday() < 5
        assert DAY_START_HOUR <= b.recorded_at.hour < DAY_END_HOUR or (
            b.recorded_at.hour == DAY_END_HOUR and b.recorded_at.minute == 0
        )


def test_daily_driving_time_is_capped(fleet):
    driving: dict[tuple[str, object], timedelta] = {}
    for b, a in _driving_steps(fleet, with_previous=True):
        key = (b.truck_id, b.recorded_at.date())
        driving[key] = driving.get(key, timedelta()) + (b.recorded_at - a.recorded_at)
    assert max(driving.values()) <= MAX_DRIVE_PER_DAY


def _driving_steps(fleet, with_previous=False):
    """Steps between two pings at most 10 minutes apart that moved more than position noise.

    Longer gaps are skipped: they span a lost ping or a parked hour and say nothing certain
    about when the truck was moving.
    """
    by_truck: dict[str, list] = {}
    for p in fleet.pings:
        by_truck.setdefault(p.truck_id, []).append(p)
    for pings in by_truck.values():
        for a, b in itertools.pairwise(pings):
            gap = b.recorded_at - a.recorded_at
            if timedelta() < gap <= timedelta(minutes=10) and (
                haversine_km((a.lat, a.lon), (b.lat, b.lon)) >= 0.5
            ):
                yield (b, a) if with_previous else b


def test_feed_has_the_noise_staging_must_handle(fleet):
    keys = [(p.truck_id, p.recorded_at) for p in fleet.pings]
    assert len(keys) > len(set(keys)), "expected some repeated pings"


def test_empty_share_is_in_a_realistic_range():
    # EU road freight runs roughly a fifth of its vehicle-km empty; the defaults aim there.
    data = generate(trucks=20, days=180, start=START, seed=3)
    empty = sum(x.km for x in data.truth if x.kind == "empty")
    total = sum(x.km for x in data.truth)
    assert 0.15 < empty / total < 0.30


@pytest.mark.db
def test_write_replaces_previous_run(test_database):
    psycopg = pytest.importorskip("psycopg")
    from empty_trips.load import write

    first = generate(trucks=3, days=20, start=START, seed=1)
    second = generate(trucks=2, days=20, start=START, seed=2)
    end = START + timedelta(days=20)
    with psycopg.connect() as conn:
        write(conn, first, seed=1, start=START, end=end)
        counts = write(conn, second, seed=2, start=START, end=end)
        n_pings = conn.execute("select count(*) from raw.gps_pings").fetchone()[0]
        n_trucks = conn.execute("select count(*) from raw.trucks").fetchone()[0]
        n_logs = conn.execute("select count(*) from raw.generation_log").fetchone()[0]
    assert n_pings == counts["pings"] == len(second.pings)
    assert n_trucks == 2
    assert n_logs == 1
