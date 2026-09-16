"""Tests for visualization.py - chart selection and rendering.
No ANTHROPIC_API_KEY is required: choose_chart() falls back to the heuristic
whenever no key is configured, so these run the same way in CI."""
import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from visualization import heuristic_chart, choose_chart, render_chart


# ---------------------------------------------------------------------------
# heuristic_chart
# ---------------------------------------------------------------------------
def test_heuristic_picks_bar_for_category_and_numeric():
    df = pd.DataFrame({"Country": ["US", "CA", "UK"], "Count": [10, 5, 3]})
    choice = heuristic_chart(df)
    assert choice["chart"] == "bar"
    assert choice["x"] == "Country"
    assert choice["y"] == "Count"


def test_heuristic_falls_back_to_table_for_single_row():
    df = pd.DataFrame({"Total": [42]})
    assert heuristic_chart(df)["chart"] == "table"


def test_heuristic_falls_back_to_table_for_non_numeric_second_column():
    df = pd.DataFrame({"Id": [1, 2, 3], "Name": ["a", "b", "c"]})
    assert heuristic_chart(df)["chart"] == "table"


# ---------------------------------------------------------------------------
# choose_chart - demo mode (no API key) always uses the heuristic
# ---------------------------------------------------------------------------
def test_choose_chart_uses_heuristic_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    df = pd.DataFrame({"Genre": ["Rock", "Jazz"], "Revenue": [100.0, 50.0]})
    choice = choose_chart("total revenue by genre", "SELECT ...", df)
    assert choice == heuristic_chart(df)


# ---------------------------------------------------------------------------
# render_chart
# ---------------------------------------------------------------------------
def test_render_chart_returns_none_for_table_choice():
    df = pd.DataFrame({"Total": [42]})
    assert render_chart(df, {"chart": "table", "x": None, "y": None, "color": None}) is None


def test_render_chart_returns_none_for_empty_df():
    df = pd.DataFrame({"x": [], "y": []})
    choice = {"chart": "bar", "x": "x", "y": "y", "color": None}
    assert render_chart(df, choice) is None


def test_render_chart_returns_figure_for_bar():
    df = pd.DataFrame({"Country": ["US", "CA"], "Count": [10, 5]})
    fig = render_chart(df, {"chart": "bar", "x": "Country", "y": "Count", "color": None})
    assert fig is not None


def test_render_chart_returns_figure_for_line():
    df = pd.DataFrame({"Month": ["2024-01", "2024-02"], "Revenue": [100.0, 120.0]})
    fig = render_chart(df, {"chart": "line", "x": "Month", "y": "Revenue", "color": None})
    assert fig is not None


def test_render_chart_returns_figure_for_pie():
    df = pd.DataFrame({"Genre": ["Rock", "Jazz", "Pop"], "Share": [50, 30, 20]})
    fig = render_chart(df, {"chart": "pie", "x": "Genre", "y": "Share", "color": None})
    assert fig is not None


def test_render_chart_returns_none_when_missing_required_columns():
    df = pd.DataFrame({"Genre": ["Rock", "Jazz"], "Share": [50, 30]})
    fig = render_chart(df, {"chart": "scatter", "x": None, "y": "Share", "color": None})
    assert fig is None
