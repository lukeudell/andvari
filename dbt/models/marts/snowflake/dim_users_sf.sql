with users as (
    select * from {{ ref('stg_users') }}
),

companies as (
    select * from {{ ref('dim_companies') }}
),

billing_tiers as (
    select * from {{ ref('dim_billing_tiers') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['users.user_id']) }} as user_key,
    users.user_id,
    companies.company_key,
    billing_tiers.billing_tier_key,
    users.signup_date,
    users.region
from users
inner join companies
    on users.company_name = companies.company_name
inner join billing_tiers
    on users.billing_tier = billing_tiers.tier_name
