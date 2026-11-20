select
    event_id,
    truck_id,
    event_type,
    occurred_at,
    lat,
    lon,
    shipment_id
from {{ source('fleet', 'cargo_events') }}
