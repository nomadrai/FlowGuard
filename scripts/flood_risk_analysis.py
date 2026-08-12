"""Flood-prone zone analysis for Nagpur.

Per-cell risk score from DEM-derived features:
  0.35 * low elevation + 0.25 * flat slope + 0.20 * high flow accumulation + 0.20 * proximity to drains
Outputs: flood_risk_map.png (30 m), flood_risk_web.png (georeferenced, for the viewer),
flood_prone_zones.geojson (coarse-grid zones for the interactive map).
"""

import json
import numpy as np
from scipy.ndimage import distance_transform_edt, uniform_filter, zoom, maximum_filter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hydro import (load_dem, flow_direction, flow_accumulation,
                   load_drainage_lines, rasterize_lines, CITY_BBOX)

print("[1/6] Loading DEM (30 m)...")
dem, bounds = load_dem()
h, w = dem.shape
west, south, east, north = bounds
valid = ~np.isnan(dem)

print("[2/6] Terrain features...")
elev = np.where(valid, dem, np.nan)
elev_min, elev_max = np.nanpercentile(elev, 1), np.nanpercentile(elev, 99)
low_elev = np.clip((elev_max - elev) / (elev_max - elev_min), 0, 1)

smooth = np.where(valid, uniform_filter(np.where(valid, elev, 0), 5), np.nan)
smooth = np.where(valid, uniform_filter(np.where(valid, elev, 0), 5), np.nan)
gx, gy = np.gradient(np.where(valid, elev, 0))
slope = np.hypot(gx / (0.0003 * 111320), gy / (0.0003 * 111320)) / 111320 * 57.3  # degrees
slope = np.where(valid, slope, np.nan)
flat_slope = 1 - np.clip(slope / np.nanpercentile(slope, 99), 0, 1)

print("[3/6] Flow accumulation + drainage proximity...")
fd = flow_direction(elev)
acc = flow_accumulation(elev, fd)
log_acc = np.log10(np.where(valid, acc + 1, 1))
high_acc = np.clip(log_acc / np.nanpercentile(log_acc, 99), 0, 1)

lines = load_drainage_lines()
channel_mask = rasterize_lines(lines, dem.shape, bounds)
dist = distance_transform_edt(~channel_mask, sampling=(0.0003 * 111320, 0.0003 * 111320))
near_drain = np.clip(1 - dist / 1500.0, 0, 1)
near_drain[~valid] = 0

print("[4/6] Risk score...")
risk = (0.35 * low_elev + 0.25 * flat_slope +
        0.20 * high_acc + 0.20 * near_drain)
risk[~valid] = np.nan

classes = {"Low": 0, "Moderate": 1, "High": 2, "Very High": 3}
thr = [0.45, 0.55, 0.68]
cls = np.full(dem.shape, -1, dtype=np.int8)
cls[risk >= thr[2]] = 3
cls[(risk >= thr[1]) & (risk < thr[2])] = 2
cls[(risk >= thr[0]) & (risk < thr[1])] = 1
cls[(risk < thr[0]) & valid] = 0
cls[~valid] = -1
counts = {k: int((cls == v).sum()) for k, v in classes.items()}
print("   zone cell counts:", counts)

print("[5/6] Saving PNG maps...")
fig, ax = plt.subplots(figsize=(14, 12))
im = ax.imshow(risk, cmap="RdYlBu_r", extent=(west, east, south, north),
               origin="upper", vmin=0.3, vmax=0.75)
for wtype, coords in lines:
    if wtype in ("river", "stream", "drain"):
        xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
        ax.plot(xs, ys, color="#08306b", lw=0.9, alpha=0.85)
plt.colorbar(im, label="Flood risk score")
ax.set_title("Nagpur Flood-Risk Zones (30 m cells)\n0.35*lowElev + 0.25*flatSlope + 0.2*flowAcc + 0.2*nearDrain", fontsize=11)
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
plt.tight_layout()
plt.savefig("flood_risk_map.png", dpi=110)
plt.close()

vmax = np.nanpercentile(risk, 99.5)
fig, ax = plt.subplots(figsize=(10, 10))
ax.imshow(np.where(valid, risk, 0), cmap="RdYlBu_r", extent=(west, east, south, north),
          origin="upper", vmin=0.2, vmax=vmax)
ax.axis("off")
plt.tight_layout()
plt.savefig("flood_risk_web.png", dpi=100)
plt.close()

print("[6/6] Saving zones GeoJSON (coarse grid)...")
factor = 6
rh, rw = (h + factor - 1) // factor, (w + factor - 1) // factor
rrisk = maximum_filter(np.where(valid, risk, 0), size=factor)[::factor, ::factor]
rcls = np.full((rh, rw), -1, dtype=np.int8)
rcls[rrisk >= thr[2]] = 3
rcls[(rrisk >= thr[1]) & (rrisk < thr[2])] = 2
rcls[(rrisk >= thr[0]) & (rrisk < thr[1])] = 1
cell_dx = (east - west) / rw
cell_dy = (north - south) / rh
name = {1: "Moderate", 2: "High", 3: "Very High"}
color = {1: "#ffd166", 2: "#f77f00", 3: "#d90429"}
feats = []
for r in range(rh):
    for c in range(rw):
        v = rcls[r, c]
        if v < 1:
            continue
        lon0 = west + c * cell_dx
        lat1 = north - r * cell_dy
        poly = [[lon0, lat1], [lon0 + cell_dx, lat1],
                [lon0 + cell_dx, lat1 - cell_dy], [lon0, lat1 - cell_dy]]
        feats.append({"type": "Feature",
                      "properties": {"risk": name[v], "fill": color[v]},
                      "geometry": {"type": "Polygon",
                                   "coordinates": [[poly[0], poly[1], poly[2], poly[3], poly[0]]]}})
geojson = {"type": "FeatureCollection", "features": feats}
with open("flood_prone_zones.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson, f)
print(f"   zones saved: {len(feats)} polygons")
frac = counts["High"] + counts["Very High"]
print(f"DONE. High+VeryHigh cells: {frac} of {int(valid.sum())} valid ({100*frac/valid.sum():.1f}% of city)")
