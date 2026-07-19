"""
Forecast arithmetic for the Token Forecaster.

Pure functions, no Streamlit: everything a visitor's numbers depend on lives
here so it can be unit-tested without a browser (see tests/test_forecast.py).
The catalog is an explicit parameter — pricing has exactly one source
(data/model_catalog.csv via catalog.py), never a module-level copy.
"""

import pandas as pd

# Relative latency burden per model, used only for the qualitative risk score.
# Roughly tracks model size, not price; unknown models score neutral.
LATENCY_WEIGHTS = {
    "claude-3-opus": 3.0,
    "claude-3-sonnet": 1.5,
    "claude-3-haiku": 0.5,
}
_NEUTRAL_LATENCY_WEIGHT = 1.0

MONTHLY_GROWTH = 1.05          # 5% MoM active-user growth
OVERHEAD_STEP = 1.10           # fixed overhead grows +10%...
OVERHEAD_STEP_MONTHS = 3       # ...every 3 months (step function)
DAYS_PER_MONTH = 30


def compute_forecast(
    catalog: dict[str, dict],
    mau: int,
    requests_per_user_day: int,
    avg_input_tokens: int,
    avg_output_tokens: int,
    model_mix: dict[str, float],
    revenue_per_user_month: float,
    infra_overhead: float,
    months: int = 12,
) -> pd.DataFrame:
    """
    Compute monthly token volume, cost, revenue, and margin projections.

    ``model_mix`` maps model_id -> percent of traffic; every key must exist in
    ``catalog`` (a typo'd id raises KeyError rather than pricing at zero).
    """
    records = []
    for month in range(1, months + 1):
        growth_factor = MONTHLY_GROWTH ** (month - 1)
        active_users = int(mau * growth_factor)
        monthly_requests = active_users * requests_per_user_day * DAYS_PER_MONTH

        total_input_tokens = 0
        total_output_tokens = 0
        variable_cost = 0.0

        for model_id, pct in model_mix.items():
            fraction = pct / 100.0
            model_requests = monthly_requests * fraction
            input_tokens = model_requests * avg_input_tokens
            output_tokens = model_requests * avg_output_tokens

            model_info = catalog[model_id]
            cost = (
                input_tokens * model_info["cost_input"]
                + output_tokens * model_info["cost_output"]
            )

            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            variable_cost += cost

        total_tokens = total_input_tokens + total_output_tokens
        overhead_growth = OVERHEAD_STEP ** ((month - 1) // OVERHEAD_STEP_MONTHS)
        total_cost = variable_cost + (infra_overhead * overhead_growth)
        revenue = active_users * revenue_per_user_month
        gross_margin = (revenue - total_cost) / revenue * 100 if revenue > 0 else 0

        records.append({
            "month": month,
            "active_users": active_users,
            "monthly_requests": monthly_requests,
            "total_tokens": total_tokens,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "cost_usd": total_cost,
            "revenue_usd": revenue,
            "gross_margin_pct": gross_margin,
        })

    return pd.DataFrame(records)


def compute_latency_risk(requests_per_user_day: int, model_mix: dict[str, float]) -> float:
    """
    Estimate latency risk score (0-100) based on request volume and model mix.
    Heavier models + higher volume = higher risk.
    """
    weighted_model_cost = sum(
        (pct / 100.0) * LATENCY_WEIGHTS.get(m, _NEUTRAL_LATENCY_WEIGHT)
        for m, pct in model_mix.items()
    )
    volume_factor = min(requests_per_user_day / 50.0, 1.0)
    raw_score = weighted_model_cost * volume_factor * 100 / 3.0
    return min(raw_score, 100.0)


def format_number(n: float) -> str:
    """Format large numbers with K/M/B suffixes."""
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:.0f}"
