-- Per month: all km run, km run empty, and the empty trips behind them.
with legs as (
    select start_month, sum(km) as total_km from {{ ref('fct_legs') }} group by start_month
),

empty as (
    select start_month, count(*) as empty_trips, sum(km) as empty_km
    from {{ ref('fct_empty_trips') }}
    group by start_month
)

select
    l.start_month as month,
    l.total_km,
    coalesce(e.empty_km, 0) as empty_km,
    coalesce(e.empty_trips, 0) as empty_trips,
    coalesce(e.empty_km, 0) / nullif(l.total_km, 0) as empty_km_share
from legs as l
left join empty as e on e.start_month = l.start_month
