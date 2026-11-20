-- The detection must find exactly the legs the simulator drove: same truck, same start and
-- end, same kind (empty or loaded). Returns the legs that disagree; passes when none do.
with detected as (
    select truck_id, start_at, end_at, kind from {{ ref('fct_legs') }}
),

truth as (
    select truck_id, start_at, end_at, kind from {{ source('truth', 'legs') }}
)

select
    coalesce(d.truck_id, t.truck_id) as truck_id,
    coalesce(d.start_at, t.start_at) as start_at,
    d.end_at as detected_end_at,
    t.end_at as true_end_at,
    d.kind as detected_kind,
    t.kind as true_kind
from detected as d
full outer join truth as t
    on t.truck_id = d.truck_id
    and t.start_at = d.start_at
where d.truck_id is null
   or t.truck_id is null
   or d.end_at <> t.end_at
   or d.kind <> t.kind
