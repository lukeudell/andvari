select
    s.endpoint_path
    , s.api_version
    , s.is_deprecated
from {{ source('raw_staging', 'endpoints') }} as s
