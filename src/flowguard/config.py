"""
config.py — SINGLE SOURCE OF TRUTH for every physical constant used across
FlowGuard. Every other file imports from here instead of hardcoding its own
copy of these numbers.

WHY THIS FILE EXISTS: earlier versions had PIPE_AREA_CM2 and Cd typed
separately in blockage_detector.py, flowguard_dashboard.py, and a live
monitor script. When those copies drifted apart even slightly, it caused
a phantom "blockage" reading on a perfectly clean pipe — a real bug that
happened during development. This file makes that class of bug impossible:
change a value ONCE here, and every script picks it up automatically.
"""

import math
from pathlib import Path

# ------------------------------------------------------------------
# HARDWARE GEOMETRY (measured with a ruler)
# ------------------------------------------------------------------
PIPE_DIAMETER_CM = 1.90
PIPE_AREA_CM2 = math.pi * (PIPE_DIAMETER_CM / 2) ** 2  # = 2.8353 cm^2

INLET_BOX_BASE_AREA_CM2 = 308.0  # cm^2, rectangular inlet box / "lake"

# ------------------------------------------------------------------
# CALIBRATION (from your jug-pour test — see calibrate_cd() in blockage_detector.py)
# ------------------------------------------------------------------
CALIBRATED_CD = 0.542

# ------------------------------------------------------------------
# ASSUMED LIVE INFLOW RATE (mL/s == cm^3/s)
# ------------------------------------------------------------------
# During a live demo, you pour water into the inlet box at roughly this
# steady rate. The blockage calculation assumes this is the current real
# inflow — for accurate results, you MUST pour at approximately this rate.
#
# IMPORTANT — verify this matches YOUR real pour rate before trusting any
# readings: with your pipe area (2.8353 cm^2) and Cd (0.542), too slow a
# pour gives water heights under 1mm — far below what an HC-SR04 can
# reliably measure (noise floor ~0.2-0.3cm even with filtering), making
# blockage % meaningless. 100-150 mL/s (a fast, steady stream — roughly a
# 500mL bottle emptied in 3-5 seconds) gives clean-pipe heights of 2-5cm,
# comfortably measurable. Test with a jug + stopwatch: pour a measured
# volume at your intended demo speed, time it, confirm volume/time lands
# in this range before setting this constant.
DEFAULT_INFLOW_Q_CM3S = 120.0

# ------------------------------------------------------------------
# BLOCKAGE ALERT THRESHOLD
# ------------------------------------------------------------------
BLOCKAGE_ALERT_THRESHOLD_PCT = 15.0  # above this % => "BLOCKAGE DETECTED"

# ------------------------------------------------------------------
# SERIAL CONNECTION (edit SERIAL_PORT to match your ESP32's actual port)
# ------------------------------------------------------------------
SERIAL_PORT = "COM7"  # <-- CHANGE THIS to your actual port (Tools -> Port in Arduino IDE)
SERIAL_BAUD = 115200

NODE_NAME = "Physical_Node_1"

# ------------------------------------------------------------------
# TRAINED ML MODEL (artifacts produced by the train_ml pipeline)
# ------------------------------------------------------------------
# The dashboard's ML confirmation layer loads the RandomForest +
# expected-rate model trained on the 16 recorded experiments. Paths
# resolve relative to the repo root so retrained artifacts are picked
# up automatically (no copying required).
REPO_ROOT = Path(__file__).resolve().parents[2]
ML_MODELS_DIR = str(REPO_ROOT / "train_ml" / "models")

# ML confirmation requires the trained model to flag BLOCKAGE for a
# MAJORITY of the last N readings — per-reading predictions chatter
# (experiment 17 flips ~20 times over 88 readings), the window steadies it.
ML_CONFIRM_WINDOW = 5
