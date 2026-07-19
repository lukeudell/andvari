# ============================================================
#  file:       app/tests/test_forecast.py
#  purpose:    pins the forecaster's growth, cost, and margin arithmetic
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-02]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
"""
Unit tests for the forecaster's arithmetic, the numbers a visitor actually
sees. Written before the extraction of ``forecast.py`` from ``app.py`` (TDD):
they pin the exact growth, cost, and margin behaviour the UI has shipped with.

Loads the sibling ``forecast.py`` by explicit path so the suite is independent
of sys.path / pytest rootdir, matching test_theme_forecaster.py.
"""

import importlib.util
import pathlib

import pytest

_FORECAST_PATH = pathlib.Path(__file__).resolve().parent.parent / "forecast.py"
_spec = importlib.util.spec_from_file_location("forecast_forecaster", _FORECAST_PATH)
forecast = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(forecast)


# A deliberately simple catalog so expected costs are hand-computable.
TOY_CATALOG = {
    "model-cheap": {"family": "toy", "cost_input": 0.000001, "cost_output": 0.000002, "label": "Cheap"},
    "model-dear": {"family": "toy", "cost_input": 0.00001, "cost_output": 0.00002, "label": "Dear"},
}


def _forecast(**overrides):
    """compute_forecast with boring defaults; override what the test cares about."""
    params = dict(
        catalog=TOY_CATALOG,
        mau=100,
        requests_per_user_day=10,
        avg_input_tokens=100,
        avg_output_tokens=50,
        model_mix={"model-cheap": 100},
        revenue_per_user_month=10.0,
        infra_overhead=1_000.0,
        months=12,
    )
    params.update(overrides)
    return forecast.compute_forecast(**params)


class TestComputeForecast:
    def test_returns_one_row_per_month(self):
        assert len(_forecast(months=12)) == 12
        assert len(_forecast(months=3)) == 3

    def test_column_order_is_stable(self):
        # app.py renames columns positionally for the display table; a silent
        # reorder would relabel every column without any error.
        df = _forecast()
        assert list(df.columns) == [
            "month", "active_users", "monthly_requests", "total_tokens",
            "total_input_tokens", "total_output_tokens", "cost_usd",
            "revenue_usd", "gross_margin_pct",
        ]

    def test_month_one_has_no_growth_applied(self):
        m1 = _forecast(mau=1234).iloc[0]
        assert m1["active_users"] == 1234
        assert m1["monthly_requests"] == 1234 * 10 * 30

    def test_growth_is_five_percent_compounding(self):
        df = _forecast(mau=1000, months=4)
        assert df.iloc[1]["active_users"] == int(1000 * 1.05)
        assert df.iloc[3]["active_users"] == int(1000 * 1.05 ** 3)

    def test_month_one_cost_is_exact(self):
        # 100 users x 10 req/day x 30 days = 30_000 requests, single model.
        # input: 30_000 * 100 tokens * 1e-6 = 3.0
        # output: 30_000 * 50 tokens * 2e-6 = 3.0
        # + overhead 1_000 (no step-up in month 1)
        m1 = _forecast().iloc[0]
        assert m1["cost_usd"] == pytest.approx(3.0 + 3.0 + 1_000.0)

    def test_model_mix_splits_requests(self):
        # 50/50 mix: cheap contributes 3.0, dear contributes 10x that of its
        # half: (15_000 * 100 * 1e-5) + (15_000 * 50 * 2e-5) = 15 + 15 = 30.
        # cheap half: 1.5 + 1.5 = 3.
        m1 = _forecast(model_mix={"model-cheap": 50, "model-dear": 50}).iloc[0]
        assert m1["cost_usd"] == pytest.approx(3.0 + 30.0 + 1_000.0)

    def test_overhead_steps_up_every_three_months(self):
        df = _forecast(avg_input_tokens=0, avg_output_tokens=0, infra_overhead=1_000.0, months=7)
        # months 1-3 flat, months 4-6 +10%, month 7 +21%
        assert df.iloc[0]["cost_usd"] == pytest.approx(1_000.0)
        assert df.iloc[2]["cost_usd"] == pytest.approx(1_000.0)
        assert df.iloc[3]["cost_usd"] == pytest.approx(1_100.0)
        assert df.iloc[6]["cost_usd"] == pytest.approx(1_210.0)

    def test_tokens_total_is_input_plus_output(self):
        df = _forecast()
        assert (df["total_tokens"] == df["total_input_tokens"] + df["total_output_tokens"]).all()

    def test_zero_revenue_does_not_divide_by_zero(self):
        df = _forecast(revenue_per_user_month=0.0)
        assert (df["gross_margin_pct"] == 0).all()

    def test_margin_formula(self):
        m1 = _forecast().iloc[0]
        expected = (m1["revenue_usd"] - m1["cost_usd"]) / m1["revenue_usd"] * 100
        assert m1["gross_margin_pct"] == pytest.approx(expected)

    def test_unknown_model_in_mix_raises(self):
        # A typo'd model id must fail loudly, not price silently at zero.
        with pytest.raises(KeyError):
            _forecast(model_mix={"model-nonexistent": 100})


class TestComputeLatencyRisk:
    def test_bounded_zero_to_one_hundred(self):
        assert forecast.compute_latency_risk(100, {"claude-3-opus": 100}) <= 100.0
        assert forecast.compute_latency_risk(1, {"claude-3-haiku": 100}) >= 0.0

    def test_heavier_models_score_higher(self):
        opus = forecast.compute_latency_risk(25, {"claude-3-opus": 100})
        haiku = forecast.compute_latency_risk(25, {"claude-3-haiku": 100})
        assert opus > haiku

    def test_monotonic_in_request_volume_until_cap(self):
        low = forecast.compute_latency_risk(10, {"claude-3-sonnet": 100})
        high = forecast.compute_latency_risk(40, {"claude-3-sonnet": 100})
        assert high > low

    def test_volume_factor_caps_at_fifty_per_day(self):
        at_cap = forecast.compute_latency_risk(50, {"claude-3-sonnet": 100})
        past_cap = forecast.compute_latency_risk(90, {"claude-3-sonnet": 100})
        assert at_cap == pytest.approx(past_cap)

    def test_known_value_full_opus_at_cap(self):
        # weight 3.0 * volume 1.0 * 100 / 3.0 == 100
        assert forecast.compute_latency_risk(50, {"claude-3-opus": 100}) == pytest.approx(100.0)

    def test_unknown_model_defaults_to_neutral_weight(self):
        neutral = forecast.compute_latency_risk(50, {"some-future-model": 100})
        assert neutral == pytest.approx(100.0 / 3.0)


class TestFormatNumber:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "0"),
            (999, "999"),
            (1_000, "1.0K"),
            (1_500, "1.5K"),
            (999_999, "1000.0K"),
            (1_000_000, "1.0M"),
            (2_340_000, "2.3M"),
            (1_000_000_000, "1.0B"),
            (7_654_000_000, "7.7B"),
            (-1_500, "-1.5K"),
            (-2_000_000, "-2.0M"),
        ],
    )
    def test_suffixes(self, value, expected):
        assert forecast.format_number(value) == expected
