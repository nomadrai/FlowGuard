"""
flowguard_dashboard.py — ties together the real physical node, the ML
confirmation layer, the network-level cascade simulation, and the audit
trail into one control-room dashboard.

Run: streamlit run flowguard_dashboard.py
"""

import pandas as pd
import streamlit as st

from blockage_detector import (
    calibrate_cd, calculate_area, blockage_percent,
    extract_window_features, BlockageAnomalyDetector, forecast_days_to_critical,
)
from network_simulation import WaterNetwork, generate_rainfall_pulse
from storage import (
    init_db, log_calibration, log_reading, log_blockage_event, log_network_run,
    get_calibration_log, get_readings, get_blockage_events, get_network_runs,
)
from config import (
    PIPE_AREA_CM2, INLET_BOX_BASE_AREA_CM2, CALIBRATED_CD,
    DEFAULT_INFLOW_Q_CM3S, BLOCKAGE_ALERT_THRESHOLD_PCT, NODE_NAME,
)

st.set_page_config(page_title="FlowGuard — Nagpur Flood Early Warning", layout="wide", initial_sidebar_state="collapsed")

# ============================================================
# THEME — control-room instrumentation palette (dark, dim-room
# monitoring). Amber = signal/caution, cyan = telemetry,
# green = clear, red = critical. IBM Plex Sans for content,
# Plex Mono for every instrument label and value.
# ============================================================
THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

:root {
    --bg-void: #0B0F14;
    --bg-panel: #131923;
    --bg-panel-2: #0E131B;
    --bg-inset: #0C1117;
    --border: #1F2A37;
    --border-strong: #32404F;
    --amber: #E8A94C;
    --amber-bright: #F2B95E;
    --amber-soft: rgba(232, 169, 76, 0.10);
    --cyan: #5FB8D9;
    --green: #5FAE7A;
    --red: #E07067;
    --text-hi: #EDEFF2;
    --text-mid: #A6B0BF;
    --text-low: #7E8A9C;
    --sans: 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
    --mono: 'IBM Plex Mono', ui-monospace, monospace;
}

html, body, [data-testid="stAppViewContainer"] { font-family: var(--sans); color: var(--text-hi); }
.stApp { background: var(--bg-void); }
#MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { visibility: hidden; }
.block-container { padding: 1.35rem 2.4rem 2.2rem; max-width: 1440px; }
@media (max-width: 768px) { .block-container { padding: 1rem 1.1rem 1.6rem; } }

/* ---------- sidebar ---------- */
div[data-testid="stSidebar"] { background: var(--bg-panel-2); border-right: 1px solid var(--border); }
div[data-testid="stSidebar"] .block-container { padding: 1.3rem 1.15rem; max-width: none; }
div[data-testid="stSidebar"] hr { border-color: var(--border); }
.fg-sb-head { border-bottom: 1px solid var(--border); padding-bottom: 0.9rem; margin-bottom: 0.2rem; }
.fg-sb-title { font-size: 0.95rem; font-weight: 700; letter-spacing: -0.005em; color: var(--text-hi); }
.fg-sb-title .fg-mark { color: var(--amber); }
.fg-sb-sub { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.1em; color: var(--text-low); margin-top: 0.3rem; }
.fg-sb-label { font-family: var(--mono); font-size: 0.62rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-low); margin: 1.15rem 0 0.45rem; }
.fg-geo { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.75rem; padding: 0.28rem 0; border-bottom: 1px dashed var(--border); }
.fg-geo .k { color: var(--text-low); }
.fg-geo .v { font-family: var(--mono); font-size: 0.72rem; color: var(--text-hi); }

/* ---------- topbar ---------- */
.fg-topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; padding-bottom: 1.05rem; margin-bottom: 1.3rem; border-bottom: 1px solid var(--border); }
.fg-title { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.01em; color: var(--text-hi); }
.fg-title .fg-mark { color: var(--amber); }
.fg-subtitle { font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.12em; color: var(--text-low); margin-top: 0.35rem; }
.fg-status-pill { display: flex; align-items: center; gap: 0.5rem; font-family: var(--mono); font-size: 0.66rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; padding: 0.45rem 0.85rem; border-radius: 999px; white-space: nowrap; }
.fg-status-pill.ok { color: var(--green); background: rgba(95, 174, 122, 0.08); border: 1px solid rgba(95, 174, 122, 0.35); }
.fg-status-pill.warn { color: var(--amber); background: var(--amber-soft); border: 1px solid rgba(232, 169, 76, 0.35); }
.fg-status-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; animation: fg-pulse 2.4s ease-in-out infinite; }
.fg-status-pill.ok .dot { box-shadow: 0 0 6px rgba(95, 174, 122, 0.7); }
.fg-status-pill.warn .dot { box-shadow: 0 0 6px rgba(232, 169, 76, 0.7); }
@keyframes fg-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.45; }
}
@media (prefers-reduced-motion: reduce) {
    .fg-status-pill .dot, .fg-feed-dot { animation: none; }
}

