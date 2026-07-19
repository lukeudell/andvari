# ============================================================
#  file:       data/generate_data.py
#  purpose:    seeded synthetic telemetry generator with realistic distributions
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-14]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
"""
Andvari: synthetic data generator
Generates realistic LLM API telemetry data with statistically accurate
distributions (see "The dataset" in README.md for the specifications, and
data/tests/test_generate_data.py for the assertions that enforce them).

Usage:
    python generate_data.py [--rows 500000] [--days 90] [--seed 42]
"""

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent / "generated"
CATALOG_PATH = Path(__file__).parent / "model_catalog.csv"
SEED = 42


def load_model_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    """
    Load the model catalog, the project's single source of pricing truth,
    shared with the app (app/catalog.py) and, via models.csv, with dim_models.
    """
    df = pd.read_csv(path)
    return [
        {
            "model_id": row.model_id,
            "model_family": row.model_family,
            "cost_per_input_token": float(row.cost_per_input_token),
            "cost_per_output_token": float(row.cost_per_output_token),
            "context_window_k": int(row.context_window_k),
            "is_active": bool(row.is_active),
            "weight": float(row.traffic_weight),
        }
        for row in df.itertuples()
    ]

# Endpoint catalog
ENDPOINTS = [
    {"endpoint_path": "/v1/messages", "api_version": "v1", "is_deprecated": False},
    {"endpoint_path": "/v1/complete", "api_version": "v1", "is_deprecated": True},
    {"endpoint_path": "/v1/embeddings", "api_version": "v1", "is_deprecated": False},
    {"endpoint_path": "/v2/messages", "api_version": "v2", "is_deprecated": False},
    {"endpoint_path": "/v2/messages/batch", "api_version": "v2", "is_deprecated": False},
]

ENDPOINT_WEIGHTS = [0.50, 0.05, 0.10, 0.30, 0.05]

# Billing tiers
BILLING_TIERS = ["Free", "Starter", "Pro", "Enterprise"]
BILLING_TIER_WEIGHTS = [0.50, 0.30, 0.15, 0.05]

# HTTP status codes
HTTP_STATUSES = [200, 429, 500, 401]
HTTP_STATUS_WEIGHTS = [0.94, 0.03, 0.02, 0.01]

# Regions
REGIONS = ["us-east", "us-west", "eu-west", "eu-central", "ap-southeast", "ap-northeast"]
REGION_WEIGHTS = [0.30, 0.20, 0.15, 0.15, 0.10, 0.10]

# Industries
INDUSTRIES = [
    "Technology", "Finance", "Healthcare", "Education", "E-commerce",
    "Media", "Legal", "Government", "Manufacturing", "Consulting",
]


def generate_timestamps(rng: np.random.Generator, n: int, days: int) -> np.ndarray:
    """
    Generate request timestamps with realistic time-of-day and day-of-week patterns.
    Uses sinusoidal modulation for diurnal pattern + weekly seasonality.
    Peak: 10am-3pm weekdays. Trough: 2am-5am. Weekend: -40%.
    """
    end_date = datetime(2026, 3, 1)
    start_date = end_date - timedelta(days=days)
    total_seconds = int((end_date - start_date).total_seconds())

    # Generate candidate timestamps using rejection sampling
    # Over-generate to account for rejection
    oversample_factor = 3
    candidate_seconds = rng.uniform(0, total_seconds, size=n * oversample_factor)

    # Convert to datetime components for modulation
    candidate_datetimes = np.array(
        [start_date + timedelta(seconds=float(s)) for s in candidate_seconds]
    )
    hours = np.array([dt.hour + dt.minute / 60.0 for dt in candidate_datetimes])
    weekdays = np.array([dt.weekday() for dt in candidate_datetimes])

    # Diurnal pattern: sinusoidal with peak at ~12:30 (hour 12.5)
    # sin peaks at pi/2, so shift: sin(2*pi*(hour - 6.5) / 24)
    diurnal = 0.5 + 0.5 * np.sin(2 * np.pi * (hours - 6.5) / 24.0)

    # Suppress overnight (2am-5am) further
    overnight_mask = (hours >= 2) & (hours < 5)
    diurnal[overnight_mask] *= 0.15

    # Weekend reduction: -40%
    is_weekend = (weekdays >= 5)
    diurnal[is_weekend] *= 0.6

    # Normalize to probabilities and sample
    probabilities = diurnal / diurnal.sum()
    chosen_indices = rng.choice(len(candidate_seconds), size=n, replace=False, p=probabilities)

    timestamps = candidate_seconds[chosen_indices]
    timestamps.sort()

    result = np.array(
        [start_date + timedelta(seconds=float(s)) for s in timestamps]
    )
    return result


