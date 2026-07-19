-- ============================================================
--  file:       dbt/models/staging/stg_models.sql
--  purpose:    stage the raw model catalog, 1:1 with source
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
select
    s.model_id
    , s.model_family
    , s.cost_per_input_token
    , s.cost_per_output_token
    , s.context_window_k
    , s.is_active
from {{ source('raw_staging', 'models') }} as s
