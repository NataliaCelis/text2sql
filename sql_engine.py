"""Agentic pipeline: Claude drives an explore/execute/visualize/finish tool loop to turn a question into validated, executed SQL and a chart choice."""
import os
import re
import json
import sqlite3
import pandas as pd
from schema import get_schema_text, list_tables_with_counts, get_table_schema
from query_log import log_query

DB_PATH = "data/chinook.db"
MAX_RETRIES = 2
MAX_STEPS = 8
MODEL = "claude-sonnet-5"
CHART_TYPES = {"bar", "line", "area", "scatter", "pie", "table"}

AGENT_SYSTEM_PROMPT = """You are a SQL analytics agent for a SQLite database. You
answer business questions by calling tools - you never just print SQL, a chart
choice, or an explanation as plain text.

You are not given the schema up front - explore it yourself:
- Call list_tables to see what's available (name + row count).
- Call describe_table for any table you plan to query, to see its columns, types,
  and foreign keys. Only describe tables you actually need.

Then:
1. Call execute_sql with a single SQLite SELECT query that answers the question.
2. Look at what comes back:
   - If it's an error, read it, fix the query, and call execute_sql again.
   - If it's a result, decide whether it actually answers the question. If not
     (wrong grouping, wrong columns, empty when it shouldn't be), fix the query
     and call execute_sql again.
3. Once a result correctly answers the question, call visualize to choose how (or
   whether) to chart it - pick "table" if a chart wouldn't help.
4. Call finish with a short, plain-English explanation of what the query computes
   (for a non-technical business stakeholder - no SQL jargon).

Rules:
- Only SELECT queries. Never INSERT, UPDATE, DELETE, DROP, ALTER, etc. - these
  are rejected before they ever reach the database.
- Use table/column names exactly as returned by list_tables / describe_table.
- If prior conversation turns are given, use them to resolve references like
  "that", "those", "the same but by X" in the current question.
- Limit results to 100 rows unless the question implies otherwise (add LIMIT 100).
- You have a limited number of tool calls - explore only what you need.
"""

TOOLS = [
    {
        "name": "list_tables",
        "description": "Lists every table in the target database with its row count.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "describe_table",
        "description": "Returns a table's column names, types, and foreign keys.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Exact table name, as returned by list_tables."}
            },
            "required": ["table"],
        },
    },
    {
        "name": "execute_sql",
        "description": (
            "Validates (SELECT-only, single statement) and executes a SQLite "
            "query against the target database. Returns the row count, column "
            "names, and up to 20 sample rows on success, or the raw database "
            "error message on failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SQLite SELECT statement."}
            },
            "required": ["sql"],
        },
    },
    {
        "name": "visualize",
        "description": "Call once, after execute_sql has succeeded, to choose how the result should be charted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chart": {"type": "string", "enum": sorted(CHART_TYPES)},
                "x": {"type": "string", "description": "Column for the x-axis/category. Omit if not applicable."},
                "y": {"type": "string", "description": "Column for the y-axis/value. Omit if not applicable."},
                "color": {"type": "string", "description": "Column to split by color/series. Omit if not applicable."},
                "reason": {"type": "string", "description": "One short sentence explaining the choice."},
            },
            "required": ["chart", "reason"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Call this once an execute_sql call has succeeded and its result "
            "correctly answers the question. Ends the turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "explanation": {
                    "type": "string",
                    "description": "One or two short, plain-English sentences describing what the query computes.",
                }
            },
            "required": ["explanation"],
        },
    },
]

SUGGEST_SYSTEM_PROMPT = """Given a SQLite schema, suggest 4 interesting, specific business
questions a user could ask about this data. Output ONLY the 4 questions, one per line,
no numbering, no bullets, no extra commentary. Make them concrete (reference actual
column/table names in spirit, not literally) and varied (aggregation, ranking, trend,
comparison)."""

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


