"""
GCC Dashboard – Streamlit UI
Monitors U.S.–Iran conflict escalation risk.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from .settings import get_settings

settings = get_settings()
API = settings.api_base_url

st.set_page_config(
    page_title="GCC Conflict Dashboard",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _get(path: str, params: dict | None = None) -> Any:
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return None


def _risk_color(value: float) -> str:
    if value >= 70:
        return "#FF4B4B"
    if value >= 40:
        return "#FFA500"
    return "#00C851"


def _category_badge(cat: str) -> str:
    colors = {
        "kinetic": "🔴",
        "shipping": "🟠",
        "nuclear": "🟣",
        "casualties": "🔴",
        "deescalation": "🟢",
    }
    return colors.get(cat, "⚪") + " " + cat


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/49/Flag_of_the_United_States_%28Pantone%29.svg/320px-Flag_of_the_United_States_%28Pantone%29.svg.png",
        width=60,
    )
    st.title("GCC Dashboard")
    st.caption("U.S.–Iran Conflict Risk Monitor")
    st.divider()
    st.markdown(f"**API:** `{API}`")
    st.markdown(f"**Risk threshold:** {settings.alert_risk_threshold}")
    st.markdown(f"**Delta threshold:** {settings.alert_delta_threshold}")
    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()

# ── Main ───────────────────────────────────────────────────────────────────────

st.title("🌍 GCC Conflict Escalation Dashboard")
st.caption(f"Last loaded: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

# Fetch data
latest_risk = _get("/risk/latest")
risk_series = _get("/risk/series", {"hours": 12}) or []
items_data = _get("/items", {"limit": 200}) or []
alerts_data = _get("/alerts", {"limit": 10}) or []

# ── Risk Overview Row ──────────────────────────────────────────────────────────
col_gauge, col_metrics, col_why = st.columns([1.5, 1.5, 2])

with col_gauge:
    st.subheader("Risk Index")
    if latest_risk:
        risk_val = latest_risk.get("risk_index", 0)
        color = _risk_color(risk_val)
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=risk_val,
            number={"font": {"size": 48, "color": color}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": color},
                "steps": [
                    {"range": [0, 40], "color": "#1a1a1a"},
                    {"range": [40, 70], "color": "#2a2000"},
                    {"range": [70, 100], "color": "#2a0000"},
                ],
                "threshold": {
                    "line": {"color": "white", "width": 2},
                    "thickness": 0.75,
                    "value": settings.alert_risk_threshold,
                },
            },
            title={"text": "Current Risk (0–100)"},
        ))
        fig.update_layout(height=260, margin=dict(t=30, b=10, l=20, r=20),
                          paper_bgcolor="rgba(0,0,0,0)", font_color="white")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Waiting for first risk computation…")

with col_metrics:
    st.subheader("Hit Counts (window)")
    if latest_risk:
        m1, m2 = st.columns(2)
        m1.metric("Kinetic", latest_risk.get("kinetic_hits", 0))
        m2.metric("Shipping", latest_risk.get("shipping_hits", 0))
        m3, m4 = st.columns(2)
        m3.metric("Nuclear", latest_risk.get("nuclear_hits", 0))
        m4.metric("Casualties", latest_risk.get("casualty_hits", 0))
        st.metric("De-escalation", latest_risk.get("deescalation_hits", 0))
        ts = latest_risk.get("timestamp", "")
        if ts:
            st.caption(f"Updated: {ts[:19].replace('T', ' ')} UTC")
    else:
        st.info("No data yet.")

with col_why:
    st.subheader("🔍 Why Risk Changed")
    if latest_risk and latest_risk.get("drivers_json"):
        for i, d in enumerate(latest_risk["drivers_json"][:3], 1):
            title = d.get("title", "Unknown") or "Unknown"
            cats = d.get("categories", [])
            publisher = d.get("publisher", "") or d.get("source_name", "")
            url = d.get("url", "")
            badge = " ".join(_category_badge(c) for c in cats)
            link = f"[{title[:90]}]({url})" if url else title[:90]
            st.markdown(f"**{i}.** {link}")
            st.caption(f"{publisher}  {badge}")
    else:
        st.info("No driver data yet.")

st.divider()

# ── Risk Sparkline ─────────────────────────────────────────────────────────────
st.subheader("📈 Risk Time Series (12 hours)")
if risk_series:
    df_risk = pd.DataFrame(risk_series)
    df_risk["timestamp"] = pd.to_datetime(df_risk["timestamp"])
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=df_risk["timestamp"],
        y=df_risk["risk_index"],
        mode="lines+markers",
        name="Risk Index",
        line=dict(color="#FF4B4B", width=2),
        fill="tozeroy",
        fillcolor="rgba(255,75,75,0.15)",
    ))
    fig2.add_hline(
        y=settings.alert_risk_threshold,
        line_dash="dash",
        line_color="orange",
        annotation_text=f"Alert threshold ({settings.alert_risk_threshold})",
    )
    fig2.update_layout(
        height=250,
        margin=dict(t=10, b=10, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        xaxis=dict(gridcolor="#333"),
        yaxis=dict(range=[0, 100], gridcolor="#333"),
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No time series data yet. Workers may still be initializing.")

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_all, tab_rss, tab_gdelt, tab_youtube, tab_alerts = st.tabs([
    "📰 All Items", "📡 Google News RSS", "🌐 GDELT", "📺 YouTube Live", "🔔 Alerts"
])


def _render_items(data: list[dict], source_filter: Optional[str] = None):
    if not data:
        st.info("No items found.")
        return

    df = pd.DataFrame(data)
    if df.empty:
        st.info("No items found.")
        return

    # Sidebar-style filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        cat_filter = st.multiselect(
            "Category",
            ["kinetic", "shipping", "nuclear", "casualties", "deescalation"],
            key=f"cat_{source_filter or 'all'}",
        )
    with col_f2:
        pub_options = sorted(df["publisher"].dropna().unique().tolist())
        pub_filter = st.multiselect("Publisher", pub_options[:20],
                                    key=f"pub_{source_filter or 'all'}")
    with col_f3:
        hours_back = st.slider("Show last N hours", 1, 24, 6,
                               key=f"hrs_{source_filter or 'all'}")

    # Apply filters
    if source_filter:
        df = df[df["source_type"] == source_filter]
    if cat_filter:
        df = df[df["categories"].apply(lambda c: bool(set(c or []) & set(cat_filter)))]
    if pub_filter:
        df = df[df["publisher"].isin(pub_filter)]

    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours_back)
    if "fetched_at" in df.columns:
        df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True, errors="coerce")
        df = df[df["fetched_at"] >= cutoff]

    st.caption(f"Showing {len(df)} items")

    for _, row in df.head(50).iterrows():
        cats = row.get("categories") or []
        badges = " ".join(_category_badge(c) for c in cats)
        score = row.get("risk_score", 0)
        title = row.get("title", "No title") or "No title"
        url = row.get("url", "")
        publisher = row.get("publisher", "") or ""
        snippet = row.get("snippet", "") or ""
        fetched = str(row.get("fetched_at", ""))[:19]

        with st.expander(f"{badges}  **{title[:100]}**  `{score:+.0f}pts`"):
            cols = st.columns([2, 1])
            with cols[0]:
                if snippet:
                    st.caption(snippet[:300])
                if url:
                    st.markdown(f"🔗 [Read article]({url})")
            with cols[1]:
                st.caption(f"**Source:** {publisher}")
                st.caption(f"**Fetched:** {fetched}")
                st.caption(f"**Categories:** {', '.join(cats) if cats else 'none'}")


with tab_all:
    _render_items(items_data)

with tab_rss:
    rss_items = [i for i in items_data if i.get("source_type") == "rss"]
    _render_items(rss_items, source_filter="rss")

with tab_gdelt:
    gdelt_items = [i for i in items_data if i.get("source_type") == "gdelt"]
    _render_items(gdelt_items, source_filter="gdelt")

with tab_youtube:
    st.subheader("📺 Live News Streams")
    streams = settings.get_youtube_streams()
    if streams:
        cols = st.columns(min(len(streams), 3))
        for i, stream in enumerate(streams):
            with cols[i % 3]:
                name = stream.get("name", f"Stream {i+1}")
                url = stream.get("url", "")
                # Try to extract channel handle for embed
                # YouTube /live pages can sometimes be embedded; use iframe
                channel_id = None
                if "/@" in url:
                    handle = url.split("/@")[1].split("/")[0]
                    embed_url = f"https://www.youtube.com/embed?listType=user_uploads&list={handle}&autoplay=0"
                else:
                    embed_url = None

                st.markdown(f"### {name}")
                if embed_url:
                    st.components.v1.iframe(embed_url, height=200, scrolling=False)
                st.markdown(f"▶️ [Open live stream]({url})")
                st.divider()
    else:
        st.info("No YouTube streams configured. Set YOUTUBE_STREAMS in .env")

with tab_alerts:
    st.subheader("🔔 Recent Alerts")
    if alerts_data:
        for alert in alerts_data:
            alert_type = alert.get("alert_type", "unknown")
            risk_val = alert.get("risk_value", 0)
            delta = alert.get("risk_delta", 0)
            sent = alert.get("sent", False)
            created = str(alert.get("created_at", ""))[:19]
            drivers = alert.get("drivers_json", [])

            icon = "🚨" if sent else "⚠️"
            color = _risk_color(risk_val)
            with st.expander(
                f"{icon} **{alert_type}** — Risk: {risk_val:.1f} | Δ: {delta:+.1f} — {created}"
            ):
                st.markdown(f"**Type:** `{alert_type}` | **Sent:** {'✅' if sent else '❌'}")
                st.markdown(f"**Risk:** {risk_val:.1f} / 100 | **Delta:** {delta:+.1f}")
                if drivers:
                    st.markdown("**Drivers:**")
                    for d in drivers[:3]:
                        title = d.get("title", "") or ""
                        url = d.get("url", "")
                        pub = d.get("publisher", "")
                        link = f"[{title[:80]}]({url})" if url else title[:80]
                        st.markdown(f"- {link} — *{pub}*")
    else:
        st.info("No alerts recorded yet.")

# ── Auto-refresh ────────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
