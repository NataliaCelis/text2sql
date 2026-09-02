"""Turns user-uploaded CSV/Excel/JSON files into a queryable SQLite database.
Each uploaded file becomes one table; multiple files can be joined together
by the LLM since they land in the same DB.
"""
import io
import re
import sqlite3
import uuid
import pandas as pd

MAX_ROWS_PER_FILE = 200_000
MAX_FILE_MB = 50
UPLOAD_DB_DIR = "tmp_uploads"


class UploadError(Exception):
    pass


def sanitize_identifier(name: str, existing: set) -> str:
    """Turns an arbitrary filename/column name into a safe, unique SQL identifier."""
    clean = re.sub(r"[^0-9a-zA-Z_]", "_", str(name)).strip("_")
    if not clean:
        clean = "col"
    if clean[0].isdigit():
        clean = f"t_{clean}"
    base = clean
    i = 1
    while clean.lower() in existing:
        i += 1
        clean = f"{base}_{i}"
    existing.add(clean.lower())
    return clean


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    """uploaded_file: a Streamlit UploadedFile object."""
    name = uploaded_file.name.lower()
    size_mb = uploaded_file.size / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise UploadError(f"{uploaded_file.name} is {size_mb:.1f}MB, over the {MAX_FILE_MB}MB limit.")

    raw = uploaded_file.read()
    buf = io.BytesIO(raw)

    if name.endswith(".csv"):
        df = pd.read_csv(buf)
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(buf)
    elif name.endswith(".json"):
        df = pd.read_json(buf)
    else:
        raise UploadError(f"Unsupported file type: {uploaded_file.name} (use .csv, .xlsx, or .json)")

    if len(df) > MAX_ROWS_PER_FILE:
        df = df.head(MAX_ROWS_PER_FILE)  # caller should warn the user this happened

    return df


def build_session_db(files: dict, session_id: str = None) -> dict:
    """files: {original_filename: DataFrame}. Builds/overwrites a per-session
    SQLite DB with one sanitized table per file. Returns metadata: db_path,
    and a list of {table, original_filename, rows, columns, truncated}."""
    session_id = session_id or uuid.uuid4().hex[:12]
    import os
    os.makedirs(UPLOAD_DB_DIR, exist_ok=True)
    db_path = f"{UPLOAD_DB_DIR}/session_{session_id}.db"

    conn = sqlite3.connect(db_path)
    table_names_used = set()
    tables_meta = []

    for filename, df in files.items():
        was_truncated = len(df) >= MAX_ROWS_PER_FILE
        table_name = sanitize_identifier(filename.rsplit(".", 1)[0], table_names_used)

        col_names_used = set()
        df = df.copy()
        df.columns = [sanitize_identifier(c, col_names_used) for c in df.columns]

        df.to_sql(table_name, conn, if_exists="replace", index=False)
        tables_meta.append({
            "table": table_name,
            "original_filename": filename,
            "rows": len(df),
            "columns": list(df.columns),
            "truncated": was_truncated,
        })

    conn.close()
    return {"db_path": db_path, "tables": tables_meta, "session_id": session_id}
