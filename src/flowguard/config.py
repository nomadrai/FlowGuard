"""
config.py — SINGLE SOURCE OF TRUTH for every physical constant used across
FlowGuard. Every other file imports from here instead of hardcoding its own
copy of these numbers.

All physical quantities are in SI units (m, m², m³/s, m/s²) internally.
Display/legacy cm-based values are provided for UI compatibility.
"""

import math

# ------------------------------------------------------------------
# HARDWARE GEOMETRY — SI units (measured prototype constants)
# ------------------------------------------------------------------
SENSOR_TO_BOTTOM_M = 0.1383          # distance from sensor face to container bottom (m)
CONTAINER_HEIGHT_M = 0.075           # container overflow height (m)
LAKE_AREA_M2 = 0.0308                # inlet box / "lake" base area (m²)
DRAIN_AREA_M2 = 2.83e-4              # drainage pipe cross-sectional area (m²)
DRAIN_CENTER_HEIGHT_M = 0.012        # height of drain center above container bottom (m)
GRAVITY_M_S2 = 9.81                  # gravitational acceleration (m/s²)

# ------------------------------------------------------------------
# HARDWARE GEOMETRY — cm / cm² legacy aliases (for UI display only)
# ------------------------------------------------------------------
PIPE_DIAMETER_CM = 1.90
PIPE_AREA_CM2 = math.pi * (PIPE_DIAMETER_CM / 2) ** 2   # ≈ 2.8353 cm²
INLET_BOX_BASE_AREA_CM2 = 308.0     # cm²

# ------------------------------------------------------------------
# CALIBRATION
# ------------------------------------------------------------------
# Cd for a sharp-edged orifice.  Field-calibrated value preserved from
# previous version.  Do NOT hardcode — recalibrate via calibrate_cd().
CALIBRATED_CD = 0.542

# ------------------------------------------------------------------
# INFLOW RATE
# ------------------------------------------------------------------
# Constant prototype inflow (SI: m³/s; display: mL/s == cm³/s)
INFLOW_RATE_M3S = 5.0e-5             # 50 mL/s in SI
DEFAULT_INFLOW_Q_CM3S = 50.0         # mL/s == cm³/s (legacy/UI alias)

# ------------------------------------------------------------------
# BLOCKAGE ALERT THRESHOLD (legacy simple-threshold, still used in UI)
# ------------------------------------------------------------------
BLOCKAGE_ALERT_THRESHOLD_PCT = 15.0

# ------------------------------------------------------------------
# RESIDUAL-BASED STATE MACHINE THRESHOLDS
# ------------------------------------------------------------------
# All residuals are in m/s (rate of water-level change).
# The enter threshold must be > exit threshold to prevent oscillation.
BLOCKAGE_ENTER_THRESHOLD = 2.0e-4    # residual (m/s) to enter POSSIBLE_BLOCKAGE
BLOCKAGE_EXIT_THRESHOLD = 8.0e-5     # residual (m/s) to exit back to NORMAL
BLOCKAGE_CONFIRMATION_SAMPLES = 5    # consecutive above-enter samples -> CONFIRMED
CLEAR_CONFIRMATION_SAMPLES = 8       # consecutive below-exit samples -> NORMAL
MIN_CLEARING_DURATION = 5            # min samples to stay in CLEARING before NORMAL
RESIDUAL_WINDOW_SIZE = 20            # rolling window for residual statistics

# ------------------------------------------------------------------
# SERIAL CONNECTION
# ------------------------------------------------------------------
SERIAL_PORT = "COM7"   # change to match actual port
SERIAL_BAUD = 115200

NODE_NAME = "Physical_Node_1"
