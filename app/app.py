"""
Andvari: Token Forecaster
Interactive tool for projecting LLM API token volume, cost, revenue, and margin.
Self-hosted Streamlit application with vaporwave aesthetic.

UI only: the arithmetic lives in forecast.py and pricing comes from the
project-wide catalog via catalog.py, both unit-tested without Streamlit.
"""

import plotly.graph_objects as go
import streamlit as st

from catalog import load_catalog
from db import fetch_baseline
from forecast import compute_forecast, compute_latency_risk, format_number
from theme import build_app_css, hex_to_rgba, plotly_layout, resolve_colors

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Token Forecaster | Andvari",
    page_icon="⚡",
    layout="wide",
)

# Pricing has one source of truth: data/model_catalog.csv. Fail loudly with an
# actionable message rather than forecasting from stale numbers.
try:
    MODEL_CATALOG = load_catalog()
except (FileNotFoundError, ValueError) as exc:
    st.error(f"Model catalog unavailable: {exc}")
    st.stop()


@st.cache_data(ttl=300)
def _load_baseline(catalog_ids: tuple[str, ...]) -> dict | None:
    """Observed-traffic defaults from the star schema; None = parametric mode."""
    return fetch_baseline(set(catalog_ids))


BASELINE = _load_baseline(tuple(sorted(MODEL_CATALOG)))

# Scenario presets
PRESETS = {
    "STARTUP": {
        "mau": 500,
        "requests_per_user_day": 5,
        "avg_input_tokens": 200,
        "avg_output_tokens": 150,
        "model_mix": {"claude-3-opus": 5, "claude-3-sonnet": 25, "claude-3-haiku": 70},
        "revenue_per_user_month": 29.0,
        "infra_overhead": 2_000.0,
    },
    "MID-MARKET": {
        "mau": 5_000,
        "requests_per_user_day": 15,
        "avg_input_tokens": 500,
        "avg_output_tokens": 350,
        "model_mix": {"claude-3-opus": 10, "claude-3-sonnet": 40, "claude-3-haiku": 50},
        "revenue_per_user_month": 49.0,
        "infra_overhead": 8_000.0,
    },
    "ENTERPRISE": {
        "mau": 25_000,
        "requests_per_user_day": 30,
        "avg_input_tokens": 1_000,
        "avg_output_tokens": 600,
        "model_mix": {"claude-3-opus": 20, "claude-3-sonnet": 50, "claude-3-haiku": 30},
        "revenue_per_user_month": 99.0,
        "infra_overhead": 25_000.0,
    },
    "HYPERSCALE": {
        "mau": 200_000,
        "requests_per_user_day": 50,
        "avg_input_tokens": 2_000,
        "avg_output_tokens": 1_200,
        "model_mix": {"claude-3-opus": 30, "claude-3-sonnet": 45, "claude-3-haiku": 25},
        "revenue_per_user_month": 149.0,
        "infra_overhead": 75_000.0,
    },
}

# Theme colors are resolved from the iframe URL query string. The parent site
# forwards the active palette so the demo matches whatever scheme is active.
# resolve_colors validates every value against a strict hex allowlist (theme.py);
# a direct visit with no params falls back to the site-default terminal palette.
COLORS = resolve_colors(st.query_params)
PLOTLY_LAYOUT = plotly_layout(COLORS)


# ---------------------------------------------------------------------------
# UI Layout
# ---------------------------------------------------------------------------
# SECURITY: unsafe_allow_html=True is used below for CSS theming and styled
# metric cards. The CSS is built by theme.build_app_css() from query-param-derived
# colors that are validated against a strict ``#RRGGBB`` allowlist; no raw user
# input reaches this string. Metric-card HTML elsewhere uses hardcoded templates
# with formatted numeric values only. Enforced by tests/test_theme_forecaster.py.

st.markdown(build_app_css(COLORS), unsafe_allow_html=True)

st.title("TOKEN FORECASTER")
st.markdown("*Project token volume, infrastructure cost, and gross margin across model mixes.*")

# The telemetry preset is what separates this from a slider calculator: its
# defaults are observed from the warehouse this stack builds, not assumed.
TELEMETRY_PRESET = "TELEMETRY (OBSERVED)"
if BASELINE:
    PRESETS = {
        TELEMETRY_PRESET: {
            "mau": BASELINE["mau"],
            "requests_per_user_day": BASELINE["requests_per_user_day"],
            "avg_input_tokens": BASELINE["avg_input_tokens"],
            "avg_output_tokens": BASELINE["avg_output_tokens"],
            "model_mix": BASELINE["model_mix"],
            "revenue_per_user_month": 49.0,
            "infra_overhead": 8_000.0,
        },
        **PRESETS,
    }
    st.caption(
        f"Calibrated from live telemetry: {BASELINE['n_requests']:,} requests · "
        f"{BASELINE['mau']:,} users · {BASELINE['window_days']}-day window"
    )
else:
    st.caption("Parametric mode — telemetry database offline; using scenario presets.")

# --- Sidebar: Scenario Presets + Inputs ---
st.sidebar.markdown("## SCENARIO")