/* ---------- panel headers ---------- */
.fg-panel-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.7rem; margin: 1.9rem 0 1.05rem; }
.fg-panel-title { font-size: 1.02rem; font-weight: 700; letter-spacing: -0.005em; color: var(--text-hi); }
.fg-panel-sub { font-family: var(--mono); font-size: 0.66rem; color: var(--text-low); margin-top: 0.3rem; letter-spacing: 0.04em; }
.fg-tag { font-family: var(--mono); font-size: 0.64rem; font-weight: 600; letter-spacing: 0.1em; color: var(--amber); border: 1px solid rgba(232, 169, 76, 0.35); background: var(--amber-soft); padding: 0.3rem 0.6rem; border-radius: 4px; white-space: nowrap; }

/* ---------- KPI strip ---------- */
.fg-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.fg-sims { grid-template-columns: repeat(3, minmax(0, 1fr)); }
@media (max-width: 1100px) { .fg-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .fg-kpis { grid-template-columns: 1fr; } }
.fg-stat { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px; padding: 0.85rem 1.05rem 0.8rem; }
.fg-stat-lbl { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.09em; text-transform: uppercase; color: var(--text-low); }
.fg-stat-val { font-family: var(--mono); font-weight: 600; font-size: 1.55rem; line-height: 1.15; color: var(--text-hi); margin-top: 0.3rem; }
.fg-stat-val .fg-unit { font-size: 0.8rem; font-weight: 500; color: var(--text-mid); margin-left: 2px; }
.fg-stat-sub { font-size: 0.68rem; color: var(--text-low); margin-top: 0.3rem; }
.fg-val-green { color: var(--green); }
.fg-val-amber { color: var(--amber); }
.fg-val-red { color: var(--red); }
.fg-val-cyan { color: var(--cyan); }

/* ---------- status card (blockage verdict) ---------- */
.fg-card { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 10px; padding: 1.1rem 1.2rem; }
.fg-card.ok { border-color: rgba(95, 174, 122, 0.35); }
.fg-card.alert { border-color: rgba(224, 112, 103, 0.45); background: linear-gradient(180deg, rgba(224, 112, 103, 0.06), var(--bg-panel) 55%); }
.fg-card-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.95rem; }
.fg-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.fg-card.ok .fg-dot { background: var(--green); box-shadow: 0 0 8px rgba(95, 174, 122, 0.55); }
.fg-card.alert .fg-dot { background: var(--red); box-shadow: 0 0 8px rgba(224, 112, 103, 0.55); }
.fg-status-text { font-family: var(--mono); font-size: 0.68rem; font-weight: 700; letter-spacing: 0.13em; }
.fg-card.ok .fg-status-text { color: var(--green); }
.fg-card.alert .fg-status-text { color: var(--red); }
.fg-src { margin-left: auto; font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.06em; color: var(--text-low); text-transform: uppercase; }
.fg-big-val { font-family: var(--mono); font-weight: 600; font-size: 2.6rem; line-height: 1; color: var(--text-hi); }
.fg-big-val .fg-unit { font-size: 1rem; font-weight: 500; color: var(--text-mid); }
.fg-big-lbl { font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-mid); margin-top: 0.4rem; }
.fg-facts { margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 0.8rem; display: grid; grid-template-columns: 1fr 1fr; gap: 0.45rem 1.4rem; }
.fg-fact { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.74rem; }
.fg-fact .k { color: var(--text-low); }
.fg-fact .v { font-family: var(--mono); font-size: 0.7rem; color: var(--text-hi); text-align: right; }

/* ---------- feed line (live banner) ---------- */
.fg-feed-line { display: flex; align-items: center; gap: 0.5rem; font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.05em; color: var(--text-mid); margin: 0.35rem 0 0.95rem; }
.fg-feed-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px rgba(95, 174, 122, 0.7); animation: fg-pulse 2.4s ease-in-out infinite; }

