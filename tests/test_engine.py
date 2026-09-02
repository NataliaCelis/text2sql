"""Test suite: safety validation, demo fallback, and end-to-end execution.
Run with: pytest tests/ -v
Tests that need a live API key are skipped automatically when
ANTHROPIC_API_KEY isn't set, so this suite runs cleanly in CI."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sql_engine import validate_sql, run_sql, ask
from demo_fallback import match_demo_query


# ---------------------------------------------------------------------------
# Safety validation - the most important tests in this suite
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT * FROM Customer",
    "select count(*) from Track",
    "SELECT Name FROM Artist LIMIT 10",
    "  SELECT   *   FROM   Album  ",
])
def test_valid_select_passes(sql):
    validate_sql(sql)  # should not raise


@pytest.mark.parametrize("sql", [
    "DROP TABLE Customer",
    "DELETE FROM Invoice",
    "UPDATE Customer SET Email='x'",
    "INSERT INTO Customer VALUES (1)",
    "ALTER TABLE Customer ADD COLUMN x",
    "SELECT * FROM Customer; DROP TABLE Customer;",
    "",
    "   ",
    "PRAGMA table_info(Customer)",
])
def test_dangerous_sql_rejected(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_forbidden_keyword_inside_subquery_still_rejected():
    with pytest.raises(ValueError):
        validate_sql("SELECT * FROM Customer WHERE 1=1; DELETE FROM Customer")


# ---------------------------------------------------------------------------
# Demo fallback matching
# ---------------------------------------------------------------------------
def test_demo_fallback_matches_known_question():
    sql = match_demo_query("top 5 artists by revenue")
    assert sql is not None
    assert "SELECT" in sql.upper()


def test_demo_fallback_returns_none_for_unknown_question():
    assert match_demo_query("what is the meaning of life") is None


# ---------------------------------------------------------------------------
# Execution against the real Chinook DB
# ---------------------------------------------------------------------------
def test_run_sql_executes_and_returns_dataframe():
    df = run_sql("SELECT COUNT(*) AS n FROM Customer")
    assert df.shape == (1, 1)
    assert df["n"].iloc[0] > 0


def test_run_sql_rejects_unsafe_query_before_execution():
    with pytest.raises(ValueError):
        run_sql("DROP TABLE Customer")


# ---------------------------------------------------------------------------
# Full pipeline via ask() in demo mode (no API key required)
# ---------------------------------------------------------------------------
def test_ask_demo_mode_end_to_end(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = ask("top 5 artists by revenue")
    assert result["mode"] == "demo"
    assert result["error"] is None
    assert len(result["result"]) == 5


def test_ask_demo_mode_graceful_failure_on_unmatched_question(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = ask("some totally unrelated question xyz")
    assert result["error"] is not None
    assert result["result"] is None


# ---------------------------------------------------------------------------
# Live-mode tests: only run if a real API key is configured
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="requires ANTHROPIC_API_KEY")
def test_ask_live_mode_generates_valid_sql():
    result = ask("How many customers are there?")
    assert result["mode"] == "live"
    assert result["error"] is None
    assert result["result"].shape[0] >= 1
