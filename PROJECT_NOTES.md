# Andvari — inherited state

Written 2026-07-19, at extraction from the `command_center` monorepo. Everything
here was found, not introduced. Nothing in this list was silently fixed: the
extraction changed packaging, not behaviour.

Ordered by what would embarrass you most if a sharp interviewer found it first.

---

## 1. The published narrative claims things the code does not do

These matter more than ordinary bugs. A portfolio piece that overstates is worse
than one that under-delivers, because the overstatement is the thing being
evaluated.

**The lineage diagram is wrong.** `docs/source-pages/pipeline.astro` draws
`dim_models_sf`, `dim_date_sf` and `dim_endpoints_sf` as distinct snowflake nodes.
Those files do not exist — `fct_api_requests_sf.sql` references the star's
`dim_models`, `dim_date`, `dim_endpoints`. `models.astro` gets this right and says
"shared with star schema", so the two pages contradict each other.

**The snowflake model count is inflated.** `models.astro` says "MODELS: 7 (1 fact +
6 dimensions)". Four snowflake model files exist; the other three are the star's,
counted twice. The 14-model total elsewhere is correct.

**"99.9% Uptime" is a hardcoded literal** on the index page with nothing measuring
it. Either measure it or delete it.

**Decide, then act:** make the claim true or stop making it. `docs/CASE_STUDY.md`
has been written to describe what the code actually does.

## 2. The forecaster has dead database wiring

`app/app.py` contains no `psycopg2` import and opens no connection — the forecaster
is entirely parametric, computing from slider inputs. Yet:

- `app/requirements.txt` ships `psycopg2-binary`
- the compose service injects five `PORTFOLIO_DB_*` variables
- `depends_on: db (service_healthy)` gates startup on a database it never queries

So the app refuses to start until Postgres is healthy, for no reason. Either wire
it to real data (which would make it a much stronger demo — it currently forecasts
from assumptions while a 500K-row fact table sits next to it), or cut the
dependency, the env vars and the driver.

The extraction kept the wiring as-is so the change is yours to make deliberately.

*(Resolved 2026-07-19: the forecaster now reads the star schema as
`portfolio_reader` — observed model mix, token averages, and request rates
become a "TELEMETRY (OBSERVED)" preset — and degrades to parametric mode when
the database is absent. See `app/db.py` and its test suite.)*

## 3. Token pricing has three sources of truth

| Where | What |
|---|---|
| `data/generate_data.py` → `MODELS` | 5 models with per-token prices |
| `app/app.py` → `MODEL_CATALOG` | 3 models, comment says "mirrors generate_data.py" |
| `dbt/models/marts/star/dim_models.sql` | prices again, via the loaded table |

The app's copy is already stale — missing `claude-2.1` and `claude-instant-1.2`.
This is the [STD-03] rule-of-three trigger. One source, derived everywhere else.

*(Resolved 2026-07-19: `data/model_catalog.csv` is now the single source. The
generator reads it, the loader ships it to `raw_staging.models` (whence
`dim_models`), and the app loads it via `app/catalog.py`. No hardcoded copy
remains.)*

## 4. Test coverage is thin and lopsided

The only Python tests are `app/tests/test_theme_forecaster.py`, and they cover
`theme.py` exclusively — an XSS/CSS-injection suite asserting that malicious hex
input cannot escape into `unsafe_allow_html`. It is a genuinely good suite.

Nothing covers `compute_forecast`, `compute_latency_risk`, `format_number`, the
generator distributions, or the loader. The forecaster's arithmetic — the thing a
visitor actually interacts with — is untested.

dbt is in better shape: 143 declarative tests across the three `schema.yml` files.

*(Mostly resolved 2026-07-19: forecast arithmetic, catalog loading, DB-baseline
shaping, and the generator's statistical distributions are now covered —
151 Python tests total. Still open: the loader has only CI integration
coverage, no unit tests.)*

## 5. Python versions disagree

`app/Dockerfile` is `python:3.11-slim`. `data/Dockerfile` is `python:3.12-slim`.
The monorepo's CI pinned 3.11 while local runs used 3.12. Pick one.

*(Resolved 2026-07-19: 3.12 everywhere — both Dockerfiles and all CI jobs.)*

## 6. Known upstream CVEs, accepted rather than fixed

From the monorepo's `docs/KNOWN_ISSUES.md`, carried forward:

- dbt transitive deps: CVE-2026-29790 (dbt-common 1.27.1), CVE-2025-58367
  (deepdiff 7.0.1). Cannot upgrade without breaking dbt-core 1.9.4's `protobuf<6.0`
  constraint.
- Metabase v0.59.1 image: 1 CRITICAL (zlib CVE-2026-22184) + 6 HIGH, unfixable
  upstream at that version.

Metabase is not part of this extraction — the BI layer was shared infrastructure.
If this project needs a dashboard, that is a decision to make fresh.

## 7. What the extraction deliberately did not bring

