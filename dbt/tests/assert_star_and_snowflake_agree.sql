-- The two marts model the same source; if their row counts or cost totals
-- ever diverge, one of them is silently wrong. This is exactly how the
-- dim_companies fan-out showed up: 500K rows became 640K and every revenue
-- number inflated 28% while the pipeline stayed green.
with star as (
    select
        count(*) as n_rows
        , round(sum(f.cost_usd), 2) as total_cost_usd
    from {{ ref('fct_api_requests') }} as f
)
, snow as (
    select
        count(*) as n_rows
        , round(sum(f.cost_usd), 2) as total_cost_usd
    from {{ ref('fct_api_requests_sf') }} as f
)
select
    star.n_rows as star_rows
    , snow.n_rows as snowflake_rows
    , star.total_cost_usd as star_cost
    , snow.total_cost_usd as snowflake_cost
from star
cross join snow
where
    star.n_rows != snow.n_rows
    or star.total_cost_usd != snow.total_cost_usd
