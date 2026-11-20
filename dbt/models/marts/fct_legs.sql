-- Every closed leg of every truck: run empty or run loaded, with its distance.
select
    l.truck_id || '-' || lpad(l.leg_seq::text, 5, '0') as leg_id,
    l.truck_id,
    t.home_depot,
    l.leg_seq,
    l.kind,
    l.start_at,
    l.end_at,
    date_trunc('month', l.start_at)::date as start_month,
    round((extract(epoch from l.end_at - l.start_at) / 3600.0)::numeric, 2) as duration_hours,
    l.km,
    l.start_lat,
    l.start_lon,
    l.end_lat,
    l.end_lon,
    {{ haversine_km('l.start_lat', 'l.start_lon', 'l.end_lat', 'l.end_lon') }} as straight_line_km,
    l.ping_count,
    l.shipment_id
from {{ ref('int_legs') }} as l
inner join {{ ref('stg_fleet__trucks') }} as t on t.truck_id = l.truck_id
where l.is_closed