class SQLGenerationError(Exception):
    pass


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SQLGenerationError("No ANTHROPIC_API_KEY set")
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def suggest_questions(db_path: str) -> list:
    """[] in demo mode (no API key)."""
    try:
        client = _client()
    except SQLGenerationError:
        return []
    schema_text = get_schema_text(db_path)
    resp = client.messages.create(
        model=MODEL,
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


def _execute_tool(sql: str, db_path: str):
    try:
        validate_sql(sql)
        df = run_sql(sql, db_path=db_path)
        payload = {
            "success": True,
            "row_count": len(df),
            "columns": list(df.columns),
            "sample_rows": json.loads(df.head(20).to_json(orient="records", date_format="iso")),
        }
        return payload, df, None
    except Exception as e:
        error = str(e)
        return {"success": False, "error": error}, None, error


def _run_agent(question: str, db_path: str, history: list) -> dict:
    """Raises SQLGenerationError if no API key is configured."""
    client = _client()

    convo_context = ""
    if history:
        turns = "\n".join(f"Q: {h['question']}\nSQL: {h['sql']}" for h in history[-3:])
        convo_context = f"PRIOR CONVERSATION (for resolving references):\n{turns}\n\n"

    messages = [{"role": "user", "content": f"{convo_context}QUESTION: {question}"}]

    last_sql, last_df, last_error = None, None, None
    retries = 0
    explanation = None
    chart_choice = None

    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=800, system=AGENT_SYSTEM_PROMPT,
            tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            break

        tool_results = []
        finished = False
        retries_exhausted = False
        for call in calls:
            if call.name == "list_tables":
                content = json.dumps(list_tables_with_counts(db_path))
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": content})

            elif call.name == "describe_table":
                table = call.input.get("table", "")
                try:
                    content = get_table_schema(db_path, table)
                    tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": content})
                except ValueError as e:
                    tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(e), "is_error": True})

            elif call.name == "execute_sql":
                sql = call.input.get("sql", "")
                payload, df, error = _execute_tool(sql, db_path)
                last_sql = sql
                if error is None:
                    last_df, last_error = df, None
                else:
                    last_error = error
                    if retries >= MAX_RETRIES:
                        retries_exhausted = True
                        payload = {
                            **payload,
                            "note": "No retries left. Do not call execute_sql again - "
                                     "report the failure in plain text instead.",
                        }
                    else:
                        retries += 1
                tool_results.append({
                    "type": "tool_result", "tool_use_id": call.id,
                    "content": json.dumps(payload, default=str),
                    "is_error": error is not None,
                })

            elif call.name == "visualize":
                if last_df is None or last_error is not None:
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": call.id,
                        "content": "No successful query result yet - call execute_sql first.",
                        "is_error": True,
                    })
                else:
                    chart = call.input.get("chart")
                    chart_choice = {
                        "chart": chart if chart in CHART_TYPES else "table",
                        "x": call.input.get("x"), "y": call.input.get("y"),
                        "color": call.input.get("color"), "reason": call.input.get("reason", ""),
                    }
                    tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": "ok"})

            elif call.name == "finish":
                if last_df is None or last_error is not None:
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": call.id,
                        "content": "No successful query result yet - call execute_sql first.",
                        "is_error": True,
                    })
                else:
                    explanation = call.input.get("explanation")
                    finished = True
                    tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": "ok"})

        messages.append({"role": "user", "content": tool_results})

        if finished:
            break
        if retries_exhausted:
            break

    if last_df is not None and last_error is None:
        return {
            "sql": last_sql, "result": last_df, "error": None, "mode": "live",
            "retries": retries, "explanation": explanation, "chart": chart_choice,
        }
    return {
        "sql": last_sql, "result": None,
        "error": last_error or "The agent could not produce a working query.",
        "mode": "live", "retries": retries, "explanation": None, "chart": None,
    }


def ask(question: str, db_path: str = None, history: list = None) -> dict:
    active_db = db_path or DB_PATH
    try:
        result = _run_agent(question, active_db, history)
    except SQLGenerationError:
        from demo_fallback import match_demo_query
        sql = match_demo_query(question) if active_db == DB_PATH else None
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
        try:
            df = run_sql(sql, db_path=active_db)
            log_query(question, sql, "demo", success=True, retries=0)
            return {
                "sql": sql, "result": df, "error": None, "mode": "demo",
                "retries": 0, "explanation": None,
            }
        except Exception as e:
            log_query(question, sql, "demo", success=False, retries=0, error=str(e))
            return {
                "sql": sql, "result": None, "error": str(e), "mode": "demo",
                "retries": 0, "explanation": None,
            }

    if result["error"] is None:
        log_query(question, result["sql"], result["mode"], success=True, retries=result["retries"])
    else:
        log_query(question, result["sql"], result["mode"], success=False, retries=result["retries"], error=result["error"])
    return result
