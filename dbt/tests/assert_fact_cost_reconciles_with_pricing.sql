-- ============================================================
--  file:       dbt/tests/assert_fact_cost_reconciles_with_pricing.sql
--  purpose:    fails the build if fact cost drifts from the pricing dimension
--  owner:      Luke Udell
--  spdx:       MIT
--  std:        [STD-14]
--  adr:        none
--  ticket:     none
--  ticket-url: none
--  created:    2026-07-19
-- ============================================================
-- Reconciliation: every fact row's cost_usd must be recomputable from the
-- pricing dimension. A drifted price table or a broken join produces rows
-- here and fails the build: the same class of silent-wrong-numbers bug the
-- dim_companies fan-out was ([STD-14]: green pipelines can still be wrong).
-- Tolerance covers the generator's 6-decimal rounding of cost_usd.
with fct as (
    select
        f.request_id
        , f.model_key
        , f.tokens_input
        , f.tokens_output
        , f.cost_usd
    from {{ ref('fct_api_requests') }} as f
)
, mdl as (
    select
        m.model_key
        , m.cost_per_input_token
        , m.cost_per_output_token
    from {{ ref('dim_models') }} as m
)
, recomputed as (
    select
        fct.request_id
        , fct.cost_usd
        , fct.tokens_input * mdl.cost_per_input_token
        + fct.tokens_output * mdl.cost_per_output_token as expected_cost_usd
    from fct
    inner join mdl
        on fct.model_key = mdl.model_key
)
select
    r.request_id
    , r.cost_usd
    , r.expected_cost_usd
from recomputed as r
where abs(r.cost_usd - r.expected_cost_usd) > 0.000001
