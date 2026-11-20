"""Write a generated fleet into PostgreSQL.

``raw`` holds what the fleet's systems would deliver (pings, cargo events, trucks). ``truth``
holds what the simulator really drove; only the tests read it. Every run replaces both in
one transaction, so a run with the same seed always leaves the same data behind.
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg

from empty_trips.generate import FleetData

DDL = """
create schema if not exists raw;
create schema if not exists truth;

create table if not exists raw.trucks (
    truck_id    text primary key,
    home_depot  text not null
);

-- No key on purpose: telematics feeds repeat pings, and staging deduplicates them.
create table if not exists raw.gps_pings (
    truck_id     text not null,
    recorded_at  timestamptz not null,
    lat          double precision not null,
    lon          double precision not null
);

create table if not exists raw.cargo_events (
    event_id     bigint primary key,
    truck_id     text not null,
    event_type   text not null check (event_type in ('load', 'unload')),
    occurred_at  timestamptz not null,
    lat          double precision not null,
    lon          double precision not null,
    shipment_id  text not null
);

create table if not exists raw.generation_log (
    generated_at  timestamptz not null,
    seed          integer not null,
    trucks        integer not null,
    period_start  timestamptz not null,
    period_end    timestamptz not null
);

create table if not exists truth.legs (
    truck_id  text not null,
    start_at  timestamptz not null,
    end_at    timestamptz not null,
    kind      text not null,
    km        double precision not null,
    primary key (truck_id, start_at)
);
"""


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC)


def write(
    conn: psycopg.Connection, data: FleetData, *, seed: int, start: datetime, end: datetime
) -> dict[str, int]:
    with conn.transaction():
        conn.execute(DDL)
        conn.execute(
            "truncate raw.trucks, raw.gps_pings, raw.cargo_events, raw.generation_log, truth.legs"
        )
        with conn.cursor() as cur:
            with cur.copy("copy raw.trucks (truck_id, home_depot) from stdin") as cp:
                for row in data.trucks:
                    cp.write_row(row)
            with cur.copy("copy raw.gps_pings (truck_id, recorded_at, lat, lon) from stdin") as cp:
                for p in data.pings:
                    cp.write_row((p.truck_id, _utc(p.recorded_at), p.lat, p.lon))
            with cur.copy(
                "copy raw.cargo_events (event_id, truck_id, event_type, occurred_at, lat, lon,"
                " shipment_id) from stdin"
            ) as cp:
                for i, e in enumerate(data.events, start=1):
                    cp.write_row(
                        (
                            i,
                            e.truck_id,
                            e.event_type,
                            _utc(e.occurred_at),
                            e.lat,
                            e.lon,
                            e.shipment_id,
                        )
                    )
            with cur.copy(
                "copy truth.legs (truck_id, start_at, end_at, kind, km) from stdin"
            ) as cp:
                for t in data.truth:
                    cp.write_row((t.truck_id, _utc(t.start_at), _utc(t.end_at), t.kind, t.km))
        conn.execute(
            "insert into raw.generation_log values (now(), %s, %s, %s, %s)",
            (seed, len(data.trucks), _utc(start), _utc(end)),
        )
        conn.execute("analyze raw.gps_pings; analyze raw.cargo_events")
    return {
        "trucks": len(data.trucks),
        "pings": len(data.pings),
        "cargo_events": len(data.events),
        "truth_legs": len(data.truth),
    }
