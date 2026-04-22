"""
GCC Dashboard – Streamlit UI
Monitors U.S.–Iran conflict escalation risk.
"""
from __future__ import annotations

import html
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

try:
    from .settings import get_settings
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from settings import get_settings

settings = get_settings()
API = settings.api_base_url
BAHRAIN_TZ = ZoneInfo("Asia/Bahrain")

st.set_page_config(
    page_title="GCC Conflict Dashboard",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _api_headers() -> dict:
    key = settings.api_key
    return {"X-API-Key": key} if key else {}


@st.cache_data(ttl=30)
def _get(path: str, params: dict | None = None) -> Any:
    try:
        r = requests.get(f"{API}{path}", params=params, headers=_api_headers(), timeout=10)
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


def _format_bahrain_time(value: datetime | str | None) -> str:
    if value in (None, ""):
        return "N/A"

    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return "N/A"
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return raw[:19]

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(BAHRAIN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _is_probably_mobile() -> bool:
    context = getattr(st, "context", None)
    headers = getattr(context, "headers", {}) if context else {}
    ua = str(headers.get("user-agent", "")).lower()
    mobile_tokens = ("android", "iphone", "ipad", "mobile")
    return any(token in ua for token in mobile_tokens)


def _safe_url(url: Any) -> str:
    """Allow only http/https URLs; return '' for anything else (e.g. javascript:, data:)."""
    s = str(url) if url else ""
    return s if s.startswith(("https://", "http://")) else ""


def _escape_md(text: str) -> str:
    """Escape markdown link-syntax characters in untrusted text."""
    return re.sub(r"([\[\]()])", r"\\\1", text)


def _clean_snippet(value: Any, publisher: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = " ".join(text.split())
    if publisher:
        pub = re.escape(publisher.strip())
        text = re.sub(rf"\s*[-|:\u2013\u2014]\s*{pub}\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(rf"\s+{pub}\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-|:\u2013\u2014]\s*[A-Z][\w&'()./\- ]{2,60}\s*$", "", text)
    return text.strip()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("GCC Dashboard")
    st.caption("U.S.–Iran Conflict Risk Monitor")
    st.divider()
    st.markdown(f"**API:** `{API}`")
    st.markdown(f"**Risk threshold:** {settings.alert_risk_threshold}")
    st.markdown(f"**Delta threshold:** {settings.alert_delta_threshold}")
    day_filter_label = st.selectbox(
        "News age filter",
        ["All", "1 day", "3 days", "7 days"],
        index=0,
    )
    time_basis_label = st.selectbox(
        "News time basis",
        ["Fetched time", "Published time"],
        index=1,
    )
    st.caption(
        "Time basis applies to item filtering only. Risk drivers show the latest computed risk snapshot."
    )
    mobile_layout = st.checkbox("Mobile layout", value=_is_probably_mobile())
    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()

# ── Main ───────────────────────────────────────────────────────────────────────

st.title("🌍 GCC Conflict Escalation Dashboard")
if mobile_layout:
    st.caption("Mobile layout: ON")
st.caption(f"Last loaded: {_format_bahrain_time(datetime.now(BAHRAIN_TZ))} Bahrain")

day_filter_map = {
    "All": None,
    "1 day": 1,
    "3 days": 3,
    "7 days": 7,
}
selected_days = day_filter_map[day_filter_label]
time_basis_map = {
    "Fetched time": "fetched",
    "Published time": "published",
}
selected_time_basis = time_basis_map[time_basis_label]
time_basis_display = "Published" if selected_time_basis == "published" else "Fetched"

# Fetch data
latest_risk = _get("/risk/latest")
risk_params = {"hours": 168} if selected_days is None else {"since_days": selected_days}
risk_series = _get("/risk/series", risk_params) or []
items_params = {"limit": 200}
if selected_days is not None:
    items_params["since_days"] = selected_days
items_params["time_basis"] = selected_time_basis
items_data = _get("/items", items_params) or []
alerts_params = {"limit": 10}
if selected_days is not None:
    alerts_params["since_days"] = selected_days
alerts_data = _get("/alerts", alerts_params) or []

debug_badge = (
    f"Filters in effect -> items: {items_params}, risk: {risk_params}, alerts: {alerts_params}"
)
st.caption(debug_badge)

# ── Risk Overview Row ──────────────────────────────────────────────────────────
def _render_risk_gauge():
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


def _render_risk_metrics():
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
            st.caption(f"Updated: {_format_bahrain_time(ts)} Bahrain")
    else:
        st.info("No data yet.")


def _render_risk_why():
    st.subheader("🔍 Why Risk Changed")
    st.caption(f"News filter basis: {time_basis_display} time")
    if latest_risk and latest_risk.get("drivers_json"):
        for i, d in enumerate(latest_risk["drivers_json"][:3], 1):
            title = d.get("title", "Unknown") or "Unknown"
            cats = d.get("categories", [])
            publisher = d.get("publisher", "") or d.get("source_name", "")
            url = _safe_url(d.get("direct_url") or d.get("url", ""))
            badge = " ".join(_category_badge(c) for c in cats)
            safe_title = _escape_md(title[:90])
            link = f"[{safe_title}]({url})" if url else safe_title
            st.markdown(f"**{i}.** {link}")
            st.caption(f"{publisher}  {badge}")
    else:
        st.info("No driver data yet.")


if mobile_layout:
    _render_risk_gauge()
    _render_risk_metrics()
    _render_risk_why()
else:
    col_gauge, col_metrics, col_why = st.columns([1.5, 1.5, 2])
    with col_gauge:
        _render_risk_gauge()
    with col_metrics:
        _render_risk_metrics()
    with col_why:
        _render_risk_why()

st.divider()

# ── Risk Sparkline ─────────────────────────────────────────────────────────────
risk_window_label = "7 days" if selected_days is None else day_filter_label
st.subheader(f"📈 Risk Time Series ({risk_window_label})")
if risk_series:
    df_risk = pd.DataFrame(risk_series)
    df_risk["timestamp"] = pd.to_datetime(df_risk["timestamp"], utc=True).dt.tz_convert(BAHRAIN_TZ)
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


def _render_items(
    data: list[dict],
    source_filter: Optional[str] = None,
    compact: bool = False,
):
    if not data:
        st.info("No items found.")
        return

    df = pd.DataFrame(data)
    if df.empty:
        st.info("No items found.")
        return

    # Sidebar-style filters
    if compact:
        cat_filter = st.multiselect(
            "Category",
            ["kinetic", "shipping", "nuclear", "casualties", "deescalation"],
            key=f"cat_{source_filter or 'all'}",
        )
        pub_options = sorted(df["publisher"].dropna().unique().tolist())
        pub_filter = st.multiselect("Publisher", pub_options[:20], key=f"pub_{source_filter or 'all'}")
    else:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            cat_filter = st.multiselect(
                "Category",
                ["kinetic", "shipping", "nuclear", "casualties", "deescalation"],
                key=f"cat_{source_filter or 'all'}",
            )
        with col_f2:
            pub_options = sorted(df["publisher"].dropna().unique().tolist())
            pub_filter = st.multiselect("Publisher", pub_options[:20], key=f"pub_{source_filter or 'all'}")

# Apply filters
    if source_filter:
        df = df[df["source_type"] == source_filter]
    if cat_filter:
        df = df[df["categories"].apply(lambda c: bool(set(c or []) & set(cat_filter)))]
    if pub_filter:
        df = df[df["publisher"].isin(pub_filter)]

    st.caption(f"Showing {len(df)} items ({day_filter_label}, {time_basis_display} time)")

    for _, row in df.head(50).iterrows():
        cats = row.get("categories") or []
        badges = " ".join(_category_badge(c) for c in cats)
        score = row.get("risk_score", 0)
        title = row.get("title", "No title") or "No title"
        url = row.get("direct_url") or row.get("url", "")
        publisher = row.get("publisher", "") or ""
        snippet = _clean_snippet(row.get("snippet", ""), publisher)
        time_field = "published_at" if selected_time_basis == "published" else "fetched_at"
        time_label = "Published" if selected_time_basis == "published" else "Fetched"
        item_time = _format_bahrain_time(row.get(time_field, ""))

        with st.expander(f"**{title[:110]}**  `{score:+.0f}pts`"):
            st.caption(f"Categories: {badges if badges else '⚪ none'}")
            if compact:
                if snippet:
                    st.caption(snippet[:600])
                if url:
                    st.markdown(f"🔗 [Read article]({url})")
                st.caption(f"**Source:** {publisher}")
                st.caption(f"**{time_label}:** {item_time}")
            else:
                cols = st.columns([2, 1])
                with cols[0]:
                    if snippet:
                        st.caption(snippet[:600])
                    safe_article_url = _safe_url(url)
                    if safe_article_url:
                        st.markdown(f"🔗 [Read article]({safe_article_url})")
                with cols[1]:
                    st.caption(f"**Source:** {publisher}")
                    st.caption(f"**{time_label}:** {item_time}")


with tab_all:
    _render_items(items_data, compact=mobile_layout)

with tab_rss:
    rss_items = [i for i in items_data if i.get("source_type") == "rss"]
    _render_items(rss_items, source_filter="rss", compact=mobile_layout)

with tab_gdelt:
    gdelt_items = [i for i in items_data if i.get("source_type") == "gdelt"]
    _render_items(gdelt_items, source_filter="gdelt", compact=mobile_layout)

with tab_youtube:
    st.subheader("📺 Live News Streams")
    streams = settings.get_youtube_streams()
    if streams:
        per_row = 1 if mobile_layout else 3
        cols = st.columns(min(len(streams), per_row))
        for i, stream in enumerate(streams):
            with cols[i % per_row]:
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
            created = _format_bahrain_time(alert.get("created_at", ""))
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
                        url = _safe_url(d.get("direct_url") or d.get("url", ""))
                        pub = d.get("publisher", "")
                        safe_title = _escape_md(title[:80])
                        link = f"[{safe_title}]({url})" if url else safe_title
                        st.markdown(f"- {link} — *{pub}*")
    else:
        st.info("No alerts recorded yet.")

# ── Auto-refresh ────────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
