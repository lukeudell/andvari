# ============================================================
#  file:       data/load_data.py
#  purpose:    loads generated CSVs into raw_staging and creates the read-only role
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-05] [STD-13]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
"""
Andvari: data loader
Creates raw staging schema in PostgreSQL and loads generated CSVs.
Also reconciles the reader role's SELECT-only access (READER_DB_USER; created only standalone).

Usage:
    python load_data.py [--host 127.0.0.1] [--port 5432]
                        [--user andvari_admin] [--password X]
                        [--dbname andvari]

Environment variables (fallback):
    PORTFOLIO_DB_HOST, PORTFOLIO_DB_PORT, PORTFOLIO_DB_USER,
    PORTFOLIO_DB_PASSWORD, PORTFOLIO_DB_NAME
"""

import argparse
import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

# Load .env from project root so DB credentials are available
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():  # local-dev convenience only; production injects env, no .env present
    load_dotenv(_env_path)
from psycopg2 import sql

CSV_DIR = Path(__file__).parent / "generated"
STAGING_SCHEMA = "raw_staging"


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

STAGING_TABLES = {
    "api_requests": """
        CREATE TABLE IF NOT EXISTS {schema}.api_requests (
            request_id      VARCHAR(20) PRIMARY KEY,
            user_id         VARCHAR(20) NOT NULL,
            model_id        VARCHAR(50) NOT NULL,
            endpoint_path   VARCHAR(100) NOT NULL,
            request_timestamp TIMESTAMP NOT NULL,
            latency_ms      NUMERIC(10, 1) NOT NULL,
            tokens_input    INTEGER NOT NULL,
            tokens_output   INTEGER NOT NULL,
            tokens_total    INTEGER NOT NULL,
            cost_usd        NUMERIC(12, 6) NOT NULL,
            http_status     SMALLINT NOT NULL,
            safety_flag     BOOLEAN NOT NULL
        )
    """,
    "users": """
        CREATE TABLE IF NOT EXISTS {schema}.users (
            user_id       VARCHAR(20) PRIMARY KEY,
            billing_tier  VARCHAR(20) NOT NULL,
            company_name  VARCHAR(200) NOT NULL,
            industry      VARCHAR(100) NOT NULL,
            signup_date   DATE NOT NULL,
            region        VARCHAR(50) NOT NULL
        )
    """,
    "models": """
        CREATE TABLE IF NOT EXISTS {schema}.models (
            model_id              VARCHAR(50) PRIMARY KEY,
            model_family          VARCHAR(50) NOT NULL,
            cost_per_input_token  NUMERIC(12, 10) NOT NULL,
            cost_per_output_token NUMERIC(12, 10) NOT NULL,
            context_window_k      INTEGER NOT NULL,
            is_active             BOOLEAN NOT NULL
        )
    """,
    "endpoints": """
        CREATE TABLE IF NOT EXISTS {schema}.endpoints (
            endpoint_path VARCHAR(100) PRIMARY KEY,
            api_version   VARCHAR(10) NOT NULL,
            is_deprecated BOOLEAN NOT NULL
        )
    """,
    "dates": """
        CREATE TABLE IF NOT EXISTS {schema}.dates (
            date_key     INTEGER PRIMARY KEY,
            full_date    DATE NOT NULL,
            day_of_week  VARCHAR(10) NOT NULL,
            is_weekend   BOOLEAN NOT NULL,
            week_of_year SMALLINT NOT NULL,
            month_name   VARCHAR(10) NOT NULL,
            quarter      VARCHAR(5) NOT NULL,
            year         SMALLINT NOT NULL
        )
    """,
}


def get_connection(args):
    """Create a database connection from args or environment variables."""
    return psycopg2.connect(
        host=args.host or os.getenv("PORTFOLIO_DB_HOST", "127.0.0.1"),
        port=args.port or os.getenv("PORTFOLIO_DB_PORT", "5432"),
        user=args.user or os.getenv("PORTFOLIO_DB_USER", "andvari_admin"),
        password=args.password or os.getenv("PORTFOLIO_DB_PASSWORD"),
        dbname=args.dbname or os.getenv("PORTFOLIO_DB_NAME", "andvari"),
    )


