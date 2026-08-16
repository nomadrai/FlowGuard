# FlowGuard ML Training Pipeline (`train_ml/`)

A self-contained ML training pipeline for FlowGuard's drain-blockage detection.
It is **completely separate** from the live sensor path (`serial_reader.py`),
the dashboard, and the SQLite audit trail — it only reads/creates CSV files in
this folder. Nothing here touches the hardware or the dashboard.

**Core idea:** the inlet container widens with depth, so the normal water-rise
rate is **not** a constant. The pipeline learns

```
expected_rise_rate = f(water_depth)
```

from experiments 1–4 (normal rainfall, no blockage) and trains models on

```
rate_deviation = actual_rise_rate - expected_rise_rate
```

- normal rise → `CLEAR`
- unusually faster rise (positive deviation) → `BLOCKAGE`
- water falling / back to normal → `CLEAR`

The absolute water depth is **never** a threshold.

---

## 1. Directory layout

```
train_ml/
├── README.md                       this file
├── record_experiment.py            record experiments 1-16 (serial or manual)
├── load_experiments.py             CSV loader + state/event derivation
├── expected_rate.py                learns expected_rise_rate = f(water_depth)
├── features.py                     per-reading features (rate, deviation, ...)
├── train.py                        train + save models (RandomForest + IsolationForest)
├── evaluate.py                     whole-experiment evaluation (leave-one-out CV)
├── predict_experiment.py           test an unseen experiment, no retraining
├── make_synthetic_experiments.py   OPTIONAL smoke-test data (no hardware needed)
├── data/                           <-- experiment_01.csv ... experiment_16.csv
│   └── .gitkeep                    (git-ignored, so nothing real is committed)
├── models/                         trained model artifacts (git-ignored)
└── predictions/                    prediction plots for unseen experiments
```

---

## 2. The experiment plan (16 experiments)

| #   | Protocol               | Meaning                                        |
|-----|------------------------|------------------------------------------------|
| 1–4   | `CLEAR`                | normal rainfall, no blockage                   |
| 5–8   | `BLOCKAGE`             | blockage from start to end                     |
| 9–12  | `CLEAR_BLOCKAGE_CLEAR` | clear → blockage → clear                       |
| 13–16 | `BLOCKAGE_CLEAR`       | blockage → clear                               |

Each experiment is one CSV file with at least `timestamp, water_depth`, plus
the `event_key` and `state` columns (the recorder writes all four):

```
timestamp,water_depth,event_key,state
0.000,0.42,NONE,CLEAR
1.000,0.90,NONE,CLEAR
2.000,1.55,BLOCKAGE_INSERTED,BLOCKAGE
...
```

- `timestamp`  — seconds (float), or an ISO datetime string (auto-parsed)
- `water_depth`— cm (positive; `ERR`/invalid rows are dropped on load)
- `event_key`  — `NONE` | `BLOCKAGE_INSERTED` | `BLOCKAGE_REMOVED`
- `state`      — `CLEAR` | `BLOCKAGE` (re-derived from the events on load, so
  the events are the single source of truth for transition times)

The loader also accepts bare `timestamp,water_depth` files — the state is then
inferred from the experiment number's protocol.

---

## 3. How `b` / `c` event logging works

`record_experiment.py` reads live sensor readings and, while recording, watches
your keyboard. Press **`b`** when you insert the blockage and **`c`** when you
remove it. The key is queued and **stamped onto the next sensor reading**, so
the CSV records the exact reading at which the state changed:

```
b  ->  event_key = BLOCKAGE_INSERTED   (that reading is the start of BLOCKAGE)
c  ->  event_key = BLOCKAGE_REMOVED    (that reading is the start of CLEAR)
q  ->  quit (Ctrl-C also works)
```

The `state` column is derived automatically from the protocol + events, so
there is no state you can forget to maintain while pouring water.

### Live serial recording

```bash
python train_ml/record_experiment.py --experiment 5 --protocol BLOCKAGE
python train_ml/record_experiment.py --experiment 9 --protocol CLEAR_BLOCKAGE_CLEAR
```

(reads the ESP32 the same way `serial_reader.py` does; `--port`/`--baud`
override `config.py`.)

### Manual paste mode (no live serial)

Paste readings from the Arduino IDE Serial Monitor instead — one number per
line, `b`/`c`/`q` on their own lines:

```bash
python train_ml/record_experiment.py --experiment 1 --protocol CLEAR --manual
```

> Tip: it is fine to record more readings than needed (2–5 minutes each).
> If you make a mistake, just re-record that experiment — the file is
> overwritten.

