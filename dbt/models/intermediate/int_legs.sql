-- Legs between consecutive cargo events of one truck. A leg that starts with an unload is
-- run without cargo (empty); one that starts with a load is run loaded. Nothing in the
-- source says this directly: it follows from the order of events.
--
-- The last leg of each truck has no closing event yet and is left out (`is_closed`), as
-- is any distance before a truck's first event.

with events as (
    select
        truck_id,
        event_type,
        occurred_at,
        lat,
        lon,
        shipment_id,
        row_number() over (partition by truck_id order by occurred_at, event_id) as leg_seq,
        lead(occurred_at) over (partition by truck_id order by occurred_at, event_id) as next_at,
        lead(event_type) over (partition by truck_id order by occurred_at, event_id) as next_type,
        lead(lat) over (partition by truck_id order by occurred_at, event_id) as next_lat,
        lead(lon) over (partition by truck_id order by occurred_at, event_id) as next_lon
    from {{ ref('stg_fleet__cargo_events') }}
),

distance as (
    select
        truck_id,
        leg_seq,
        sum(step_km) as km,
        sum(raw_step_km) as raw_km,
        count(*) filter (where not is_event) as ping_count
    from {{ ref('int_track_steps') }}
    group by truck_id, leg_seq
)

select
    e.truck_id,
    e.leg_seq,
    e.occurred_at as start_at,
    e.next_at as end_at,
    case e.event_type when 'unload' then 'empty' else 'loaded' end as kind,
    -- Two loads (or two unloads) in a row mean a missing event in the source.
    e.event_type = e.next_type as is_sequence_break,
    e.next_at is not null as is_closed,
    e.lat as start_lat,
    e.lon as start_lon,
    e.next_lat as end_lat,
    e.next_lon as end_lon,
    coalesce(d.km, 0) as km,
    coalesce(d.raw_km, 0) as raw_km,
    coalesce(d.ping_count, 0) as ping_count,
    case when e.event_type = 'load' then e.shipment_id end as shipment_id
from events as e
left join distance as d
    on d.truck_id = e.truck_id
    and d.leg_seq = e.leg_seq
