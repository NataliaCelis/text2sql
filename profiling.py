"""Table preview + column-level profiling, used by the Data Preview tab.
Works on any SQLite DB (demo Chinook or an uploaded session DB)."""
import sqlite3
import pandas as pd


def get_preview(db_path: str, table: str, n: int = 10) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT {n}', conn)
    finally:
        conn.close()


def get_row_count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]
    finally:
        conn.close()


def get_column_profile(db_path: str, table: str, sample_rows: int = 5000) -> pd.DataFrame:
    """Per-column profile: dtype, non-null count, distinct count, and
    min/max for numeric columns. Profiles a sample for speed on large tables
    rather than the full table."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT {sample_rows}', conn)
    finally:
        conn.close()

    rows = []
    for col in df.columns:
        series = df[col]
        row = {
            "column": col,
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "nulls": int(series.isna().sum()),
            "distinct": int(series.nunique()),
        }
        if pd.api.types.is_numeric_dtype(series) and series.notna().any():
            row["min"] = series.min()
            row["max"] = series.max()
        else:
            row["min"] = None
            row["max"] = None
        rows.append(row)
    return pd.DataFrame(rows)
