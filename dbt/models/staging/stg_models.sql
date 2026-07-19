with source as (
    select * from {{ source('raw_staging', 'models') }}
)

select
    model_id,
    model_family,
    cost_per_input_token,
    cost_per_output_token,
    context_window_k,
    is_active
from source
