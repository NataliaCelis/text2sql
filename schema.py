"""Extracts and formats DB schema info, in full or one table at a time."""
import sqlite3

DB_PATH = "data/chinook.db"


def _table_block(cur, table: str) -> str:
    cur.execute(f"PRAGMA table_info('{table}')")
    col_strs = [f"{c[1]} {c[2]}" for c in cur.fetchall()]
    cur.execute(f"PRAGMA foreign_key_list('{table}')")
    fk_strs = [f"{f[3]} -> {f[2]}.{f[4]}" for f in cur.fetchall()]
    block = f"TABLE {table} ({', '.join(col_strs)})"
    if fk_strs:
        block += f"\n  FOREIGN KEYS: {', '.join(fk_strs)}"
    return block


def get_schema_text(db_path: str = DB_PATH) -> str:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    lines = [_table_block(cur, t) for t in tables]
    conn.close()
    return "\n".join(lines)


def get_table_names(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    conn.close()
    return tables


def list_tables_with_counts(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    result = []
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM '{t}'")
        result.append({"table": t, "row_count": cur.fetchone()[0]})
    conn.close()
    return result


def get_table_schema(db_path: str, table: str) -> str:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    valid_tables = {r[0] for r in cur.fetchall()}
    if table not in valid_tables:
        conn.close()
        raise ValueError(f"No such table: {table}")
    block = _table_block(cur, table)
    conn.close()
    return block


if __name__ == "__main__":
    print(get_schema_text())
