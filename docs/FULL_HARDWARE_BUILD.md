# FlowGuard — Complete Hardware Build (Every Step, Nothing Skipped)

Follow in exact order. Each step has a ✅ Checkpoint — do not move forward until you see it.

---

## STEP 1 — Lay out and identify every part

Put everything on the table and confirm you have all of these before touching anything:

1. ESP32 Dev Board
2. HC-SR04 Ultrasonic Sensor — a small board with two round silver "eyes" (these are the transmitter and receiver), 4 pins on the back labeled VCC, Trig, Echo, GND
3. Resistors — one 1kΩ (color bands: brown, black, red), one 2kΩ (color bands: red, black, red) — if unsure which is which, ask the shop to mark them, or use a multimeter if you have one
4. Breadboard
5. Jumper wires (male-to-male), at least 8-10 pieces
6. Small plastic tray, gutter piece, or PVC pipe cut open lengthwise — your "drain channel"
7. Sponge or foam block — your removable "blockage"
8. A cup or small jug with volume markings (or any cup + a separate measuring cup)
9. A ruler or measuring tape
10. Something steady to mount the sensor above the channel (a small box, a stack of books, a simple stand/clamp)
11. USB cable matching your ESP32 (micro-USB or USB-C)
12. Laptop with Arduino IDE and Python already installed (from the earlier software setup)

✅ Checkpoint: every item above is physically in front of you. If anything is missing, get it before continuing — don't start wiring with a partial kit.

---

## STEP 2 — Prepare the breadboard

1. Place the breadboard flat on the table.
2. Place the ESP32 onto the breadboard, straddling the center gap if it fits, so pins are accessible on both sides. If your ESP32 is too wide for the breadboard, that's fine — just place it beside the breadboard and use jumper wires to reach its pins directly instead.

✅ Checkpoint: ESP32 is stable, not wobbling, pins accessible.

---

## STEP 3 — Wire the HC-SR04 power connections

