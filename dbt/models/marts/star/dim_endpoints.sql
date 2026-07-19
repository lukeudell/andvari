with endpoints as (
    select * from {{ ref('stg_endpoints') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['endpoint_path']) }} as endpoint_key,
    endpoint_path,
    api_version,
    is_deprecated
from endpoints
