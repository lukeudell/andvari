with users as (
    select * from {{ ref('stg_users') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['user_id']) }} as user_key,
    user_id,
    billing_tier,
    company_name,
    industry,
    signup_date,
    region
from users
