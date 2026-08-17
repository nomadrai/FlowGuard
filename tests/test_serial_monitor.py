"""
Tests for serial_reader.py — the live ESP32 serial engine (SerialMonitor +
process_reading).

Proves the no-artificial-delay contract:
- a processed reading lands in the in-memory store synchronously with line
  arrival (no timers, no DB round-trip in the push path);
- the background thread's line -> store latency is sub-100ms;
- history is bounded, callbacks fire, and port failures surface an error
  state that clears on reconnect.

The real database is never touched (log_reading is monkeypatched away).
"""
import sys
import os
import time
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'flowguard'))

import serial

# pyrefly: ignore [missing-import]
import serial_reader


class FakeSerial:
    """Stand-in for pyserial: configurable open failure, lines fed from a queue."""

    instances = []
    fail_open = False

    def __init__(self, port, baud, timeout=2):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.lines = deque()
        self.closed = False
        FakeSerial.instances.append(self)
        if FakeSerial.fail_open:
            raise serial.SerialException("fake: port busy")

    def readline(self):
        if self.lines:
            return self.lines.popleft()
        time.sleep(0.005)
        return b""

    def close(self):
        self.closed = True


def _noop(*args, **kwargs):
    return None


def _wait_for(predicate, timeout=2.0, interval=0.01):
    """Poll `predicate` until truthy or the deadline passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _make_monitor(monkeypatch, **kwargs):
    monkeypatch.setattr(serial_reader, "log_reading", _noop)
    return serial_reader.SerialMonitor(**kwargs)


def _feed_lines(monitor, lines):
    for line in lines:
        monitor._handle_raw_line(line)


# ---------------------------------------------------------------
# process_reading — the shared per-reading engine
# ---------------------------------------------------------------

def test_process_reading_dry_returns_none():
    rec = serial_reader.process_reading(1000, 5.0, 0.0, deque(), serial_reader.ReferenceHeightTracker())
    assert rec is None


def test_process_reading_early_data_is_clear():
    tracker = serial_reader.ReferenceHeightTracker()
    rate_history = deque()
    recs = [
        serial_reader.process_reading(i * 1000, 5.0, 1.0 + 0.3 * i, rate_history, tracker)
        for i in range(15)
    ]
    assert all(r is not None for r in recs)
    assert recs[-1]["status"] == "CLEAR"
    assert recs[-1]["current_rate"] is None  # baseline not yet established
    assert recs[-1]["area_cm2"] is not None
    assert recs[-1]["blockage_pct"] is not None


def test_process_reading_acceleration_flags_blockage_then_clear():
    tracker = serial_reader.ReferenceHeightTracker()
    rate_history = deque()
    statuses = []
    for i in range(30):  # steady rainfall rise ~0.3 cm/s
        h = 1.0 + 0.3 * i
        rec = serial_reader.process_reading(i * 1000, 5.0, h, rate_history, tracker)
        statuses.append(rec["status"])
    assert statuses[-1] == "CLEAR"
    for j in range(10):  # blockage: rise accelerates to ~1.5 cm/s
        h = 1.0 + 0.3 * 29 + 1.5 * (j + 1)
        rec = serial_reader.process_reading((30 + j) * 1000, 5.0, h, rate_history, tracker)
        statuses.append(rec["status"])
    assert statuses[-1] == "BLOCKAGE DETECTED"
    for k in range(10):  # blockage cleared: water falls
        h = 24.7 - 0.5 * (k + 1)
        rec = serial_reader.process_reading((40 + k) * 1000, 5.0, h, rate_history, tracker)
        statuses.append(rec["status"])
    assert statuses[-1] == "CLEAR"


# ---------------------------------------------------------------
# SerialMonitor — the in-memory push store
# ---------------------------------------------------------------

def test_monitor_pushes_synchronously_no_timers(monkeypatch):
    monitor = _make_monitor(monkeypatch)
    assert monitor.snapshot()["latest"] is None
    assert monitor.snapshot()["version"] == 0

    t0 = time.monotonic()
    monitor._handle_raw_line("1000,5.0,2.0\n")
    elapsed = time.monotonic() - t0

    snap = monitor.snapshot()
    assert snap["version"] == 1
    assert snap["latest"]["water_level_cm"] == 2.0
    assert snap["latest"]["status"] == "CLEAR"
    assert snap["error"] is None
    assert elapsed < 0.05  # push happens inside the same call — zero delay


def test_monitor_skips_garbage_and_dry(monkeypatch):
    dry_calls = []
    monitor = _make_monitor(monkeypatch, on_dry=lambda t, h: dry_calls.append((t, h)))
    monitor._handle_raw_line("# header line\n")
    monitor._handle_raw_line("1,ERR,3.0\n")
    monitor._handle_raw_line("2,5.0,0.0\n")
    assert monitor.snapshot()["version"] == 0
    assert dry_calls == [(2.0, 0.0)]


def test_monitor_history_is_bounded(monkeypatch):
    monitor = _make_monitor(monkeypatch, history_len=3)
    _feed_lines(monitor, [f"{i},5.0,2.0\n" for i in range(5)])
    assert len(monitor.history()) == 3
    assert monitor.snapshot()["history_len"] == 3
    assert monitor.history()[-1]["t_ms"] == 4.0  # newest retained


def test_monitor_callbacks(monkeypatch):
    received = []
    monitor = _make_monitor(monkeypatch, on_reading=received.append)
    monitor._handle_raw_line("1000,5.0,2.0\n")
    assert len(received) == 1
    assert received[0]["status"] == "CLEAR"


def test_monitor_thread_line_to_store_latency(monkeypatch):
    """End-to-end through the real reader thread: a written serial line must
    land in the store almost immediately (no buffering, no polling)."""
    monkeypatch.setattr(serial_reader, "log_reading", _noop)
    monkeypatch.setattr(serial_reader.serial, "Serial", FakeSerial)
    FakeSerial.instances.clear()
    FakeSerial.fail_open = False

    monitor = serial_reader.SerialMonitor(port="FAKE", reset_delay_s=0.0).start()
    try:
        assert _wait_for(lambda: FakeSerial.instances)  # thread opened the port
        ser = FakeSerial.instances[0]
        ser.lines.append(b"1000,5.0,2.0\n")
        assert _wait_for(lambda: monitor.snapshot()["version"] >= 1)

        # Measure line -> store latency with a fresh reading.
        latencies = []
        for i in range(5):
            t0 = time.monotonic()
            version_before = monitor.snapshot()["version"]
            ser.lines.append(f"{2000 + i},5.0,2.0\n".encode())
            assert _wait_for(lambda: monitor.snapshot()["version"] > version_before, timeout=1.0)
            latencies.append(time.monotonic() - t0)
        assert max(latencies) < 0.1, f"line->store latency too high: {latencies}"
    finally:
        monitor.stop()


def test_monitor_surfaces_error_and_recovers(monkeypatch):
    monkeypatch.setattr(serial_reader, "log_reading", _noop)
    monkeypatch.setattr(serial_reader.serial, "Serial", FakeSerial)
    FakeSerial.instances.clear()

    FakeSerial.fail_open = True
    monitor = serial_reader.SerialMonitor(
        port="FAKE", retry_delay_s=0.05, reset_delay_s=0.0,
    ).start()
    try:
        assert _wait_for(lambda: monitor.snapshot()["error"] is not None), "error state missing"
        assert "unavailable" in monitor.snapshot()["error"]

        FakeSerial.fail_open = False  # cable plugged back in
        assert _wait_for(lambda: monitor.snapshot()["error"] is None), "error never cleared"
        assert _wait_for(lambda: FakeSerial.instances)

        ser = FakeSerial.instances[-1]
        ser.lines.append(b"1000,5.0,2.0\n")
        assert _wait_for(lambda: monitor.snapshot()["version"] >= 1)
    finally:
        monitor.stop()
