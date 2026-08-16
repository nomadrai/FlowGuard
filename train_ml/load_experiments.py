"""
load_experiments.py — load the recorded experiments into clean DataFrames.

Expected CSV layout (e.g. train_ml/data/experiment_01.csv):

    timestamp, water_depth, event_key, state
    0.0, 0.12, NONE, CLEAR
    1.0, 0.85, NONE, CLEAR
    2.0, 1.60, BLOCKAGE_INSERTED, BLOCKAGE
    ...

    timestamp  : seconds (float) or an ISO-format datetime string
    water_depth: water depth in cm (positive; rows with invalid/ERR values drop)
    event_key  : NONE | BLOCKAGE_INSERTED | BLOCKAGE_REMOVED
    state      : CLEAR | BLOCKAGE  (written by record_experiment.py; re-derived
                 from the event keys here, so the events are the single source
                 of truth for the exact transition time)

When the state/event columns are missing entirely, the protocol of the
experiment number is used instead:

    1-4   CLEAR                     (normal rainfall, no blockage)
    5-8   BLOCKAGE                  (blockage from start to end)
    9-12  CLEAR -> BLOCKAGE -> CLEAR
    13-16 BLOCKAGE -> CLEAR

The state label is NEVER inferred from the absolute water depth — only from
the recorded events / the experiment protocol.
"""

import glob
import os

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

EVENT_NONE = "NONE"
EVENT_INSERTED = "BLOCKAGE_INSERTED"
EVENT_REMOVED = "BLOCKAGE_REMOVED"
STATE_CLEAR = "CLEAR"
STATE_BLOCKAGE = "BLOCKAGE"

# Protocol -> (start state, allowed event-key transitions). The number ranges
# are the experiment groups defined in the experiment plan (see README.md).
PROTOCOL_GROUPS = {
    "CLEAR": {"numbers": (1, 5), "start": STATE_CLEAR, "transitions": {}},
    "BLOCKAGE": {"numbers": (5, 9), "start": STATE_BLOCKAGE, "transitions": {}},
    "CLEAR_BLOCKAGE_CLEAR": {
        "numbers": (9, 13),
        "start": STATE_CLEAR,
        "transitions": {EVENT_INSERTED: STATE_BLOCKAGE, EVENT_REMOVED: STATE_CLEAR},
    },
    "BLOCKAGE_CLEAR": {
        "numbers": (13, 17),
        "start": STATE_BLOCKAGE,
        "transitions": {EVENT_REMOVED: STATE_CLEAR},
    },
}
PROTOCOLS = list(PROTOCOL_GROUPS)


def protocol_for(number):
    """Return the (start_state, transitions) dict for an experiment number."""
    for group in PROTOCOL_GROUPS.values():
        start, end = group["numbers"]
        if start <= number < end:
            return group["start"], group["transitions"]
    # Unknown experiment numbers (e.g. an unseen experiment 17) use the most
    # general event-driven behaviour: start CLEAR, switch on b/c events.
    return STATE_CLEAR, {
        EVENT_INSERTED: STATE_BLOCKAGE,
        EVENT_REMOVED: STATE_CLEAR,
    }


def derive_state(event_keys, number):
    """
    Recompute the CLEAR/BLOCKAGE state column from the event keys.

    The reading that carries a BLOCKAGE_INSERTED / BLOCKAGE_REMOVED key IS the
    first reading of the new phase — that is what makes the transition time
    exact in the data.
    """
    start, transitions = protocol_for(number)
    states = []
    current = start
    for key in event_keys:
        key = str(key).strip().upper()
        if key in transitions:
            current = transitions[key]
        states.append(current)
    return states


def _parse_timestamps_seconds(series):
    """Accept float seconds or ISO datetime strings; return seconds-since-start."""
    if len(series) == 0:
        return np.array([])
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        ts = numeric.to_numpy().astype(float)
    else:
        dt = pd.to_datetime(series, errors="coerce")
        ts = dt.astype("int64").to_numpy().astype(float) / 1e9
    finite = np.isfinite(ts)
    if finite.any():
        first = np.nanmin(ts)
        ts = np.where(finite, ts - first, 0.0)
    return ts


