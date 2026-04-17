"""
Podcast Automation — Performance Dashboard

Run locally:
    streamlit run dashboard.py

Shows historical performance data stored in the SQLite database.
"""
import sqlite3
import os
import sys
from pathlib import Path

# Make sure the package can be imported when run from the repo root
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd

DB_PATH = Path(__file__).parent / "podcast_automation.db"

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Podcast Automation Dashboard",
    page_icon="🎙️",
    layout="wide",
)

st.title("🎙️ Podcast Automation — Performance Dashboard")

if not DB_PATH.exists():
    st.warning(
        "No database found. Run the pipeline at least once to generate data.\n\n"
        f"Expected path: `{DB_PATH}`"
    )
    st.stop()


def _make_link(url) -> str:
    """Format a YouTube URL as a Markdown hyperlink, or return '–'."""
    if url and str(url).startswith("http"):
        return f"[Watch]({url})"
    return "–"


# ── Load data ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_shorts() -> pd.DataFrame:
    with sqlite3.connect(str(DB_PATH)) as conn:
        df = pd.read_sql_query(
            """SELECT s.id, s.title, s.views, s.likes, s.comments,
                      s.viral_score, s.is_uploaded, s.created_at,
                      s.video_url, s.analytics_fetched_at,
                      e.podcast_name,
                      ROUND((s.end_time - s.start_time), 1) AS duration_s
               FROM shorts s
               LEFT JOIN episodes e ON s.episode_id = e.video_id
               ORDER BY s.created_at DESC""",
            conn,
        )
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df


@st.cache_data(ttl=60)
def load_episodes() -> pd.DataFrame:
    with sqlite3.connect(str(DB_PATH)) as conn:
        df = pd.read_sql_query(
            "SELECT * FROM episodes ORDER BY processed_at DESC", conn
        )
    return df


shorts = load_shorts()
episodes = load_episodes()

# ── KPI row ────────────────────────────────────────────────────────────────────
uploaded = shorts[shorts["is_uploaded"] == 1]

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Shorts", len(shorts))
col2.metric("Uploaded", len(uploaded))
col3.metric("Total Views", f"{int(uploaded['views'].sum()):,}")
col4.metric("Total Likes", f"{int(uploaded['likes'].sum()):,}")
col5.metric(
    "Avg Viral Score",
    f"{shorts['viral_score'].mean():.1f}" if not shorts.empty else "–",
)

st.divider()

# ── Views over time ────────────────────────────────────────────────────────────
st.subheader("📈 Views Over Time")
if not uploaded.empty and uploaded["created_at"].notna().any():
    chart_df = (
        uploaded[["created_at", "views"]]
        .dropna()
        .sort_values("created_at")
        .set_index("created_at")
    )
    st.line_chart(chart_df)
else:
    st.info("No analytics data yet. Run the analytics workflow to populate view counts.")

# ── Top performing shorts ──────────────────────────────────────────────────────
st.subheader("🏆 Top 10 Performing Shorts")
if not uploaded.empty:
    top = (
        uploaded[["title", "podcast_name", "views", "likes", "comments", "viral_score", "video_url"]]
        .sort_values("views", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    top.index += 1

    # Make video_url clickable
    top["video_url"] = top["video_url"].apply(_make_link)
    st.dataframe(top, use_container_width=True)
else:
    st.info("No uploaded shorts yet.")

# ── Per-podcast breakdown ──────────────────────────────────────────────────────
st.subheader("📊 Per-Podcast Breakdown")
if not uploaded.empty and "podcast_name" in uploaded.columns:
    breakdown = (
        uploaded.groupby("podcast_name")
        .agg(
            shorts_count=("id", "count"),
            total_views=("views", "sum"),
            total_likes=("likes", "sum"),
            avg_viral_score=("viral_score", "mean"),
        )
        .sort_values("total_views", ascending=False)
        .reset_index()
    )
    breakdown["avg_viral_score"] = breakdown["avg_viral_score"].round(1)
    st.dataframe(breakdown, use_container_width=True)
else:
    st.info("No per-podcast data available yet.")

# ── Full shorts table ──────────────────────────────────────────────────────────
with st.expander("📋 All Shorts"):
    st.dataframe(shorts, use_container_width=True)

with st.expander("📋 All Episodes"):
    st.dataframe(episodes, use_container_width=True)

st.caption("Data refreshes every 60 seconds. Run the analytics workflow to update view counts.")
