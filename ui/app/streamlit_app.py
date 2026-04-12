"""
GCC Dashboard – Streamlit UI
Monitors U.S.–Iran conflict escalation risk.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

from settings import get_settings

settings = get_settings()
API = settings.api_base_url

# ── Bahrain Time (UTC+3) ───────────────────────────────────────────────────────
BHT = timezone(timedelta(hours=3))


def _to_bht(ts: str | datetime | None) -> str:
    """Convert a UTC ISO string or datetime to a Bahrain Time display string."""
    if ts is None:
        return "—"
    if isinstance(ts, str):
        ts = ts.strip()
        if not ts:
            return "—"
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return ts[:19]
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BHT).strftime("%d %b %Y %H:%M BHT")


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities from snippet text."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _safe_url(url: str | None) -> str | None:
    """Return url only if it uses http/https; otherwise return None."""
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return None


st.set_page_config(
    page_title="GCC Conflict Dashboard",
    page_icon="🚨",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_API_HEADERS = {"X-API-Key": settings.api_key} if settings.api_key else {}


@st.cache_data(ttl=30)
def _get(path: str, params: dict | None = None) -> Any:
    try:
        r = requests.get(f"{API}{path}", params=params, headers=_API_HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
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
    st.title("GCC Dashboard")
    st.caption("U.S.–Iran Conflict Risk Monitor")
    st.divider()
    st.markdown(f"**Risk threshold:** {settings.alert_risk_threshold}")
    st.markdown(f"**Delta threshold:** {settings.alert_delta_threshold}")
    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()

# ── Main ───────────────────────────────────────────────────────────────────────

st.title("🌍 GCC Conflict Dashboard")
st.caption(f"Last updated: {_to_bht(datetime.now(timezone.utc))}")

# Fetch data
latest_risk = _get("/risk/latest")
risk_series = _get("/risk/series", {"hours": 12}) or []
items_data = _get("/items", {"limit": 200}) or []
alerts_data = _get("/alerts", {"limit": 10}) or []

# ── Risk Gauge ────────────────────────────────────────────────────────────────
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
    fig.update_layout(
        height=260,
        margin=dict(t=30, b=10, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
    )
    st.plotly_chart(fig, use_container_width=True)

    ts = latest_risk.get("timestamp", "")
    st.caption(f"Computed: {_to_bht(ts)}")
else:
    st.info("Waiting for first risk computation…")

# ── Hit Counts ────────────────────────────────────────────────────────────────
if latest_risk:
    st.subheader("Category Hits (rolling window)")
    c1, c2, c3 = st.columns(3)
    c1.metric("🔴 Kinetic", latest_risk.get("kinetic_hits", 0))
    c2.metric("🟠 Shipping", latest_risk.get("shipping_hits", 0))
    c3.metric("🟣 Nuclear", latest_risk.get("nuclear_hits", 0))
    c4, c5 = st.columns(2)
    c4.metric("🔴 Casualties", latest_risk.get("casualty_hits", 0))
    c5.metric("🟢 De-escalation", latest_risk.get("deescalation_hits", 0))

# ── Why Risk Changed ──────────────────────────────────────────────────────────
if latest_risk and latest_risk.get("drivers_json"):
    st.subheader("🔍 Why Risk Changed")
    for i, d in enumerate(latest_risk["drivers_json"][:3], 1):
        title = d.get("title", "Unknown") or "Unknown"
        cats = d.get("categories", [])
        publisher = d.get("publisher", "") or d.get("source_name", "")
        snippet = _strip_html(d.get("snippet", "") or "")[:200]
        published = _to_bht(d.get("published_at"))
        badge = " ".join(_category_badge(c) for c in cats)
        st.markdown(f"**{i}.** {title[:100]}")
        if snippet:
            st.caption(snippet)
        st.caption(f"{publisher} · {published} · {badge}")
        st.divider()

st.divider()

# ── Risk Time Series ──────────────────────────────────────────────────────────
st.subheader("📈 Risk Time Series (12 hours)")
if risk_series:
    df_risk = pd.DataFrame(risk_series)
    df_risk["timestamp"] = pd.to_datetime(df_risk["timestamp"], utc=True).dt.tz_convert(BHT)
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
        xaxis=dict(gridcolor="#333", title="Bahrain Time"),
        yaxis=dict(range=[0, 100], gridcolor="#333"),
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No time series data yet. Workers may still be initializing.")

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_all, tab_rss, tab_gdelt, tab_youtube, tab_alerts = st.tabs([
    "📰 All Items", "📡 RSS", "🌐 GDELT", "📺 YouTube", "🔔 Alerts"
])


def _render_items(data: list[dict], source_filter: Optional[str] = None):
    if not data:
        st.info("No items found.")
        return

    df = pd.DataFrame(data)
    if df.empty:
        st.info("No items found.")
        return

    # Filters — single column on mobile
    cat_filter = st.multiselect(
        "Filter by category",
        ["kinetic", "shipping", "nuclear", "casualties", "deescalation"],
        key=f"cat_{source_filter or 'all'}",
    )
    pub_options = sorted(df["publisher"].dropna().unique().tolist())
    pub_filter = st.multiselect(
        "Filter by publisher",
        pub_options[:20],
        key=f"pub_{source_filter or 'all'}",
    )
    hours_back = st.slider(
        "Show last N hours",
        1, 24, 6,
        key=f"hrs_{source_filter or 'all'}",
    )

    # Apply filters
    if source_filter:
        df = df[df["source_type"] == source_filter]
    if cat_filter:
        df = df[df["categories"].apply(lambda c: bool(set(c or []) & set(cat_filter)))]
    if pub_filter:
        df = df[df["publisher"].isin(pub_filter)]

    # Filter by published_at when available, else fetched_at
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours_back)
    if "published_at" in df.columns:
        df["published_at_ts"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    if "fetched_at" in df.columns:
        df["fetched_at_ts"] = pd.to_datetime(df["fetched_at"], utc=True, errors="coerce")

    has_published = df.get("published_at_ts", pd.Series(dtype="datetime64[ns, UTC]")).notna()
    if "published_at_ts" in df.columns and "fetched_at_ts" in df.columns:
        effective_ts = df["published_at_ts"].where(has_published, df["fetched_at_ts"])
        df = df[effective_ts >= cutoff]
    elif "fetched_at_ts" in df.columns:
        df = df[df["fetched_at_ts"] >= cutoff]

    st.caption(f"Showing {len(df)} items")

    for _, row in df.head(50).iterrows():
        cats = row.get("categories") or []
        badges = " ".join(_category_badge(c) for c in cats)
        score = row.get("risk_score", 0)
        title = row.get("title", "No title") or "No title"
        snippet = _strip_html(row.get("snippet", "") or "")
        publisher = row.get("publisher", "") or ""
        published = _to_bht(row.get("published_at"))

        with st.expander(f"{badges}  **{title[:100]}**  `{score:+.0f}pts`"):
            # Snippet as main content
            if snippet:
                st.write(snippet[:400])
            else:
                st.caption("No snippet available.")
            st.caption(f"**{publisher}** · Published: {published}")
            if cats:
                st.caption(f"Categories: {', '.join(cats)}")


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
        for stream in streams:
            name = stream.get("name", "Stream")
            url = stream.get("url", "")
            embed_url = None
            if "/@" in url:
                handle = url.split("/@")[1].split("/")[0]
                embed_url = f"https://www.youtube.com/embed?listType=user_uploads&list={handle}&autoplay=0"
            st.markdown(f"### {name}")
            if embed_url:
                components.iframe(embed_url, height=200, scrolling=False)
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
            created = _to_bht(alert.get("created_at"))
            drivers = alert.get("drivers_json", [])

            icon = "🚨" if sent else "⚠️"
            with st.expander(
                f"{icon} **{alert_type}** — Risk: {risk_val:.1f} | Δ: {delta:+.1f} — {created}"
            ):
                st.markdown(f"**Type:** `{alert_type}` | **Sent:** {'✅' if sent else '❌'}")
                st.markdown(f"**Risk:** {risk_val:.1f} / 100 | **Delta:** {delta:+.1f}")
                if drivers:
                    st.markdown("**Drivers:**")
                    for d in drivers[:3]:
                        title = d.get("title", "") or ""
                        snippet = _strip_html(d.get("snippet", "") or "")[:150]
                        pub = d.get("publisher", "")
                        published = _to_bht(d.get("published_at"))
                        st.markdown(f"- **{title[:80]}**")
                        if snippet:
                            st.caption(snippet)
                        st.caption(f"{pub} · {published}")
    else:
        st.info("No alerts recorded yet.")

# ── Auto-refresh ────────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
