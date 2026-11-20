-- Across the whole fleet, GPS-measured empty km must be within 0.5% of what was driven.
with d as (select sum(km) as km from {{ ref('fct_legs') }} where kind = 'empty'),
     t as (select sum(km) as km from {{ source('truth', 'legs') }} where kind = 'empty')
select d.km as detected_km, t.km as true_km
from d cross join t
where abs(d.km - t.km) > 0.005 * t.km
