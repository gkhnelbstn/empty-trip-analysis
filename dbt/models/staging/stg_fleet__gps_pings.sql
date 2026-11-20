-- The feed repeats some pings verbatim; keep one per truck and timestamp.
select distinct on (truck_id, recorded_at)
    truck_id,
    recorded_at,
    lat,
    lon
from {{ source('fleet', 'gps_pings') }}
order by truck_id, recorded_at