---

## 4. Where to put the CSV files

The pipeline expects `train_ml/data/experiment_01.csv` … `experiment_16.csv`.
`record_experiment.py` writes them there automatically (`--out` changes the
directory). For an extra/unseen experiment simply drop the file in the same
directory, e.g. `train_ml/data/experiment_17.csv`.

---

## 5. Training

```bash
source .venv/bin/activate
pip install -e ".[analysis]"     # once: adds joblib/pyserial/matplotlib

python train_ml/train.py
```

What it does:

1. loads experiments 1–16 from `train_ml/data/`,
2. computes per-reading features: `water_depth, rate, smoothed_rate,
   rate_change, expected_rate, rate_deviation`,
3. learns `expected_rise_rate = f(water_depth)` from experiments **1–4 only**,
4. trains **RandomForestClassifier** (main model, class-balanced) and
   **Isolation Forest** (existing baseline) on all 16 experiments,
5. saves to `train_ml/models/`:

```
expected_rate_model.joblib   the depth-dependent normal rise rate
random_forest.joblib         main supervised model (BLOCKAGE vs CLEAR)
isolation_forest.joblib      baseline anomaly detector
model_meta.json              feature columns + metadata
```

The console output shows the learned expected-rate curve (depth → normal
cm/s) and the RandomForest feature importances.

---

## 6. Evaluation (whole experiments, not random rows)

```bash
python train_ml/evaluate.py
```

Rows inside one experiment are autocorrelated, so evaluating on random rows
would be cheating. Instead this runs **leave-one-experiment-out cross
validation**: each of the 16 experiments is held out *entirely*, the models
are trained on the other 15, and the whole held-out experiment is predicted.
Output:

- a per-experiment table and macro **Accuracy, Precision, Recall, F1**
  (BLOCKAGE is the positive class),
- `train_ml/evaluation_predictions.png` — for every experiment: water depth,
  true state (dashed) and predicted state (solid) over time,
- the **final** models retrained on all 16 experiments and re-saved to
  `train_ml/models/`.

---

## 7. Testing an unseen experiment (no retraining)

```bash
python train_ml/predict_experiment.py --experiment 17
# or, for a file anywhere on disk:
python train_ml/predict_experiment.py --file path/to/experiment_17.csv
```

Loads the saved models, computes the same features, and predicts
`CLEAR`/`BLOCKAGE` for every reading of the new experiment. If the CSV
carries a `state` column you also get Accuracy/Precision/Recall/F1; the
prediction plot is saved to `train_ml/predictions/experiment_17_prediction.png`
and the console shows how many times the prediction changed state.

---

## 8. What each output means

| Output | Meaning |
|---|---|
| `expected_rate_model.joblib` | learned `expected_rise_rate(depth)` — the normal, no-blockage rise rate at each depth (cm/s) |
| `random_forest.joblib` | main model; predicts BLOCKAGE when rate features deviate from the depth-expected behaviour |
| `isolation_forest.joblib` | baseline; flags unusual rate-behaviour patterns (same algorithm family as the dashboard's ML confirmation layer) |
| `evaluation_predictions.png` | true vs predicted state per experiment — where the model is wrong at a glance |
| per-experiment table | accuracy/precision/recall/F1 per held-out experiment + macro averages |
| `predictions/experiment_XX_prediction.png` | prediction timeline for one unseen experiment |

Metrics are always for the `BLOCKAGE` class: Precision = of all readings the
model called BLOCKAGE, how many really were; Recall = of all really-blocked
readings, how many the model caught; F1 = their harmonic mean.

---

## 9. Smoke test without hardware

```bash
python train_ml/make_synthetic_experiments.py            # writes experiments 1-16
python train_ml/make_synthetic_experiments.py --extra 17 # also an unseen exp 17
python train_ml/train.py
python train_ml/evaluate.py
python train_ml/predict_experiment.py --experiment 17
```

**Delete the synthetic CSVs before recording real experiments** — they share
the same filenames and would be silently overwritten by
`record_experiment.py` anyway, but don't confuse them with real data.

---

## 10. Troubleshooting

- **`no experiment_*.csv files found`** → record experiments 1–16 first (section 3).
- **`pyserial is not installed`** → `pip install -e .` (live serial mode);
  `--manual` mode never needs it.
- **Missing `expected_rate_model.joblib`** → run `python train_ml/train.py`
  before `predict_experiment.py`.
- **Expected-rate curve looks flat** → too few clean (depth, rate) samples;
  record longer experiments 1–4 spanning a wider depth range.