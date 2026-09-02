import os
import streamlit as st
import pandas as pd
from sql_engine import ask, run_sql, validate_sql, suggest_questions, DB_PATH
from query_log import get_recent_queries
from data_loader import read_uploaded_file, build_session_db, UploadError
from schema import get_table_names
from profiling import get_preview, get_row_count, get_column_profile

st.set_page_config(page_title="Text-to-SQL Analyst", page_icon="💻", layout="wide")

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

for key, default in [
    ("history", []), ("turns", []), ("active_db", DB_PATH),
    ("uploaded_tables", []), ("suggested_qs", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title("Text-to-SQL Analyst")
st.caption(
    "Ask a business question in plain English and get back SQL, results, a chart, and an explanation. Upload your own CSV/Excel/JSON to query your own data!"
)

# --- Data source: upload or demo -------------------------------------------
with st.expander("Data source", expanded=(st.session_state.active_db == DB_PATH and not st.session_state.uploaded_tables)):
    tab_upload, tab_demo = st.tabs(["Upload your own files", "Use demo database"])

    with tab_upload:
        st.caption("Upload one or more CSV / Excel / JSON files (max 50MB, 200K rows each). Each file becomes a table you can query — including joining across files.")
        uploaded_files = st.file_uploader("Choose file(s)", type=["csv", "xlsx", "xls", "json"], accept_multiple_files=True)
        if uploaded_files and st.button("Load these files", type="primary"):
            with st.spinner("Reading files and building your database..."):
                dfs, errors = {}, []
                for f in uploaded_files:
                    try:
                        dfs[f.name] = read_uploaded_file(f)
                    except UploadError as e:
                        errors.append(str(e))
                for e in errors:
                    st.error(e)
                if dfs:
                    meta = build_session_db(dfs)
                    st.session_state.active_db = meta["db_path"]
                    st.session_state.uploaded_tables = meta["tables"]
                    st.session_state.history = []
                    st.session_state.turns = []
                    st.session_state.suggested_qs = []
                    st.success(f"Loaded {len(meta['tables'])} table(s). Check the Data Preview tab, then ask away!")
                    st.rerun()

        if st.session_state.uploaded_tables and st.session_state.active_db != DB_PATH:
            st.markdown("**Currently querying your uploaded data:**")
            for t in st.session_state.uploaded_tables:
                warn = " truncated to 200K rows" if t["truncated"] else ""
                st.caption(f"`{t['table']}` — {t['rows']:,} rows, {len(t['columns'])} columns{warn} (from {t['original_filename']})")

    with tab_demo:
        st.caption("A pre-loaded music store database (customers, invoices, tracks, artists, genres) — works even without an API key, via a small offline demo set.")
        if st.button("Switch to demo database"):
            st.session_state.active_db = DB_PATH
            st.session_state.uploaded_tables = []
            st.session_state.history = []
            st.session_state.turns = []
            st.session_state.suggested_qs = []
            st.rerun()

using_own_data = st.session_state.active_db != DB_PATH
st.info("Querying **your uploaded data**" if using_own_data else "Querying the **demo Chinook database**", icon=" 📌 ")

# --- Sidebar: recent query history -----------------------------------------
with st.sidebar:
    st.subheader("Recent queries")
    recent = get_recent_queries(limit=10)
    if not recent:
        st.caption("No queries yet.")
    for ts, q, mode, success, retries in recent:
        icon = "YES" if success else "NO"
        badge = f" · {retries} retr{'y' if retries==1 else 'ies'}" if retries else ""
        st.markdown(f"{icon} **{q}**  \n<small>{mode}{badge}</small>", unsafe_allow_html=True)
    if st.button("Clear conversation"):
        st.session_state.history = []
        st.session_state.turns = []
        st.rerun()

tab_ask, tab_preview, tab_history = st.tabs(["Ask", "Data Preview", "Full History"])

# =============================================================================
# TAB: Ask
# =============================================================================
with tab_ask:
    if not using_own_data:
        EXAMPLES = [
            "Top 5 artists by revenue", "Which country has the most customers",
            "Total revenue by genre", "Who are the top 10 customers by total spend",
            "Monthly revenue trend",
        ]
        st.markdown("**Try an example:**")
        cols = st.columns(len(EXAMPLES))
        clicked = None
        for c, ex in zip(cols, EXAMPLES):
            if c.button(ex, use_container_width=True):
                clicked = ex
    else:
        clicked = None
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if has_key:
            if st.button("Suggest questions for my data"):
                with st.spinner("Thinking of good questions..."):
                    st.session_state.suggested_qs = suggest_questions(st.session_state.active_db)
            if st.session_state.suggested_qs:
                st.markdown("**Suggested questions:**")
                cols = st.columns(len(st.session_state.suggested_qs))
                for c, sq in zip(cols, st.session_state.suggested_qs):
                    if c.button(sq, use_container_width=True):
                        clicked = sq
        else:
            st.warning("Querying your own data requires ANTHROPIC_API_KEY (demo mode only covers the built-in database).")

    question = st.text_input(
        "Ask a question (follow-ups like 'now show it by country' work too)",
        placeholder="e.g. Which employee generated the most sales?",
    )

    go = st.button("Ask", type="primary") or clicked
    if go:
        q = clicked if clicked else question
        if not q:
            st.warning("Enter a question first.")
        else:
            with st.spinner("Generating SQL and running query..."):
                result = ask(q, db_path=st.session_state.active_db, history=st.session_state.history)
            st.session_state.turns.append({"question": q, **result})
            if result["sql"] and result["error"] is None:
                st.session_state.history.append({"question": q, "sql": result["sql"]})
            st.rerun()

    for i, turn in enumerate(reversed(st.session_state.turns)):
        with st.container(border=True):
            st.markdown(f"**Q: {turn['question']}**")

            if turn["mode"] == "demo":
                st.caption("Offline demo mode (no ANTHROPIC_API_KEY set)")
            if turn.get("retries"):
                st.caption(f"Self-corrected after {turn['retries']} failed attempt(s)")

            if turn["error"]:
                st.error(turn["error"])
                if turn["sql"]:
                    st.code(turn["sql"], language="sql")
            else:
                st.code(turn["sql"], language="sql")
                if turn.get("explanation"):
                    st.caption(f" {turn['explanation']}")

                df = turn["result"]
                st.dataframe(df, use_container_width=True)

                c1, c2 = st.columns([1, 3])
                with c1:
                    st.download_button(
                        "Download CSV", df.to_csv(index=False).encode("utf-8"),
                        file_name="query_result.csv", mime="text/csv", key=f"dl_{i}",
                    )

                if df.shape[1] == 2 and df.shape[0] > 1 and pd.api.types.is_numeric_dtype(df[df.columns[1]]):
                    chart_type = st.radio(
                        "Chart type", ["Bar", "Line", "Area"], horizontal=True,
                        key=f"chart_{i}", label_visibility="collapsed",
                    )
                    label_col, value_col = df.columns[0], df.columns[1]
                    chart_df = df.set_index(label_col)[value_col]
                    if chart_type == "Bar":
                        st.bar_chart(chart_df)
                    elif chart_type == "Line":
                        st.line_chart(chart_df)
                    else:
                        st.area_chart(chart_df)

                with st.expander("Edit & re-run this SQL"):
                    edited = st.text_area("SQL", value=turn["sql"], key=f"edit_{i}", height=100, label_visibility="collapsed")
                    if st.button("Run edited SQL", key=f"run_edit_{i}"):
                        try:
                            validate_sql(edited)
                            edited_df = run_sql(edited, db_path=st.session_state.active_db)
                            st.dataframe(edited_df, use_container_width=True)
                        except Exception as e:
                            st.error(str(e))

# =============================================================================
# TAB: Data Preview
# =============================================================================
with tab_preview:
    tables = get_table_names(st.session_state.active_db)
    if not tables:
        st.info("No tables found.")
    else:
        selected_table = st.selectbox("Table", tables)
        if selected_table:
            row_count = get_row_count(st.session_state.active_db, selected_table)
            preview_df = get_preview(st.session_state.active_db, selected_table, n=20)
            profile_df = get_column_profile(st.session_state.active_db, selected_table)

            m1, m2 = st.columns(2)
            m1.metric("Rows", f"{row_count:,}")
            m2.metric("Columns", len(preview_df.columns))

            st.markdown("**Column profile**")
            st.dataframe(profile_df, use_container_width=True, hide_index=True)

            st.markdown("**Preview (first 20 rows)**")
            st.dataframe(preview_df, use_container_width=True)

# =============================================================================
# TAB: Full History
# =============================================================================
with tab_history:
    all_recent = get_recent_queries(limit=50)
    if not all_recent:
        st.caption("No queries logged yet.")
    for ts, q, mode, success, retries in all_recent:
        icon = "YES" if success else "NO"
        with st.expander(f"{icon} {q}  —  {ts.split('T')[0]} {ts.split('T')[1][:8]} UTC"):
            st.caption(f"Mode: {mode} · Retries: {retries}")
            if st.button("Ask this again", key=f"rerun_{ts}_{q[:20]}"):
                with st.spinner("Re-running..."):
                    result = ask(q, db_path=st.session_state.active_db, history=st.session_state.history)
                st.session_state.turns.append({"question": q, **result})
                st.rerun()

st.divider()
with st.expander("How this works / safety notes"):
    st.markdown(
        """
- **Bring your own data**: upload CSV/Excel/JSON files above and they're loaded into an
  isolated, session-scoped SQLite database. Multiple files can be joined in the same
  question since they land in the same database.
- **Data Preview tab**: browse any table's row/column counts, per-column dtype/null/distinct
  stats, and a sample of rows before you even ask a question.
- The database schema (+ up to 3 prior conversation turns, for follow-ups) is sent to Claude
  along with your question, which returns a single SQL query.
- Before execution, the query is validated: **only `SELECT` statements are allowed** — any
  `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc. is rejected, and multi-statement queries
  are blocked. The same validation applies if you manually edit and re-run a query.
- **Self-healing retries**: if the query fails to execute, the database error is fed back to
  the model, which gets up to 2 attempts to fix it before giving up.
- Every query is logged (question, SQL, mode, success/failure, retry count) — see the sidebar
  or the Full History tab, which also lets you re-run any past question.
- Demo database: [Chinook](https://github.com/lerocha/chinook-database) (a music store).
        """
    )
