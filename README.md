# Text-to-SQL Analyst

A self-healing LLM analytics agent that turns plain-English business questions
into validated SQL, executes it against your uploaded datasets (or a built-in
demo database), and generates interactive visualizations — with SELECT-only
safeguards enforced independently of the model. Claude drives its own
`execute_sql` / `finish` tool-use loop: it writes a query, sees the real
database error (or result) come back, and decides for itself whether to
retry with a fix or stop. Supports follow-up questions.

## Features
- **Agentic SQL generation** — Claude doesn't just emit SQL once; it calls an
  `execute_sql` tool, reads back the real database error or result, and
  decides on its own whether to retry with a corrected query or call `finish`.
  Every `execute_sql` call is independently re-validated (SELECT-only, single
  statement) before it touches the database, regardless of what the model asks for.
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
- **Agentic, interactive visualization** — once a query succeeds, a second
  Claude call looks at the question and the shape of the result and picks a
  chart type (bar/line/area/scatter/pie, or "table" when a chart wouldn't
  help) and which columns go on which axis. Rendered with Plotly for real
  interactivity — hover tooltips, zoom/pan, toggleable legends — with a
  manual override and a graceful heuristic fallback in demo mode.
- **Suggested questions** — a button that asks Claude to propose 4 relevant
  questions tailored to your specific uploaded schema.
- **Editable SQL** — every result has an "Edit & re-run" panel so a SQL-
  literate user can tweak the generated query directly.
- **Query history** — sidebar shows the last 10; a Full History tab shows
  the last 50 with one-click re-run of any past question.
- **Tested + CI'd** — a pytest suite (45 tests: safety validation, the
  agentic tool-use loop, demo fallback, execution, upload/sanitization,
  multi-file joins, profiling, visualization, full pipeline) runs
  automatically on every push via GitHub Actions.

## Architecture
```
upload (CSV/Excel/JSON) -> data_loader.py -> session-scoped SQLite DB
        (or) demo Chinook DB
                |
question (Streamlit UI, with conversation history)
      -> schema.py                    builds table/column/FK context for active DB
      -> sql_engine._run_agent()      Claude drives its own tool-use loop:
           execute_sql tool  -> sql_engine.validate_sql()   SELECT-only safety check
                              -> sql_engine.run_sql()        executes against the active DB
                                 on failure: DB error returned as the tool result,
                                 model decides whether to retry (up to MAX_RETRIES)
           finish tool       -> plain-English explanation, ends the loop
      -> visualization.choose_chart()  agentic chart-type + axis selection
      -> visualization.render_chart()  interactive Plotly figure
      -> query_log.log_query()         every attempt logged
      -> Streamlit                     shows SQL + explanation + result + chart + CSV download
```

## Files
```
app.py                Streamlit UI - tabbed: Ask / Data Preview / Full History
sql_engine.py          agentic tool-use loop, validation, execution, suggestions
visualization.py        agentic chart selection + interactive Plotly rendering
schema.py               extracts schema text + table list for any SQLite DB
profiling.py            table preview, row counts, column-level stats
data_loader.py           CSV/Excel/JSON upload -> sanitized, session-scoped SQLite DB
demo_fallback.py         offline demo mode (no API key required, Chinook DB only)
query_log.py             logs every query to data/query_log.db
tests/test_engine.py      pytest: safety, agentic loop, demo, execution, full pipeline
tests/test_data_loader.py   pytest: sanitization, upload, joins, schema
tests/test_profiling.py     pytest: preview, row counts, column stats
tests/test_visualization.py  pytest: chart selection heuristic + Plotly rendering
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

