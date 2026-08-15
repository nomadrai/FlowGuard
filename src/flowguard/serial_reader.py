"""
serial_reader.py — runs continuously in its own terminal, reads live CSV from
the ESP32, and drives the reversible state machine in blockage_detector.py.

The state machine (NORMAL → POSSIBLE_BLOCKAGE → BLOCKAGE_CONFIRMED →
CLEARING → NORMAL) evaluates CURRENT hydraulic behaviour every reading.
Historical blockage events are logged to the database but never force the
current state to stay blocked after a drain clears.

Usage:
    python serial_reader.py
(port/baud are read from config.py — edit SERIAL_PORT there)
"""

import time
import serial

from blockage_detector import (
    BlockageDetectorState,
    BlockageState,
    process_reading,
    calculate_area,
    blockage_percent,
    ml_confirm_anomaly,
)
from storage import log_reading, log_blockage_event
from config import (
    SERIAL_PORT, SERIAL_BAUD, PIPE_AREA_CM2, CALIBRATED_CD,
    DEFAULT_INFLOW_Q_CM3S, INFLOW_RATE_M3S, NODE_NAME,
    SENSOR_TO_BOTTOM_M,
)

_STATE_LABELS = {
    BlockageState.NORMAL: "NORMAL — channel clear",
    BlockageState.POSSIBLE_BLOCKAGE: "POSSIBLE BLOCKAGE — monitoring",
    BlockageState.BLOCKAGE_CONFIRMED: "BLOCKAGE CONFIRMED",
    BlockageState.CLEARING: "CLEARING — drain recovering",
}


def parse_line(line: str):
    """
    Expects CSV: t_ms,distance_cm,water_level_cm
    Returns (t_ms, distance_cm, water_level_cm) or None on bad lines.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(",")
    if len(parts) != 3:
        return None
    try:
        t_ms = float(parts[0])
        distance_cm = float(parts[1])
        water_level_cm = float(parts[2])
    except ValueError:
        return None

    if distance_cm < 0 or water_level_cm < 0:
        return None

    return t_ms, distance_cm, water_level_cm


def main():
    print("FlowGuard Live Monitor — residual-based state machine active")
    print(f"Pipe area: {PIPE_AREA_CM2:.4f} cm²  |  Cd: {CALIBRATED_CD}")
    print(f"Inflow: {DEFAULT_INFLOW_Q_CM3S} mL/s  |  Sensor-to-bottom: {SENSOR_TO_BOTTOM_M*100:.2f} cm")
    print(f"Connecting to {SERIAL_PORT} @ {SERIAL_BAUD} baud...")

    ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
    time.sleep(2)
    print("Connected. Reading live data.\n")

    # One detector state object — persists across all readings so the state
    # machine and rolling windows accumulate correctly.
    det = BlockageDetectorState(cd=CALIBRATED_CD, q_in_m3s=INFLOW_RATE_M3S)

    prev_t_ms = None
    prev_state = None

    while True:
        raw_line = ser.readline().decode("utf-8", errors="ignore")
        parsed = parse_line(raw_line)
        if parsed is None:
            continue

        t_ms, distance_cm, water_level_cm = parsed

        # Convert sensor distance from cm → m for the physics engine
        distance_m = distance_cm / 100.0

        # Estimate dt; default 1 s if we can't compute it
        dt_s = (t_ms - prev_t_ms) / 1000.0 if prev_t_ms is not None else 1.0
        if dt_s <= 0 or dt_s > 60:
            dt_s = 1.0
        prev_t_ms = t_ms

        reading, current_state = process_reading(det, distance_m, dt_s)

        if reading is None:
            print(f"[t={t_ms:.0f}ms] INVALID reading (distance={distance_cm:.2f}cm) — skipped")
            continue

        # Legacy cm-based blockage % for UI/logging compatibility
        area_cm2 = calculate_area(DEFAULT_INFLOW_Q_CM3S, CALIBRATED_CD,
                                   water_level_cm)
        pct = blockage_percent(area_cm2, PIPE_AREA_CM2)

        ml_flag = ml_confirm_anomaly(det, reading)
        state_label = _STATE_LABELS[current_state]

        area_str = f"{area_cm2:.3f}" if area_cm2 is not None else "N/A"
        pct_str = f"{pct:.1f}%" if pct is not None else "N/A"
        overflow_str = " ⚠ OVERFLOW" if reading.overflow else ""

        print(
            f"[t={t_ms:.0f}ms] dist={distance_cm:.2f}cm | depth={reading.water_depth_m*100:.2f}cm "
            f"| h={reading.hydraulic_head_m*100:.2f}cm | resid={reading.residual*1000:.3f}mm/s "
            f"| area={area_str}cm² | blk={pct_str} | ML={'YES' if ml_flag else 'no'} "
            f"| STATE: {state_label}{overflow_str}"
        )

        # Log every reading to the database
        log_reading(NODE_NAME, water_level_cm, DEFAULT_INFLOW_Q_CM3S, area_cm2, pct)

        # Log a blockage event on state transitions into CONFIRMED
        if (current_state == BlockageState.BLOCKAGE_CONFIRMED and
                prev_state != BlockageState.BLOCKAGE_CONFIRMED):
            log_blockage_event(NODE_NAME, pct or 0.0, int(ml_flag), None)
            print(f"  >>> BLOCKAGE EVENT LOGGED <<<")

        prev_state = current_state


if __name__ == "__main__":
    main()
