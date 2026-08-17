"""
serial_reader.py — the live ESP32 serial engine, usable two ways:

1. EMBEDDED IN THE DASHBOARD (the normal flow): the dashboard starts a
   SerialMonitor in a background thread (via st.cache_resource) which opens
   the port, reads live CSV from the ESP32, computes the RATE-BASED blockage
   status for every valid reading, pushes each result straight into an
   in-memory store, and logs it to the database for the audit trail. No
   polling, no database round-trip in the live path — the instant a serial
   line arrives it is parsed, classified, and visible in the dashboard.

2. STANDALONE TERMINAL (optional): `python serial_reader.py` prints the same
   stream line by line, driven by the same engine — terminal and dashboard
   can never disagree.

The printed status is RATE-BASED: it compares the current water-level rise
rate against the recently learned normal (rainfall) rise rate and flags only
unusual accelerations. The absolute water level never decides the status.

Usage (standalone):
    python serial_reader.py
(port/baud are read from config.py — edit SERIAL_PORT there if needed)
"""

import threading
import time
from collections import deque
from datetime import datetime

import serial

# pyrefly: ignore [missing-import]
from blockage_detector import (
    calculate_area, blockage_percent, detect_blockage_from_rise,
    ReferenceHeightTracker,
)
# pyrefly: ignore [missing-import]
from storage import log_reading
# pyrefly: ignore [missing-import]
from config import (
    SERIAL_PORT, SERIAL_BAUD, PIPE_AREA_CM2, CALIBRATED_CD,
    DEFAULT_INFLOW_Q_CM3S, NODE_NAME,
)

RATE_HISTORY_LEN = 60  # readings kept in memory for rise-rate estimation


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


def process_reading(t_ms, distance_cm, water_level_cm, rate_history, ref_tracker):
    """
    The per-reading engine shared by the dashboard's SerialMonitor and the
    standalone CLI: orifice physics estimate + RATE-BASED blockage verdict,
    exactly as the demo terminal has always printed them.

    Args:
        t_ms: firmware timestamp (ms)
        distance_cm: raw HC-SR04 distance (cm)
        water_level_cm: derived water level (cm)
        rate_history: deque of (t_seconds, level_cm) tuples — mutated here
        ref_tracker: ReferenceHeightTracker — mutated here

    Returns:
        dict describing the reading (status, rates, area, timestamps), or
        None when the box is empty/dry (no flow to analyze).
    """
    h = water_level_cm
    if h <= 0:
        return None  # box empty/dry, no flow to analyze

    area = calculate_area(DEFAULT_INFLOW_Q_CM3S, CALIBRATED_CD, h)
    pct = blockage_percent(area, PIPE_AREA_CM2)

    # RATE-BASED status: flag only unusual accelerations above the
    # learned normal rise rate; a falling level means the blockage
    # has been cleared. The absolute water level never decides this.
    rate_history.append((t_ms / 1000.0, h))
    ref_tracker.update(h)
    verdict = detect_blockage_from_rise(
        [w for _, w in rate_history],
        times=[t for t, _ in rate_history],
    )
    falling = verdict["current_rate"] is not None and verdict["current_rate"] <= 0
    if ref_tracker.decrease_detected or falling:
        status = "CLEAR"
        reason = "water level decreasing — blockage has been cleared/opened"
    else:
        status = "BLOCKAGE DETECTED" if verdict["verdict"] == "BLOCKAGE_DETECTED" else "CLEAR"
        reason = verdict["reason"]

    return {
        "t_ms": t_ms,
        "distance_cm": distance_cm,
        "water_level_cm": h,
        "area_cm2": area,
        "blockage_pct": pct,
        "inflow": DEFAULT_INFLOW_Q_CM3S,
        "status": status,
        "reason": reason,
        "current_rate": verdict["current_rate"],
        "baseline_rate": verdict["baseline_rate"],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "received_at": time.monotonic(),
    }


def format_cli_line(rec):
    """Render one reading exactly as the standalone terminal has always printed it."""
    t_ms = rec["t_ms"]
    distance_cm = rec["distance_cm"]
    h = rec["water_level_cm"]
    area = rec["area_cm2"]
    status = rec["status"]
    reason = rec["reason"]
    cur = rec["current_rate"]
    base = rec["baseline_rate"]
    cur_str = f"{cur:>7}" if cur is not None else "      —"
    base_str = f"{base:.4f}" if base is not None else "—"
    area_str = f"{area:.3f}" if area is not None else "N/A"
    return (f"[t={t_ms:.0f}ms] distance={distance_cm:.2f}cm | water={h:.2f}cm | "
            f"area={area_str}cm^2 | {status} "
            f"(rise {cur_str} vs baseline {base_str} cm/s | {reason})")


