select
    s.user_id
    , s.billing_tier
    , s.company_name
    , s.industry
    , s.signup_date
    , s.region
from {{ source('raw_staging', 'users') }} as s
