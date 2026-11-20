-- Per truck: how much of its distance it ran empty, ranked worst first.
with legs as (
    select truck_id, home_depot, sum(km) as total_km
    from {{ ref('fct_legs') }}
    group by truck_id, home_depot
),

empty as (
    select truck_id, count(*) as empty_trips, sum(km) as empty_km
    from {{ ref('fct_empty_trips') }}
    group by truck_id
)

select
    l.truck_id,
    l.home_depot,
    l.total_km,
    coalesce(e.empty_km, 0) as empty_km,
    coalesce(e.empty_trips, 0) as empty_trips,
    coalesce(e.empty_km, 0) / nullif(l.total_km, 0) as empty_km_share,
    rank() over (order by coalesce(e.empty_km, 0) / nullif(l.total_km, 0) desc) as share_rank
from legs as l
left join empty as e on e.truck_id = l.truck_id