class SerialMonitor:
    """
    Reads live CSV from the ESP32 in a background thread and keeps the latest
    readings + RATE-BASED status in a thread-safe in-memory store.

    The dashboard embeds one of these per process (st.cache_resource), so
    every serial line is pushed straight into the store the moment it
    arrives — no polling delay, no database round-trip in the live path.
    Each valid reading is also logged to the audit-trail database.

    Thread-safety: every public accessor takes an internal lock; the store
    is only ever mutated from the reader thread.
    """

    def __init__(self, port=SERIAL_PORT, baud=SERIAL_BAUD, history_len=400,
                 retry_delay_s=2.0, reset_delay_s=2.0, on_reading=None, on_dry=None,
                 on_connect=None, on_error=None):
        self.port = port
        self.baud = baud
        self.history_len = history_len
        self.retry_delay_s = retry_delay_s
        self.reset_delay_s = reset_delay_s
        self.on_reading = on_reading   # optional: called with each processed reading dict
        self.on_dry = on_dry           # optional: called with (t_ms, water_level_cm) on dry readings
        self.on_connect = on_connect   # optional: called once the port is open
        self.on_error = on_error       # optional: called with error message on port failures

        self._lock = threading.Lock()
        self._history = deque(maxlen=history_len)
        self._latest = None
        self._version = 0
        self._error = None
        self._stop = threading.Event()
        self._thread = None
        self._rate_history = deque(maxlen=RATE_HISTORY_LEN)
        self._ref_tracker = ReferenceHeightTracker()

    def start(self):
        """Idempotent: spawns the reader thread once per monitor."""
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._run, name="flowguard-serial", daemon=True
                )
                self._thread.start()
        return self

    def stop(self):
        """Signal the reader thread to exit (daemon thread; process exit also stops it)."""
        self._stop.set()

    def snapshot(self):
        """
        Thread-safe snapshot of the current stream state.

        Returns:
            dict: latest (reading dict or None), version (increments on every
            stored reading — use to detect "new data arrived"), error (str or
            None), history_len.
        """
        with self._lock:
            return {
                "latest": self._latest,
                "version": self._version,
                "error": self._error,
                "history_len": len(self._history),
            }

    def history(self):
        """Thread-safe copy of the recent readings, oldest -> newest."""
        with self._lock:
            return list(self._history)

    def _set_error(self, message):
        with self._lock:
            self._error = message
        if self.on_error:
            self.on_error(message)

    def _handle_raw_line(self, raw_line):
        """
        Parse one raw serial line and, if valid, push the processed reading
        into the store immediately (synchronous with line arrival — this is
        the no-delay path). Invalid/dry lines are skipped (on_dry notified).
        """
        parsed = parse_line(raw_line)
        if parsed is None:
            return
        t_ms, distance_cm, water_level_cm = parsed
        rec = process_reading(
            t_ms, distance_cm, water_level_cm, self._rate_history, self._ref_tracker
        )
        if rec is None:
            if self.on_dry:
                self.on_dry(t_ms, water_level_cm)
            return
        with self._lock:
            self._history.append(rec)
            self._latest = rec
            self._version += 1
        log_reading(NODE_NAME, rec["water_level_cm"], rec["inflow"], rec["area_cm2"],
                    rec["blockage_pct"])
        if self.on_reading:
            self.on_reading(rec)

    def _run(self):
        """Reader loop: connect (retrying forever), read lines, disconnect on error, retry."""
        while not self._stop.is_set():
            try:
                ser = serial.Serial(self.port, self.baud, timeout=2)
            except (serial.SerialException, OSError, ValueError) as exc:
                self._set_error(
                    f"serial port '{self.port}' unavailable ({exc}) — "
                    f"retrying every {self.retry_delay_s}s"
                )
                self._stop.wait(self.retry_delay_s)
                continue
            time.sleep(self.reset_delay_s)  # let ESP32 reset after serial connect
            self._set_error(None)
            if self.on_connect:
                self.on_connect()
            try:
                while not self._stop.is_set():
                    raw_line = ser.readline().decode("utf-8", errors="ignore")
                    self._handle_raw_line(raw_line)
            except (serial.SerialException, OSError) as exc:
                self._set_error(f"serial read failed on '{self.port}' ({exc}) — reconnecting")
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
            self._stop.wait(self.retry_delay_s)


def main():
    print(f"FlowGuard Live Monitor")
    print(f"Pipe area: {PIPE_AREA_CM2:.4f} cm^2  |  Cd: {CALIBRATED_CD}  |  Assumed inflow: {DEFAULT_INFLOW_Q_CM3S} mL/s")
    print(f"Connecting to {SERIAL_PORT} @ {SERIAL_BAUD} baud...")

    def on_reading(rec):
        print(format_cli_line(rec))

    def on_dry(t_ms, h):
        print(f"[t={t_ms:.0f}ms] water={h:.2f}cm — box empty/dry, no flow to analyze")

    def on_connect():
        print("Connected. Reading live data — pour water and try blocking the pipe.\n")
        print("Reminder: pour at roughly the rate set in config.py (DEFAULT_INFLOW_Q_CM3S) for accurate readings.\n")

    monitor = SerialMonitor(
        on_reading=on_reading, on_dry=on_dry, on_connect=on_connect,
    ).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
        monitor.stop()


if __name__ == "__main__":
    main()