1. Take a jumper wire. Connect **HC-SR04's VCC pin** → **ESP32's 5V pin** (sometimes labeled "VIN" — check your specific board's silkscreen text printed near the pin).
2. Take another jumper wire. Connect **HC-SR04's GND pin** → **any ESP32 GND pin**.

✅ Checkpoint: two wires connected — VCC to 5V/VIN, GND to GND. Double check you didn't mix these up (connecting VCC to GND or GND to 5V can damage the sensor).

---

## STEP 4 — Wire the Trig pin (simple, direct connection)

1. Take a jumper wire. Connect **HC-SR04's Trig pin** → **ESP32's GPIO5**.

✅ Checkpoint: one wire, Trig to GPIO5, nothing else needed for this pin.

---

## STEP 5 — Wire the Echo pin through the voltage divider (the careful part)

This is the step most likely to go wrong if rushed — go slowly.

**Why this step exists:** the HC-SR04 sends its Echo signal at 5 volts. The ESP32's pins can only safely handle up to 3.3 volts. If you connect Echo directly to the ESP32, you risk damaging it. The two resistors "divide" that voltage down to a safe level.

1. Insert the **1kΩ resistor** into the breadboard so one leg is in an empty row, and the other leg is in a different empty row (not touching each other, not touching anything else yet).
2. Connect a jumper wire from **HC-SR04's Echo pin** → the row where the 1kΩ resistor's first leg sits.
3. Connect a jumper wire from the row where the 1kΩ resistor's **second leg** sits → **ESP32's GPIO18**.
4. Now insert the **2kΩ resistor** into the breadboard so one leg is in the **same row as the 1kΩ resistor's second leg / the GPIO18 wire** (this is the shared junction point), and the other leg is in a new, separate empty row.
5. Connect a jumper wire from that 2kΩ resistor's second leg's row → **any ESP32 GND pin**.

**In summary, the electrical path is:** Echo → 1kΩ resistor → (this junction point also connects to GPIO18) → 2kΩ resistor → GND.

✅ Checkpoint: trace the path with your finger one more time before powering anything on:
- Echo connects to one leg of the 1kΩ resistor ✓
- The 1kΩ resistor's other leg connects to BOTH the GPIO18 wire AND the 2kΩ resistor's first leg (same junction) ✓
- The 2kΩ resistor's other leg connects to GND ✓
- Echo is NOT connected directly to GPIO18 anywhere ✓

---

## STEP 6 — Visual final check before power-on

1. Take a photo of your complete wiring.
2. Check every single connection one more time against Steps 3-5.
3. Make sure no bare wire ends are touching each other accidentally (a stray wire touching two rows it shouldn't can short-circuit things).

✅ Checkpoint: wiring photographed and re-checked.

---

## STEP 7 — Connect to laptop and upload firmware

1. Connect the ESP32 to your laptop with the USB cable.
2. Open Arduino IDE.
3. Go to **Tools → Board**, confirm your ESP32 board type is selected (should already be set from your earlier setup).
4. Go to **Tools → Port**, select the port for your ESP32.
5. Open the file `flowguard_hcsr04.ino` (provided earlier).
6. Find this line near the top:
   ```
   const float SENSOR_MOUNT_HEIGHT_CM = 20.0;
   ```
   Leave it at any value for now — you'll fix this precisely in Step 9.
7. Click the Upload button (arrow icon, top left).
8. Wait for "Done uploading" message at the bottom.

✅ Checkpoint: upload completes with no red error text.

---

## STEP 8 — Verify the sensor is reading correctly

1. Click **Tools → Serial Monitor**.
2. Set the baud rate dropdown (bottom right of that window) to **115200**.
3. You should see the header `t_ms,distance_cm,water_level_cm` followed by streaming numbers.
4. Wave your hand slowly toward and away from the sensor — the `distance_cm` number should change accordingly (smaller when your hand is closer).

✅ Checkpoint: numbers respond correctly to your hand movement. If nothing changes, or you see `-1` constantly, stop and recheck Steps 3-5's wiring before continuing.

---

## STEP 9 — Build and mount the physical channel

1. Place your tray/channel flat and steady on the table.
2. Position the HC-SR04 sensor directly above the channel, pointing straight down, mounted on your stand/box/clamp so it stays perfectly still.
3. With the channel completely **empty**, look at the `distance_cm` reading in Serial Monitor. Write this exact number down — this is your real, sensor-measured mount height (more accurate than measuring with a ruler).
4. Go back into the Arduino code, update:
   ```
   const float SENSOR_MOUNT_HEIGHT_CM = [your written-down number];
   ```
5. Re-upload the code (Upload button again).
6. Check Serial Monitor again — with the empty channel, `water_level_cm` should now read very close to **0**.

✅ Checkpoint: empty channel shows `water_level_cm` ≈ 0.

---

## STEP 10 — Measure the channel's clean cross-sectional area

1. Using your ruler, measure the **width** of the channel opening at the point where you'll later insert the sponge obstruction, in centimeters.
2. Measure the **depth** of the channel opening at that same point, in centimeters.
3. Multiply: Area = width × depth. Write this number down (this is your `a_clean_cm2`).

✅ Checkpoint: you have a written-down area number, e.g., "4 cm × 3 cm = 12 cm²".

---

## STEP 11 — Test water response (before calibration)

1. Pour a small amount of water into the channel.
2. Watch `water_level_cm` in Serial Monitor — it should rise.
3. Let the water drain or remove it — the number should fall back toward 0.

✅ Checkpoint: water level rises and falls correctly with real water.

---

## STEP 12 — Calibration experiment (the jug-pour test)

Do this 3 separate times, writing down all numbers each time:

1. Fill your measuring jug with a known volume — e.g., 500 mL. Write it down.
2. Start a stopwatch (phone works). Pour the entire 500 mL into the channel at a steady, even pace. Stop the stopwatch the moment you finish pouring. Write down the time in seconds.
3. Right as the water level stabilizes (stops rising), read and write down the `water_level_cm` value from Serial Monitor.
4. Empty the channel completely before the next trial.
5. Repeat this entire process 2 more times (3 trials total).

✅ Checkpoint: you have 3 complete sets of (volume, time, steady height) numbers written down, plus your channel area from Step 10.

---

## STEP 13 — Calculate Cd

1. On your laptop, open a terminal in the folder containing `blockage_detector.py`.
2. Run Python interactively:
   ```
   python
   ```
3. Type:
   ```python
   from blockage_detector import calibrate_cd
   cd1 = calibrate_cd(pour_volume_ml=500, pour_time_sec=10, steady_h_cm=3.0, a_clean_cm2=12.0)
   ```
   (replace the numbers with your actual Trial 1 numbers and your area from Step 10)
4. Repeat for Trials 2 and 3, then average the three Cd values by hand (add them, divide by 3).
5. Type `exit()` to leave Python.

✅ Checkpoint: you have one final averaged Cd number written down.

---

## STEP 14 — Prepare your obstruction for the live demo

1. Cut or shape your sponge/foam block so it fits snugly into the channel at the point where you measured area in Step 10 — it should visibly reduce the opening when inserted, but be easy to insert/remove quickly by hand during your demo.
2. Test: with the obstruction inserted, pour water at roughly the same rate as your calibration trials, and confirm `water_level_cm` rises **higher** than it did during your clean calibration trials for a similar pour. This proves your obstruction actually restricts flow enough to be detectable.

✅ Checkpoint: obstruction visibly changes water behavior when inserted.

---

## STEP 15 — Launch the full dashboard and enter your real numbers

1. In your terminal:
   ```
   streamlit run flowguard_dashboard.py
   ```
2. In the sidebar, enter your Step 12 numbers (use your Trial 1 numbers, or the averages) and your Step 10 area.
3. Click **"Calibrate Cd"** — confirm it shows a Cd value close to what you calculated by hand in Step 13.

✅ Checkpoint: dashboard's calculated Cd matches your manual calculation from Step 13.

---

## STEP 16 — Build up baseline readings before your demo

1. With the clean channel, pour water at varying rates 5-6 times, entering the inflow rate (volume ÷ time) and resulting water height into the dashboard's "Physical Node" section each time, clicking **Submit reading** after each.
2. Insert the obstruction, pour again 5-6 times the same way, submitting each reading.
3. Aim for at least 15-20 total submitted readings before judging, so the ML confirmation layer has enough history to work correctly live (fewer than that, and it won't have learned what "normal" looks like yet).

✅ Checkpoint: Audit Trail's `blockage_readings` tab shows 15+ logged readings, mix of clean and blocked.

---

## STEP 17 — Full dry run of your demo sequence

1. Reset your channel to clean, obstruction removed.
2. Pour water, submit a reading live — confirm it shows low/no blockage.
3. Insert the obstruction live, pour again, submit — confirm blockage % rises and (given your Step 16 baseline) ML confirmation triggers.
4. Switch to Network Cascade section, run a simulation, briefly explain it.
5. Show the Audit Trail tabs.
6. Time this entire sequence — practice until it reliably fits your pitch window.

✅ Checkpoint: full sequence rehearsed at least 3 times, timed, working consistently.

---

## You're done. Final pre-event checklist

- [ ] All 17 steps above completed and checked
- [ ] Wiring photographed (Step 6) — keep the photo in case you need to re-check or rebuild quickly
- [ ] Cd calibration numbers written down physically (backup, in case a laptop issue happens)
- [ ] At least 15-20 baseline readings already in the database before judging
- [ ] Obstruction tested and ready to insert quickly and cleanly
- [ ] Full demo sequence rehearsed 3+ times, timed
- [ ] Every team member can explain what happens at each step, not just the person who built it
