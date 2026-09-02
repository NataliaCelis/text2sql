"""Tests for data_loader.py - upload sanitization, session DB building, and
that the resulting DB is queryable through the normal run_sql() path."""
import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import sanitize_identifier, build_session_db
from sql_engine import run_sql
from schema import get_schema_text


def test_sanitize_identifier_handles_special_chars():
    existing = set()
    assert sanitize_identifier("My Weird Column!", existing) == "My_Weird_Column"


def test_sanitize_identifier_dedupes_collisions():
    existing = set()
    first = sanitize_identifier("col", existing)
    second = sanitize_identifier("col", existing)
    assert first != second


def test_sanitize_identifier_prefixes_leading_digit():
    existing = set()
    result = sanitize_identifier("2024_sales", existing)
    assert not result[0].isdigit()


def test_build_session_db_creates_one_table_per_file(tmp_path):
    df1 = pd.DataFrame({"a": [1, 2]})
    df2 = pd.DataFrame({"b": [3, 4]})
    meta = build_session_db({"one.csv": df1, "two.csv": df2}, session_id="pytest_multi")
    assert len(meta["tables"]) == 2
    assert os.path.exists(meta["db_path"])


def test_uploaded_data_is_queryable_via_run_sql():
    df = pd.DataFrame({"product": ["A", "B", "C"], "revenue": [100, 200, 150]})
    meta = build_session_db({"products.csv": df}, session_id="pytest_query")
    result = run_sql("SELECT product FROM products WHERE revenue > 120 ORDER BY revenue DESC", db_path=meta["db_path"])
    assert list(result["product"]) == ["B", "C"]


def test_multi_file_join_works():
    customers = pd.DataFrame({"customer_id": [1, 2], "name": ["Alice", "Bob"]})
    orders = pd.DataFrame({"order_id": [1, 2, 3], "customer_id": [1, 1, 2], "amount": [10, 20, 15]})
    meta = build_session_db({"customers.csv": customers, "orders.csv": orders}, session_id="pytest_join")
    result = run_sql(
        "SELECT c.name, SUM(o.amount) as total FROM customers c "
        "JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.name ORDER BY total DESC",
        db_path=meta["db_path"],
    )
    assert result.iloc[0]["name"] == "Alice"
    assert result.iloc[0]["total"] == 30


def test_schema_extraction_works_on_uploaded_db():
    df = pd.DataFrame({"x": [1], "y": ["a"]})
    meta = build_session_db({"simple.csv": df}, session_id="pytest_schema")
    schema_text = get_schema_text(meta["db_path"])
    assert "TABLE simple" in schema_text