_options = ["Custom"] + list(PRESETS.keys())
preset_choice = st.sidebar.selectbox(
    "Load Preset",
    options=_options,
    index=_options.index(TELEMETRY_PRESET) if BASELINE else 0,
)

if preset_choice != "Custom":
    preset = PRESETS[preset_choice]
    default_mau = preset["mau"]
    default_rpd = preset["requests_per_user_day"]
    default_input = preset["avg_input_tokens"]
    default_output = preset["avg_output_tokens"]
    default_mix = preset["model_mix"]
    default_revenue = preset["revenue_per_user_month"]
    default_overhead = preset["infra_overhead"]
else:
    default_mau = 5_000
    default_rpd = 15
    default_input = 500
    default_output = 350
    default_mix = {"claude-3-opus": 10, "claude-3-sonnet": 40, "claude-3-haiku": 50}
    default_revenue = 49.0
    default_overhead = 8_000.0

st.sidebar.markdown("---")
st.sidebar.markdown("## INPUTS")

mau = st.sidebar.number_input("Monthly Active Users", min_value=10, max_value=1_000_000,
                               value=default_mau, step=100)
requests_per_user_day = st.sidebar.slider("Requests / User / Day", 1, 100, default_rpd)
avg_input_tokens = st.sidebar.slider("Avg Input Tokens", 50, 10_000, default_input, step=50)
avg_output_tokens = st.sidebar.slider("Avg Output Tokens", 50, 10_000, default_output, step=50)
revenue_per_user_month = st.sidebar.number_input(
    "Revenue per User / Month ($)", min_value=0.0, max_value=1000.0,
    value=default_revenue, step=5.0,
)
infra_overhead = st.sidebar.number_input(
    "Fixed Infra Overhead / Month ($)", min_value=0.0, max_value=500_000.0,
    value=default_overhead, step=500.0,
    help="Fixed monthly cost (servers, ops, monitoring) that doesn't scale with users",
)

st.sidebar.markdown("---")
st.sidebar.markdown("## MODEL MIX")
st.sidebar.markdown("*Must sum to 100%*")

opus_pct = st.sidebar.slider("Opus %", 0, 100, default_mix.get("claude-3-opus", 10))
sonnet_pct = st.sidebar.slider("Sonnet %", 0, 100, default_mix.get("claude-3-sonnet", 40))
haiku_pct = st.sidebar.slider("Haiku %", 0, 100, default_mix.get("claude-3-haiku", 50))

mix_total = opus_pct + sonnet_pct + haiku_pct
if mix_total != 100:
    st.sidebar.error(f"Model mix sums to {mix_total}% -- must be exactly 100%")
    st.stop()

model_mix = {
    "claude-3-opus": opus_pct,
    "claude-3-sonnet": sonnet_pct,
    "claude-3-haiku": haiku_pct,
}

# --- Compute ---
forecast_df = compute_forecast(
    catalog=MODEL_CATALOG,
    mau=mau,
    requests_per_user_day=requests_per_user_day,
    avg_input_tokens=avg_input_tokens,
    avg_output_tokens=avg_output_tokens,
    model_mix=model_mix,
    revenue_per_user_month=revenue_per_user_month,
    infra_overhead=infra_overhead,
    months=12,
)

latency_risk = compute_latency_risk(requests_per_user_day, model_mix)

# --- Month 1 snapshot metrics ---
m1 = forecast_df.iloc[0]

st.markdown("### MONTH 1 PROJECTIONS")
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-label">Token Volume</div>
        <div class="metric-value">{format_number(m1['total_tokens'])}</div>
    </div>""", unsafe_allow_html=True)
with col2:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-label">Infra Cost</div>
        <div class="metric-value">${format_number(m1['cost_usd'])}</div>
    </div>""", unsafe_allow_html=True)
with col3:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-label">Revenue</div>
        <div class="metric-value">${format_number(m1['revenue_usd'])}</div>
    </div>""", unsafe_allow_html=True)
with col4:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-label">Gross Margin</div>
        <div class="metric-value">{m1['gross_margin_pct']:.1f}%</div>
    </div>""", unsafe_allow_html=True)
with col5:
    risk_color = COLORS["green"] if latency_risk < 33 else (COLORS["amber"] if latency_risk < 66 else COLORS["pink"])
    st.markdown(f"""<div class="metric-card">
        <div class="metric-label">Latency Risk</div>
        <div class="metric-value" style="color: {risk_color}">{latency_risk:.0f}/100</div>
    </div>""", unsafe_allow_html=True)

# --- Charts ---
st.markdown("---")
chart_col1, chart_col2 = st.columns(2)

