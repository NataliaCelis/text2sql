# Text-to-SQL Analyst

A web app that turns plain-English business questions into validated SQL,
runs them against a real relational database. It takes your own uploaded CSV/
Excel/JSON files, or a built-in demo database and returns results + a
chart + a plain-English explanation. Supports follow-up questions and
self-heals when the generated SQL fails to execute.

## Features
- **Bring your own data** — upload one or more CSV/Excel/JSON files and
  they're loaded into a session-scoped SQLite database. Multiple
  files can be joined in the same question (e.g. a `customers.csv` +
  `orders.csv` pair), since they land in the same DB. Column/table names
  are automatically sanitized into valid SQL identifiers.
- **Data Preview tab** — browse any table's row/column counts, per-column
  dtype/null/distinct-value stats, and a sample of rows, before asking a
  single question.
- **Self-healing retries** — if generated SQL fails to execute, the DB error
  is fed back to the model, which gets up to 2 attempts to fix it before
  giving up. Shown in the UI ("Self-corrected after N attempt(s)").
- **Multi-turn conversation** — follow-ups like "now break that down by
  country" resolve against the last 3 turns of context.
- **Plain-English explanation** under every query.
- **Suggested questions** — a button that asks Claude to propose 4 relevant
  questions tailored to your specific uploaded schema.
- **Editable SQL** — every result has an "Edit & re-run" panel so a SQL-
  literate user can tweak the generated query directly.
- **Chart type picker** (bar/line/area) per result, plus CSV export.
- **Query history** — sidebar shows the last 10; a Full History tab shows
  the last 50 with one-click re-run of any past question.
- **Tested + CI'd** — a pytest suite (32 tests: safety validation, demo
  fallback, execution, upload/sanitization, multi-file joins, profiling,
  full pipeline) runs automatically on every push via GitHub Actions.

## Architecture
```
upload (CSV/Excel/JSON) -> data_loader.py -> session-scoped SQLite DB
        (or) demo Chinook DB
                |
question (Streamlit UI, with conversation history)
      -> schema.py            builds table/column/FK context for active DB
      -> sql_engine.generate_sql()   Claude API -> SQL (+ prior-turn context)
      -> sql_engine.validate_sql()   SELECT-only safety check
      -> sql_engine.run_sql()        executes against the active DB
         on failure: error fed back to generate_sql() for self-healing retry
      -> sql_engine.explain_sql()    plain-English explanation
      -> query_log.log_query()       every attempt logged
      -> Streamlit             shows SQL + explanation + result + chart + CSV download
```

## Files
```
app.py                Streamlit UI - tabbed: Ask / Data Preview / Full History
sql_engine.py          LLM call, retries, validation, execution, explanation, suggestions
schema.py               extracts schema text + table list for any SQLite DB
profiling.py            table preview, row counts, column-level stats
data_loader.py           CSV/Excel/JSON upload -> sanitized, session-scoped SQLite DB
demo_fallback.py         offline demo mode (no API key required, Chinook DB only)
query_log.py             logs every query to data/query_log.db
tests/test_engine.py      pytest: safety, demo, execution, full pipeline (21 tests)
tests/test_data_loader.py   pytest: sanitization, upload, joins, schema (7 tests)
tests/test_profiling.py     pytest: preview, row counts, column stats (5 tests)
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
The model is only ever allowed to answer with a `SELECT`. Before execution,
`validate_sql()` independently re-checks the output:
- Rejects anything that isn't a single `SELECT` statement
- Blocks `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/PRAGMA/VACUUM`
- Blocks multi-statement queries (`;`-separated)

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