/* ---------- notes / empty states ---------- */
.fg-note { font-size: 0.78rem; color: var(--text-mid); background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem 1rem; line-height: 1.65; }
.fg-note b { color: var(--text-hi); }
.fg-note .mono { color: var(--cyan); }
.fg-empty { border: 1px dashed var(--border-strong); border-radius: 10px; padding: 1.4rem 1.5rem; background: var(--bg-inset); }
.fg-empty-title { font-family: var(--mono); font-size: 0.68rem; font-weight: 600; letter-spacing: 0.12em; color: var(--amber); }
.fg-empty ol { margin: 0.65rem 0 0 1.15rem; padding: 0; font-size: 0.8rem; color: var(--text-mid); line-height: 1.95; }
.fg-empty ol b { color: var(--text-hi); font-family: var(--mono); font-weight: 500; font-size: 0.75rem; }

/* ---------- charts ---------- */
.fg-chart-lbl { font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-low); margin-bottom: 0.4rem; }

/* ---------- footer ---------- */
.fg-footer { margin-top: 2.4rem; padding-top: 1rem; border-top: 1px solid var(--border); display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.08em; color: var(--text-low); }

/* ---------- native widgets ---------- */
.stButton > button, [data-testid="stDownloadButton"] button {
    background: var(--bg-panel); color: var(--text-hi);
    border: 1px solid var(--border-strong); border-radius: 6px;
    font-size: 0.8rem; font-weight: 600; line-height: 1.2;
    padding: 0.44rem 0.95rem; cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.05s ease;
}
.stButton > button:hover, [data-testid="stDownloadButton"] button:hover {
    border-color: var(--amber); color: var(--amber); background: var(--amber-soft);
}
.stButton > button:active, [data-testid="stDownloadButton"] button:active { transform: translateY(1px); }
.stButton > button:focus-visible, [data-testid="stDownloadButton"] button:focus-visible {
    outline: 2px solid var(--amber); outline-offset: 2px;
}
.st-key-submit_reading button, .st-key-run_network button {
    background: var(--amber); border-color: var(--amber); color: #191204; font-weight: 700;
}
.st-key-submit_reading button:hover, .st-key-run_network button:hover {
    background: var(--amber-bright); border-color: var(--amber-bright); color: #191204;
}
div[data-baseweb="input"] {
    background: var(--bg-inset); border-color: var(--border-strong); border-radius: 6px;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
div[data-baseweb="input"]:focus-within { border-color: var(--amber); box-shadow: 0 0 0 2px rgba(232, 169, 76, 0.16); }
div[data-baseweb="input"] input { color: var(--text-hi); caret-color: var(--amber); font-size: 0.8rem; }
.stTabs [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] {
    font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.07em;
    color: var(--text-low); padding: 0.55rem 0.95rem; border-radius: 6px 6px 0 0;
    transition: color 0.15s ease, background 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--text-hi); background: rgba(255, 255, 255, 0.03); }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color: var(--amber); background: var(--amber-soft); }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--amber); height: 2px; }
