"""Tests for profiling.py - table preview, row counts, column profiling."""
import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import build_session_db
from profiling import get_preview, get_row_count, get_column_profile
from schema import get_table_names


@pytest.fixture
def sample_db():
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "category": ["A", "B", "A", None, "B"],
        "value": [10.5, 20.0, 15.5, 30.0, None],
    })
    meta = build_session_db({"sample.csv": df}, session_id="pytest_profile")
    return meta["db_path"]


def test_get_table_names_returns_uploaded_table(sample_db):
    assert "sample" in get_table_names(sample_db)


def test_get_row_count(sample_db):
    assert get_row_count(sample_db, "sample") == 5


def test_get_preview_respects_limit(sample_db):
    df = get_preview(sample_db, "sample", n=2)
    assert len(df) == 2


def test_column_profile_counts_nulls_correctly(sample_db):
    profile = get_column_profile(sample_db, "sample")
    category_row = profile[profile["column"] == "category"].iloc[0]
    assert category_row["nulls"] == 1
    assert category_row["non_null"] == 4
    assert category_row["distinct"] == 2


def test_column_profile_min_max_for_numeric(sample_db):
    profile = get_column_profile(sample_db, "sample")
    value_row = profile[profile["column"] == "value"].iloc[0]
    assert value_row["min"] == 10.5
    assert value_row["max"] == 30.0
