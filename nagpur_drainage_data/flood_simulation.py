"""Flood water clearance simulation for Nagpur.

Linear-reservoir cell model on a ~120 m grid:
  - rain adds water (40 mm/hr for 4 h), infiltration removes 5 mm/hr
  - each 10-min step, every cell pushes a slope-dependent fraction of its water
    to its D8 downstream neighbour (overland flow)
  - cells on the OSM drainage network (river/stream/drain) clear water fast
    (storm-drain + nallah capacity)
Outputs: flood_animation.gif, flood_peak_depth.png, flood_summary.json
"""

import json
import numpy as np
from scipy.ndimage import zoom
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import PillowWriter

from hydro import (load_dem, flow_direction, load_drainage_lines,
                   rasterize_lines, CITY_BBOX, D8_OFFSETS)

DT = 600.0                 # s per step (10 min)
CELL = 120.0               # ~m after 1/4 downsample
RAIN = 40.0 / 1000.0 / 3600.0 * DT      # 40 mm/hr -> m per step
INFIL = 5.0 / 1000.0 / 3600.0 * DT      # 5 mm/hr
RAIN_STEPS = 24            # 4 h of rain
TOTAL_STEPS = 72           # + 8 h of drainage clearance
DEPTH_CAP = 1.5            # m; excess assumed to spill beyond the 120 m cell

print("[1/6] Loading DEM at ~120 m grid...")
dem, bounds = load_dem(downsample=0.25)
h, w = dem.shape
west, south, east, north = bounds
dem = np.where(np.isnan(dem), np.nanmin(dem), dem)
valid = np.ones(dem.shape, dtype=bool)

print("[2/6] Flow direction + drainage channel mask...")
fd = flow_direction(dem)
lines = load_drainage_lines()
channels = rasterize_lines(lines, dem.shape, bounds)

# downstream neighbour linear index per cell
recv = np.full(h * w, -1, dtype=np.int64)
for i, (dr, dc) in enumerate(D8_OFFSETS):
    ids = np.where((fd.ravel() == i))
    for idx in ids[0]:
        r, c = divmod(idx, w)
        nr, nc = r + dr, c + dc
        if 0 <= nr < h and 0 <= nc < w:
            recv[idx] = nr * w + nc
flat_has_recv = recv >= 0

# outlets: drainage channel cells whose flow leaves the city grid (river exits east)
outlet = np.zeros((h, w), dtype=bool)
for idx in np.where(flat_has_recv == False)[0]:  # noqa: E712
    r, c = divmod(idx, w)
    if channels[r, c]:
        outlet[r, c] = True
flat_outlet = outlet.ravel()

print("[3/6] Slope-dependent outflow fraction...")
gx, gy = np.gradient(dem)
slope = np.hypot(gx, gy) / CELL
sm = np.maximum(slope, 1e-6)
f_flow = np.clip(0.04 + 0.55 * np.sqrt(sm / np.percentile(sm, 99)), 0, 0.85)
f_drain = np.clip(0.30 + 0.45 * np.sqrt(sm / np.percentile(sm, 99)), 0, 0.85)

print("[4/6] Simulating rain + runoff + drainage clearance...")
W = np.zeros((h, w))
peak = np.zeros((h, w))
frames = []
times = []

for step in range(TOTAL_STEPS):
    if step < RAIN_STEPS:
        W += RAIN
    W = np.maximum(W - INFIL, 0.0)
    f = np.where(channels, f_drain, f_flow)
    outflow = W * f
    idx_src = np.where(flat_has_recv)[0]
    idx_dst = recv[idx_src]
    np.add.at(W.ravel(), idx_dst, outflow.ravel()[idx_src])
    W.ravel()[idx_src] -= outflow.ravel()[idx_src]
    W[outlet] -= W[outlet]  # water that reaches the river outlet leaves the city
    excess = np.maximum(W - DEPTH_CAP, 0.0)  # over-cap depth spills beyond cell
    W -= excess
    W = np.maximum(W, 0.0)
    peak = np.maximum(peak, W)

    t_hr = step * DT / 3600.0
    if step % 3 == 0 or step == TOTAL_STEPS - 1:
        frames.append(W.copy())
        times.append(t_hr)

