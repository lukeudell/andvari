with source as (
    select * from {{ source('raw_staging', 'api_requests') }}
)

select
    request_id,
    user_id,
    model_id,
    endpoint_path,
    request_timestamp,
    latency_ms,
    tokens_input,
    tokens_output,
    tokens_total,
    cost_usd,
    http_status,
    safety_flag
from source