[data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
[data-testid="stMarkdownContainer"] p { font-size: 0.84rem; line-height: 1.6; }
"""

st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)

init_db()


# ============================================================
# SHARED RENDER HELPERS
# ============================================================
def _fmt(value, fmt):
    return fmt % value if value is not None else "—"


def _pct_state(pct):
    return "alert" if pct is not None and pct > BLOCKAGE_ALERT_THRESHOLD_PCT else "ok"


def compute_ml_and_forecast(history_df):
    """Shared logic: given the readings history, compute ML confirmation + forecast for the LATEST reading."""
    recent_pcts = history_df["blockage_pct"].head(5).tolist()[::-1]  # oldest to newest
    ml_confirmed = False
    forecast = None
    if len(recent_pcts) >= 5:
        features = extract_window_features(recent_pcts)
        baseline_pool = history_df["blockage_pct"].tolist()
        if len(baseline_pool) >= 15:
            baseline_windows = [baseline_pool[i:i + 5] for i in range(0, len(baseline_pool) - 5, 5)]
            baseline_features = [extract_window_features(w) for w in baseline_windows if len(w) == 5]
            if len(baseline_features) >= 5:
                detector = BlockageAnomalyDetector(contamination=0.1)
                detector.fit(baseline_features)
                ml_confirmed = detector.is_confirmed_anomaly(features)
        days = list(range(len(recent_pcts)))
        forecast = forecast_days_to_critical(recent_pcts, days, critical_threshold_pct=50.0)
    return ml_confirmed, forecast


def maybe_log_blockage_event(reading_id, pct, ml_confirmed, forecast):
    """Log a blockage event only when the reading is new — prevents duplicate rows on every auto-refresh."""
    if pct is not None and pct > BLOCKAGE_ALERT_THRESHOLD_PCT:
        if st.session_state.get("last_logged_reading_id") != reading_id:
            log_blockage_event(NODE_NAME, pct, int(ml_confirmed), forecast)
            st.session_state["last_logged_reading_id"] = reading_id


def render_panel_head(title, tag, sub=None):
    sub_html = f'<div class="fg-panel-sub">{sub}</div>' if sub else ""
    st.markdown(f"""
    <div class="fg-panel-head">
        <div>
            <div class="fg-panel-title">{title}</div>
            {sub_html}
        </div>
        <div class="fg-tag">{tag}</div>
    </div>
    """, unsafe_allow_html=True)


def render_kpis(current=None):
    """Four-number monitoring strip: blockage %, water height, effective area, days to critical."""
    if current:
        pct, height, area = current.get("pct"), current.get("height"), current.get("area")
        forecast, ts, ml = current.get("forecast"), current.get("ts"), current.get("ml_confirmed")
    else:
        pct = height = area = forecast = ts = ml = None
    pct_cls = {"ok": "fg-val-green", "alert": "fg-val-red"}[_pct_state(pct)]
    ml_sub = "ML CONFIRMED" if ml else "ML UNCONFIRMED" if ml is not None else "no baseline yet"
    st.markdown(f"""
    <div class="fg-kpis">
        <div class="fg-stat">
            <div class="fg-stat-lbl">Blockage estimate</div>
            <div class="fg-stat-val {pct_cls}">{_fmt(pct, "%.1f")}<span class="fg-unit">%</span></div>
            <div class="fg-stat-sub">alert at {BLOCKAGE_ALERT_THRESHOLD_PCT:.0f}%</div>
        </div>
        <div class="fg-stat">
            <div class="fg-stat-lbl">Water height</div>
            <div class="fg-stat-val fg-val-cyan">{_fmt(height, "%.2f")}<span class="fg-unit">cm</span></div>
            <div class="fg-stat-sub">{ts if ts else "no reading yet"}</div>
        </div>
        <div class="fg-stat">
            <div class="fg-stat-lbl">Effective area</div>
            <div class="fg-stat-val">{_fmt(area, "%.3f")}<span class="fg-unit">cm²</span></div>
            <div class="fg-stat-sub">clean pipe = {PIPE_AREA_CM2:.4f} cm²</div>
        </div>
        <div class="fg-stat">
            <div class="fg-stat-lbl">Days to critical</div>
            <div class="fg-stat-val fg-val-amber">{_fmt(forecast, "%.0f")}</div>
            <div class="fg-stat-sub">{ml_sub}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_reading_card(current, source_label):
    """The blockage verdict: status dot + headline estimate + the physical facts behind it."""
    pct = current.get("pct")
    state_cls = _pct_state(pct)
    status_text = "BLOCKAGE DETECTED" if state_cls == "alert" else "CHANNEL CLEAR"
    ml_text = "ML CONFIRMED" if current.get("ml_confirmed") else "not yet confirmed"
    forecast = current.get("forecast")
    forecast_text = f"{forecast:.1f} days" if forecast is not None else "insufficient trend data"
    st.markdown(f"""
    <div class="fg-card {state_cls}">
        <div class="fg-card-head">
            <span class="fg-dot"></span>
            <span class="fg-status-text">{status_text}</span>
            <span class="fg-src">{source_label}</span>
        </div>
        <div class="fg-big-val">{_fmt(pct, "%.1f")}<span class="fg-unit">%</span></div>
        <div class="fg-big-lbl">Blockage estimate</div>
        <div class="fg-facts">
            <div class="fg-fact"><span class="k">Effective area</span><span class="v">{_fmt(current.get("area"), "%.4f")} cm²</span></div>
            <div class="fg-fact"><span class="k">Clean pipe area</span><span class="v">{PIPE_AREA_CM2:.4f} cm²</span></div>
            <div class="fg-fact"><span class="k">Assumed inflow</span><span class="v">{DEFAULT_INFLOW_Q_CM3S:.0f} mL/s</span></div>
            <div class="fg-fact"><span class="k">Water height</span><span class="v">{_fmt(current.get("height"), "%.2f")} cm</span></div>
            <div class="fg-fact"><span class="k">ML confirmation</span><span class="v">{ml_text}</span></div>
            <div class="fg-fact"><span class="k">Trend forecast</span><span class="v">{forecast_text}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_charts(hist):
    ts = hist.iloc[::-1].reset_index(drop=True)
    col1, col2 = st.columns([1.6, 1], gap="medium")
    with col1:
        st.markdown('<div class="fg-chart-lbl">Blockage estimate over readings</div>', unsafe_allow_html=True)
        line = pd.DataFrame({
            "Blockage estimate (%)": ts["blockage_pct"],
            f"Alert threshold ({BLOCKAGE_ALERT_THRESHOLD_PCT:.0f}%)": BLOCKAGE_ALERT_THRESHOLD_PCT,
        })
        st.line_chart(line, color=["#E8A94C", "#E07067"], height=235)
    with col2:
        st.markdown('<div class="fg-chart-lbl">Water level (cm)</div>', unsafe_allow_html=True)
        st.line_chart(ts[["water_level_cm"]], color=["#5FB8D9"], height=235)


def render_empty_state(live=True):
    if live:
        st.markdown("""
        <div class="fg-empty">
            <div class="fg-empty-title">NO LIVE READINGS YET</div>
            <ol>
                <li><b>01</b> — run <span class="mono">python serial_reader.py</span> in a separate terminal</li>
                <li><b>02</b> — pour water through the inlet box (≈ 120 mL/s for clean-pipe heights of 2–5 cm)</li>
                <li><b>03</b> — watch this panel update within ~1–2 seconds per reading</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="fg-empty">
            <div class="fg-empty-title">NO READINGS LOGGED</div>
            <ol>
                <li><b>01</b> — enter a water height below and submit the reading</li>
                <li><b>02</b> — the verdict card, KPI strip, and history chart fill in</li>
                <li><b>03</b> — every entry lands in the audit trail for the civic record</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)


# ============================================================
# SIDEBAR — operating mode, node geometry, recalibration
# (defined first so the topbar can reflect the active mode)
# ============================================================
with st.sidebar:
    st.markdown("""
    <div class="fg-sb-head">
        <div class="fg-sb-title"><span class="fg-mark">▣</span> FLOWGUARD</div>
        <div class="fg-sb-sub">NAGPUR DRAINAGE · NODE 01</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="fg-sb-label">Operating mode</div>', unsafe_allow_html=True)
    live_mode = st.toggle(
        "Live mode — serial feed",
        value=True,
        help="Auto-refresh from serial_reader.py. Turn off for manual entry.",
    )
    if live_mode:
        refresh_rate = st.slider("Refresh rate (sec)", 1, 5, 2)
        st.caption("Run `python serial_reader.py` in a separate terminal FIRST — the dashboard just displays what it logs.")

    st.markdown('<div class="fg-sb-label">Node geometry</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="fg-geo"><span class="k">Pipe diameter</span><span class="v">1.90 cm</span></div>
    <div class="fg-geo"><span class="k">Pipe area</span><span class="v">{PIPE_AREA_CM2:.4f} cm²</span></div>
    <div class="fg-geo"><span class="k">Inlet box base</span><span class="v">{INLET_BOX_BASE_AREA_CM2:.0f} cm²</span></div>
    <div class="fg-geo"><span class="k">Calibrated Cd</span><span class="v">{CALIBRATED_CD}</span></div>
    <div class="fg-geo"><span class="k">Assumed inflow</span><span class="v">{DEFAULT_INFLOW_Q_CM3S:.0f} mL/s</span></div>
    <div class="fg-geo"><span class="k">Alert threshold</span><span class="v">{BLOCKAGE_ALERT_THRESHOLD_PCT:.0f}%</span></div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="fg-sb-label">Recalibration</div>', unsafe_allow_html=True)
    st.caption("Only needed to recompute Cd from a fresh test pour. Otherwise the config.py value above is already active.")
    pour_volume = st.number_input("Pour volume (mL)", value=200.0, min_value=1.0)
    pour_time = st.number_input("Pour time (sec)", value=10.0, min_value=0.1)
    steady_h = st.number_input("Steady water height (cm)", value=2.0, min_value=0.1)
    a_clean = PIPE_AREA_CM2

    if st.button("Recalibrate Cd", use_container_width=True):
        cd_val = calibrate_cd(pour_volume, pour_time, steady_h, a_clean)
        st.session_state["cd"] = cd_val
        log_calibration(cd_val, pour_volume, pour_time, steady_h, a_clean)
        st.success(f"New Cd = {cd_val:.4f} — update CALIBRATED_CD in config.py to make this permanent.")

# Active Cd: use a fresh recalibration if one was just run this session,
# otherwise fall back to the shared config value (this is what serial_reader.py
# is also using, so live and dashboard stay consistent).
cd_active = st.session_state.get("cd", CALIBRATED_CD)
a_clean_active = a_clean

# ============================================================
# TOPBAR
# ============================================================
status_pill = (
    '<div class="fg-status-pill ok"><span class="dot"></span>System live</div>'
    if live_mode
    else '<div class="fg-status-pill warn"><span class="dot"></span>Manual mode</div>'
)
st.markdown(f"""
<div class="fg-topbar">
    <div>
        <div class="fg-title"><span class="fg-mark">▣</span>&nbsp;FlowGuard — Cascading Flood Early Warning</div>
        <div class="fg-subtitle">PHYSICS-BASED BLOCKAGE DETECTION &nbsp;&middot;&nbsp; NAGPUR WATER NETWORK</div>
    </div>
    {status_pill}
</div>
""", unsafe_allow_html=True)

# ============================================================
# SECTION 1 — Physical Node
# ============================================================
render_panel_head(
    "Physical Node",
    "PHYSICAL NODE",
    "Orifice equation converts live water height into effective channel area",
)

if live_mode:
    @st.fragment(run_every=refresh_rate)
    def live_panel():
        """Auto-refreshing live surface — only this block reruns, so the rest of the page never flickers."""
        hist = get_readings(NODE_NAME)
        if hist.empty:
            render_empty_state(live=True)
            return

        latest = hist.iloc[0]
        ml_confirmed, forecast = compute_ml_and_forecast(hist)
        maybe_log_blockage_event(int(latest["id"]), latest["blockage_pct"], ml_confirmed, forecast)

        current = {
            "pct": latest["blockage_pct"],
            "height": latest["water_level_cm"],
            "area": latest["calculated_area_cm2"],
            "forecast": forecast,
            "ml_confirmed": ml_confirmed,
            "ts": latest["timestamp"],
        }
        st.markdown(f"""
        <div class="fg-feed-line">
            <span class="fg-feed-dot"></span>
            LATEST {latest["timestamp"]} &nbsp;&middot;&nbsp; {len(hist)} READINGS STORED &nbsp;&middot;&nbsp; SOURCE serial_reader.py
        </div>
        """, unsafe_allow_html=True)

        render_kpis(current)
        col1, col2 = st.columns([1, 1.6], gap="medium")
        with col1:
            render_reading_card(current, "LIVE — serial_reader.py")
        with col2:
            if len(hist) > 1:
                render_charts(hist)

    live_panel()

else:
    st.markdown("""
    <div class="fg-note">Manual mode — enter a water height reading by hand (useful for testing without the live serial connection).</div>
    """, unsafe_allow_html=True)

    hist = get_readings(NODE_NAME)
    current = st.session_state.get("last_reading")
    if current is None and not hist.empty:
        latest = hist.iloc[0]
        ml_confirmed, forecast = compute_ml_and_forecast(hist)
        current = {
            "pct": latest["blockage_pct"],
            "height": latest["water_level_cm"],
            "area": latest["calculated_area_cm2"],
            "forecast": forecast,
            "ml_confirmed": ml_confirmed,
            "ts": latest["timestamp"],
        }

    render_kpis(current)

    col1, col2 = st.columns([1, 1.6], gap="medium")
    with col1:
        st.markdown('<div class="fg-chart-lbl">Manual reading entry</div>', unsafe_allow_html=True)
        live_h = st.number_input("Current water height h (cm)", value=2.0, key="live_h",
                                 help="Read the water_level_cm column from the ESP32 Serial Monitor output.")
        if st.button("Submit reading", key="submit_reading"):
            area = calculate_area(DEFAULT_INFLOW_Q_CM3S, cd_active, live_h)
            pct = blockage_percent(area, a_clean_active)
            log_reading(NODE_NAME, live_h, DEFAULT_INFLOW_Q_CM3S, area, pct)

            history = get_readings(NODE_NAME)
            ml_confirmed, forecast = compute_ml_and_forecast(history)
            maybe_log_blockage_event(int(history.iloc[0]["id"]), pct, ml_confirmed, forecast)

            st.session_state["last_reading"] = {
                "pct": pct, "height": live_h, "area": area,
                "forecast": forecast, "ml_confirmed": ml_confirmed,
                "ts": history.iloc[0]["timestamp"],
            }
            st.rerun()
    with col2:
        if current:
            render_reading_card(current, "MANUAL ENTRY")
        else:
            render_empty_state(live=False)

    if not hist.empty and len(hist) > 1:
        render_charts(hist)

# ============================================================
# SECTION 2 — Network Cascade Simulation (software-only)
# ============================================================
render_panel_head(
    "Network Cascade",
    "NETWORK SIM",
    "Muskingum routing across Ambazari Lake → Nag River segments — the citywide story around your one real node",
)

col_a, col_b = st.columns([1, 2], gap="medium")
with col_a:
    peak_rain = st.slider("Rainfall intensity — peak inflow (mL/s)", 20, 200, 100)
    if st.button("Run network simulation", key="run_network", use_container_width=True):
        network = WaterNetwork()
        network.add_node("Ambazari Lake", k=2.0, x=0.2, node_type="lake")
        network.add_node("Nag River Segment 1", k=3.0, x=0.25, node_type="drain")
        network.add_node("Nag River Segment 2 (downstream)", k=4.0, x=0.3, node_type="drain")

        rainfall = generate_rainfall_pulse(duration_steps=30, peak_step=10, peak_value=peak_rain, base_value=5)
        nodes = network.simulate(rainfall, dt=1.0)
        st.session_state["network_nodes"] = nodes
        st.session_state["rainfall"] = rainfall

        last_node = nodes[-1]
        delay = int(last_node.outflow.argmax() - rainfall.argmax())
        attenuation = (1.0 - last_node.outflow.max() / rainfall.max()) * 100.0
        st.session_state["net_metrics"] = {
            "peak": last_node.outflow.max(),
            "delay": delay,
            "attenuation": attenuation,
        }
        log_network_run(rainfall.max(), len(nodes), last_node.outflow.max(), delay)

    if "net_metrics" in st.session_state:
        st.markdown("""
        <div class="fg-chart-lbl" style="margin-top:1.1rem;">Downstream outcome</div>
        """, unsafe_allow_html=True)
        m = st.session_state["net_metrics"]
        st.markdown(f"""
        <div class="fg-kpis fg-sims">
            <div class="fg-stat">
                <div class="fg-stat-lbl">Peak outflow</div>
                <div class="fg-stat-val">{m["peak"]:.1f}<span class="fg-unit">mL/s</span></div>
                <div class="fg-stat-sub">at Nag River Seg. 2</div>
            </div>
            <div class="fg-stat">
                <div class="fg-stat-lbl">Peak delay</div>
                <div class="fg-stat-val fg-val-cyan">+{m["delay"]}<span class="fg-unit">steps</span></div>
                <div class="fg-stat-sub">vs rainfall peak</div>
            </div>
            <div class="fg-stat">
                <div class="fg-stat-lbl">Attenuation</div>
                <div class="fg-stat-val fg-val-green">−{m["attenuation"]:.1f}<span class="fg-unit">%</span></div>
                <div class="fg-stat-sub">peak vs rainfall peak</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_b:
    if "network_nodes" in st.session_state:
        nodes = st.session_state["network_nodes"]
        rainfall = st.session_state["rainfall"]

        chart_data = pd.DataFrame({"Rainfall inflow (mL/s)": rainfall})
        for node in nodes:
            chart_data[node.name] = node.outflow
        st.line_chart(chart_data, color=["#E8A94C", "#5FB8D9", "#5FAE7A", "#A6B0BF"], height=280)

        st.markdown("""
        <div class="fg-note">Each downstream node's peak arrives <b>later</b> and <b>lower</b> than the one before — the flood wave is delayed and smoothed as it travels through the network, exactly as real hydrological routing predicts.</div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="fg-empty">
            <div class="fg-empty-title">SIMULATION READY</div>
            <ol>
                <li><b>01</b> — set the rainfall intensity on the left</li>
                <li><b>02</b> — hit <span class="mono">RUN NETWORK SIMULATION</span> to route the pulse through 3 segments</li>
                <li><b>03</b> — compare downstream peak, delay, and attenuation</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

# ============================================================
# SECTION 3 — Audit Trail
# ============================================================
render_panel_head(
    "Audit Trail",
    "AUDIT TRAIL",
    "Every calibration, reading, and confirmed blockage event, timestamped and stored locally",
)

cal_df = get_calibration_log()
read_df = get_readings()
ev_df = get_blockage_events()
net_df = get_network_runs()

tabs = st.tabs([
    f"Calibrations · {len(cal_df)}",
    f"Readings · {len(read_df)}",
    f"Blockage events · {len(ev_df)}",
    f"Network runs · {len(net_df)}",
])

with tabs[0]:
    if cal_df.empty:
        st.markdown('<div class="fg-note">No calibrations logged yet — run a recalibration from the sidebar to populate this table.</div>', unsafe_allow_html=True)
    else:
        st.dataframe(
            cal_df.drop(columns=["id"]),
            hide_index=True, width="stretch", height=400,
            column_config={
                "timestamp": st.column_config.TextColumn("Timestamp"),
                "cd": st.column_config.NumberColumn("Cd", format="%.4f"),
                "pour_volume_ml": st.column_config.NumberColumn("Pour volume (mL)", format="%.1f"),
                "pour_time_sec": st.column_config.NumberColumn("Pour time (s)", format="%.1f"),
                "steady_h_cm": st.column_config.NumberColumn("Steady height (cm)", format="%.2f"),
                "a_clean_cm2": st.column_config.NumberColumn("Clean area (cm²)", format="%.4f"),
            },
        )
        st.download_button("Export CSV", cal_df.to_csv(index=False).encode("utf-8"),
                           "flowguard_calibrations.csv", "text/csv", key="dl_cal")

with tabs[1]:
    if read_df.empty:
        st.markdown('<div class="fg-note">No readings logged yet — the physical node section above feeds this table.</div>', unsafe_allow_html=True)
    else:
        st.dataframe(
            read_df.drop(columns=["id", "node"]),
            hide_index=True, width="stretch", height=400,
            column_config={
                "timestamp": st.column_config.TextColumn("Timestamp"),
                "water_level_cm": st.column_config.NumberColumn("Water level (cm)", format="%.2f"),
                "inflow_q_cm3s": st.column_config.NumberColumn("Inflow (mL/s)", format="%.1f"),
                "calculated_area_cm2": st.column_config.NumberColumn("Effective area (cm²)", format="%.4f"),
                "blockage_pct": st.column_config.NumberColumn("Blockage (%)", format="%.2f"),
            },
        )
        st.download_button("Export CSV", read_df.to_csv(index=False).encode("utf-8"),
                           "flowguard_readings.csv", "text/csv", key="dl_read")

with tabs[2]:
    if ev_df.empty:
        st.markdown('<div class="fg-note">No confirmed blockage events yet — events appear here when blockage % stays above the alert threshold.</div>', unsafe_allow_html=True)
    else:
        ev_disp = ev_df.copy()
        ev_disp["ml_confirmed"] = ev_disp["ml_confirmed"].map({1: "ML CONFIRMED", 0: "single reading"}).fillna("—")
        st.dataframe(
            ev_disp.drop(columns=["id", "node"]),
            hide_index=True, width="stretch", height=400,
            column_config={
                "timestamp": st.column_config.TextColumn("Timestamp"),
                "blockage_pct": st.column_config.NumberColumn("Blockage (%)", format="%.2f"),
                "ml_confirmed": st.column_config.TextColumn("ML confirmation"),
                "forecast_days_to_critical": st.column_config.NumberColumn("Days to critical", format="%.1f"),
            },
        )
        st.download_button("Export CSV", ev_df.to_csv(index=False).encode("utf-8"),
                           "flowguard_blockage_events.csv", "text/csv", key="dl_ev")

with tabs[3]:
    if net_df.empty:
        st.markdown('<div class="fg-note">No network simulation runs logged yet — run the cascade simulation above to populate this table.</div>', unsafe_allow_html=True)
    else:
        st.dataframe(
            net_df.drop(columns=["id"]),
            hide_index=True, width="stretch", height=400,
            column_config={
                "timestamp": st.column_config.TextColumn("Timestamp"),
                "rainfall_peak": st.column_config.NumberColumn("Rainfall peak (mL/s)", format="%.1f"),
                "num_nodes": st.column_config.NumberColumn("Nodes", format="%d"),
                "downstream_peak_outflow": st.column_config.NumberColumn("Downstream peak (mL/s)", format="%.1f"),
                "downstream_peak_delay_steps": st.column_config.NumberColumn("Peak delay (steps)", format="%d"),
            },
        )
        st.download_button("Export CSV", net_df.to_csv(index=False).encode("utf-8"),
                           "flowguard_network_runs.csv", "text/csv", key="dl_net")

# ============================================================
# FOOTER
# ============================================================
st.markdown("""
<div class="fg-footer">
    <span>FLOWGUARD · V1.0 · NAGPUR DRAINAGE NETWORK</span>
    <span>AUDIT TRAIL → data/flowguard_history.db</span>
</div>
""", unsafe_allow_html=True)
