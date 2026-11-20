-- Without the stationary filter, parked trucks would add distance. The filtered distance
-- must never exceed the raw sum, and the difference is the noise removed.
select truck_id, leg_seq, km, raw_km
from {{ ref('int_legs') }}
where km > raw_km + 1e-9
