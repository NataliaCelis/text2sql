"""Chart-choice heuristic (demo-mode fallback) + interactive Plotly rendering."""
import pandas as pd
import plotly.express as px


def heuristic_chart(df: pd.DataFrame) -> dict:
    if df.shape[1] >= 2 and df.shape[0] > 1 and pd.api.types.is_numeric_dtype(df[df.columns[1]]):
        return {"chart": "bar", "x": df.columns[0], "y": df.columns[1], "color": None, "reason": "default heuristic"}
    return {"chart": "table", "x": None, "y": None, "color": None, "reason": "default heuristic"}


def render_chart(df: pd.DataFrame, choice: dict):
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
