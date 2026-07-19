"""
Andvari: star-vs-snowflake query benchmark

Reruns the case study's EXPLAIN ANALYZE comparison so the published numbers
are a command, not a claim. Each query answers the same business question
against both marts; the star's denormalised dim_users is why "cost by
industry" needs one join instead of three.

Usage (against the compose stack):
    python benchmark_star_vs_snowflake.py [--runs 5]

Connection comes from PORTFOLIO_DB_* environment variables (or .env), the
same convention as the loader. Read-only: every statement is a SELECT under
EXPLAIN, so the SELECT-only portfolio_reader role is sufficient.
"""

import argparse
import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():  # local-dev convenience only; production injects env, no .env present
    load_dotenv(_env_path)

QUERIES = [
    {
        "label": "Cost by model (star, 1 join)",
        "sql": """
select
    m.model_id
    , sum(f.cost_usd) as total_cost_usd
from public_star.fct_api_requests as f
inner join public_star.dim_models as m
    on f.model_key = m.model_key
group by m.model_id
""",
    },
    {
        "label": "Cost by industry (star, 1 join)",
        "sql": """
select
    u.industry
    , sum(f.cost_usd) as total_cost_usd
from public_star.fct_api_requests as f
inner join public_star.dim_users as u
    on f.user_key = u.user_key
group by u.industry
""",
    },
    {
        "label": "Cost by industry (snowflake, 3 joins)",
        "sql": """
select
    c.industry
    , sum(f.cost_usd) as total_cost_usd
from public_snowflake.fct_api_requests_sf as f
inner join public_snowflake.dim_users_sf as u
    on f.user_key = u.user_key
inner join public_snowflake.dim_companies as c
    on u.company_key = c.company_key
group by c.industry
""",
    },
]


def execution_time_ms(explain_json: list) -> float:
    """Pull the executor time from an EXPLAIN (ANALYZE, FORMAT JSON) result."""
    return float(explain_json[0]["Execution Time"])


def median(samples: list[float]) -> float:
    ordered = sorted(samples)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def benchmark(conn, sql: str, runs: int) -> list[float]:
    """One warmup (populates cache, discarded) then the measured runs."""
    times = []
    with conn.cursor() as cur:
        for i in range(runs + 1):
            cur.execute(f"explain (analyze, format json) {sql}")
            elapsed = execution_time_ms(cur.fetchone()[0])
            if i > 0:
                times.append(elapsed)
    return times


def main():
    parser = argparse.ArgumentParser(description="Rerun the star-vs-snowflake comparison")
    parser.add_argument("--runs", type=int, default=5, help="Measured runs per query")
    # PORTFOLIO_DB_* is the container convention; DB_* is what .env defines
    # for the compose stack, so a host-side run works from a plain checkout.
    parser.add_argument("--host", default=os.getenv("PORTFOLIO_DB_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=os.getenv("PORTFOLIO_DB_PORT", "55432"))
    parser.add_argument(
        "--user",
        default=os.getenv("PORTFOLIO_DB_USER") or os.getenv("DB_USER", "andvari_admin"),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("PORTFOLIO_DB_PASSWORD") or os.getenv("DB_PASSWORD", ""),
    )
    parser.add_argument(
        "--dbname",
        default=os.getenv("PORTFOLIO_DB_NAME") or os.getenv("DB_NAME", "andvari"),
    )
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=args.host, port=args.port,
        user=args.user, password=args.password,
        dbname=args.dbname,
    )
    conn.autocommit = True

    print(f"Median of {args.runs} runs (1 discarded warmup), EXPLAIN ANALYZE executor time:\n")
    print("| Query | Median (ms) |")
    print("|---|---|")
    for q in QUERIES:
        times = benchmark(conn, q["sql"], args.runs)
        print(f"| {q['label']} | {median(times):.0f} |")

    conn.close()
    print("\nNumbers vary by host; the ordering is the point, not the digits.")


if __name__ == "__main__":
    main()
