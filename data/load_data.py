"""
Andvari: data loader
Creates raw staging schema in PostgreSQL and loads generated CSVs.
Also creates the portfolio_reader role with SELECT-only access.

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


def create_reader_role(conn, reader_password: str):
    """
    Create portfolio_reader role with SELECT-only access.
    Idempotent: drops and recreates if exists.
    """
    with conn.cursor() as cur:
        # Check if role exists
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'portfolio_reader'")
        if cur.fetchone():
            # Revoke and drop existing
            # why: reassign to whoever we are actually connected as, not a hardcoded
            # name. In the monorepo the admin was always called portfolio_admin, so
            # the literal worked by coincidence; extracted, each project has its own
            # owner and re-running the loader failed on the second attempt.
            cur.execute(
                sql.SQL("REASSIGN OWNED BY portfolio_reader TO {}").format(
                    sql.Identifier(conn.info.user)
                )
            )
            cur.execute("DROP OWNED BY portfolio_reader")
            cur.execute("DROP ROLE portfolio_reader")

        cur.execute(
            sql.SQL("CREATE ROLE portfolio_reader WITH LOGIN PASSWORD {}").format(
                sql.Literal(reader_password)
            )
        )

        # Grant CONNECT on database
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO portfolio_reader").format(
            sql.Identifier(conn.info.dbname)
        ))

        # Grant USAGE on staging schema
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO portfolio_reader").format(
            sql.Identifier(STAGING_SCHEMA)
        ))

        # Grant SELECT on all tables in staging
        cur.execute(sql.SQL(
            "GRANT SELECT ON ALL TABLES IN SCHEMA {} TO portfolio_reader"
        ).format(sql.Identifier(STAGING_SCHEMA)))

        # Default privileges for future tables
        cur.execute(sql.SQL(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
            "GRANT SELECT ON TABLES TO portfolio_reader"
        ).format(sql.Identifier(STAGING_SCHEMA)))

        # Grant on public schema and dbt-created schemas
        for schema in ["public", "public_staging", "public_star", "public_snowflake"]:
            cur.execute(sql.SQL(
                "CREATE SCHEMA IF NOT EXISTS {}"
            ).format(sql.Identifier(schema)))
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

        print("\n  Created role: portfolio_reader (SELECT only)")

    conn.commit()


def verify_reader_permissions(conn_args, reader_password: str):
    """Verify portfolio_reader can SELECT but cannot write."""
    reader_conn = psycopg2.connect(
        host=conn_args.host or os.getenv("PORTFOLIO_DB_HOST", "127.0.0.1"),
        port=conn_args.port or os.getenv("PORTFOLIO_DB_PORT", "5432"),
        user="portfolio_reader",
        password=reader_password,
        dbname=conn_args.dbname or os.getenv("PORTFOLIO_DB_NAME", "andvari"),
    )
    reader_conn.autocommit = True

    with reader_conn.cursor() as cur:
        # Should succeed: SELECT
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.api_requests").format(
            sql.Identifier(STAGING_SCHEMA)
        ))
        count = cur.fetchone()[0]
        print(f"  [PASS] portfolio_reader can SELECT ({count:,} rows)")

        # Should fail: INSERT
        try:
            cur.execute(
                sql.SQL(
                    "INSERT INTO {}.users (user_id, billing_tier, company_name, "
                    "industry, signup_date, region) "
                    "VALUES ('test', 'Free', 'Test', 'Test', '2026-01-01', 'us-east')"
                ).format(sql.Identifier(STAGING_SCHEMA))
            )
            print("  [FAIL] portfolio_reader was able to INSERT (should be denied)")
        except psycopg2.errors.InsufficientPrivilege:
            print("  [PASS] portfolio_reader cannot INSERT (permission denied)")

        # Should fail: DELETE
        try:
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE user_id = 'test'").format(
                sql.Identifier(STAGING_SCHEMA)
            ))
            print("  [FAIL] portfolio_reader was able to DELETE (should be denied)")
        except psycopg2.errors.InsufficientPrivilege:
            print("  [PASS] portfolio_reader cannot DELETE (permission denied)")

    reader_conn.close()


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
        help="Password for portfolio_reader role (or set STREAMLIT_DB_PASSWORD env var)",
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

    # --- Role creation (order matters: create all roles before verification) ---

    print("\nCreating portfolio_reader role...")
    create_reader_role(conn, args.reader_password)

    # --- Verification (non-critical: failures logged but don't block) ---

    print("\nVerifying portfolio_reader permissions...")
    try:
        verify_reader_permissions(args, args.reader_password)
    except Exception as e:
        print(f"  [WARN] Reader verification failed (non-blocking): {e}")

    conn.close()
    print("\nPhase 1 data load complete.")


if __name__ == "__main__":
    main()
