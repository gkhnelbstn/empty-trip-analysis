-- The answer, in one row: what empty running costs this fleet a year, and what cutting it
-- by `reduction_share` would save after paying for it.
--
--   cost per empty km = fuel + tolls + tyres/maintenance + driver time
--   annual empty km   = empty-trip km observed, scaled to 365 days
--   gross saving      = annual empty km x reduction share x cost per empty km
--   detour cost       = the avoided km x detour share x cost per km
--                       (reaching a backhaul load usually means a detour)
--   programme cost    = trucks x cost per truck per year (load boards, planner time)
--   net saving        = gross - detour - programme
--
-- Every input is in seeds/cost_assumptions.csv.

with a as (
    select
        max(value) filter (where parameter = 'fuel_l_per_100km_empty') as fuel_l_per_100km,
        max(value) filter (where parameter = 'diesel_eur_per_l') as diesel_eur_per_l,
        max(value) filter (where parameter = 'tolls_eur_per_km') as tolls_eur_per_km,
        max(value) filter (where parameter = 'maintenance_tyres_eur_per_km') as maint_eur_per_km,
        max(value) filter (where parameter = 'driver_eur_per_hour') as driver_eur_per_hour,
        max(value) filter (where parameter = 'avg_empty_speed_kmh') as avg_speed_kmh,
        max(value) filter (where parameter = 'reduction_share') as reduction_share,
        max(value) filter (where parameter = 'detour_share') as detour_share,
        max(value) filter (where parameter = 'programme_eur_per_truck_year')
            as programme_eur_per_truck_year
    from {{ ref('cost_assumptions') }}
),

period as (
    select period_days::numeric as period_days from {{ ref('stg_fleet__observation_period') }}
),

fleet as (
    select count(*) as trucks from {{ ref('stg_fleet__trucks') }}
),

observed as (
    select
        (select sum(km) from {{ ref('fct_legs') }})::numeric as total_km,
        (select sum(km) from {{ ref('fct_empty_trips') }})::numeric as empty_km,
        (select count(*) from {{ ref('fct_empty_trips') }}) as empty_trips
),

unit_cost as (
    select
        a.*,
        a.fuel_l_per_100km / 100 * a.diesel_eur_per_l as fuel_eur_per_km,
        a.driver_eur_per_hour / a.avg_speed_kmh as driver_eur_per_km,
        a.fuel_l_per_100km / 100 * a.diesel_eur_per_l
            + a.tolls_eur_per_km
            + a.maint_eur_per_km
            + a.driver_eur_per_hour / a.avg_speed_kmh as cost_per_empty_km
    from a
),

annual as (
    select
        f.trucks,
        p.period_days,
        o.total_km,
        o.empty_km,
        o.empty_trips,
        o.empty_km / nullif(o.total_km, 0) as empty_km_share,
        o.empty_trips * 365 / p.period_days as empty_trips_per_year,
        o.empty_km * 365 / p.period_days as annual_empty_km,
        u.*
    from observed as o
    cross join period as p
    cross join fleet as f
    cross join unit_cost as u
)

select
    trucks,
    round(period_days)::int as period_days,
    total_km,
    empty_km,
    empty_trips,
    empty_km_share,
    empty_trips_per_year,
    annual_empty_km,
    fuel_eur_per_km,
    tolls_eur_per_km,
    maint_eur_per_km,
    driver_eur_per_km,
    cost_per_empty_km,
    annual_empty_km * cost_per_empty_km as annual_empty_cost,
    reduction_share,
    detour_share,
    annual_empty_km * reduction_share as avoided_km_per_year,
    annual_empty_km * reduction_share * cost_per_empty_km as gross_saving,
    annual_empty_km * reduction_share * detour_share * cost_per_empty_km as detour_cost,
    trucks * programme_eur_per_truck_year as programme_cost,
    annual_empty_km * reduction_share * cost_per_empty_km * (1 - detour_share)
        - trucks * programme_eur_per_truck_year as net_saving
from annual