depth_metric = peak[~np.isnan(dem)]
print(f"   peak depth: max {peak.max():.2f} m | flooded cells (>5 cm): "
      f"{(peak > 0.05).sum()} of {h*w}")
summary = {
    "grid": [h, w], "cell_m": CELL, "rain_mm_hr": RAIN * 3600 / DT * 1000,
    "rain_hours": RAIN_STEPS * DT / 3600, "sim_hours": TOTAL_STEPS * DT / 3600,
    "peak_depth_m": round(float(peak.max()), 2),
    "flooded_cells_5cm": int((peak > 0.05).sum()),
    "pct_city_flooded": round(100.0 * (peak > 0.05).sum() / (h * w), 1),
    "drain_network_cells": int(channels.sum()),
}
with open("flood_summary.json", "w") as f:
    json.dump(summary, f, indent=1)
print("   summary:", summary)

print("[5/6] Peak depth map...")
fig, ax = plt.subplots(figsize=(13, 11))
im = ax.imshow(np.where(peak > 0.005, peak, np.nan), cmap="Blues",
               extent=(west, east, south, north), origin="upper",
               vmin=0, vmax=np.percentile(peak[peak > 0.005], 99))
for wtype, coords in lines:
    if wtype in ("river", "stream", "drain"):
        xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
        ax.plot(xs, ys, color="#b71c1c", lw=0.8, alpha=0.6)
plt.colorbar(im, label="Peak water depth (m)")
ax.set_title(f"Peak flood depth - 40 mm/hr for {RAIN_STEPS*DT/3600:.0f} h "
             f"(max {peak.max():.2f} m)", fontsize=12)
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
plt.tight_layout()
plt.savefig("flood_peak_depth.png", dpi=110)
plt.close()

fig, ax = plt.subplots(figsize=(10, 10))
ax.imshow(np.where(peak > 0.005, peak, 0), cmap="Blues", extent=(west, east, south, north),
          origin="upper", vmin=0, vmax=min(float(np.percentile(peak[peak > 0.005], 99)), DEPTH_CAP))
ax.axis("off")
plt.tight_layout()
plt.savefig("flood_peak_web.png", dpi=100)
plt.close()

print("[6/6] Rendering animation GIF...")
cmap = plt.cm.Blues
norm = matplotlib.colors.Normalize(vmin=0, vmax=max(float(np.percentile(peak[peak > 0.005], 99)), 0.3))
fig, ax = plt.subplots(figsize=(8, 7.5))
bg = ax.imshow(np.zeros((h, w)), extent=(west, east, south, north), origin="upper")
water_im = ax.imshow(np.zeros((h, w)), cmap=cmap, norm=norm, extent=(west, east, south, north),
                     origin="upper", alpha=0.95)
for wtype, coords in lines:
    if wtype in ("river", "stream", "drain"):
        xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
        ax.plot(xs, ys, color="#08306b", lw=1.0, alpha=0.7)
txt = ax.text(0.02, 0.98, "", transform=ax.transAxes, ha="left", va="top",
              fontsize=12, color="black",
              bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.9))
ax.set_xlim(west, east); ax.set_ylim(south, north)
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
ax.set_title("Nagpur Flood Water Clearance Simulation (D8 routing + drain capacity)",
             fontsize=11)
cbar = fig.colorbar(water_im, ax=ax, fraction=0.035, pad=0.02)
cbar.set_label("Water depth (m)")

writer = PillowWriter(fps=4, bitrate=1800)
with writer.saving(fig, "flood_animation.gif", dpi=100):
    for frame, t in zip(frames, times):
        Wf = np.where(frame > 0.002, frame, 0.0)
        water_im.set_data(Wf)
        stage = "RAINFALL" if t < RAIN_STEPS * DT / 3600 else "DRAINAGE CLEARANCE"
        txt.set_text(f"t = {t:4.1f} h   |   {stage}\nflooded: {(frame > 0.05).sum()} cells   "
                     f"|   max depth: {frame.max():.2f} m")
        writer.grab_frame()
plt.close(fig)
print("SAVED: flood_animation.gif")
