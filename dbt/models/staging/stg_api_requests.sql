select
    s.request_id
    , s.user_id
    , s.model_id
    , s.endpoint_path
    , s.request_timestamp
    , s.latency_ms
    , s.tokens_input
    , s.tokens_output
    , s.tokens_total
    , s.cost_usd
    , s.http_status
    , s.safety_flag
from {{ source('raw_staging', 'api_requests') }} as s
