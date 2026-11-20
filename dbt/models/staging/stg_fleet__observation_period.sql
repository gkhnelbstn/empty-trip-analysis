-- The current data covers exactly one generation run; keep its period.
select
    period_start,
    period_end,
    extract(epoch from period_end - period_start) / 86400.0 as period_days,
    seed
from {{ source('fleet', 'generation_log') }}
