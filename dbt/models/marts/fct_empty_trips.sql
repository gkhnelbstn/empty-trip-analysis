-- Empty trips: legs run without cargo that went somewhere. A few kilometres across the same
-- yard between an unload and the next load is not a trip; `min_empty_trip_km` draws the line.
select
    leg_id,
    truck_id,
    home_depot,
    start_at,
    end_at,
    start_month,
    duration_hours,
    km,
    straight_line_km,
    start_lat,
    start_lon,
    end_lat,
    end_lon,
    case
        when km < 50 then '5-50 km'
        when km < 150 then '50-150 km'
        when km < 300 then '150-300 km'
        else '300+ km'
    end as distance_band
from {{ ref('fct_legs') }}
where kind = 'empty'
  and km >= {{ var('min_empty_trip_km') }}