def _number_from_filename(path):
    digits = "".join(ch for ch in os.path.basename(path) if ch.isdigit())
    return int(digits) if digits else None


def load_experiment(path, number=None):
    """
    Load one experiment CSV into a clean DataFrame with columns
    timestamp, water_depth, event_key, state.
    """
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "timestamp" not in df.columns or "water_depth" not in df.columns:
        raise ValueError(
            f"{path}: needs at least 'timestamp' and 'water_depth' columns, "
            f"got {list(df.columns)}"
        )

    if number is None:
        number = _number_from_filename(path)

    df = df.copy()
    df["timestamp"] = _parse_timestamps_seconds(df["timestamp"])
    df["water_depth"] = pd.to_numeric(df["water_depth"], errors="coerce")
    df = df.dropna(subset=["water_depth"])
    df = df[df["water_depth"] >= 0]

    if "event_key" in df.columns:
        df["event_key"] = df["event_key"].fillna(EVENT_NONE).astype(str).str.strip().str.upper()
        df["event_key"] = df["event_key"].apply(
            lambda e: e if e in (EVENT_NONE, EVENT_INSERTED, EVENT_REMOVED) else EVENT_NONE
        )
        # Events are authoritative for the state column.
        df["state"] = derive_state(df["event_key"], number)
    elif "state" in df.columns:
        df["event_key"] = EVENT_NONE
        df["state"] = df["state"].astype(str).str.strip().str.upper()
        df["state"] = df["state"].apply(
            lambda s: s if s in (STATE_CLEAR, STATE_BLOCKAGE) else STATE_CLEAR
        )
    else:
        df["event_key"] = EVENT_NONE
        df["state"] = derive_state([EVENT_NONE] * len(df), number)

    return df.reset_index(drop=True)


def experiment_numbers(data_dir=DATA_DIR):
    """Experiment numbers present as experiment_XX.csv in the data dir."""
    numbers = []
    for path in sorted(glob.glob(os.path.join(data_dir, "experiment_*.csv"))):
        num = _number_from_filename(path)
        if num is not None:
            numbers.append(num)
    return sorted(numbers)


def load_all(data_dir=DATA_DIR, numbers=None):
    """
    Load the requested experiments as a list of (number, name, DataFrame).

    By default all experiments found in the data dir are loaded; pass
    numbers=[1, 2, ...] to load a specific subset.
    """
    if numbers is None:
        numbers = experiment_numbers(data_dir)
    if not numbers:
        raise FileNotFoundError(
            f"no experiment_*.csv files found in {data_dir} — record experiments "
            f"1-16 first (see train_ml/README.md)"
        )
    experiments = []
    for number in numbers:
        path = os.path.join(data_dir, f"experiment_{number:02d}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{path} not found — record experiment {number} first (see train_ml/README.md)"
            )
        experiments.append(
            (number, f"experiment_{number:02d}", load_experiment(path, number=number))
        )
    return experiments


if __name__ == "__main__":
    # Quick self-check: state derivation must follow the protocol rules.
    assert derive_state(["NONE"] * 3, 2) == [STATE_CLEAR] * 3
    assert derive_state(["NONE"] * 3, 6) == [STATE_BLOCKAGE] * 3
    ev = ["NONE", "BLOCKAGE_INSERTED", "NONE", "BLOCKAGE_REMOVED", "NONE"]
    assert derive_state(ev, 10) == [
        STATE_CLEAR,
        STATE_BLOCKAGE,
        STATE_BLOCKAGE,
        STATE_CLEAR,
        STATE_CLEAR,
    ]
    assert derive_state(["NONE", "NONE", "BLOCKAGE_REMOVED"], 15) == [
        STATE_BLOCKAGE,
        STATE_BLOCKAGE,
        STATE_CLEAR,
    ]
    print("load_experiments self-check passed.")
