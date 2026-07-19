# ============================================================
#  file:       data/tests/test_generate_data.py
#  purpose:    asserts the generator's distributions under the fixed seed
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-02] [STD-14]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
"""
Statistical property tests for the synthetic data generator.

The README claims the data is "not random noise": log-normal latency, Pareto
tokens, weighted status codes, Bernoulli safety flags. These tests assert those
properties hold under the fixed seed, so the claim is enforced rather than
narrated. Tolerances are wide enough to be seed-stable but tight enough to
catch a swapped distribution or a broken weight table.
"""

import importlib.util
import pathlib

import numpy as np
import pytest
from faker import Faker

_GENERATOR_PATH = pathlib.Path(__file__).resolve().parent.parent / "generate_data.py"
_spec = importlib.util.spec_from_file_location("generate_data_andvari", _GENERATOR_PATH)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

N_ROWS = 20_000
N_USERS = 300
DAYS = 30
SEED = 42


@pytest.fixture(scope="module")
def models():
    return gen.load_model_catalog()


@pytest.fixture(scope="module")
def users():
    rng = np.random.default_rng(SEED)
    fake = Faker()
    Faker.seed(SEED)
    return gen.generate_users(rng, fake, N_USERS)


@pytest.fixture(scope="module")
def facts(users, models):
    rng = np.random.default_rng(SEED)
    return gen.generate_facts(rng, N_ROWS, DAYS, users, models)


class TestModelCatalog:
    def test_five_models(self, models):
        assert len(models) == 5

    def test_traffic_weights_sum_to_one(self, models):
        assert sum(m["weight"] for m in models) == pytest.approx(1.0)

    def test_three_active_models(self, models):
        assert sum(1 for m in models if m["is_active"]) == 3

    def test_required_keys_present(self, models):
        required = {
            "model_id", "model_family", "cost_per_input_token",
            "cost_per_output_token", "context_window_k", "is_active", "weight",
        }
        for m in models:
            assert required <= set(m)

    def test_prices_are_positive_floats(self, models):
        for m in models:
            assert m["cost_per_input_token"] > 0
            assert m["cost_per_output_token"] > m["cost_per_input_token"]


class TestUsers:
    def test_row_count(self, users):
        assert len(users) == N_USERS

    def test_user_ids_unique(self, users):
        assert users["user_id"].is_unique

    def test_tiers_are_valid(self, users):
        assert set(users["billing_tier"]) <= set(gen.BILLING_TIERS)

    def test_free_tier_dominates(self, users):
        # 50% weight on Free; with 300 users, far from any other tier's share.
        counts = users["billing_tier"].value_counts(normalize=True)
        assert counts["Free"] > 0.35


class TestFactDistributions:
    def test_row_count_and_unique_ids(self, facts):
        assert len(facts) == N_ROWS
        assert facts["request_id"].is_unique

    def test_latency_is_lognormal_shaped(self, facts):
        # mu=6.5 -> median e^6.5 ~ 665ms; heavy right tail from sigma=0.8
        median = facts["latency_ms"].median()
        assert 500 <= median <= 800
        assert facts["latency_ms"].quantile(0.95) > 2 * median

    def test_latency_clamped(self, facts):
        assert facts["latency_ms"].min() >= 50
        assert facts["latency_ms"].max() <= 30_000

    def test_tokens_input_has_pareto_tail(self, facts):
        # Power law: p99 an order of magnitude beyond the median.
        p50 = facts["tokens_input"].median()
        p99 = facts["tokens_input"].quantile(0.99)
        assert p99 > 8 * p50

    def test_tokens_total_identity(self, facts):
        assert (
            facts["tokens_total"] == facts["tokens_input"] + facts["tokens_output"]
        ).all()

    def test_http_status_proportions(self, facts):
        props = facts["http_status"].value_counts(normalize=True)
        assert props[200] == pytest.approx(0.94, abs=0.015)
        assert props[429] == pytest.approx(0.03, abs=0.01)
        assert props[500] == pytest.approx(0.02, abs=0.01)
        assert props[401] == pytest.approx(0.01, abs=0.01)

    def test_safety_flag_rate(self, facts):
        assert facts["safety_flag"].mean() == pytest.approx(0.008, abs=0.004)

    def test_model_ids_come_from_catalog(self, facts, models):
        assert set(facts["model_id"]) <= {m["model_id"] for m in models}

    def test_cost_is_tokens_times_price(self, facts, models):
        # The invariant dim_models depends on: cost_usd must be recomputable
        # from the catalog. A drifted price table breaks this immediately.
        price_in = {m["model_id"]: m["cost_per_input_token"] for m in models}
        price_out = {m["model_id"]: m["cost_per_output_token"] for m in models}
        expected = (
            facts["tokens_input"] * facts["model_id"].map(price_in)
            + facts["tokens_output"] * facts["model_id"].map(price_out)
        ).round(6)
        assert np.allclose(facts["cost_usd"], expected)


class TestDeterminism:
    def test_same_seed_same_output(self, users, models):
        a = gen.generate_facts(np.random.default_rng(7), 2_000, DAYS, users, models)
        b = gen.generate_facts(np.random.default_rng(7), 2_000, DAYS, users, models)
        assert a.equals(b)

    def test_different_seed_different_output(self, users, models):
        a = gen.generate_facts(np.random.default_rng(7), 2_000, DAYS, users, models)
        b = gen.generate_facts(np.random.default_rng(8), 2_000, DAYS, users, models)
        assert not a.equals(b)


class TestDateDimension:
    def test_covers_window_inclusive(self):
        from datetime import datetime
        df = gen.generate_date_dimension(datetime(2026, 1, 1), datetime(2026, 1, 31))
        assert len(df) == 31

    def test_weekend_flags(self):
        from datetime import datetime
        df = gen.generate_date_dimension(datetime(2026, 1, 1), datetime(2026, 1, 7))
        # 2026-01-03 is a Saturday, 2026-01-04 a Sunday
        flagged = set(df[df["is_weekend"]]["date_key"])
        assert flagged == {20260103, 20260104}

    def test_date_key_format(self):
        from datetime import datetime
        df = gen.generate_date_dimension(datetime(2026, 2, 1), datetime(2026, 2, 3))
        assert list(df["date_key"]) == [20260201, 20260202, 20260203]
