with mdl as (
    select
        m.model_id
        , m.model_family
        , m.cost_per_input_token
        , m.cost_per_output_token
        , m.context_window_k
        , m.is_active
    from {{ ref('stg_models') }} as m
)
select
    {{ dbt_utils.generate_surrogate_key(['mdl.model_id']) }} as model_key
    , mdl.model_id
    , mdl.model_family
    , mdl.cost_per_input_token
    , mdl.cost_per_output_token
    , mdl.context_window_k
    , mdl.is_active
from mdl
