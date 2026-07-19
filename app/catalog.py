# ============================================================
#  file:       app/catalog.py
#  purpose:    loads the single-source model pricing catalog
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        [STD-03]
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
"""
Model catalog loader for the Token Forecaster.

``data/model_catalog.csv`` is the single source of pricing truth for the whole
project ([STD-03]): the generator prices synthetic requests from it, the loader
ships it to Postgres (where dbt builds dim_models), and this module feeds the
app. The app deliberately reads the file rather than the database copy: the
database is rebuilt from this same file, so a second code path would add
failure modes without adding freshness.

Dependency-free (stdlib csv) so it can be imported without Streamlit or pandas.
"""

import csv
import os
from pathlib import Path

REQUIRED_COLUMNS = {
    "model_id",
    "model_family",
    "cost_per_input_token",
    "cost_per_output_token",
    "is_active",
    "display_label",
}

_TRUTHY = {"true", "1", "yes"}


def default_catalog_path() -> Path:
    """Resolve the catalog location: env override, else the repo's canonical file."""
    override = os.getenv("MODEL_CATALOG_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data" / "model_catalog.csv"


def load_catalog(path: Path | str | None = None) -> dict[str, dict]:
    """
    Load active models keyed by model_id.

    Raises FileNotFoundError if the file is absent and ValueError if the header
    is wrong or no model is active; an empty forecaster must fail loudly
    rather than render blank.
    """
    resolved = Path(path) if path is not None else default_catalog_path()
    if not resolved.exists():
        raise FileNotFoundError(
            f"model catalog not found at {resolved}; set MODEL_CATALOG_PATH or "
            "run from a full checkout (data/model_catalog.csv)"
        )

    with open(resolved, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"model catalog {resolved} is missing columns: {sorted(missing)}"
            )
        rows = list(reader)

    active = {
        row["model_id"]: {
            "family": row["model_family"],
            "cost_input": float(row["cost_per_input_token"]),
            "cost_output": float(row["cost_per_output_token"]),
            "label": row["display_label"],
        }
        for row in rows
        if row["is_active"].strip().lower() in _TRUTHY
    }
    if not active:
        raise ValueError(f"model catalog {resolved} contains no active models")
    return active
