-- ============================================================
--  file:       dbt/models/marts/star/dim_endpoints.sql
--  purpose:    endpoint dimension with version and deprecation status
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
with edp as (
    select
        e.endpoint_path
        , e.api_version
        , e.is_deprecated
    from {{ ref('stg_endpoints') }} as e
)
select
    {{ dbt_utils.generate_surrogate_key(['edp.endpoint_path']) }} as endpoint_key
    , edp.endpoint_path
    , edp.api_version
    , edp.is_deprecated
from edp
