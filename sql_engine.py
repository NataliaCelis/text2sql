"""Core engine: natural language -> SQL -> validated -> executed."""
import os
import re
import sqlite3
import pandas as pd
from schema import get_schema_text

DB_PATH = "data/chinook.db"

SYSTEM_PROMPT = """You are a SQL generator for a SQLite database. Given a schema and a
question, output ONLY a single valid SQLite SELECT query that answers the question.
Rules:
- Output ONLY the SQL query, no explanation, no markdown code fences, no comments.
- Only generate SELECT statements. Never INSERT, UPDATE, DELETE, DROP, ALTER, etc.
- Use table/column names exactly as given in the schema.
- If the question is ambiguous, make a reasonable assumption and answer it.
- Limit results to 100 rows unless the question implies otherwise (add LIMIT 100).
"""

# Forbidden keywords as a defense-in-depth check even though we only ever
# ask the model for SELECTs. Never trust LLM output as inherently safe.
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


class SQLGenerationError(Exception):
    pass


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```sql\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def generate_sql(question: str) -> str:
    """Calls the Claude API to translate a question into SQL. Raises
    SQLGenerationError if no API key is configured (caller should fall
    back to demo mode)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SQLGenerationError("No ANTHROPIC_API_KEY set")

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    schema_text = get_schema_text()
    user_prompt = f"SCHEMA:\n{schema_text}\n\nQUESTION: {question}\n\nSQL:"

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    sql = resp.content[0].text
    return _strip_code_fences(sql)


def validate_sql(sql: str) -> None:
    """Raises ValueError if the SQL isn't a safe, single SELECT statement."""
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise ValueError("Empty query generated.")
    if ";" in stripped:
        raise ValueError("Multiple statements are not allowed.")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(stripped):
        raise ValueError("Query contains a forbidden keyword.")


def run_sql(sql: str, db_path: str = DB_PATH) -> pd.DataFrame:
    validate_sql(sql)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql, conn)
    finally:
        conn.close()
    return df


def ask(question: str) -> dict:
    """Full pipeline: question -> SQL -> validated -> executed -> result.
    Returns a dict with keys: sql, result (DataFrame), error (str or None),
    mode ('live' or 'demo')."""
    try:
        sql = generate_sql(question)
        mode = "live"
    except SQLGenerationError:
        from demo_fallback import match_demo_query
        sql = match_demo_query(question)
        mode = "demo"
        if sql is None:
            return {
                "sql": None,
                "result": None,
                "error": (
                    "No ANTHROPIC_API_KEY configured, and this question doesn't "
                    "match a demo example. Set ANTHROPIC_API_KEY to enable live "
                    "generation, or try one of the example questions."
                ),
                "mode": "demo",
            }

    try:
        df = run_sql(sql)
        return {"sql": sql, "result": df, "error": None, "mode": mode}
    except Exception as e:
        return {"sql": sql, "result": None, "error": str(e), "mode": mode}
