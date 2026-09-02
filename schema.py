"""Extracts and formats the DB schema so it can be passed to the LLM as context."""
import sqlite3

DB_PATH = "data/chinook.db"


def get_schema_text(db_path: str = DB_PATH) -> str:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]

    lines = []
    for t in tables:
        cur.execute(f"PRAGMA table_info('{t}')")
        cols = cur.fetchall()
        col_strs = [f"{c[1]} {c[2]}" for c in cols]
        cur.execute(f"PRAGMA foreign_key_list('{t}')")
        fks = cur.fetchall()
        fk_strs = [f"{f[3]} -> {f[2]}.{f[4]}" for f in fks]
        block = f"TABLE {t} ({', '.join(col_strs)})"
        if fk_strs:
            block += f"\n  FOREIGN KEYS: {', '.join(fk_strs)}"
        lines.append(block)
    conn.close()
    return "\n".join(lines)


def get_table_names(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    conn.close()
    return tables


if __name__ == "__main__":
    print(get_schema_text())
