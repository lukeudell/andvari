-- ============================================================
--  file:       dbt/models/staging/stg_dates.sql
--  purpose:    stage the raw date dimension, 1:1 with source
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
select
    s.date_key
    , s.full_date
    , s.day_of_week
    , s.is_weekend
    , s.week_of_year
    , s.month_name
    , s.quarter
    , s.year
from {{ source('raw_staging', 'dates') }} as s
