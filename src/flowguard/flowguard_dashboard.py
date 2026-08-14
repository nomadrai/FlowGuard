"""
flowguard_dashboard.py — ties together the real physical node, the ML
confirmation layer, the network-level cascade simulation, and the audit
trail into one dashboard.

Run: streamlit run flowguard_dashboard.py
"""

import numpy as np
import pandas as pd
import streamlit as st

from blockage_detector import (
    PIPE_AREA_CM2, INLET_BOX_BASE_AREA_CM2,
    calibrate_cd, calculate_area, blockage_percent,
    extract_window_features, BlockageAnomalyDetector, forecast_days_to_critical,
)
from network_simulation import WaterNetwork, generate_rainfall_pulse
from storage import (
    init_db, log_calibration, log_reading, log_blockage_event, log_network_run,
    get_calibration_log, get_readings, get_blockage_events, get_network_runs,
)

st.set_page_config(page_title="FlowGuard — Nagpur Flood Early Warning", layout="wide", initial_sidebar_state="collapsed")

# ============================================================
# THEME — same control-room instrumentation palette as before
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
:root {
    --bg-void: #0B0F14; --bg-panel: #151B23; --border: #2A3442; --border-bright: #3D4A5C;
    --amber: #E8A94C; --amber-dim: #6B5530; --cyan: #5FB8D9;
    --safe: #5FAE7A; --safe-dim: rgba(95,174,122,0.12);
    --critical: #D9695F; --critical-dim: rgba(217,105,95,0.12);
    --text-hi: #E8EAED; --text-mid: #9AA5B5; --text-low: #5C6779;
}
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: var(--bg-void); }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem; max-width: 1400px; }
.mono { font-family: 'IBM Plex Mono', monospace; }
.fg-topbar { display:flex; justify-content:space-between; align-items:flex-start; padding-bottom:18px; margin-bottom:24px; border-bottom:1px solid var(--border); }
.fg-title { font-size:1.55rem; font-weight:700; color:var(--text-hi); }
.fg-subtitle { font-family:'IBM Plex Mono', monospace; font-size:0.78rem; color:var(--text-mid); margin-top:6px; letter-spacing:0.02em; }
.fg-status-pill { font-family:'IBM Plex Mono', monospace; font-size:0.72rem; font-weight:600; color:var(--safe); background:var(--safe-dim); border:1px solid rgba(95,174,122,0.35); padding:6px 14px; border-radius:3px; letter-spacing:0.05em; text-transform:uppercase; }
.fg-section-label { font-family:'IBM Plex Mono', monospace; font-size:0.72rem; font-weight:600; color:var(--amber); text-transform:uppercase; letter-spacing:0.12em; margin:28px 0 4px 0; display:flex; align-items:center; gap:8px; }
.fg-section-label::before { content:''; width:3px; height:14px; background:var(--amber); display:inline-block; }
.fg-section-sub { font-size:0.85rem; color:var(--text-mid); margin-bottom:14px; }
.fg-card { background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; padding:18px; position:relative; }
.fg-card::before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--card-accent, var(--border-bright)); }
.fg-stat .val { font-family:'IBM Plex Mono', monospace; font-size:1.65rem; font-weight:600; color:var(--text-hi); line-height:1; }
.fg-stat .lbl { font-size:0.68rem; color:var(--text-mid); text-transform:uppercase; letter-spacing:0.05em; margin-top:4px; }
.fg-note { font-size:0.82rem; color:var(--text-mid); background:var(--bg-panel); border:1px solid var(--border); border-radius:4px; padding:12px 14px; line-height:1.6; }
.fg-note b { color:var(--cyan); }
.fg-badge { font-family:'IBM Plex Mono', monospace; font-size:0.62rem; font-weight:600; padding:3px 8px; border-radius:3px; letter-spacing:0.04em; }
.fg-badge.hw { background:rgba(95,184,217,0.14); color:var(--cyan); border:1px solid rgba(95,184,217,0.3); }
.fg-badge.sim { background:rgba(154,165,181,0.1); color:var(--text-mid); border:1px solid var(--border-bright); }
</style>
""", unsafe_allow_html=True)

init_db()

st.markdown("""
<div class="fg-topbar">
    <div>
        <div class="fg-title">FlowGuard — Cascading Flood Early Warning</div>
        <div class="fg-subtitle">PHYSICS-BASED BLOCKAGE DETECTION &nbsp;&middot;&nbsp; NAGPUR WATER NETWORK</div>
    </div>
    <div class="fg-status-pill">&#9679; SYSTEM ACTIVE</div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# SIDEBAR — system config (inflow rate) + calibration
