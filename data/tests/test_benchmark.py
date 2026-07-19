"""
Tests for the benchmark's result-shaping logic. The measurement itself needs a
live warehouse; the parsing and statistics must not.
"""

import importlib.util
import pathlib

import pytest

_BENCH_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "benchmark_star_vs_snowflake.py"
)
_spec = importlib.util.spec_from_file_location("benchmark_andvari", _BENCH_PATH)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def _plan(execution_ms: float) -> list:
    """Shape of one EXPLAIN (ANALYZE, FORMAT JSON) result row."""
    return [{"Execution Time": execution_ms, "Planning Time": 0.2, "Plan": {}}]


class TestExecutionTime:
    def test_extracts_execution_time(self):
        assert bench.execution_time_ms(_plan(51.3)) == pytest.approx(51.3)

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            bench.execution_time_ms([{"Plan": {}}])


class TestMedian:
    def test_odd_count(self):
        assert bench.median([3.0, 1.0, 2.0]) == 2.0

    def test_even_count_averages_middle_pair(self):
        assert bench.median([4.0, 1.0, 3.0, 2.0]) == 2.5

    def test_single_sample(self):
        assert bench.median([7.5]) == 7.5


class TestQueries:
    def test_the_three_published_comparisons_exist(self):
        labels = {q["label"] for q in bench.QUERIES}
        assert labels == {
            "Cost by model (star, 1 join)",
            "Cost by industry (star, 1 join)",
            "Cost by industry (snowflake, 3 joins)",
        }

    def test_queries_are_read_only(self):
        for q in bench.QUERIES:
            sql = q["sql"].strip().lower()
            assert sql.startswith("select")
            for verb in ("insert", "update", "delete", "drop", "alter"):
                assert verb + " " not in sql
