-- The track of each truck, one row per step between two consecutive position fixes, with
-- the distance driven and the leg the step belongs to.
--
-- Position fixes are the GPS pings plus the cargo events, which carry the position where
-- the load or unload happened. Using the events too matters when a ping is lost: without
-- them, the step from the last ping before an unload to the first ping after it would be
-- booked entirely to the next leg.
--
-- Legs: a running count of events along the track numbers the legs. A step belongs to the
-- leg in progress where it started, so a step that ends on an event closes the old leg and
-- a step that starts on an event opens the new one. Pings and events with the same
-- timestamp sort ping first.
--
-- Distance: a parked truck still "moves" a few metres per ping because of position noise.
-- Steps shorter than `stationary_step_km` count as zero, so a weekend in a car park does not
-- add kilometres.

with track as (
    select truck_id, recorded_at as ts, lat, lon, 0 as is_event
    from {{ ref('stg_fleet__gps_pings') }}
    union all
    select truck_id, occurred_at as ts, lat, lon, 1 as is_event
    from {{ ref('stg_fleet__cargo_events') }}
),

ordered as (
    select
        *,
        sum(is_event) over w_running as legs_started,
        lag(lat) over w as prev_lat,
        lag(lon) over w as prev_lon,
        lag(ts) over w as prev_ts
    from track
    window
        w as (partition by truck_id order by ts, is_event),
        w_running as (partition by truck_id order by ts, is_event rows unbounded preceding)
),

steps as (
    select
        *,
        lag(legs_started) over (partition by truck_id order by ts, is_event) as leg_seq,
        {{ haversine_km('prev_lat', 'prev_lon', 'lat', 'lon') }} as raw_step_km
    from ordered
)

select
    truck_id,
    ts,
    is_event = 1 as is_event,
    prev_ts,
    lat,
    lon,
    leg_seq,
    raw_step_km,
    case when raw_step_km < {{ var('stationary_step_km') }} then 0 else raw_step_km end as step_km
from steps
-- Steps before a truck's first event belong to no leg.
where leg_seq >= 1
