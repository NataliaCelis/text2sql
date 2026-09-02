import os
import streamlit as st
import pandas as pd
from sql_engine import ask
from query_log import get_recent_queries

st.set_page_config(page_title="Text-to-SQL Analyst", page_icon="🎧", layout="centered")

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass  # no secrets.toml present locally - fine, falls back to demo mode

if "history" not in st.session_state:
    st.session_state.history = []  # list of {"question": str, "sql": str}
if "turns" not in st.session_state:
    st.session_state.turns = []  # full display log: question, sql, result df, explanation, mode, retries

st.title("🎧 Text-to-SQL Analyst")
st.caption(
    "Ask a business question in plain English. It's translated into SQL, "
    "run against a real database (Chinook music store), and returned as a "
    "table + chart + plain-English explanation. Follow-up questions ('now "
    "break that down by country') work too. No API key? Falls back to a "
    "small offline demo set."
)

# --- Sidebar: recent query history -----------------------------------------
with st.sidebar:
    st.subheader("Recent queries")
    recent = get_recent_queries(limit=10)
    if not recent:
        st.caption("No queries yet.")
    for ts, q, mode, success, retries in recent:
        icon = "✅" if success else "❌"
        badge = f" · {retries} retr{'y' if retries==1 else 'ies'}" if retries else ""
        st.markdown(f"{icon} **{q}**  \n<small>{mode}{badge}</small>", unsafe_allow_html=True)
    if st.button("Clear conversation"):
        st.session_state.history = []
        st.session_state.turns = []
        st.rerun()

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
    "Or ask your own question (follow-ups like 'now show it by country' work too)",
    placeholder="e.g. Which employee generated the most sales?",
)

go = st.button("Ask", type="primary") or clicked
if go:
    q = clicked if clicked else question
    if not q:
        st.warning("Enter a question first.")
    else:
        with st.spinner("Generating SQL and running query..."):
            result = ask(q, history=st.session_state.history)

        st.session_state.turns.append({"question": q, **result})
        if result["sql"] and result["error"] is None:
            st.session_state.history.append({"question": q, "sql": result["sql"]})
        st.rerun()

# --- Render conversation, most recent first ---------------------------------
for turn in reversed(st.session_state.turns):
    with st.container(border=True):
        st.markdown(f"**Q: {turn['question']}**")

        if turn["mode"] == "demo":
            st.caption("ℹ️ Offline demo mode (no ANTHROPIC_API_KEY set)")

        if turn.get("retries"):
            st.caption(f"🔁 Self-corrected after {turn['retries']} failed attempt(s)")

        if turn["error"]:
            st.error(turn["error"])
            if turn["sql"]:
                st.code(turn["sql"], language="sql")
        else:
            st.code(turn["sql"], language="sql")
            if turn.get("explanation"):
                st.caption(f"💡 {turn['explanation']}")

            df = turn["result"]
            st.dataframe(df, use_container_width=True)

            if df.shape[1] == 2 and df.shape[0] > 1:
                label_col, value_col = df.columns[0], df.columns[1]
                if pd.api.types.is_numeric_dtype(df[value_col]):
                    st.bar_chart(df.set_index(label_col)[value_col])

st.divider()
with st.expander("How this works / safety notes"):
    st.markdown(
        """
- The database schema (+ up to 3 prior conversation turns, for follow-ups) is sent to Claude
  along with your question, which returns a single SQL query.
- Before execution, the query is validated: **only `SELECT` statements are allowed** — any
  `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, etc. is rejected, and multi-statement queries
  are blocked.
- **Self-healing retries**: if the query fails to execute (bad column name, syntax error), the
  database error is fed back to the model, which gets up to 2 attempts to fix it before
  giving up.
- Every query (question, SQL, success/failure, retry count) is logged to a local history table,
  shown in the sidebar.
- This demo uses the [Chinook sample database](https://github.com/lerocha/chinook-database)
  (a music store: customers, invoices, tracks, artists, genres).
        """
    )