def generate_users(rng: np.random.Generator, fake: Faker, n_users: int) -> pd.DataFrame:
    """Generate user dimension data."""
    users = []
    for i in range(n_users):
        tier = rng.choice(BILLING_TIERS, p=BILLING_TIER_WEIGHTS)
        region = rng.choice(REGIONS, p=REGION_WEIGHTS)
        industry = rng.choice(INDUSTRIES)
        company = fake.company()

        users.append({
            "user_id": f"user_{i + 1:06d}",
            "billing_tier": tier,
            "company_name": company,
            "industry": industry,
            "signup_date": fake.date_between(
                start_date=datetime(2023, 3, 1),
                end_date=datetime(2026, 2, 28),
            ),
            "region": region,
        })

    return pd.DataFrame(users)


def generate_facts(
    rng: np.random.Generator,
    n_rows: int,
    days: int,
    users: pd.DataFrame,
    models: list[dict],
) -> pd.DataFrame:
    """
    Generate fact table with correct statistical distributions.
    See "The dataset" in README.md for specifications.
    """
    # Pre-compute model and endpoint indices
    model_weights = np.array([m["weight"] for m in models])
    model_weights /= model_weights.sum()
    model_indices = rng.choice(len(models), size=n_rows, p=model_weights)

    endpoint_weights = np.array(ENDPOINT_WEIGHTS)
    endpoint_weights /= endpoint_weights.sum()
    endpoint_indices = rng.choice(len(ENDPOINTS), size=n_rows, p=endpoint_weights)

    # User assignment: Enterprise users generate more requests (power law)
    user_ids = users["user_id"].values
    user_tiers = users["billing_tier"].values

    # Weight users by tier: Enterprise generates ~10x more than Free
    tier_request_multiplier = {"Free": 1.0, "Starter": 3.0, "Pro": 8.0, "Enterprise": 20.0}
    user_weights = np.array([tier_request_multiplier[t] for t in user_tiers], dtype=float)
    user_weights /= user_weights.sum()
    user_indices = rng.choice(len(user_ids), size=n_rows, p=user_weights)

    # Timestamps with realistic diurnal + weekly pattern
    timestamps = generate_timestamps(rng, n_rows, days)

    # Latency: log-normal, mu=6.5, sigma=0.8 (~600ms median, tail to ~5000ms)
    latency_ms = np.round(rng.lognormal(mean=6.5, sigma=0.8, size=n_rows), 1)
    # Clamp extreme outliers
    latency_ms = np.clip(latency_ms, 50, 30000)

    # Tokens input: Pareto, alpha=1.5 (power-law: most small, some very large)
    tokens_input_raw = (rng.pareto(a=1.5, size=n_rows) + 1) * 50
    tokens_input = np.round(tokens_input_raw).astype(int)
    tokens_input = np.clip(tokens_input, 10, 100000)

    # Tokens output: correlated with input (0.6 * input + log-normal noise)
    output_noise = rng.lognormal(mean=4.0, sigma=0.8, size=n_rows)
    tokens_output = np.round(0.6 * tokens_input + output_noise).astype(int)
    tokens_output = np.clip(tokens_output, 1, 50000)

    tokens_total = tokens_input + tokens_output

    # HTTP status: weighted choice
    http_status = rng.choice(HTTP_STATUSES, size=n_rows, p=HTTP_STATUS_WEIGHTS)

    # Safety flag: Bernoulli, p=0.008
    safety_flag = rng.random(size=n_rows) < 0.008

    # Cost calculation, vectorised: index price arrays by each row's model
    price_in = np.array([m["cost_per_input_token"] for m in models])[model_indices]
    price_out = np.array([m["cost_per_output_token"] for m in models])[model_indices]
    cost_usd = np.round(tokens_input * price_in + tokens_output * price_out, 6)

    # Build DataFrame
    df = pd.DataFrame({
        "request_id": [f"req_{i + 1:07d}" for i in range(n_rows)],
        "user_id": user_ids[user_indices],
        "model_id": [models[idx]["model_id"] for idx in model_indices],
        "endpoint_path": [ENDPOINTS[idx]["endpoint_path"] for idx in endpoint_indices],
        "request_timestamp": timestamps,
        "latency_ms": latency_ms,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_total": tokens_total,
        "cost_usd": cost_usd,
        "http_status": http_status,
        "safety_flag": safety_flag,
    })

    return df


