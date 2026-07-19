with source as (
    select * from {{ source('raw_staging', 'endpoints') }}
)

select
    endpoint_path,
    api_version,
    is_deprecated
from source
