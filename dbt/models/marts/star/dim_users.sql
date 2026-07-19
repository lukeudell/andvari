-- ============================================================
--  file:       dbt/models/marts/star/dim_users.sql
--  purpose:    denormalised user dimension for the star mart
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
        , u.industry
        , u.signup_date
        , u.region
    from {{ ref('stg_users') }} as u
)
select
    {{ dbt_utils.generate_surrogate_key(['usr.user_id']) }} as user_key
    , usr.user_id
    , usr.billing_tier
    , usr.company_name
    , usr.industry
    , usr.signup_date
    , usr.region
from usr
