"""
make_synthetic_experiments.py — OPTIONAL smoke-test data generator.

Generates physically plausible stand-ins for experiments 1-16 (and optionally
17) so the whole pipeline can be smoke-tested BEFORE real hardware recording:

  - the container widens with depth:  area(h) = 308 + 40*h cm^2
  - rainfall inflow Q fills the box while the pipe drains via the orifice
    equation:  Q_out = Cd * A_pipe * sqrt(2*g*h)
  - normal rise rate therefore decreases with depth (the exact behaviour the
    expected-rate model must learn)
  - a blockage scales Q_out by (1 - blockage_fraction), so the level rises
    faster and settles higher
  - HC-SR04-scale noise (+/-~0.3 cm) is added to every reading

The output files are valid experiment CSVs (timestamp, water_depth,
event_key, state) with the same protocol structure as real recordings.

Usage:
    python train_ml/make_synthetic_experiments.py            # writes experiments 1-16
    python train_ml/make_synthetic_experiments.py --extra 17 # also writes exp 17
    python train_ml/make_synthetic_experiments.py --out train_ml/data_synthetic
"""

import argparse
import os

import numpy as np
import pandas as pd
from load_experiments import (
    DATA_DIR,
    EVENT_INSERTED,
    EVENT_NONE,
    EVENT_REMOVED,
    PROTOCOL_GROUPS,
)

G = 981.0  # cm/s^2
PIPE_AREA_CM2 = 2.8353  # cm^2
CD = 0.542
BASE_AREA_CM2 = 308.0  # cm^2 at depth 0
WIDENING_CM2_PER_CM = 40.0
BLOCKAGE_FRACTION = 0.5  # blockage closes 50% of the outflow area (finger over the pipe)
SENSOR_NOISE_CM = 0.08  # HC-SR04 spec +/-0.3 cm -> std ~0.08-0.1
SEED = 42


def protocol_name_for(number):
    for name, group in PROTOCOL_GROUPS.items():
        start, end = group["numbers"]
        if start <= number < end:
            return name
    return "CLEAR"


def simulate(q, duration_s, events, seed, protocol, blockage_fraction=BLOCKAGE_FRACTION):
    """
    Euler-integrate the box level, one reading per second.

    events: list of (time_s, event_key) in chronological order.
    Returns (timestamps, depths, event_keys, states).
    """
    rng = np.random.default_rng(seed)
    outflow_factor = 1.0  # 1 = clear pipe, (1 - fraction) = blocked
    transitions = PROTOCOL_GROUPS[protocol]["transitions"]
    state = PROTOCOL_GROUPS[protocol]["start"]

    h = 0.4
    timestamps, depths, keys, states = [0.0], [h], [EVENT_NONE], [state]
    next_event = 0

    for t in range(1, duration_s):
        fired = False
        while next_event < len(events) and events[next_event][0] <= t:
            ev = events[next_event][1]
            if ev == EVENT_INSERTED:
                outflow_factor = 1.0 - blockage_fraction
            elif ev == EVENT_REMOVED:
                outflow_factor = 1.0
            if ev in transitions:
                state = transitions[ev]
            keys.append(ev)
            states.append(state)
            next_event += 1
            fired = True
        if not fired:  # no event fired this second
            keys.append(EVENT_NONE)
            states.append(state)

        outflow = CD * PIPE_AREA_CM2 * np.sqrt(max(2.0 * G * h, 0.0)) * outflow_factor
        area = BASE_AREA_CM2 + WIDENING_CM2_PER_CM * h
        h = max(0.0, h + (q - outflow) / area + rng.normal(0, SENSOR_NOISE_CM))
        timestamps.append(float(t))
        depths.append(h)

    return np.array(timestamps), np.array(depths), keys, states


def experiment_spec(number, rng):
    """Inflow rate, duration and event times for one experiment."""
    q = float(rng.uniform(100.0, 140.0))
    duration = int(rng.integers(180, 260))
    if number in range(1, 5):  # CLEAR
        return q, duration, []
    if number in range(5, 9):  # BLOCKAGE start -> end
        return q, duration, [(1, EVENT_INSERTED)]
    if number in range(9, 13):  # CLEAR -> BLOCKAGE -> CLEAR
        t_insert = int(rng.integers(int(0.35 * duration), int(0.45 * duration)))
        t_remove = int(rng.integers(int(0.65 * duration), int(0.75 * duration)))
        return q, duration, [(t_insert, EVENT_INSERTED), (t_remove, EVENT_REMOVED)]
    if number in range(13, 17):  # BLOCKAGE -> CLEAR
        t_remove = int(rng.integers(int(0.5 * duration), int(0.7 * duration)))
        return q, duration, [(1, EVENT_INSERTED), (t_remove, EVENT_REMOVED)]
    raise ValueError(f"experiment number {number} outside 1-16")


def write_experiment(number, out_dir, protocol=None, events=None):
    rng = np.random.default_rng(SEED + number)
    if number in range(1, 17):
        q, duration, events = experiment_spec(number, rng)
        protocol = protocol_name_for(number)
    else:
        # Extra experiment (e.g. 17): an unseen CLEAR->BLOCKAGE->CLEAR case.
        protocol = protocol or "CLEAR_BLOCKAGE_CLEAR"
        q = float(rng.uniform(100.0, 140.0))
        duration = int(rng.integers(200, 280))
        if events is None:
            t_insert = int(rng.integers(int(0.35 * duration), int(0.45 * duration)))
            t_remove = int(rng.integers(int(0.65 * duration), int(0.75 * duration)))
            events = [(t_insert, EVENT_INSERTED), (t_remove, EVENT_REMOVED)]

    t, depth, keys, states = simulate(q, duration, events, SEED + number, protocol)
    df = pd.DataFrame(
        {"timestamp": t, "water_depth": np.round(depth, 3), "event_key": keys, "state": states}
    )
    path = os.path.join(out_dir, f"experiment_{number:02d}.csv")
    df.to_csv(path, index=False)
    print(f"wrote {path}  ({len(df)} readings, Q={q:.0f} mL/s, protocol={protocol})")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic smoke-test experiments")
    parser.add_argument("--out", default=DATA_DIR)
    parser.add_argument(
        "--extra", type=int, default=None, help="also write an extra experiment number (e.g. 17)"
    )
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for number in range(1, 17):
        write_experiment(number, args.out)
    if args.extra is not None:
        write_experiment(args.extra, args.out)
    print("\nDone. Delete these files before recording real experiments.")


if __name__ == "__main__":
    main()