def create_schema_and_tables(conn):
    """Create the staging schema and all tables."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
            sql.Identifier(STAGING_SCHEMA)
        ))

        for table_name, ddl_template in STAGING_TABLES.items():
            # Drop and recreate for idempotent loads
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                sql.Identifier(STAGING_SCHEMA),
                sql.Identifier(table_name),
            ))
            ddl = ddl_template.replace("{schema}", STAGING_SCHEMA)
            cur.execute(ddl)
            print(f"  Created {STAGING_SCHEMA}.{table_name}")

    conn.commit()


def load_csv(conn, table_name: str, csv_path: Path):
    """Load a CSV into a staging table using COPY for performance."""
    with conn.cursor() as cur:
        with open(csv_path, "r", encoding="utf-8") as f:
            # Skip header, use COPY for bulk load
            cur.copy_expert(
                sql.SQL("COPY {}.{} FROM STDIN WITH (FORMAT csv, HEADER true)").format(
                    sql.Identifier(STAGING_SCHEMA),
                    sql.Identifier(table_name),
                ).as_string(conn),
                f,
            )
    conn.commit()


def verify_row_counts(conn):
    """Print row counts for all staging tables."""
    print("\n--- Row Count Verification ---")
    with conn.cursor() as cur:
        for table_name in STAGING_TABLES:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(STAGING_SCHEMA),
                sql.Identifier(table_name),
            ))
            count = cur.fetchone()[0]
            print(f"  {STAGING_SCHEMA}.{table_name}: {count:,} rows")


def ensure_reader_access(conn, reader_role: str, reader_password: str):
    """
    Grant SELECT-only access to the reader role, creating it only when absent.

    On the portfolio platform the role already exists: the connector provisions
    demo_<slug>_ro and this loader's account deliberately lacks CREATEROLE, so a
    plugged-in project must never manage roles (the content contract's rule).
    Standalone, the role is absent on first run and is created here.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (reader_role,))
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(reader_role), sql.Literal(reader_password)
                )
            )
            print(f"  Created role: {reader_role} (standalone mode)")
        else:
            print(f"  Role {reader_role} exists; granting only, never recreating")

        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(conn.info.dbname), sql.Identifier(reader_role)
        ))

        for schema in [STAGING_SCHEMA, "public", "public_staging", "public_star", "public_snowflake"]:
            cur.execute(sql.SQL(
                "CREATE SCHEMA IF NOT EXISTS {}"
            ).format(sql.Identifier(schema)))
            cur.execute(sql.SQL(
                "GRANT USAGE ON SCHEMA {} TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(reader_role)))
            cur.execute(sql.SQL(
                "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(reader_role)))
            cur.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                "GRANT SELECT ON TABLES TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(reader_role)))

        print(f"\n  Reader access reconciled for: {reader_role} (SELECT only)")

    conn.commit()


def verify_reader_permissions(conn, reader_role: str):
    """
    Verify the reader can SELECT and cannot write, via catalog checks.

    Asked of the catalog rather than proven by logging in: on the platform the
    reader's password is sealed by the connector and is none of this loader's
    business, so a connection test would fail for the wrong reason there.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege(%s, %s, 'SELECT'),"
            "       has_table_privilege(%s, %s, 'INSERT')",
            (reader_role, f"{STAGING_SCHEMA}.api_requests",
             reader_role, f"{STAGING_SCHEMA}.api_requests"),
        )
        can_select, can_insert = cur.fetchone()
        print(f"  [{'PASS' if can_select else 'FAIL'}] {reader_role} can SELECT")
        print(f"  [{'PASS' if not can_insert else 'FAIL'}] {reader_role} cannot INSERT")
        if not can_select or can_insert:
            raise RuntimeError(f"reader privileges are wrong for {reader_role}")


def main():
    parser = argparse.ArgumentParser(description="Load generated CSVs into PostgreSQL staging")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--dbname", default=None)
    parser.add_argument(
        "--reader-password",
        default=os.getenv("STREAMLIT_DB_PASSWORD"),
        help="Reader password, used only if the role must be created standalone",
    )
    args = parser.parse_args()

    if not args.reader_password:
        parser.error("--reader-password is required (or set STREAMLIT_DB_PASSWORD env var)")

    conn = get_connection(args)
    conn.autocommit = False

    print("Creating staging schema and tables...")
    create_schema_and_tables(conn)

    # Load each CSV
    csv_table_map = {
        "users.csv": "users",
        "models.csv": "models",
        "endpoints.csv": "endpoints",
        "dates.csv": "dates",
        "api_requests.csv": "api_requests",
    }

    print("\nLoading CSVs...")
    for csv_file, table_name in csv_table_map.items():
        csv_path = CSV_DIR / csv_file
        if not csv_path.exists():
            print(f"  [SKIP] {csv_file} not found, run generate_data.py first")
            continue
        load_csv(conn, table_name, csv_path)
        print(f"  Loaded {csv_file} -> {STAGING_SCHEMA}.{table_name}")

    verify_row_counts(conn)

    # --- Reader access (grants always; creation only standalone) ---

    reader_role = os.getenv("READER_DB_USER", "portfolio_reader")
    print(f"\nReconciling reader access for {reader_role}...")
    ensure_reader_access(conn, reader_role, args.reader_password)

    # --- Verification (non-critical: failures logged but don't block) ---

    print(f"\nVerifying {reader_role} permissions...")
    try:
        verify_reader_permissions(conn, reader_role)
    except Exception as e:
        print(f"  [WARN] Reader verification failed (non-blocking): {e}")

    conn.close()
    print("\nPhase 1 data load complete.")


if __name__ == "__main__":
    main()