def generate_date_dimension(start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """Generate date dimension table covering the data window."""
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    records = []
    for d in dates:
        records.append({
            "date_key": int(d.strftime("%Y%m%d")),
            "full_date": d.date(),
            "day_of_week": d.strftime("%A"),
            "is_weekend": d.weekday() >= 5,
            "week_of_year": d.isocalendar()[1],
            "month_name": d.strftime("%B"),
            "quarter": f"Q{(d.month - 1) // 3 + 1}",
            "year": d.year,
        })
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic LLM API telemetry data")
    parser.add_argument("--rows", type=int, default=500000, help="Number of fact rows")
    parser.add_argument("--days", type=int, default=90, help="Time window in days")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    parser.add_argument("--users", type=int, default=5000, help="Number of unique users")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    fake = Faker()
    Faker.seed(args.seed)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    models = load_model_catalog()

    # --- Users ---
    print(f"Generating {args.users} users...")
    users_df = generate_users(rng, fake, args.users)
    users_df.to_csv(OUTPUT_DIR / "users.csv", index=False)
    print(f"  -> users.csv: {len(users_df)} rows")

    # --- Models ---
    print("Generating model dimension...")
    # traffic_weight and display_label are generator/app concerns, not
    # warehouse columns: models.csv keeps the raw_staging.models contract.
    models_df = pd.DataFrame([
        {
            "model_id": m["model_id"],
            "model_family": m["model_family"],
            "cost_per_input_token": m["cost_per_input_token"],
            "cost_per_output_token": m["cost_per_output_token"],
            "context_window_k": m["context_window_k"],
            "is_active": m["is_active"],
        }
        for m in models
    ])
    models_df.to_csv(OUTPUT_DIR / "models.csv", index=False)
    print(f"  -> models.csv: {len(models_df)} rows")

    # --- Endpoints ---
    print("Generating endpoint dimension...")
    endpoints_df = pd.DataFrame(ENDPOINTS)
    endpoints_df.to_csv(OUTPUT_DIR / "endpoints.csv", index=False)
    print(f"  -> endpoints.csv: {len(endpoints_df)} rows")

    # --- Date dimension ---
    print("Generating date dimension...")
    end_date = datetime(2026, 3, 1)
    start_date = end_date - timedelta(days=args.days)
    dates_df = generate_date_dimension(start_date, end_date)
    dates_df.to_csv(OUTPUT_DIR / "dates.csv", index=False)
    print(f"  -> dates.csv: {len(dates_df)} rows")

    # --- Fact table ---
    print(f"Generating {args.rows} API request facts...")
    facts_df = generate_facts(rng, args.rows, args.days, users_df, models)
    facts_df.to_csv(OUTPUT_DIR / "api_requests.csv", index=False)
    print(f"  -> api_requests.csv: {len(facts_df)} rows")

    # --- Quick distribution summary ---
    print("\n--- Distribution Spot Check ---")
    print(f"  latency_ms  median={facts_df['latency_ms'].median():.0f}, "
          f"p95={facts_df['latency_ms'].quantile(0.95):.0f}, "
          f"p99={facts_df['latency_ms'].quantile(0.99):.0f}")
    print(f"  tokens_input median={facts_df['tokens_input'].median():.0f}, "
          f"mean={facts_df['tokens_input'].mean():.0f}")
    print("  http_status  distribution:")
    status_counts = facts_df["http_status"].value_counts(normalize=True).sort_index()
    for status, pct in status_counts.items():
        print(f"    {status}: {pct:.2%}")
    safety_rate = facts_df["safety_flag"].mean()
    print(f"  safety_flag  rate={safety_rate:.4f} (target: 0.008)")
    print(f"\nDone. Files written to {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
