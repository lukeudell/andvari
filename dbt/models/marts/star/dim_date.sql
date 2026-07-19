-- ============================================================
--  file:       dbt/models/marts/star/dim_date.sql
--  purpose:    calendar dimension over the data window
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
select
    d.date_key
    , d.full_date
    , d.day_of_week
    , d.is_weekend
    , d.week_of_year
    , d.month_name
    , d.quarter
    , d.year
from {{ ref('stg_dates') }} as d
