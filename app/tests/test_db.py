"""
Tests for the telemetry-baseline module (db.py) — the piece that turns the
500K-row star schema into calibrated forecaster defaults.

The row-shaping logic is pure and tested exactly; the connection path is
tested with injected fakes, never a live database ([STD-02]: unit tests use
fakes, integration against real Postgres happens in CI's pipeline job).
"""

import importlib.util
import pathlib

import pytest

_DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "db.py"
_spec = importlib.util.spec_from_file_location("db_forecaster", _DB_PATH)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

CATALOG_IDS = {"claude-3-opus", "claude-3-sonnet", "claude-3-haiku"}

STATS = {
    "n_requests": 45_000,
    "n_users": 300,
    "n_days": 30,
    "avg_tokens_input": 512.4,
    "avg_tokens_output": 341.7,
}

MIX_ROWS = [
    ("claude-3-opus", 4_500),
    ("claude-3-sonnet", 15_750),
    ("claude-3-haiku", 24_750),
]


class TestShapeBaseline:
    def test_happy_path_shapes_all_fields(self):
        b = db.shape_baseline(STATS, MIX_ROWS, CATALOG_IDS)
        assert b["mau"] == 300
        # 45_000 / 300 users / 30 days = 5 requests/user/day
        assert b["requests_per_user_day"] == 5
        assert b["model_mix"] == {
            "claude-3-opus": 10, "claude-3-sonnet": 35, "claude-3-haiku": 55,
        }
        assert b["n_requests"] == 45_000
        assert b["window_days"] == 30

    def test_mix_always_sums_to_exactly_100(self):
        # The UI hard-stops unless the mix sums to 100; naive rounding of
        # thirds gives 33+33+33=99. Largest-remainder must repair that.
        rows = [("claude-3-opus", 1), ("claude-3-sonnet", 1), ("claude-3-haiku", 1)]
        mix = db.shape_baseline(STATS, rows, CATALOG_IDS)["model_mix"]
        assert sum(mix.values()) == 100

    def test_avg_tokens_snap_to_slider_steps(self):
        b = db.shape_baseline(STATS, MIX_ROWS, CATALOG_IDS)
        # sliders run 50..10_000 step 50
        assert b["avg_input_tokens"] % 50 == 0
        assert b["avg_output_tokens"] % 50 == 0
        assert b["avg_input_tokens"] == 500
        assert b["avg_output_tokens"] == 350

    def test_avg_tokens_clamped_to_slider_floor(self):
        stats = dict(STATS, avg_tokens_input=3.2, avg_tokens_output=1.0)
        b = db.shape_baseline(stats, MIX_ROWS, CATALOG_IDS)
        assert b["avg_input_tokens"] == 50
        assert b["avg_output_tokens"] == 50

    def test_requests_per_day_clamped_to_slider_range(self):
        heavy = dict(STATS, n_requests=3_000_000)  # 333/user/day
        assert db.shape_baseline(heavy, MIX_ROWS, CATALOG_IDS)["requests_per_user_day"] == 100
        light = dict(STATS, n_requests=10)
        assert db.shape_baseline(light, MIX_ROWS, CATALOG_IDS)["requests_per_user_day"] == 1

    def test_models_outside_catalog_are_dropped_and_renormalised(self):
        rows = MIX_ROWS + [("claude-2.1", 45_000)]  # retired model, half of traffic
        mix = db.shape_baseline(STATS, rows, CATALOG_IDS)["model_mix"]
        assert set(mix) == CATALOG_IDS
        assert sum(mix.values()) == 100

    def test_empty_stats_returns_none(self):
        assert db.shape_baseline(dict(STATS, n_users=0), MIX_ROWS, CATALOG_IDS) is None
        assert db.shape_baseline(dict(STATS, n_days=0), MIX_ROWS, CATALOG_IDS) is None

    def test_no_catalog_traffic_returns_none(self):
        assert db.shape_baseline(STATS, [("claude-2.1", 9)], CATALOG_IDS) is None


class _FakeCursor:
    def __init__(self, stats_row, mix_rows):
        self._stats_row = stats_row
        self._mix_rows = mix_rows
        self._last = None

    def execute(self, query, *args):
        self._last = "mix" if "group by" in query.lower() else "stats"

    def fetchone(self):
        return self._stats_row

    def fetchall(self):
        return self._mix_rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, stats_row, mix_rows):
        self._cursor = _FakeCursor(stats_row, mix_rows)
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class TestFetchBaseline:
    def test_connection_error_returns_none(self):
        def refuse(**kwargs):
            raise db.psycopg2.OperationalError("connection refused")
        assert db.fetch_baseline(CATALOG_IDS, connect=refuse) is None

    def test_missing_password_returns_none(self, monkeypatch):
        monkeypatch.delenv("PORTFOLIO_DB_PASSWORD", raising=False)
        def explode(**kwargs):  # must never be called without credentials
            raise AssertionError("attempted connection without credentials")
        assert db.fetch_baseline(CATALOG_IDS, connect=explode) is None

    def test_happy_path_returns_shaped_baseline(self, monkeypatch):
        monkeypatch.setenv("PORTFOLIO_DB_PASSWORD", "x")
        stats_row = (45_000, 300, 30, 512.4, 341.7)
        conn = _FakeConn(stats_row, MIX_ROWS)
        baseline = db.fetch_baseline(CATALOG_IDS, connect=lambda **kw: conn)
        assert baseline is not None
        assert baseline["mau"] == 300
        assert baseline["requests_per_user_day"] == 5
        assert conn.closed  # no leaked connections

    def test_empty_fact_table_returns_none(self, monkeypatch):
        monkeypatch.setenv("PORTFOLIO_DB_PASSWORD", "x")
        conn = _FakeConn((0, 0, 0, None, None), [])
        assert db.fetch_baseline(CATALOG_IDS, connect=lambda **kw: conn) is None
