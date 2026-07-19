with users as (
    select * from {{ ref('stg_users') }}
),

companies as (
    select
        company_name,
        -- Pick the most common industry per company to avoid fan-out
        mode() within group (order by industry) as industry
    from users
    group by company_name
)

select
    {{ dbt_utils.generate_surrogate_key(['company_name']) }} as company_key,
    company_name,
    industry,
    case
        when length(company_name) < 15 then 'Small'
        when length(company_name) < 25 then 'Medium'
        else 'Large'
    end as company_size_band,
    'US' as hq_country
from companies
