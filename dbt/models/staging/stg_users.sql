with source as (
    select * from {{ source('raw_staging', 'users') }}
)

select
    user_id,
    billing_tier,
    company_name,
    industry,
    signup_date,
    region
from source
