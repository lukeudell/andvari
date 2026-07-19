with usr as (
    select
        u.company_name
        , u.industry
    from {{ ref('stg_users') }} as u
)
, cmp as (
    select
        usr.company_name
        -- Pick the most common industry per company: a plain distinct fanned
        -- the fact table out 28% when one name carried two industries.
        , mode() within group (order by usr.industry) as industry
    from usr
    group by usr.company_name
)
select
    {{ dbt_utils.generate_surrogate_key(['cmp.company_name']) }} as company_key
    , cmp.company_name
    , cmp.industry
    , case
        when length(cmp.company_name) < 15 then 'Small'
        when length(cmp.company_name) < 25 then 'Medium'
        else 'Large'
    end as company_size_band
    , 'US' as hq_country
from cmp
