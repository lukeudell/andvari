# Andvari — case study source

The narrative for lukeudell.com, rewritten from `source-pages/*.astro` to describe
what the code **actually does**. Where the original pages overstated, this corrects
rather than repeats — see `../PROJECT_NOTES.md` §1 for the specific gaps.

This file is the source for `project.yaml`. Edit here, then mirror into the config.

---

## Overview

A full-stack data engineering demonstration: synthetic LLM API telemetry processed
through a modern analytics pipeline. From generation with statistically realistic
distributions, through Kimball dimensional modelling, to self-hosted BI and an
interactive forecaster.

The domain is modelled on real-world patterns from APIs like Anthropic's Claude:
500K API requests across 5,000 users, 5 models and 5 endpoints over a 91-day window.

Everything is self-hosted and open source. No third-party analytics, no managed
warehouse, no vendor account required to run it.

## Data generation: distributions, not noise

The synthetic dataset is not random noise. Each column uses a domain-appropriate
statistical distribution, because realistic data exposes real query-planner
behaviour and index selectivity — uniform random data makes every plan look alike.

| Column | Distribution | Why |
|---|---|---|
| Latency | Log-normal μ=6.5 σ=0.8 | Clusters around a median with a heavy right tail from cold starts, queue contention and large context windows |
| Tokens | Pareto α=1.5 | Power law: a small fraction of enterprise users send massive context windows |
| Traffic | Sinusoidal, rejection sampling | −85% overnight, −40% weekends |
| HTTP status | Weighted categorical | 200/429/500/401 at 94/3/2/1% |
| Safety flags | Bernoulli p=0.008 | A textbook Bernoulli trial |
| User volume | Tier power law | Free 1 : Starter 3 : Pro 8 : Enterprise 20 |

Seed 42 throughout, so the dataset is reproducible.

## Two schemas over one source

The same raw data is modelled twice on purpose:

- **Star** — `fct_api_requests` with four conformed, denormalised dimensions.
  Industry lives directly on `dim_users`.
- **Snowflake** — `fct_api_requests_sf` → `dim_users_sf` → `dim_companies` and
  `dim_billing_tiers`, reusing the star's `dim_models`, `dim_date`, `dim_endpoints`.

Building both is what makes the trade-off measurable instead of theoretical.

## Query performance: EXPLAIN ANALYZE

Asking one business question — total cost by industry — against both schemas:

| Query | Schema | Joins | Time | Plan |
|---|---|---|---|---|
| Cost by model | star | 1 | 197 ms | Parallel seq scan, 2 workers |
| Cost by industry | snowflake | 3 | 206 ms | 3 hash builds, no parallelism |
| Cost by industry | star | 1 | **51 ms** | Denormalised, 4× faster |

This is the Kimball trade-off: storage redundancy buys query speed. The snowflake
schema earns its cost when dimension tables are large, frequently updated, or when
write-path consistency matters more than read performance.

## A bug the tests caught

`dim_companies` was built with `SELECT DISTINCT company_name, industry`. It returned
6,457 rows against roughly 4,900 real companies, because the generator had assigned
multiple industries to the same company name. The surplus rows fanned out the join
and silently inflated the fact table from 500K to 640K rows — a 28% error in every
revenue figure downstream, with nothing visibly broken.

The `unique` test on `company_key` failed. The fix was `mode() WITHIN GROUP` to pick
one industry per company deterministically.

This is the argument for declarative data tests in one paragraph: the pipeline ran
green, the dashboards rendered, and every number was wrong.

## Engineering discipline

143 declarative dbt tests. Dependencies pinned exactly, checked monthly for CVEs.
Read-only database role (`portfolio_reader`) with schema isolation, so the
presentation layer cannot reach raw staging. Healthchecks and idempotent loads.

Known limitations are documented rather than hidden — see `PROJECT_NOTES.md`.
