-- ============================================================
--  file:       dbt/models/staging/stg_users.sql
--  purpose:    stage raw user accounts, 1:1 with source
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
select
    s.user_id
    , s.billing_tier
    , s.company_name
    , s.industry
    , s.signup_date
    , s.region
from {{ source('raw_staging', 'users') }} as s