# ============================================================
st.sidebar.header("System Configuration")
st.sidebar.caption(
    "Set the rainfall inflow rate **once before each monitoring session**, "
    "then submit individual water-height readings below."
)
inflow_ml_s = st.sidebar.number_input(
    "Rainfall inflow rate (mL/s)",
    value=20.0,
    min_value=0.1,
    help=(
        "How much water is entering the inlet box per second (rainfall rate). "
        "Measure this with a measuring jug: pour a known volume at a steady "
        "rate, time it, then compute volume ÷ time. 1 mL = 1 cm³."
    ),
)
# Convert mL/s → cm³/s (they are equal by definition; label is clearer in mL/s)
inflow_q_cm3s = inflow_ml_s  # 1 mL == 1 cm³

st.sidebar.markdown("---")
st.sidebar.caption(
    f"**Hardware geometry (fixed):**  \n"
    f"Drainage pipe: ⌀ 1.90 cm, area = {PIPE_AREA_CM2:.4f} cm²  \n"
    f"Inlet box base: {INLET_BOX_BASE_AREA_CM2:.0f} cm²"
)
st.sidebar.markdown("---")
st.sidebar.header("Calibration")
st.sidebar.caption("Run once per physical channel using a clean (unblocked) test pour.")
pour_volume = st.sidebar.number_input("Pour volume (mL)", value=200.0, min_value=1.0)
pour_time = st.sidebar.number_input("Pour time (sec)", value=10.0, min_value=0.1)
steady_h = st.sidebar.number_input("Steady water height (cm)", value=2.0, min_value=0.1)
# Clean area is fixed by the pipe geometry — show it read-only for transparency
a_clean = PIPE_AREA_CM2
st.sidebar.markdown(
    f"Known clean pipe area (cm²): **{a_clean:.4f}** *(pipe ⌀ 1.90 cm, auto-set)*"
)

if st.sidebar.button("Calibrate Cd"):
    cd_val = calibrate_cd(pour_volume, pour_time, steady_h, a_clean)
    st.session_state["cd"] = cd_val
    st.session_state["a_clean"] = a_clean
    log_calibration(cd_val, pour_volume, pour_time, steady_h, a_clean)
    st.sidebar.success(f"Cd = {cd_val:.4f}")

cd_active = st.session_state.get("cd", None)
a_clean_active = st.session_state.get("a_clean", a_clean)

# ============================================================
# SECTION 1 — Real Physical Node
# ============================================================
st.markdown('<div class="fg-section-label">Physical Node — Live Blockage Detection</div>', unsafe_allow_html=True)
st.markdown('<div class="fg-section-sub">Orifice equation (Bernoulli-derived) converts live water height into calculated channel area</div>', unsafe_allow_html=True)

if cd_active is None:
    st.markdown('<div class="fg-note">⚠️ Set the inflow rate and calibrate Cd in the sidebar first, then submit readings here.</div>', unsafe_allow_html=True)
else:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(
            f"**Enter a live reading** from Serial Monitor  \n"
            f"*(inflow rate: {inflow_ml_s:.1f} mL/s — change in sidebar if needed)*"
        )
        live_h = st.number_input("Current water height h (cm)", value=2.0, key="live_h",
                                  help="Read the water_level_cm column from the ESP32 Serial Monitor output.")

        if st.button("Submit reading"):
            # inflow Q comes from the sidebar — not entered per-reading
            area = calculate_area(inflow_q_cm3s, cd_active, live_h)
            pct = blockage_percent(area, a_clean_active)
            log_reading("Physical_Node_1", live_h, inflow_q_cm3s, area, pct)

            # Rolling window ML confirmation
            history = get_readings("Physical_Node_1")
            recent_pcts = history["blockage_pct"].head(5).tolist()[::-1]  # oldest to newest
            ml_confirmed = False
            forecast = None
            if len(recent_pcts) >= 5:
                features = extract_window_features(recent_pcts)
                # Build a baseline detector from readings beyond the recent window, if enough exist
                baseline_pool = history["blockage_pct"].tolist()
                if len(baseline_pool) >= 15:
                    baseline_windows = [baseline_pool[i:i+5] for i in range(0, len(baseline_pool) - 5, 5)]
                    baseline_features = [extract_window_features(w) for w in baseline_windows if len(w) == 5]
                    if len(baseline_features) >= 5:
                        detector = BlockageAnomalyDetector(contamination=0.1)
                        detector.fit(baseline_features)
                        ml_confirmed = detector.is_confirmed_anomaly(features)

                days = list(range(len(recent_pcts)))
                forecast = forecast_days_to_critical(recent_pcts, days, critical_threshold_pct=50.0)

            if pct is not None and pct > 15:
                log_blockage_event("Physical_Node_1", pct, int(ml_confirmed), forecast)

            st.session_state["last_reading"] = {"area": area, "pct": pct, "ml_confirmed": ml_confirmed, "forecast": forecast}

    with col2:
        last = st.session_state.get("last_reading")
        if last:
            pct = last["pct"]
            accent = "var(--critical)" if (pct is not None and pct > 15) else "var(--safe)"
            status_text = "BLOCKAGE DETECTED" if (pct is not None and pct > 15) else "CHANNEL CLEAR"
            ml_text = "ML-CONFIRMED" if last["ml_confirmed"] else "single reading — not yet confirmed"
            forecast_text = f"{last['forecast']} days to critical (50%)" if last["forecast"] is not None else "insufficient trend data"

            st.markdown(f"""
            <div class="fg-card" style="--card-accent: {accent};">
                <div style="font-size:1.1rem; font-weight:700; color:{accent}; margin-bottom:10px;">{status_text}</div>
                <div class="fg-stat" style="margin-bottom:10px;">
                    <div class="val">{pct:.1f}%</div>
                    <div class="lbl">Blockage estimate</div>
                </div>
                <div style="font-size:0.8rem; color:var(--text-mid);">
                    Calculated area: {last['area']:.4f} cm² (clean pipe = {a_clean_active:.4f} cm²)<br>
                    Inflow used: {inflow_ml_s:.1f} mL/s (set in sidebar)<br>
                    ML confirmation: {ml_text}<br>
                    Trend forecast: {forecast_text}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # History chart
    hist = get_readings("Physical_Node_1")
    if not hist.empty and len(hist) > 1:
        st.markdown("**Blockage % over readings**")
        chart_df = hist.iloc[::-1][["blockage_pct"]].reset_index(drop=True)
        st.line_chart(chart_df)

# ============================================================
# SECTION 2 — Network Cascade Simulation (software-only)
# ============================================================
st.markdown('<div class="fg-section-label">Network Cascade — Muskingum Flood Routing</div>', unsafe_allow_html=True)
st.markdown('<div class="fg-section-sub">Simulated network (Ambazari Lake → Nag River segments) — completes the citywide story around your one real node</div>', unsafe_allow_html=True)

col_a, col_b = st.columns([1, 2])
with col_a:
    peak_rain = st.slider("Simulated rainfall intensity (peak inflow)", 20, 200, 100)
    if st.button("Run network simulation"):
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
        log_network_run(rainfall.max(), len(nodes), last_node.outflow.max(), delay)

with col_b:
    if "network_nodes" in st.session_state:
        nodes = st.session_state["network_nodes"]
        rainfall = st.session_state["rainfall"]

        chart_data = pd.DataFrame({"Rainfall Inflow": rainfall})
        for node in nodes:
            chart_data[node.name] = node.outflow
        st.line_chart(chart_data)

        st.markdown('<div class="fg-note">Each downstream node\'s peak arrives <b>later</b> and <b>lower</b> than the one before — the flood wave is delayed and smoothed as it travels through the network, exactly as real hydrological routing predicts.</div>', unsafe_allow_html=True)

# ============================================================
# SECTION 3 — Audit Trail
# ============================================================
st.markdown('<div class="fg-section-label">Audit Trail — flowguard_history.db</div>', unsafe_allow_html=True)
st.markdown('<div class="fg-section-sub">Every calibration, reading, and confirmed blockage event, timestamped and stored locally</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["calibration_log", "blockage_readings", "blockage_events", "network_simulation_runs"])

with tab1:
    df = get_calibration_log()
    st.dataframe(df, hide_index=True, width="stretch") if not df.empty else st.markdown('<div class="fg-note">No calibration logged yet.</div>', unsafe_allow_html=True)

with tab2:
    df = get_readings()
    st.dataframe(df, hide_index=True, width="stretch") if not df.empty else st.markdown('<div class="fg-note">No readings logged yet.</div>', unsafe_allow_html=True)

with tab3:
    df = get_blockage_events()
    st.dataframe(df, hide_index=True, width="stretch") if not df.empty else st.markdown('<div class="fg-note">No confirmed blockage events yet.</div>', unsafe_allow_html=True)

with tab4:
    df = get_network_runs()
    st.dataframe(df, hide_index=True, width="stretch") if not df.empty else st.markdown('<div class="fg-note">No network simulation runs logged yet.</div>', unsafe_allow_html=True)
