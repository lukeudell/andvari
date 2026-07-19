-- ============================================================
--  file:       dbt/models/marts/snowflake/dim_users_sf.sql
--  purpose:    normalised user dimension for the snowflake mart
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
with usr as (
    select
        u.user_id
        , u.billing_tier
        , u.company_name
        , u.signup_date
        , u.region
    from {{ ref('stg_users') }} as u
)
, cmp as (
    select
        c.company_key
        , c.company_name
    from {{ ref('dim_companies') }} as c
)
, bt as (
    select
        b.billing_tier_key
        , b.tier_name
    from {{ ref('dim_billing_tiers') }} as b
)
select
    {{ dbt_utils.generate_surrogate_key(['usr.user_id']) }} as user_key
    , usr.user_id
    , cmp.company_key
    , bt.billing_tier_key
    , usr.signup_date
    , usr.region
from usr
inner join cmp
    on usr.company_name = cmp.company_name
inner join bt
    on usr.billing_tier = bt.tier_name
