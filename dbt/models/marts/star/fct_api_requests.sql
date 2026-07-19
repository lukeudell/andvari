-- ============================================================
--  file:       dbt/models/marts/star/fct_api_requests.sql
--  purpose:    star fact, one row per API request
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-04] [STD-13]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
-- Grain: one row per API request event.
with req as (
    select
        r.request_id
        , r.user_id
        , r.model_id
        , r.endpoint_path
        , r.request_timestamp
        , r.latency_ms
        , r.tokens_input
        , r.tokens_output
        , r.tokens_total
        , r.cost_usd
        , r.http_status
        , r.safety_flag
    from {{ ref('stg_api_requests') }} as r
)
, usr as (
    select
        u.user_key
        , u.user_id
    from {{ ref('dim_users') }} as u
)
, mdl as (
    select
        m.model_key
        , m.model_id
    from {{ ref('dim_models') }} as m
)
, edp as (
    select
        e.endpoint_key
        , e.endpoint_path
    from {{ ref('dim_endpoints') }} as e
)
, dt as (
    select d.date_key
    from {{ ref('dim_date') }} as d
)
select
    req.request_id
    , usr.user_key
    , mdl.model_key
    , dt.date_key
    , edp.endpoint_key
    , req.latency_ms
    , req.tokens_input
    , req.tokens_output
    , req.tokens_total
    , req.cost_usd
    , req.http_status
    , req.safety_flag
    , req.request_timestamp
from req
inner join usr
    on req.user_id = usr.user_id
inner join mdl
    on req.model_id = mdl.model_id
inner join dt
    on cast(to_char(req.request_timestamp, 'YYYYMMDD') as integer) = dt.date_key
inner join edp
    on req.endpoint_path = edp.endpoint_path
