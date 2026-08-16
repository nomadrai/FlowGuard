"""
record_experiment.py — record live experiments 1-16 from the ESP32 serial.

Writes train_ml/data/experiment_XX.csv with columns:

    timestamp, water_depth, event_key, state

EVENT KEYS — press a single key and it is stamped onto the NEXT sensor
reading, so the exact transition time is captured in the data:

    b  ->  BLOCKAGE_INSERTED   (you just inserted the blockage)
    c  ->  BLOCKAGE_REMOVED    (you just removed it)
    q  ->  quit (Ctrl-C also works)

The state column is derived automatically from the events and the protocol:

    CLEAR                  : always CLEAR                       (exps 1-4)
    BLOCKAGE               : always BLOCKAGE                    (exps 5-8)
    CLEAR_BLOCKAGE_CLEAR   : CLEAR -> (b) BLOCKAGE -> (c) CLEAR (exps 9-12)
    BLOCKAGE_CLEAR         : BLOCKAGE -> (c) CLEAR              (exps 13-16)

Usage (live serial, reuse the same parsing as serial_reader.py):
    python train_ml/record_experiment.py --experiment 5 --protocol BLOCKAGE
    python train_ml/record_experiment.py --experiment 9 --protocol CLEAR_BLOCKAGE_CLEAR

Manual mode (paste readings from the Serial Monitor / Arduino IDE instead of
opening the live serial port — type a number for a reading, b/c/q for keys):
    python train_ml/record_experiment.py --experiment 1 --protocol CLEAR --manual
"""

import argparse
import os
import sys
import time

from load_experiments import (
    DATA_DIR,
    EVENT_INSERTED,
    EVENT_NONE,
    EVENT_REMOVED,
    PROTOCOL_GROUPS,
    PROTOCOLS,
)

# Reuse serial_reader's proven CSV-line parser (t_ms,distance_cm,water_level_cm).
# serial_reader imports `serial` (pyserial); if pyserial is missing the live
# serial mode cannot run, but manual mode still works.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "flowguard")
)
try:
    from serial_reader import parse_line
except ImportError:  # pragma: no cover - fallback when pyserial is unavailable

    def parse_line(line):
        """Local copy of serial_reader.parse_line (kept in sync)."""
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


class ExperimentLogger:
    """Holds the recording state and writes rows to the experiment CSV."""

    def __init__(self, out_path, protocol):
        self.out_path = out_path
        self.protocol = protocol
        self.state = PROTOCOL_GROUPS[protocol]["start"]
        self.transitions = PROTOCOL_GROUPS[protocol]["transitions"]
        self.pending_event = None
        self.n_rows = 0

    def __enter__(self):
        os.makedirs(os.path.dirname(self.out_path), exist_ok=True)
        self._f = open(self.out_path, "w")
        self._f.write("timestamp,water_depth,event_key,state\n")
        return self

    def __exit__(self, *exc):
        self._f.close()

    def set_event(self, key):
        """Queue an event key; it is stamped onto the next reading."""
        if key == "b":
            self.pending_event = EVENT_INSERTED
            print(">>> BLOCKAGE_INSERTED queued for the next reading")
        elif key == "c":
            self.pending_event = EVENT_REMOVED
            print(">>> BLOCKAGE_REMOVED queued for the next reading")
        else:
            print(">>> unknown key — use b / c / q")

    def log(self, timestamp, water_depth):
        """Write one reading (cm). The queued event, if any, is consumed here."""
        event = self.pending_event if self.pending_event is not None else EVENT_NONE
        self.pending_event = None
        if event in self.transitions:
            self.state = self.transitions[event]
        self._f.write(f"{timestamp:.3f},{water_depth:.3f},{event},{self.state}\n")
        self._f.flush()
        self.n_rows += 1
        print(
            f"[t={timestamp:8.3f}s] depth={water_depth:6.2f} cm | "
            f"event={event:<20s} | state={self.state}"
        )


def poll_key():
    """Return a pressed key (lowercased) or None — non-blocking, cross-platform.

    Windows: msvcrt.kbhit() (select.select cannot poll stdin on Windows —
    WinError 10038).
    POSIX: select on sys.stdin.
    """
    if sys.platform == "win32":
        import msvcrt

        if msvcrt.kbhit():
            ch = msvcrt.getwch().lower()
            if ch in ("\x00", "\xe0"):  # arrow/function-key prefix
                return None
            print(ch, end="", flush=True)  # getwch does not echo the key
            return ch
        return None
    import select

    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.readline().strip().lower()
    return None


def record_serial(ser, logger):
    """Live serial mode: read ESP32 CSV lines, react to b/c/q keypresses."""
    print("Live serial recording. Press  b=insert blockage  c=remove blockage  q=quit\n")
    while True:
        key = poll_key()
        if key is not None:
            if key.startswith("q"):
                print("\nQuitting.")
                return
            logger.set_event(key[0])
        raw = ser.readline()
        if not raw:
            continue
        parsed = parse_line(raw.decode("utf-8", errors="ignore"))
        if parsed is None:
            continue
        t_ms, _distance_cm, water_level_cm = parsed
        if water_level_cm <= 0:
            print(f"[t={t_ms:.0f}ms] box dry/empty — skipped")
            continue
        logger.log(t_ms / 1000.0, water_level_cm)


def record_manual(logger):
    """Manual mode: type a reading (cm), or b / c / q on its own line."""
    print(
        "Manual recording — paste a water depth per line; b/c/q for events. "
        "Ctrl-C or q to quit.\n"
    )
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nQuitting.")
            return
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("q"):
            print("Quitting.")
            return
        if lowered.startswith("b") or lowered.startswith("c"):
            logger.set_event(lowered[0])
            continue
        try:
            depth = float(line)
        except ValueError:
            print(f"'{line}' is not a number, b, c or q")
            continue
        logger.log(time.time(), depth)


def main():
    parser = argparse.ArgumentParser(description="Record a FlowGuard experiment (1-16)")
    parser.add_argument("--experiment", type=int, default=1, help="experiment number 1-16")
    parser.add_argument(
        "--protocol",
        choices=PROTOCOLS,
        default="CLEAR",
        help="experiment protocol (state machine for the b/c keys)",
    )
    parser.add_argument("--out", default=DATA_DIR, help="output directory for the CSV")
    parser.add_argument("--port", default=None, help="serial port (default: config.py SERIAL_PORT)")
    parser.add_argument("--baud", type=int, default=115200, help="serial baud rate")
    parser.add_argument(
        "--manual", action="store_true", help="manual paste mode instead of live serial"
    )
    args = parser.parse_args()

    if not 1 <= args.experiment <= 16:
        raise SystemExit("--experiment must be 1-16 (the experiment plan has 16 experiments)")

    out_path = os.path.join(args.out, f"experiment_{args.experiment:02d}.csv")
    logger = ExperimentLogger(out_path, args.protocol)

    with logger:
        if args.manual:
            record_manual(logger)
        else:
            try:
                import serial
            except ImportError:
                raise SystemExit(
                    "pyserial is not installed — run `pip install -e .` first, "
                    "or use --manual mode"
                )
            from config import SERIAL_PORT

            port = args.port or SERIAL_PORT
            print(f"Connecting to {port} @ {args.baud} baud ...")
            with serial.Serial(port, args.baud, timeout=1) as ser:
                time.sleep(2)  # let the ESP32 reset after serial connect
                try:
                    record_serial(ser, logger)
                except KeyboardInterrupt:
                    print("\nQuitting.")

    print(f"\nRecorded {logger.n_rows} readings -> {out_path}")


if __name__ == "__main__":
    main()
