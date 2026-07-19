"""
Telemetry baseline for the Token Forecaster.

Reads the star schema (as the SELECT-only portfolio_reader role) and turns
observed traffic into calibrated slider defaults: real model mix, real token
averages, real request rates — instead of guessed ones. Every failure path
(no credentials, database down, empty warehouse) degrades to None and the app
falls back to parametric mode; a forecaster must never crash because the
database is absent.
"""

import os

import psycopg2

# Slider bounds mirrored from the UI; a baseline outside them would render an
# invalid widget default and crash the page.
_RPD_MIN, _RPD_MAX = 1, 100
_TOKENS_MIN, _TOKENS_MAX, _TOKENS_STEP = 50, 10_000, 50

_STATS_QUERY = """
with requests as (
    select f.user_key
         , f.tokens_input
         , f.tokens_output
         , f.request_timestamp
    from public_star.fct_api_requests as f
)
select count(*)                                          as n_requests
     , count(distinct r.user_key)                        as n_users
     , count(distinct cast(r.request_timestamp as date)) as n_days
     , avg(r.tokens_input)                               as avg_tokens_input
     , avg(r.tokens_output)                              as avg_tokens_output
from requests as r
"""

_MIX_QUERY = """
select m.model_id
     , count(*) as n_requests
from public_star.fct_api_requests as f
inner join public_star.dim_models as m
    on f.model_key = m.model_key
group by m.model_id
"""


def _snap(value: float, low: int, high: int, step: int = 1) -> int:
    snapped = round(value / step) * step
    return max(low, min(high, snapped))


def shape_baseline(stats: dict, mix_rows: list[tuple], catalog_ids: set) -> dict | None:
    """
    Turn raw aggregates into forecaster defaults. Pure — fully unit-testable.

    Returns None when the telemetry cannot support a calibration (empty
    warehouse, or no traffic on any model the catalog still offers).
    """
    if not stats["n_users"] or not stats["n_days"]:
        return None

    in_catalog = [(m, n) for m, n in mix_rows if m in catalog_ids]
    total = sum(n for _, n in in_catalog)
    if total == 0:
        return None

    # Largest-remainder rounding: integer percentages that sum to exactly 100,
    # because the UI refuses any mix that doesn't.
    exact = {m: n / total * 100 for m, n in in_catalog}
    floors = {m: int(v) for m, v in exact.items()}
    shortfall = 100 - sum(floors.values())
    by_remainder = sorted(exact, key=lambda m: exact[m] - floors[m], reverse=True)
    for m in by_remainder[:shortfall]:
        floors[m] += 1

    rpd = stats["n_requests"] / stats["n_users"] / stats["n_days"]
    return {
        "mau": int(stats["n_users"]),
        "requests_per_user_day": _snap(rpd, _RPD_MIN, _RPD_MAX),
        "avg_input_tokens": _snap(
            float(stats["avg_tokens_input"]), _TOKENS_MIN, _TOKENS_MAX, _TOKENS_STEP
        ),
        "avg_output_tokens": _snap(
            float(stats["avg_tokens_output"]), _TOKENS_MIN, _TOKENS_MAX, _TOKENS_STEP
        ),
        "model_mix": floors,
        "n_requests": int(stats["n_requests"]),
        "window_days": int(stats["n_days"]),
    }


def fetch_baseline(catalog_ids: set, connect=psycopg2.connect) -> dict | None:
    """
    Fetch and shape the telemetry baseline; None on any failure.

    ``connect`` is injectable for tests. Credentials come from the same
    PORTFOLIO_DB_* variables the compose stack injects; without a password we
    don't even attempt a connection — standalone runs stay silent and fast.
    """
    password = os.getenv("PORTFOLIO_DB_PASSWORD")
    if not password:
        return None

    try:
        conn = connect(
            host=os.getenv("PORTFOLIO_DB_HOST", "127.0.0.1"),
            port=os.getenv("PORTFOLIO_DB_PORT", "55432"),
            user=os.getenv("PORTFOLIO_DB_USER", "portfolio_reader"),
            password=password,
            dbname=os.getenv("PORTFOLIO_DB_NAME", "andvari"),
            connect_timeout=3,
        )
    except psycopg2.Error:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(_STATS_QUERY)
            n_requests, n_users, n_days, avg_in, avg_out = cur.fetchone()
            cur.execute(_MIX_QUERY)
            mix_rows = cur.fetchall()
    except psycopg2.Error:
        return None
    finally:
        conn.close()

    stats = {
        "n_requests": n_requests or 0,
        "n_users": n_users or 0,
        "n_days": n_days or 0,
        "avg_tokens_input": avg_in or 0,
        "avg_tokens_output": avg_out or 0,
    }
    return shape_baseline(stats, mix_rows, catalog_ids)
