# ============================================================
#  file:       data/grant_reader_access.py
#  purpose:    post-dbt grant reconciliation for the read-only reader role
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-05]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
"""
Andvari: post-dbt permission grant
Grants portfolio_reader SELECT on all dbt-created schemas.

Must be run AFTER dbt build completes, because dbt creates schemas with
a 'public_' prefix (e.g., public_star) that don't exist until dbt
materializes models. load_data.py pre-creates these schemas with default
privileges, so this script is a reconciliation pass: it catches tables
created by a different role than the one that set those defaults.

Usage:
    python grant_reader_access.py [--host HOST] [--port PORT]
"""

import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():  # local-dev convenience only; production injects env, no .env present
    load_dotenv(_env_path)
from psycopg2 import sql

# All schemas that portfolio_reader should have SELECT on
DBT_SCHEMAS = [
    "public_staging",
    "public_star",
    "public_snowflake",
]


def main():
    parser = argparse.ArgumentParser(description="Grant portfolio_reader on dbt schemas")
    parser.add_argument("--host", default=os.getenv("PORTFOLIO_DB_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=os.getenv("PORTFOLIO_DB_PORT", "5432"))
    parser.add_argument("--user", default=os.getenv("PORTFOLIO_DB_USER", "andvari_admin"))
    parser.add_argument("--password", default=os.getenv("PORTFOLIO_DB_PASSWORD", ""))
    parser.add_argument("--dbname", default=os.getenv("PORTFOLIO_DB_NAME", "andvari"))
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=args.host, port=args.port,
        user=args.user, password=args.password,
        dbname=args.dbname
    )
    conn.autocommit = True
    cur = conn.cursor()

    print("Granting portfolio_reader access on dbt schemas...")
    for schema in DBT_SCHEMAS:
        # Check if schema exists
        cur.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)
        )
        if not cur.fetchone():
            print(f"  SKIP {schema} (does not exist)")
            continue

        cur.execute(sql.SQL(
            "GRANT USAGE ON SCHEMA {} TO portfolio_reader"
        ).format(sql.Identifier(schema)))
        cur.execute(sql.SQL(
            "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO portfolio_reader"
        ).format(sql.Identifier(schema)))
        cur.execute(sql.SQL(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
            "GRANT SELECT ON TABLES TO portfolio_reader"
        ).format(sql.Identifier(schema)))
        # Count accessible tables
        cur.execute(
            "SELECT COUNT(*) FROM pg_tables WHERE schemaname = %s", (schema,)
        )
        count = cur.fetchone()[0]
        print(f"  OK {schema} ({count} tables)")

    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
