"""Generic interactive dashboard for any transactions-style CSV.

    streamlit run toolkit/dashboard_app.py -- data/demo/orders.csv

Auto-detects a date column, measures and dimensions. Use it to explore in the first
hour, then replace the auto picks with the challenge's real questions. A judge wants
an answer ("reorder X by Tuesday"), not a wall of charts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from charts import GRID, INK, INK_2, MUTED, SERIES, SURFACE, complete_periods

st.set_page_config(page_title="Dashboard", layout="wide")


@st.cache_data
def load(src) -> pd.DataFrame:
    df = pd.read_csv(src, low_memory=False)
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]):
            sample = df[c].dropna().astype(str).head(100)
            if sample.str.contains(r"\d{1,4}[-/]\d{1,2}").mean() > 0.9:
                parsed = pd.to_datetime(df[c], errors="coerce", format="mixed")
                if parsed.notna().mean() > 0.9:
                    df[c] = parsed
    return df


def style(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(color=INK_2, family="Segoe UI, system-ui, sans-serif", size=13),
        colorway=SERIES, legend=dict(orientation="h", y=1.08, x=0, title=""),
        hovermode="x unified", hoverlabel=dict(bgcolor="#ffffff", font_color=INK),
    )
    fig.update_xaxes(showgrid=False, linecolor="#c3c2b7", tickfont_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont_color=MUTED)
    return fig


src = sys.argv[1] if len(sys.argv) > 1 else None
if src is None:
    src = st.file_uploader("Upload a CSV", type="csv")
    if src is None:
        st.stop()
df = load(src)

date_cols = df.select_dtypes("datetime").columns.tolist()
measures = [c for c in df.select_dtypes("number").columns if df[c].nunique() > 20] or df.select_dtypes("number").columns.tolist()
dims = [c for c in df.columns if c not in date_cols and df[c].nunique() <= 50 and c not in measures]

if not measures:
    st.error("No numeric column found to measure.")
    st.stop()

st.title(Path(str(getattr(src, "name", src))).stem.replace("_", " ").title())

# Filters live in one row above the charts.
cols = st.columns(4)
measure = cols[0].selectbox("Measure", measures, index=len(measures) - 1)
agg = cols[1].selectbox("Aggregate", ["sum", "mean", "count"])
dim = cols[2].selectbox("Break down by", dims) if dims else None
choice = cols[3].multiselect(f"Filter {dim}", sorted(df[dim].dropna().astype(str).unique())) if dim else []

view = df
if choice:
    view = view[view[dim].astype(str).isin(choice)]
date = date_cols[0] if date_cols else None
if date is not None:
    lo, hi = df[date].min().date(), df[date].max().date()
    picked = st.slider("Date range", lo, hi, (lo, hi))
    view = view[view[date].dt.date.between(*picked)]

if view.empty:
    st.warning("No rows match these filters.")
    st.stop()

# Stat tiles
v = getattr(view[measure], agg)()
tiles = st.columns(4)
tiles[0].metric(f"{agg} of {measure}", f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}")
tiles[1].metric("Rows", f"{len(view):,}")
if dim:
    top = view.groupby(dim, observed=True)[measure].agg(agg).sort_values(ascending=False)
    tiles[2].metric(f"Top {dim}", str(top.index[0]))
    tiles[3].metric(f"Top {dim} share", f"{top.iloc[0] / top.sum():.0%}" if agg != "mean" and top.sum() else "n/a")

left, right = st.columns([3, 2])

if date is not None:
    with left:
        st.subheader(f"{measure} over time")
        grain = {"Day": "D", "Week": "W", "Month": "M"}[st.radio("Grain", ["Day", "Week", "Month"], index=1, horizontal=True)]
        fig = go.Figure()
        d = complete_periods(view, date, grain)
        if dim and d[dim].nunique() <= 8:
            # Colour follows the entity: order comes from the unfiltered data, so a filter never repaints.
            order = df.groupby(dim, observed=True)[measure].sum().sort_values(ascending=False).index.tolist()
            for name in order:
                g = d[d[dim] == name]
                if len(g):
                    s = g.groupby("period")[measure].agg(agg)
                    fig.add_scatter(x=s.index, y=s.values, name=str(name), mode="lines",
                                    line=dict(width=2, color=SERIES[order.index(name)]))
        else:
            s = d.groupby("period")[measure].agg(agg)
            fig.add_scatter(x=s.index, y=s.values, name=measure, mode="lines", line=dict(width=2, color=SERIES[0]))
        st.plotly_chart(style(fig), width="stretch", theme=None)

with right if date is not None else left:
    if dim:
        st.subheader(f"{measure} by {dim}")
        s = view.groupby(dim, observed=True)[measure].agg(agg).sort_values().tail(12)
        fig = go.Figure(go.Bar(x=s.values, y=s.index.astype(str), orientation="h", width=0.55,
                               marker=dict(color=SERIES[0], cornerradius=4)))
        st.plotly_chart(style(fig).update_layout(hovermode="closest"), width="stretch", theme=None)

with st.expander("Table view"):
    st.dataframe(view, width="stretch", height=320)
    st.download_button("Download filtered CSV", view.to_csv(index=False), "filtered.csv", "text/csv")