- **Metabase.** One shared instance served all three data projects. Re-adding BI
  here is a fresh decision, not a port.
- **Traefik / nginx.** The monorepo's public ingress. This project now publishes a
  local port directly; production ingress is a deployment concern.
- **`leaderboard/`.** A FastAPI arcade high-score service for the site's CTF
  easter egg. It was never part of this project despite living next door.
  *(Resolved 2026-07-19: the `leaderboard_writer` role and `game.scores` code
  is no longer present in `data/load_data.py` — verified by grep across the
  repo. The note below in the appendix is retained as written but is stale.)*
- **`dbt/profiles.yml`.** It contained a plaintext dev password. Write your own
  from the example; it is gitignored.
- **`data/generated/*.csv`.** Committed CSV output in the monorepo. Regenerate
  instead: `docker compose --profile seed up`.

## 8. The strongest material here, for when you write it up

Two things are genuinely good and should be led with, not buried:

**The star-vs-snowflake `EXPLAIN ANALYZE` comparison.** Real measured numbers:
star cost-by-model 197ms (1 join), snowflake cost-by-industry 206ms (3 joins, no
parallelism), star cost-by-industry 51ms — 4× faster because industry is
denormalised into `dim_users`. That is the Kimball trade-off demonstrated rather
than asserted.

**The `dim_companies` fan-out bug.** `SELECT DISTINCT company_name, industry`
returned 6,457 rows instead of ~4,900 because the generator assigned multiple
industries to the same company name, silently inflating the fact table from 500K to
640K rows. The `unique` test on `company_key` caught it; fixed with
`mode() WITHIN GROUP`. A test catching a silent data-correctness bug is the most
persuasive story in the whole project.

---

## Appendix: what the extraction had to repair

Recorded separately from the inherited state above, because these are changes made
on 2026-07-19 rather than problems still waiting for you.

The monorepo's packaging did not survive the split, and fixing it surfaced one real
bug that was invisible while every project shared one database.

**The loader hardcoded the database name in its GRANT statements.**
`data/load_data.py` granted `CONNECT ON DATABASE command_center` as a literal, in
two places, while connecting to whatever `--dbname` said. Inside the monorepo those
were always the same string, so the bug could not fire. Extracted, the load
succeeded and then failed at role creation against a database that does not exist.
Now uses `conn.info.dbname`, so the grant follows the connection.

That is the general shape of what a split is good for: assumptions that were true
by coincidence stop being true, and say so.

**Packaging changes made:**

- `data/Dockerfile` copied six generators and a shared `seed.sh` orchestrating all
  three projects. Now copies this project's directory only.
- `data/seed.sh` written fresh: validates required environment, generates, loads,
  and prints the grant-ordering warning.
- `dbt/profiles.docker.yml` written for this project, reading `DBT_*` from the
  environment. `dbt/profiles.yml.example` added for local runs; `profiles.yml`
  itself is gitignored, because the monorepo's copy carried a plaintext password.
- `docker-compose.yml` written fresh, with its own Postgres on `127.0.0.1:55432`
  so all four extracted projects and the portfolio can run simultaneously.

**Verified working after these changes**, from an empty volume:
`docker compose up -d db` then `--profile seed run seed` (500K rows generated,
loaded, `portfolio_reader` created and its SELECT-only permissions asserted) then
`--profile seed run dbt` — **PASS=157, ERROR=0**: 9 tables, 5 views, 143 data tests.

**Still outstanding:** ~~`data/load_data.py` also creates the `leaderboard_writer`
role and the `game.scores` table for the site's CTF arcade feature, which has
nothing to do with this project. `data/seed.sh` therefore passes a throwaway
password to satisfy the argument. Delete that code path.~~ *(Resolved
2026-07-19: verified absent from the loader and seed script.)*


---

## Appendix: the app assumed it was behind a reverse proxy

Added 2026-07-19, during verification.

`app/.streamlit/config.toml` hardcoded `baseUrlPath = "forecaster"`. That was correct
inside the monorepo, where Traefik routed `/forecaster` to this container, and wrong
everywhere else: standalone, the app answered 404 at `/` and only worked if you
happened to know the prefix. The container healthcheck had the same path baked in.

An app that only starts correctly in one deployment is not portable, so the path is
now supplied by `STREAMLIT_SERVER_BASE_URL_PATH`, defaulting to empty:

- standalone, `APP_BASE_PATH=` (the default) serves at `http://localhost:8501/`
- behind a proxy, `APP_BASE_PATH=forecaster` restores the old behaviour

The healthcheck reads the same variable, so it follows whichever is configured.

**Verified both ways** on `andvari`: root serves 200 and reports healthy; with the
prefix set, `/forecaster/` serves and `/` correctly 404s, and the container still
reports healthy.

**App test suite:** passes. It covers `theme.py` only -- the palette resolver and
its hex allowlist, asserting that injected CSS cannot escape into
`unsafe_allow_html`. Good tests, narrow scope; see the coverage note above.
