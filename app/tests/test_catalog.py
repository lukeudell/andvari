"""
Tests for the model catalog loader — the app's single source of pricing truth.

Written before ``catalog.py`` existed (TDD): pricing used to be hardcoded in
three places (generator, app, dim_models); these tests pin the contract of the
one canonical file, ``data/model_catalog.csv``, that replaced them.
"""

import importlib.util
import pathlib

import pytest

_CATALOG_PATH = pathlib.Path(__file__).resolve().parent.parent / "catalog.py"
_spec = importlib.util.spec_from_file_location("catalog_forecaster", _CATALOG_PATH)
catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catalog)

_REPO_CATALOG_CSV = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "model_catalog.csv"
)

VALID_HEADER = (
    "model_id,model_family,cost_per_input_token,cost_per_output_token,"
    "context_window_k,is_active,traffic_weight,display_label\n"
)


def _write_csv(tmp_path, rows, header=VALID_HEADER):
    path = tmp_path / "model_catalog.csv"
    path.write_text(header + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


class TestLoadCatalog:
    def test_returns_only_active_models(self, tmp_path):
        path = _write_csv(tmp_path, [
            "m-live,fam,0.000001,0.000002,200,true,0.5,Live",
            "m-dead,fam,0.000003,0.000004,100,false,0.5,Dead",
        ])
        result = catalog.load_catalog(path)
        assert set(result) == {"m-live"}

    def test_parses_costs_as_floats(self, tmp_path):
        path = _write_csv(tmp_path, ["m1,fam,0.000015,0.000075,200,true,1.0,Opus"])
        m = catalog.load_catalog(path)["m1"]
        assert m["cost_input"] == pytest.approx(0.000015)
        assert m["cost_output"] == pytest.approx(0.000075)

    def test_carries_label_and_family(self, tmp_path):
        path = _write_csv(tmp_path, ["m1,claude-3,0.1,0.2,200,true,1.0,Opus (Premium)"])
        m = catalog.load_catalog(path)["m1"]
        assert m["label"] == "Opus (Premium)"
        assert m["family"] == "claude-3"

    def test_is_active_parsing_is_case_insensitive(self, tmp_path):
        # The generator writes pandas booleans ("True"/"False"); a hand edit
        # may write lowercase. Both must round-trip.
        path = _write_csv(tmp_path, [
            "m1,fam,0.1,0.2,200,True,0.5,A",
            "m2,fam,0.1,0.2,200,FALSE,0.5,B",
        ])
        assert set(catalog.load_catalog(path)) == {"m1"}

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            catalog.load_catalog(tmp_path / "nope.csv")

    def test_missing_column_raises_value_error(self, tmp_path):
        path = _write_csv(
            tmp_path,
            ["m1,fam,0.1,0.2"],
            header="model_id,model_family,cost_per_input_token,cost_per_output_token\n",
        )
        with pytest.raises(ValueError):
            catalog.load_catalog(path)

    def test_empty_catalog_raises_value_error(self, tmp_path):
        # An all-inactive catalog would render an app with zero models —
        # fail loudly instead of showing an empty forecaster.
        path = _write_csv(tmp_path, ["m1,fam,0.1,0.2,200,false,1.0,A"])
        with pytest.raises(ValueError):
            catalog.load_catalog(path)


class TestRepoCatalogFile:
    """The canonical checked-in file: the contract all consumers share."""

    def test_exists(self):
        assert _REPO_CATALOG_CSV.exists()

    def test_active_models_are_the_claude_3_lineup(self):
        result = catalog.load_catalog(_REPO_CATALOG_CSV)
        assert set(result) == {"claude-3-opus", "claude-3-sonnet", "claude-3-haiku"}

    def test_default_path_resolves_to_repo_csv(self, monkeypatch):
        monkeypatch.delenv("MODEL_CATALOG_PATH", raising=False)
        assert catalog.default_catalog_path() == _REPO_CATALOG_CSV

    def test_env_var_overrides_default_path(self, monkeypatch):
        monkeypatch.setenv("MODEL_CATALOG_PATH", "/somewhere/else.csv")
        assert catalog.default_catalog_path() == pathlib.Path("/somewhere/else.csv")
