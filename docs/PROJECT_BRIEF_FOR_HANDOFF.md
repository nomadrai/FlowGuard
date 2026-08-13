# FlowGuard — Complete Project Brief (For Handoff / New AI Chats / Team Reference)

Paste this entire document into a new Claude chat, ChatGPT, or any other AI assistant to give it full context on this project instantly.

---

## 1. Event Context

**Event:** Viksit Nagpur Hackathon, 24-hour format, VNIT Nagpur.
**Theme:** Smart City (also fits Open Innovation).
**Team:** 5 members (4 + 1 lead), all 3rd-year ML/IoT students.
**Registration deadline:** 15 August 2026.
**Pitch format:** 3 minutes presentation + 3 minutes Jury Q&A, strictly enforced.

---

## 2. The Real-World Problem (verified facts)

On **September 23-24, 2023**, Nagpur experienced serious flooding. **Ambazari Lake overflowed into the Nag River**, which was already choked by blocked drains, silt, and encroachment. Result: **4 deaths, 400+ people evacuated, ~10,000 houses affected.** There is an **active Public Interest Litigation (PIL)** demanding ₹2,000 crore for Nag River rejuvenation, holding NMC (Nagpur Municipal Corporation) and Maha Metro accountable for blocking natural water channels.

**The structural gap:** every flood-warning system — anywhere, not just Nagpur — uses ONE water-level sensor at ONE point, with a fixed threshold, that alerts once water is already dangerously high. This tells you a flood is happening. **It cannot tell you WHICH specific drain is blocked, or that it's been silently losing capacity for weeks, because nobody measures that continuously.** The only current method is manual physical inspection — rare, slow, easy to skip.

---

## 3. Our Solution — FlowGuard

**Core idea:** instead of just detecting a flood after it starts, continuously detect and quantify drain blockage on any ordinary day — before the next storm — using physics and data, not manual inspection.

### The physics (this is the heart of the project)

We use the **orifice equation**, derived from **Bernoulli's principle** — a standard, century-old fluid mechanics formula relating how fast water drains through an opening to how deep the water is above it:

```
Q = Cd × A × √(2 × g × h)
```
- Q = inflow rate (known — we control/measure it)
- Cd = discharge coefficient (a constant, calibrated once per channel via a controlled test pour — this single constant absorbs friction, turbulence, AND viscosity effects, so we never need to separately measure water's viscosity)
- A = the channel's open cross-sectional area — THIS is what we solve for
- g = gravity (9.8 m/s²)
- h = water height (measured live by an ultrasonic sensor)

**We know Q, we measure h, we solve backward for A.** If the calculated A is smaller than the channel's known clean area, that gap IS the blockage, expressed as a percentage, detected from data alone, no physical inspection needed.

### Why nobody else has built this (the unique angle)

Every competing flood-monitoring approach treats "flood alerting" and "infrastructure inspection" as two separate problems: a sensor that alarms during a flood, and a rare manual survey for finding blockages. We treat them as the same data problem: the gap between what physics predicts and what the sensor observes IS the blockage, continuous and automatic, on any normal day.

---

## 4. Two Versions — Basic (for new teammates) and Advanced (what we're building)

### BASIC VERSION (good starting point, single physics layer only)
- One physical node: ESP32 + HC-SR04 ultrasonic sensor + a small model channel
- Just the orifice equation: calibrate Cd once, then calculate live blockage % from Q and h
- No ML, no network simulation, no database — just print/display the blockage % number
- This alone is a complete, understandable, demoable idea. Good for teammates newer to the project to build and understand first, before adding complexity.

### ADVANCED VERSION (what we are actually building for the hackathon)
Adds three layers on top of the Basic Version's physics core:

1. **ML Confirmation Layer** — a single noisy reading (a splash, sensor glitch) shouldn't trigger a false alarm. We use an Isolation Forest (trained on known-clean behavior) to confirm that a sustained pattern of rising blockage is statistically real, not noise.
2. **Network Cascade Layer** — Nagpur's water bodies are connected (Ambazari Lake to Nag River segments to downstream). We model this as a graph and use Muskingum flow routing (a standard hydrological technique) to predict how a rainfall pulse propagates and attenuates through the network, giving real multi-hour lead time to downstream areas, not just a point alert. This part is simulated in software since we don't have hardware at every real lake, completing the citywide story around our one real physical node.
3. **Audit Trail / Database** — every calibration, reading, and confirmed blockage event is logged to a local SQLite database with timestamps. This is our answer to "how would a civic body trust and act on this," directly relevant to the PIL/accountability angle.

**Recommended team workflow:** have newer teammates build and fully understand the Basic Version first, then everyone works together to layer in the Advanced Version's ML + network + database pieces.

---

## 5. Complete File Manifest — Everything Built So Far

| File | What it does | Status |
|---|---|---|
| firmware/flowguard_hcsr04/flowguard_hcsr04.ino | ESP32 firmware, reads HC-SR04 ultrasonic sensor, converts to water level, streams CSV over Serial | Built and tested |
| blockage_detector.py | Core physics (Cd calibration, orifice equation, blockage % calculation) plus ML confirmation layer (Isolation Forest) plus trend forecasting (days-to-critical) | Built and tested, includes self-tests, one bug found and fixed (ML layer needed more training samples for a stable decision boundary) |
| network_simulation.py | Muskingum flood routing across a simulated Ambazari Lake to Nag River network | Built and tested, verified textbook-correct behavior (downstream peaks arrive later and lower) |
| storage.py | SQLite audit trail, 4 tables: calibration_log, blockage_readings, blockage_events, network_simulation_runs | Built and tested end-to-end |
| flowguard_dashboard.py | Streamlit dashboard tying everything together: calibration input, live readings, ML confirmation display, network simulation chart, audit trail viewer | Built, verified starts with no errors |
| PS_AND_SOLUTION.md | Problem statement, solution, and unique approach, written for mentor/team | Complete |
| COMPLETE_BUILD_STEPS.md | Software build guide, continuing from a working sensor to the full ML plus network system | Complete |
| FLOWGUARD_BEGINNER_GUIDE.md | Zero-experience beginner's guide, problem explained simply, first physical sensor setup | Complete |
| FULL_HARDWARE_BUILD.md | Complete 17-step hardware build, every wiring connection, calibration experiment, obstruction prep, demo rehearsal | Complete |
| FLOWGUARD_BUILD_GUIDE.md | Earlier draft build guide, superseded by the files above, kept for reference | Superseded |

Everything above has been actually run and tested, not just written. The physics self-tests, the network routing self-tests, and the storage layer were all executed and their outputs verified correct before being handed over.

---

## 6. Current Status / What's Left

- Sensor hardware wired and reading correctly (per team's confirmation)
- All software layers built and individually tested
- Pending: real Cd calibration on the team's actual physical channel (jug-pour experiment)
- Pending: building up 15-20 baseline readings (clean and blocked) before the ML confirmation layer will work reliably live
- Pending: full demo rehearsal (timed, 3-minute pitch sequence)
- Pending: team-wide understanding check — everyone should be able to explain the orifice equation, why Cd calibration removes the need for a viscosity sensor, what the ML layer confirms, and what Muskingum routing does

---

## 7. One-Line Pitch

"Nagpur already knows blocked drains caused a deadly flood — there's a court case about it right now. FlowGuard doesn't just warn you next time; it finds the exact blocked segments automatically, using physics and machine learning, before the next flood happens, not after."
