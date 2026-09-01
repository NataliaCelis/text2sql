import os
import streamlit as st
import pandas as pd

# Bridge Streamlit Cloud secrets -> env var the engine reads
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass  # no secrets.toml present locally - fine, falls back to demo mode

from sql_engine import ask

st.set_page_config(page_title="Text-to-SQL Analyst", page_icon="🎧", layout="centered")

st.title("🎧 Text-to-SQL Analyst")
st.caption(
    "Ask a business question in plain English. It's translated into SQL, "
    "run against a real Postgres/SQLite database (Chinook music store), "
    "and returned as a table + chart. No API key set? The app falls back "
    "to a small offline demo set below."
)

EXAMPLES = [
    "Top 5 artists by revenue",
    "Which country has the most customers",
    "Total revenue by genre",
    "Who are the top 10 customers by total spend",
    "Monthly revenue trend",
]

st.markdown("**Try an example:**")
cols = st.columns(len(EXAMPLES))
clicked = None
for c, ex in zip(cols, EXAMPLES):
    if c.button(ex, use_container_width=True):
        clicked = ex

question = st.text_input(
    "Or ask your own question",
    value=clicked if clicked else "",
    placeholder="e.g. Which employee generated the most sales?",
)

if st.button("Ask", type="primary") or clicked:
    q = question if question else clicked
    if not q:
        st.warning("Enter a question first.")
    else:
        with st.spinner("Generating SQL and running query..."):
            result = ask(q)

        if result["mode"] == "demo":
            st.info(
                "Running in **offline demo mode** (no ANTHROPIC_API_KEY set). "
                "Set the key as an environment variable / Streamlit secret to "
                "enable live SQL generation for any question.",
                icon="ℹ️",
            )

        if result["error"]:
            st.error(result["error"])
            if result["sql"]:
                st.code(result["sql"], language="sql")
        else:
            st.markdown("**Generated SQL**")
            st.code(result["sql"], language="sql")

            df = result["result"]
            st.markdown("**Result**")
            st.dataframe(df, use_container_width=True)

            # Auto-chart if the shape looks chartable: 1 label col + 1 numeric col
            if df.shape[1] == 2 and df.shape[0] > 1:
                label_col, value_col = df.columns[0], df.columns[1]
                if pd.api.types.is_numeric_dtype(df[value_col]):
                    st.markdown("**Chart**")
                    st.bar_chart(df.set_index(label_col)[value_col])

st.divider()
with st.expander("How this works / safety notes"):
    st.markdown(
        """
- The database schema is sent to Claude along with your question, which returns a single SQL query.
- Before execution, the query is validated: **only `SELECT` statements are allowed** — any
  `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc. is rejected, and multi-statement queries
  (`;`-separated) are blocked.
- The query then runs read-only against the database and results are shown exactly as returned.
- This demo uses the [Chinook sample database](https://github.com/lerocha/chinook-database)
  (a music store: customers, invoices, tracks, artists, genres).
        """
    )
