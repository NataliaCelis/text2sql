# Text-to-SQL Analyst

A self-healing LLM analytics agent that turns plain-English business questions
into validated SQL, executes it against your uploaded datasets (or a built-in
demo database), and generates interactive visualizations — with SELECT-only
safeguards enforced independently of the model. Claude isn't handed a schema
and a fixed pipeline; it's given five tools (`list_tables`, `describe_table`,
`execute_sql`, `visualize`, `finish`) and works the problem itself — deciding
what to explore, when to retry, and how to chart the result. Supports
follow-up questions.

## Features
- **Agentic, tool-driven pipeline** — Claude gets no schema up front. It
  explores the database itself (`list_tables`, `describe_table`), writes and
  runs SQL (`execute_sql`), reads back the real database error or result,
  and decides on its own whether to retry with a corrected query, look at
  another table, chart the result (`visualize`), or stop (`finish`). The
  loop doesn't script that sequence — it just executes whichever tool the
  model calls next, up to a hard step cap. Every `execute_sql` call is
  independently re-validated (SELECT-only, single statement) before it
  touches the database, regardless of what the model asks for.
- **Bring your own data** — upload one or more CSV/Excel/JSON files and
  they're loaded into a session-scoped SQLite database. Multiple
  files can be joined in the same question (e.g. a `customers.csv` +
  `orders.csv` pair), since they land in the same DB. Column/table names
  are automatically sanitized into valid SQL identifiers.
- **Data Preview tab** — browse any table's row/column counts, per-column
  dtype/null/distinct-value stats, and a sample of rows, before asking a
  single question.
- **Self-healing retries** — if a query fails to execute, the DB error is fed
  back to the model as its tool result, and it gets up to 2 attempts to fix
  it before giving up. Shown in the UI ("Self-corrected after N attempt(s)").
- **Multi-turn conversation** — follow-ups like "now break that down by
  country" resolve against the last 3 turns of context.
- **Plain-English explanation** under every query.
- **Interactive visualization, chosen by the same agent** — once a query
  succeeds, the agent's own `visualize` tool call picks a chart type
  (bar/line/area/scatter/pie, or "table" when a chart wouldn't help) and
  which columns go on which axis, in the same tool-use session as the SQL -
  no separate LLM call. Rendered with Plotly for real interactivity — hover
  tooltips, zoom/pan, toggleable legends — with a manual override and a
  heuristic fallback in demo mode.
- **Suggested questions** — a button that asks Claude to propose 4 relevant
  questions tailored to your specific uploaded schema.
- **Editable SQL** — every result has an "Edit & re-run" panel so a SQL-
  literate user can tweak the generated query directly.
- **Query history** — sidebar shows the last 10; a Full History tab shows
  the last 50 with one-click re-run of any past question.
- **Tested + CI'd** — a pytest suite (48 tests: safety validation, the
  agentic tool loop and its schema-exploration/visualize/finish gating,
  demo fallback, execution, upload/sanitization, multi-file joins,
  profiling, visualization, full pipeline) runs automatically on every push
  via GitHub Actions.

## Architecture
```
upload (CSV/Excel/JSON) -> data_loader.py -> session-scoped SQLite DB
        (or) demo Chinook DB
                |
question (Streamlit UI, with conversation history)
      -> sql_engine._run_agent()   Claude drives its own tool loop, calling
                                    whichever of these it needs, in whatever order:
           list_tables      -> schema.list_tables_with_counts()   table names + row counts
           describe_table    -> schema.get_table_schema()          one table's columns/types/FKs
           execute_sql       -> sql_engine.validate_sql()          SELECT-only safety check
                              -> sql_engine.run_sql()               executes against the active DB
                                 on failure: DB error returned as the tool result,
                                 model decides whether to retry (up to MAX_RETRIES)
           visualize         -> chart type + axis choice, gated on a successful execute_sql
           finish            -> plain-English explanation, ends the loop
      -> visualization.render_chart()   interactive Plotly figure from the agent's choice
      -> query_log.log_query()          every attempt logged
      -> Streamlit                      shows SQL + explanation + result + chart + CSV download
```

## Files
```
app.py                Streamlit UI - tabbed: Ask / Data Preview / Full History
sql_engine.py          agentic tool loop (explore/execute/visualize/finish), validation, suggestions
visualization.py        heuristic chart fallback (demo mode) + interactive Plotly rendering
schema.py               full-schema text, per-table schema, and table/row-count listing
profiling.py            table preview, row counts, column-level stats
data_loader.py           CSV/Excel/JSON upload -> sanitized, session-scoped SQLite DB
demo_fallback.py         offline demo mode (no API key required, Chinook DB only)
query_log.py             logs every query to data/query_log.db
tests/test_engine.py      pytest: safety, agentic loop + tool gating, demo, execution, full pipeline
tests/test_data_loader.py   pytest: sanitization, upload, joins, schema
tests/test_profiling.py     pytest: preview, row counts, column stats
tests/test_visualization.py  pytest: chart heuristic + Plotly rendering
.github/workflows/ci.yml   GitHub Actions: runs pytest on every push
data/chinook.db            demo SQLite DB (customers, invoices, tracks, artists...)
tmp_uploads/                session-scoped DBs built from user uploads (gitignored)
requirements.txt
runtime.txt                pins Python 3.11 for Streamlit Cloud
.streamlit/secrets.toml.example   copy -> .streamlit/secrets.toml, add your key
```

## Run locally
```bash
pip install -r requirements.txt
pip install pytest    # for running tests
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

## Run tests
```bash
pytest tests/ -v
```

## Deploy (free)
1. Push this folder to a public GitHub repo (CI runs automatically on push).
2. Go to share.streamlit.io -> New app -> point at the repo, `app.py` as the entrypoint.
3. In the app's Settings -> Secrets, paste:
   ```
   ANTHROPIC_API_KEY = "sk-ant-your-key-here"
   ```
4. Deploy

## Safety design
The model is only ever allowed to answer with a `SELECT`. It doesn't get
direct database access - it can only ask for a query to run via the
`execute_sql` tool, and every single call to that tool is independently
re-checked by `validate_sql()` before anything touches the database:
- Rejects anything that isn't a single `SELECT` statement
- Blocks `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/PRAGMA/VACUUM`
- Blocks multi-statement queries (`;`-separated)

This check is enforced in the tool executor itself, not just trusted from the
model's output - see `test_run_agent_enforces_select_only_even_if_model_tries_unsafe_sql`
in `tests/test_engine.py` for a regression test that proves it.

Uploaded data is isolated per session (a separate SQLite file per upload
session under `tmp_uploads/`), and table/column names are sanitized before
being written to SQL, so malicious file/column names can't inject SQL.

## Datasets
- **Demo**: [Chinook](https://github.com/lerocha/chinook-database) — an
  11-table music store schema (customers, invoices, tracks, albums, artists,
  genres, employees) with real foreign-key relationships.
- **Your own**: any CSV/Excel/JSON, up to 50MB / 200K rows per file.

## Known limitations
- Ambiguous questions ("show me the best stuff") may produce a technically
  valid but semantically wrong query.
- Self-healing retries fix execution errors (bad column names, syntax),
  not semantic misunderstandings of the question.
- Read-only by design; this is an analyst tool, not a database admin tool.

