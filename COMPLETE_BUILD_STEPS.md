# FlowGuard — Complete Build Guide (Continuing From Your Working Sensor)

You've already completed: ESP32 + HC-SR04 wired correctly, real calibrated water-level readings streaming in Serial Monitor. This guide takes you from there to the complete system.

---

## Step 1 — Install the Python packages you'll need

```
pip install numpy pandas scikit-learn streamlit
```

---

## Step 2 — Get all 4 files into one folder

Put these together in your project folder:
`blockage_detector.py`, `network_simulation.py`, `storage.py`, `flowguard_dashboard.py`

---

## Step 3 — Test the physics + ML core standalone (no dashboard yet)

```
python blockage_detector.py
```

This runs self-tests with example numbers and should print, without any errors:
- A calibrated Cd value
- A clean-channel test showing ~0% blockage
- A blocked-channel test showing a clear positive blockage %
- ML confirmation correctly distinguishing a normal noisy window from a genuinely rising-blockage window
- A trend forecast estimating days until critical blockage

✅ Checkpoint: all of the above prints with no errors. This proves the physics and ML logic are correct before you touch real hardware data.

---

## Step 4 — Test the network cascade simulation standalone

```
python network_simulation.py
```

This builds a small Ambazari Lake → Nag River network and simulates a rainfall pulse propagating through it. You should see, for each downstream node, the peak arrival time getting **later** and the peak magnitude getting **lower** — this is correct, expected hydrological behavior (the flood wave delays and smooths out as it travels).

✅ Checkpoint: "Peak arrival times are non-decreasing downstream: True" printed at the end.

---

## Step 5 — Calibrate Cd on your REAL physical channel

Do the jug-pour experiment from earlier:
1. Measure a known volume of water (e.g. 500 mL).
2. Time how long it takes to pour it into your channel at a steady rate.
3. Read the steady-state water height your sensor shows once it stabilizes.
4. Measure your channel's known clean cross-sectional area with a ruler (width × depth of the opening).
5. Repeat 3 times, note all 3 sets of numbers.

Write down your 4 numbers (average across your 3 trials): pour volume, pour time, steady height, clean area.

---

## Step 6 — Launch the full dashboard

```
streamlit run flowguard_dashboard.py
```

In the sidebar:
1. Enter your 4 calibration numbers from Step 5.
2. Click **"Calibrate Cd"** — you should see your calculated Cd value appear.

---

## Step 7 — Feed in real readings

For each live reading from your Serial Monitor:
1. Note the current inflow rate (how fast you're pouring — measure this the same way as calibration: volume ÷ time)
2. Note the current water height reading from Serial Monitor
3. Enter both numbers in the dashboard's "Physical Node" section, click **"Submit reading"**

Do this multiple times:
- A few times with a **clean channel** (varying your pour rate a little each time) — this builds your baseline
- Then insert your **sponge obstruction**, pour again, and submit more readings

✅ Checkpoint: after ~15-20 total readings (mix of clean and blocked), the dashboard should show a rising blockage % once you're pouring through the obstruction, and after enough readings accumulate, the ML confirmation should start correctly flagging the blocked readings as "ML-CONFIRMED" rather than just a single noisy point.

---

## Step 8 — Run the network cascade simulation in the dashboard

In the "Network Cascade" section:
1. Adjust the rainfall intensity slider.
2. Click **"Run network simulation"**.
3. You'll see a chart showing the rainfall pulse and how each downstream node's outflow is delayed and smoothed — this is your citywide story, completing the picture around your one real node.

---

## Step 9 — Check the Audit Trail

Scroll to the bottom — 4 tabs show your full history: every calibration run, every reading, every confirmed blockage event, every network simulation run. This is your proof-of-work / compliance trail if a judge asks "how would you prove this to a civic authority."

---

## Step 10 — Rehearse the demo

Suggested live sequence for judging:
1. Show the working physical setup — ESP32, sensor, channel.
2. Pour water through the clean channel, submit 2-3 readings live, show ~0% blockage.
3. **Live moment:** insert the sponge obstruction in front of judges, pour again, submit the reading — watch blockage % jump and (if you've built up enough baseline readings beforehand) the ML confirmation trigger live.
4. Switch to the Network Cascade section, run a simulation, explain the citywide story.
5. Show the Audit Trail as your accountability/compliance answer.
6. Close with the one-line pitch from `PS_AND_SOLUTION.md`.

**Tip:** build up your baseline readings (Step 7, the "several clean + several blocked" readings) BEFORE judging starts, so the ML confirmation layer has enough history to work correctly live, rather than trying to build the whole history from scratch during your 3-minute window.

---

## Non-negotiable checklist before you present

- [ ] Steps 3 and 4 (standalone self-tests) both pass with no errors
- [ ] Cd calibrated using your real channel's real measurements, not placeholder numbers
- [ ] At least 15-20 readings already logged (mix of clean and blocked) before judging, so ML confirmation works live
- [ ] Network simulation runs and shows the expected delay/attenuation pattern
- [ ] Every team member can explain: the orifice equation in one sentence, why Cd calibration removes the need to worry about viscosity, what the ML layer is confirming and why, and what Muskingum routing does
- [ ] `PS_AND_SOLUTION.md` reviewed with your mentor before the pitch
