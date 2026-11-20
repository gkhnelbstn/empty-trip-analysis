-- GPS distance per leg must be within 3% (or 2 km on short legs) of what was driven, for at
-- least 99.9% of legs.
--
-- Not 100%: pings every 10 minutes cut the corners of a winding road, so GPS distance runs a
-- little short, most of all on short legs driven slowly through town. That is a property of
-- the data, not of the detection, and a real fleet would see it too.
with compared as (
    select abs(d.km - t.km) > greatest(2, 0.03 * t.km) as is_off
    from {{ ref('fct_legs') }} as d
    inner join {{ source('truth', 'legs') }} as t
        on t.truck_id = d.truck_id
        and t.start_at = d.start_at
)

select count(*) filter (where is_off) as legs_off, count(*) as legs
from compared
having count(*) filter (where is_off) > 0.001 * count(*)
