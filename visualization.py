"""Agentic visualization: after a query result comes back, the model looks at
the question, the SQL, and the shape of the result (columns, dtypes, a sample
of rows) and decides how best to chart it - bar/line/area/scatter/pie, which
columns go on which axis, or "table" when a chart wouldn't help. In demo mode
(no API key) a simple heuristic takes over instead. Charts render with Plotly
so results are interactive: hover tooltips, zoom/pan, and toggleable legends,
rather than a static image."""
import json
import pandas as pd
import plotly.express as px

from sql_engine import _client, _strip_code_fences, SQLGenerationError, MODEL

CHART_TYPES = {"bar", "line", "area", "scatter", "pie", "table"}

VIZ_SYSTEM_PROMPT = """You choose how to visualize a SQL query result for a business
user. Given the original question, the SQL, and the result's columns/dtypes/sample
rows, reply with ONLY a JSON object (no markdown fences, no commentary):
{"chart": "bar"|"line"|"area"|"scatter"|"pie"|"table", "x": "<column name or null>",
 "y": "<column name or null>", "color": "<column name or null>", "reason": "<short reason, one sentence>"}
Rules:
- "table" means the data isn't well suited to a chart (too many columns, a single
  scalar value, free-text-heavy, or too many rows to plot meaningfully) - the app
  will just show the table.
- Prefer "line" or "area" when x is a date/time or otherwise sequential column.
- Prefer "pie" only for a small number (<=8) of categories that sum to a meaningful whole.
- Prefer "scatter" for two numeric columns with no natural ordering between them.
- x, y, and color must be exact column names from the result, or null.
"""


def heuristic_chart(df: pd.DataFrame) -> dict:
    """No-API-key / no-LLM fallback: chart the first two columns if the second is numeric."""
    if df.shape[1] >= 2 and df.shape[0] > 1 and pd.api.types.is_numeric_dtype(df[df.columns[1]]):
        return {"chart": "bar", "x": df.columns[0], "y": df.columns[1], "color": None, "reason": "default heuristic"}
    return {"chart": "table", "x": None, "y": None, "color": None, "reason": "default heuristic"}


def choose_chart(question: str, sql: str, df: pd.DataFrame) -> dict:
    """Agentic visualization step: asks Claude how to best chart this result.
    Falls back to a heuristic if no API key is configured or the call/parse fails."""
    try:
        client = _client()
    except SQLGenerationError:
        return heuristic_chart(df)

    sample = json.loads(df.head(5).to_json(orient="records", date_format="iso"))
    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    user_prompt = (
        f"QUESTION: {question}\nSQL: {sql}\n"
        f"COLUMNS/DTYPES: {json.dumps(dtypes)}\n"
        f"ROW COUNT: {len(df)}\nSAMPLE ROWS: {json.dumps(sample, default=str)}\n"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=VIZ_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        choice = json.loads(_strip_code_fences(resp.content[0].text))
    except Exception:
        return heuristic_chart(df)

    if choice.get("chart") not in CHART_TYPES:
        return heuristic_chart(df)
    for key in ("x", "y", "color"):
        col = choice.get(key)
        if col is not None and col not in df.columns:
            choice[key] = None
    return choice


def render_chart(df: pd.DataFrame, choice: dict):
    """Builds an interactive Plotly figure for the given chart choice, or
    returns None for "table" / when there isn't enough data to plot."""
    if df.empty or not choice:
        return None
    chart = choice.get("chart")
    x, y, color = choice.get("x"), choice.get("y"), choice.get("color")
    try:
        if chart == "bar" and x and y:
            fig = px.bar(df, x=x, y=y, color=color)
        elif chart == "line" and x and y:
            fig = px.line(df, x=x, y=y, color=color, markers=True)
        elif chart == "area" and x and y:
            fig = px.area(df, x=x, y=y, color=color)
        elif chart == "scatter" and x and y:
            fig = px.scatter(df, x=x, y=y, color=color)
        elif chart == "pie" and x and y:
            fig = px.pie(df, names=x, values=y)
        else:
            return None
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=420)
        return fig
    except Exception:
        return None
