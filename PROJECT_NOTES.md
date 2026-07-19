# Andvari: extraction and hardening log

This project was deliberately split out of the `command_center` monorepo on
2026-07-19. The goal of the split was independence: the portfolio site and its
projects had grown interdependent, and this one now owns its own Postgres, its
own dbt project, and its own compose stack, with no shared infrastructure.

A split like that is diagnostic. Assumptions that were true by coincidence
inside the monorepo stop being true outside it, and say so. This log records
what the split surfaced, what was done about each item, and how the fixes were
verified. Items are kept even after resolution, because the finding is often
more instructive than the fix.

---

## Findings at extraction, tracked to resolution

### 1. The published narrative had drifted from the code

The old site pages described a lineage diagram with snowflake dimension tables
that do not exist (the snowflake mart reuses the star's conformed dimensions),
counted shared dimensions twice to inflate the model count, and displayed a
hardcoded "99.9% Uptime" figure that nothing measured.

**Resolved.** `docs/CASE_STUDY.md` and `project.yaml` were rewritten to
describe what the code does, and they are the only sources that feed the
portfolio. The original pages are kept verbatim in `docs/source-pages/` as a
historical record and are not a build input. The operating rule that came out
of this: make the claim true or stop making it.

### 2. The forecaster shipped database wiring it never used

`app/app.py` imported nothing from psycopg2 and opened no connection, yet the
image shipped the driver, the compose service injected five database variables,
and startup was gated on a healthy Postgres it never queried.

**Resolved.** The forecaster now reads the star schema as the SELECT-only
`portfolio_reader` role and turns observed traffic into a TELEMETRY (OBSERVED)
preset: real model mix, real token averages, real request rates. When the
database is absent it degrades to parametric mode instead of crashing. See
`app/db.py` and its test suite.

### 3. Token pricing had three sources of truth

The generator, the app, and `dim_models` each carried their own price table,
and the app's copy had already drifted (two models missing).

**Resolved.** `data/model_catalog.csv` is the single source. The generator
prices requests from it, the loader ships it to the warehouse where
`dim_models` is built from it, and the app loads it through `app/catalog.py`.
A reconciliation test asserts every fact row's cost is recomputable from the
pricing dimension, so drift now fails the build.

### 4. Test coverage was thin outside dbt

The only Python tests covered the theme's CSS-injection allowlist. The
forecaster's arithmetic, the generator's distributions, and the loader had
none. dbt was healthier, with 143 declarative tests.

**Mostly resolved.** Forecast arithmetic, catalog loading, baseline shaping,
and the generator's statistical properties are now covered: 158 Python tests.
dbt carries 145 data tests including two reconciliation tests, with enforced
contracts on every mart. Still open: the loader has integration coverage in CI
but no unit tests.

### 5. Python versions disagreed

The app image was 3.11, the data image 3.12, and CI pinned both at different
times. **Resolved:** 3.12 everywhere.

### 6. Known upstream CVEs, accepted with reasons

dbt's transitive dependencies carry findings that cannot clear without moving
dbt-core past its protobuf constraint. They are accepted explicitly: listed as
`--ignore-vuln` flags in CI with reasons recorded in `SECURITY.md`, never
swallowed with a silent exit code. App and data dependencies must audit clean.

---

## What the split deliberately left behind

- **The BI layer (Metabase).** One shared instance served several projects in
  the monorepo, and its pinned image carried unfixable CVEs. Re-adding
  dashboards here is a fresh decision, not a port.
- **Ingress (Traefik).** A deployment concern, not a project concern. The app
  serves at the root by default and honors a base path variable when behind a
  proxy; both modes are verified.
- **A neighboring arcade service** and its database role, which never belonged
  to this project. Verified absent from the loader by grep on 2026-07-19.
- **Checked-in generated CSVs.** Regenerate instead:
  `docker compose --profile seed run --rm seed`.
- **`dbt/profiles.yml`.** The monorepo's copy carried a plaintext dev
  password. It is gitignored here; an example ships instead.

## What the split repaired

The loader hardcoded the monorepo's database name inside its GRANT statements.
Inside the monorepo the hardcoded name and the connected database were always
the same string, so the bug could not fire; standalone, the load succeeded and
role creation failed against a database that did not exist. The grants now
follow `conn.info.dbname`, so they apply to whatever database the loader is
actually connected to.

Packaging was rebuilt for independence: the data image copies only this
project, `seed.sh` validates its environment before touching the database, the
compose stack binds Postgres to loopback on its own port (55432) so every
extracted project can run side by side, and the whole chain was verified from
an empty volume.

## Verification snapshot

Current state, verified end to end on 2026-07-19:

- 500K rows generated and loaded; `portfolio_reader` created, SELECT verified,
  INSERT and DELETE verified denied.
- `dbt build`: 14 models, 145 data tests, contracts enforced. PASS=159,
  ERROR=0.
- 158 Python tests passing. sqlfluff, bandit (medium+), and gitleaks clean.
- App healthy standalone and behind a base path; telemetry calibration
  verified inside the container against the live star schema.

## The measurement that changed under re-measurement

The strongest artifact here is the star-vs-snowflake comparison, and it earned
that status twice. The original monorepo measurement showed the star answering
cost-by-industry 4x faster (51 ms vs 206 ms) because the planner ran the
snowflake's three hash joins without parallelism. When the comparison became a
reproducible script (`data/benchmark_star_vs_snowflake.py`), the current
hardware told a different story: Postgres 16 parallelises all three plans and
the gap narrows to a few percent at 500K rows.

The published narrative presents both measurements. Two environments, two
answers, one lesson: the denormalisation trade-off is real but
environment-dependent, and a claim you can rerun is worth ten you can only
read.

The other keeper is the `dim_companies` fan-out. A plain SELECT DISTINCT
returned 6,457 rows against roughly 4,900 real companies because the generator
assigned some company names two industries. The surplus rows fanned the join
and silently inflated the fact table from 500K to 640K rows, a 28% error in
every downstream revenue figure, while the pipeline ran green. The `unique`
test on `company_key` caught it; the fix was `mode() within group`, and a
cross-mart reconciliation test now guards the invariant permanently.
