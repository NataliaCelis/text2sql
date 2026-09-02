"""Core engine: natural language -> SQL -> validated -> executed.
v2: adds self-healing retries on execution error, multi-turn conversation
context, plain-English SQL explanation, and query history logging."""
import os
import re
import sqlite3
import pandas as pd
from schema import get_schema_text
from query_log import log_query

DB_PATH = "data/chinook.db"
MAX_RETRIES = 2

SYSTEM_PROMPT = """You are a SQL generator for a SQLite database. Given a schema and a
question, output ONLY a single valid SQLite SELECT query that answers the question.
Rules:
- Output ONLY the SQL query, no explanation, no markdown code fences, no comments.
- Only generate SELECT statements. Never INSERT, UPDATE, DELETE, DROP, ALTER, etc.
- Use table/column names exactly as given in the schema.
- If the question is ambiguous, make a reasonable assumption and answer it.
- If prior conversation turns are given, use them to resolve references like
  "that", "those", "the same but by X" in the current question.
- Limit results to 100 rows unless the question implies otherwise (add LIMIT 100).
"""

EXPLAIN_SYSTEM_PROMPT = """Explain the given SQL query in one or two short, plain-English
sentences a non-technical business stakeholder would understand. No jargon, no
restating the SQL syntax itself - describe what it computes."""

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


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SQLGenerationError("No ANTHROPIC_API_KEY set")
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def generate_sql(question: str, db_path: str = None, history: list = None, prior_error: str = None, prior_sql: str = None) -> str:
    """Calls Claude to translate a question into SQL.
    db_path: which SQLite DB's schema to use as context (defaults to Chinook).
    history: list of {"question": str, "sql": str} from earlier turns, for
             multi-turn follow-up questions.
    prior_error/prior_sql: when retrying after a failed execution, passes the
             broken SQL and the DB error back so the model can fix it."""
    client = _client()
    schema_text = get_schema_text(db_path or DB_PATH)

    convo_context = ""
    if history:
        turns = "\n".join(f"Q: {h['question']}\nSQL: {h['sql']}" for h in history[-3:])
        convo_context = f"\nPRIOR CONVERSATION (for resolving references):\n{turns}\n"

    if prior_error:
        user_prompt = (
            f"SCHEMA:\n{schema_text}\n{convo_context}\n"
            f"QUESTION: {question}\n\n"
            f"Your previous attempt failed. Fix it.\n"
            f"PREVIOUS SQL:\n{prior_sql}\n"
            f"DATABASE ERROR:\n{prior_error}\n\n"
            f"Corrected SQL:"
        )
    else:
        user_prompt = f"SCHEMA:\n{schema_text}\n{convo_context}\nQUESTION: {question}\n\nSQL:"

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return _strip_code_fences(resp.content[0].text)


def explain_sql(sql: str) -> str:
    """Plain-English explanation of a query. Returns None in demo mode
    (no API key) rather than failing the whole pipeline over a nice-to-have."""
    try:
        client = _client()
    except SQLGenerationError:
        return None
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=150,
        system=EXPLAIN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": sql}],
    )
    return resp.content[0].text.strip()


SUGGEST_SYSTEM_PROMPT = """Given a SQLite schema, suggest 4 interesting, specific business
questions a user could ask about this data. Output ONLY the 4 questions, one per line,
no numbering, no bullets, no extra commentary. Make them concrete (reference actual
column/table names in spirit, not literally) and varied (aggregation, ranking, trend,
comparison)."""


def suggest_questions(db_path: str) -> list:
    """Returns 4 example questions tailored to the given DB's schema.
    Returns [] in demo mode (no API key)."""
    try:
        client = _client()
    except SQLGenerationError:
        return []
    schema_text = get_schema_text(db_path)
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        system=SUGGEST_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"SCHEMA:\n{schema_text}"}],
    )
    lines = [l.strip("-• \t") for l in resp.content[0].text.strip().split("\n") if l.strip()]
    return lines[:4]


def validate_sql(sql: str) -> None:
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


def ask(question: str, db_path: str = None, history: list = None) -> dict:
    """Full pipeline: question -> SQL -> validated -> executed -> result,
    with up to MAX_RETRIES self-healing attempts on execution failure.
    db_path: which SQLite DB to query (defaults to the Chinook demo DB).
    Returns dict: sql, result, error, mode, retries, explanation."""
    active_db = db_path or DB_PATH
    try:
        sql = generate_sql(question, db_path=active_db, history=history)
        mode = "live"
    except SQLGenerationError:
        from demo_fallback import match_demo_query
        # demo fallback only makes sense against the built-in Chinook DB
        sql = match_demo_query(question) if active_db == DB_PATH else None
        mode = "demo"
        if sql is None:
            log_query(question, None, "demo", success=False, error="no demo match")
            reason = (
                "No ANTHROPIC_API_KEY configured, and this question doesn't "
                "match a demo example. Set ANTHROPIC_API_KEY to enable live "
                "generation, or try one of the example questions."
                if active_db == DB_PATH else
                "No ANTHROPIC_API_KEY configured. Live SQL generation is "
                "required to query your uploaded data (demo mode only "
                "covers the built-in Chinook dataset)."
            )
            return {
                "sql": None, "result": None, "explanation": None, "retries": 0,
                "error": reason, "mode": "demo",
            }

    retries = 0
    last_error = None
    while True:
        try:
            df = run_sql(sql, db_path=active_db)
            explanation = explain_sql(sql) if mode == "live" else None
            log_query(question, sql, mode, success=True, retries=retries)
            return {
                "sql": sql, "result": df, "error": None, "mode": mode,
                "retries": retries, "explanation": explanation,
            }
        except Exception as e:
            last_error = str(e)
            if mode != "live" or retries >= MAX_RETRIES:
                log_query(question, sql, mode, success=False, retries=retries, error=last_error)
                return {
                    "sql": sql, "result": None, "error": last_error, "mode": mode,
                    "retries": retries, "explanation": None,
                }
            # self-healing retry: feed the error back to the model
            retries += 1
            try:
                sql = generate_sql(question, db_path=active_db, history=history, prior_error=last_error, prior_sql=sql)
            except SQLGenerationError:
                log_query(question, sql, mode, success=False, retries=retries, error=last_error)
                return {
                    "sql": sql, "result": None, "error": last_error, "mode": mode,
                    "retries": retries, "explanation": None,
                }
