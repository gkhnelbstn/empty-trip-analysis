select
    truck_id,
    home_depot
from {{ source('fleet', 'trucks') }}
