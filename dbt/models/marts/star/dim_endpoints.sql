with edp as (
    select
        e.endpoint_path
        , e.api_version
        , e.is_deprecated
    from {{ ref('stg_endpoints') }} as e
)
select
    {{ dbt_utils.generate_surrogate_key(['edp.endpoint_path']) }} as endpoint_key
    , edp.endpoint_path
    , edp.api_version
    , edp.is_deprecated
from edp
