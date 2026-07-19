select
    s.model_id
    , s.model_family
    , s.cost_per_input_token
    , s.cost_per_output_token
    , s.context_window_k
    , s.is_active
from {{ source('raw_staging', 'models') }} as s
