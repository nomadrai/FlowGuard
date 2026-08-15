"""
run_calibration.py — do this ONCE, using your actual real demo pouring
style (the same speed/technique you'll use live). This measures Q and Cd
TOGETHER from the same experiment, so they're guaranteed to be consistent
with each other — this is what actually fixes the negative-blockage bug,
not guessing Cd separately.

IMPORTANT: Cd is a property of your pipe's shape — it does NOT change
based on how fast you pour. Only Q changes when you pour faster/slower.
Don't adjust Cd to "match" a different pour rate — recalibrate both
together instead, using this script.

Usage:
    python run_calibration.py
"""

from blockage_detector import calibrate_cd, calculate_area, blockage_percent
from config import PIPE_AREA_CM2

print("=== FlowGuard Calibration ===")
print(f"Pipe area (fixed, from config.py): {PIPE_AREA_CM2:.4f} cm^2")
print()
print("Instructions:")
print("1. Make sure the pipe is completely CLEAR (no finger, no obstruction).")
print("2. Pour a measured volume of water into the box at your NORMAL demo")
print("   pouring speed — the same speed you'll actually use live.")
print("3. Time the pour with a stopwatch.")
print("4. Let the water level settle (keep pouring steadily) and read the")
print("   STEADY water_level_cm from serial_reader.py's live output.")
print()

pour_volume_ml = float(input("Volume poured (mL): "))
pour_time_sec = float(input("Time taken to pour it (seconds): "))
steady_h_cm = float(input("Steady-state water_level_cm you observed (cm): "))

q = pour_volume_ml / pour_time_sec
cd = calibrate_cd(pour_volume_ml, pour_time_sec, steady_h_cm, PIPE_AREA_CM2)

print()
print(f"=== Results ===")
print(f"Measured Q  = {q:.2f} mL/s")
print(f"Computed Cd = {cd:.4f}")

if cd < 0.4 or cd > 1.0:
    print(f"\n⚠️  WARNING: Cd={cd:.3f} is outside the typical physical range (0.6-0.8)")
    print("   for a simple pipe/orifice. This usually means one of your three")
    print("   input measurements (volume, time, or steady height) was off.")
    print("   Double-check them and try again before trusting this calibration.")
else:
    print("   This is within the expected physical range — looks good.")

print()
print("=== Verification: does this Cd/Q pair give ~0% blockage on the SAME clean pour? ===")
area = calculate_area(q, cd, steady_h_cm)
pct = blockage_percent(area, PIPE_AREA_CM2)
print(f"Calculated area: {area:.4f} cm^2 (should equal pipe area {PIPE_AREA_CM2:.4f})")
print(f"Blockage: {pct:.2f}% (should be very close to 0%)")

print()
print("=== Next step ===")
print("If the verification above shows ~0%, update config.py with these two lines:")
print(f"    CALIBRATED_CD = {cd:.4f}")
print(f"    DEFAULT_INFLOW_Q_CM3S = {q:.2f}")
print()
print("Then restart serial_reader.py so it picks up the new values.")
