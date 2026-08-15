"""
serial_reader.py — runs continuously in its own terminal window, separate
from the dashboard. Reads live CSV from the ESP32, computes blockage % for
every valid reading using the SAME shared config as the dashboard, and logs
each result to the database. The dashboard auto-refreshes and displays
whatever the latest logged reading is — this is what makes it "live":
place your finger over the pipe -> this script picks up the next reading
-> computes and logs blockage -> dashboard shows it within ~1-2 seconds.

Run this BEFORE opening the dashboard, and leave it running throughout
your demo, in its own terminal window.

Usage:
    python serial_reader.py
(port/baud are read from config.py — edit SERIAL_PORT there if needed)
"""

import time
import serial

from blockage_detector import calculate_area, blockage_percent
from storage import log_reading
from config import (
    SERIAL_PORT, SERIAL_BAUD, PIPE_AREA_CM2, CALIBRATED_CD,
    DEFAULT_INFLOW_Q_CM3S, NODE_NAME,
)


def parse_line(line):
    """
    Expects CSV: t_ms,distance_cm,water_level_cm
    Firmware sends "ERR" in place of a number on bad readings — float()
    will raise ValueError on that, which we catch and skip, same as any
    other malformed line (like the header/comment lines starting with '#').
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
        return None  # "ERR" reading, header line, or garbage — skip

    if distance_cm < 0 or water_level_cm < 0:
        return None  # extra safety, shouldn't trigger given the try/except above

    return t_ms, distance_cm, water_level_cm


def main():
    print(f"FlowGuard Live Monitor")
    print(f"Pipe area: {PIPE_AREA_CM2:.4f} cm^2  |  Cd: {CALIBRATED_CD}  |  Assumed inflow: {DEFAULT_INFLOW_Q_CM3S} mL/s")
    print(f"Connecting to {SERIAL_PORT} @ {SERIAL_BAUD} baud...")

    ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
    time.sleep(2)  # let ESP32 reset after serial connect
    print("Connected. Reading live data — pour water and try blocking the pipe.\n")
    print("Reminder: pour at roughly the rate set in config.py (DEFAULT_INFLOW_Q_CM3S) for accurate readings.\n")

    while True:
        raw_line = ser.readline().decode("utf-8", errors="ignore")
        parsed = parse_line(raw_line)
        if parsed is None:
            continue

        t_ms, distance_cm, water_level_cm = parsed
        h = water_level_cm

        if h <= 0:
            print(f"[t={t_ms:.0f}ms] water={h:.2f}cm — box empty/dry, no flow to analyze")
            continue

        area = calculate_area(DEFAULT_INFLOW_Q_CM3S, CALIBRATED_CD, h)
        pct = blockage_percent(area, PIPE_AREA_CM2)

        status = "CLEAR"
        if pct is not None:
            if pct > 15:
                status = "BLOCKAGE DETECTED"
            elif pct > 5:
                status = "MINOR / WITHIN NOISE"

        area_str = f"{area:.3f}" if area is not None else "N/A"
        pct_str = f"{pct:.1f}%" if pct is not None else "N/A"

        print(f"[t={t_ms:.0f}ms] distance={distance_cm:.2f}cm | water={h:.2f}cm | "
              f"area={area_str}cm^2 | blockage={pct_str} | {status}")

        # Log every reading — the dashboard reads the latest one on each auto-refresh
        log_reading(NODE_NAME, h, DEFAULT_INFLOW_Q_CM3S, area, pct)


if __name__ == "__main__":
    main()
