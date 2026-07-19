with models as (
    select * from {{ ref('stg_models') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['model_id']) }} as model_key,
    model_id,
    model_family,
    cost_per_input_token,
    cost_per_output_token,
    context_window_k,
    is_active
from models