# Cost vs Revenue Growth
with chart_col1:
    st.markdown("### COST vs REVENUE (12-Month)")
    fig_growth = go.Figure()
    fig_growth.add_trace(go.Scatter(
        x=forecast_df["month"], y=forecast_df["revenue_usd"],
        name="Revenue", line=dict(color=COLORS["green"], width=3),
        fill="tozeroy", fillcolor=hex_to_rgba(COLORS["green"], 0.1),
    ))
    fig_growth.add_trace(go.Scatter(
        x=forecast_df["month"], y=forecast_df["cost_usd"],
        name="Infra Cost", line=dict(color=COLORS["pink"], width=3),
        fill="tozeroy", fillcolor=hex_to_rgba(COLORS["pink"], 0.1),
    ))
    fig_growth.update_layout(
        **PLOTLY_LAYOUT,
        xaxis_title="Month",
        yaxis_title="USD",
        legend=dict(x=0.02, y=0.98),
        height=400,
    )
    fig_growth.update_xaxes(gridcolor=COLORS["border"], dtick=1)
    fig_growth.update_yaxes(gridcolor=COLORS["border"])
    st.plotly_chart(fig_growth, use_container_width=True)

# Model Mix Bar
with chart_col2:
    st.markdown("### MODEL MIX")
    mix_labels = [MODEL_CATALOG[m]["label"] for m in model_mix]
    mix_values = list(model_mix.values())
    mix_colors = [COLORS["violet"], COLORS["cyan"], COLORS["green"]]
    fig_mix = go.Figure(data=[go.Bar(
        x=mix_labels,
        y=mix_values,
        marker=dict(color=mix_colors),
        text=[f"{v}%" for v in mix_values],
        textposition="outside",
        textfont=dict(color=COLORS["text"], size=13),
    )])
    fig_mix.update_layout(
        **PLOTLY_LAYOUT,
        showlegend=False,
        height=400,
        yaxis_title="Allocation %",
        yaxis=dict(range=[0, max(mix_values) * 1.25]),
    )
    fig_mix.update_xaxes(gridcolor=COLORS["border"])
    fig_mix.update_yaxes(gridcolor=COLORS["border"])
    st.plotly_chart(fig_mix, use_container_width=True)

# Margin trend
st.markdown("### GROSS MARGIN TREND")
fig_margin = go.Figure()
fig_margin.add_trace(go.Bar(
    x=forecast_df["month"], y=forecast_df["gross_margin_pct"],
    marker=dict(
        color=[COLORS["green"] if m > 50 else COLORS["amber"] if m > 20 else COLORS["pink"]
               for m in forecast_df["gross_margin_pct"]],
    ),
    text=[f"{m:.1f}%" for m in forecast_df["gross_margin_pct"]],
    textposition="outside",
    textfont=dict(color=COLORS["text"], size=11),
))
fig_margin.update_layout(
    **PLOTLY_LAYOUT,
    xaxis_title="Month",
    yaxis_title="Gross Margin %",
    showlegend=False,
    height=350,
    yaxis=dict(range=[0, 105]),
)
fig_margin.update_xaxes(gridcolor=COLORS["border"], dtick=1)
fig_margin.update_yaxes(gridcolor=COLORS["border"])
st.plotly_chart(fig_margin, use_container_width=True)

# --- 12-Month Summary Table ---
st.markdown("### 12-MONTH PROJECTION TABLE")

COL_MONTH = "Month"
COL_ACTIVE_USERS = "Active Users"
COL_MONTHLY_REQUESTS = "Monthly Requests"
COL_TOTAL_TOKENS = "Total Tokens"
COL_INPUT_TOKENS = "Input Tokens"
COL_OUTPUT_TOKENS = "Output Tokens"
COL_COST = "Cost (USD)"
COL_REVENUE = "Revenue (USD)"
COL_MARGIN = "Gross Margin %"

DISPLAY_COLUMNS = [
    COL_MONTH, COL_ACTIVE_USERS, COL_MONTHLY_REQUESTS, COL_TOTAL_TOKENS,
    COL_INPUT_TOKENS, COL_OUTPUT_TOKENS, COL_COST, COL_REVENUE, COL_MARGIN,
]

display_df = forecast_df.copy()
display_df.columns = DISPLAY_COLUMNS
display_df[COL_COST] = display_df[COL_COST].apply(lambda x: f"${x:,.2f}")
display_df[COL_REVENUE] = display_df[COL_REVENUE].apply(lambda x: f"${x:,.2f}")
display_df[COL_MARGIN] = display_df[COL_MARGIN].apply(lambda x: f"{x:.1f}%")
display_df[COL_TOTAL_TOKENS] = display_df[COL_TOTAL_TOKENS].apply(lambda x: format_number(x))
display_df[COL_INPUT_TOKENS] = display_df[COL_INPUT_TOKENS].apply(lambda x: format_number(x))
display_df[COL_OUTPUT_TOKENS] = display_df[COL_OUTPUT_TOKENS].apply(lambda x: format_number(x))
display_df[COL_ACTIVE_USERS] = display_df[COL_ACTIVE_USERS].apply(lambda x: f"{x:,}")
display_df[COL_MONTHLY_REQUESTS] = display_df[COL_MONTHLY_REQUESTS].apply(lambda x: format_number(x))

st.dataframe(display_df, use_container_width=True, hide_index=True)

# --- Footer ---
st.markdown("---")
st.markdown(
    f"<div style='text-align: center; color: {COLORS['violet']}; font-size: 0.8rem;'>"
    "ANDVARI // Token Forecaster v0.1.0 // lukeudell.com"
    "</div>",
    unsafe_allow_html=True,
)
