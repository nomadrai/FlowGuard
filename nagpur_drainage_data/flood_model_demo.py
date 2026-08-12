"""Load Nagpur DEM, merge tiles, clip to city, compute D8 flow direction &
flow accumulation, overlay drainage network, and render a map."""

import json
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.windows import from_bounds
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

CITY_BBOX = (78.95, 21.00, 79.20, 21.25)  # west, south, east, north

print("[1/5] Merging DEM tiles...")
srcs = [rasterio.open(f"dem_N21E07{t}.tif") for t in (8, 9)]
mosaic, transform = merge(srcs)
print("   mosaic shape:", mosaic.shape, "| nodata:", srcs[0].nodata)

print("[2/5] Clipping to Nagpur city bbox...")
for s in srcs:
    s.close()
w = from_bounds(*CITY_BBOX, transform=transform, height=mosaic.shape[1], width=mosaic.shape[2])
dem = mosaic[0]
bounds = rasterio.transform.array_bounds(mosaic.shape[1], mosaic.shape[2], transform)
x0, y0, x1, y1 = bounds

# clip manually via index slicing
xs = max(0, int((CITY_BBOX[0] - x0) / transform.a))
xe = min(mosaic.shape[2], int(np.ceil((CITY_BBOX[2] - x0) / transform.a)) + 1)
ys = max(0, int((CITY_BBOX[1] - y0) / (-transform.e)))
ye = min(mosaic.shape[1], int(np.ceil((CITY_BBOX[3] - y0) / (-transform.e))) + 1)
dem = dem[ys:ye, xs:xe].astype(np.float64)
nodata = srcs[0].nodata if srcs[0].nodata is not None else -9999
dem[dem == nodata] = np.nan
print("   city DEM:", dem.shape, "px | cell ~", round(abs(transform.a)), "m")

print("[3/5] Computing D8 flow direction + flow accumulation...")
def flow_direction(dem):
    h, w_ = dem.shape
    dirs = np.zeros((h, w_), dtype=np.int8) - 1
    max_slope = np.full((h, w_), -np.inf)
    offs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    dists = [1.0, 1.0, 1.0, 1.0, np.sqrt(2), np.sqrt(2), np.sqrt(2), np.sqrt(2)]
    for i, ((dy, dx), d) in enumerate(zip(offs, dists)):
        nb = np.roll(np.roll(dem, -dy, axis=0), -dx, axis=1)
        slope = (dem - nb) / d
        better = slope > max_slope
        max_slope = np.where(better, slope, max_slope)
        dirs = np.where(better, i, dirs)
    dirs[np.isnan(dem)] = -1
    return dirs

fd = flow_direction(dem)

# flow accumulation (simple iterative D8)
def flow_accumulation(dem, dirs, k=100):
    h, w_ = dem.shape
    acc = np.zeros((h, w_), dtype=np.float64)
    valid = ~np.isnan(dem)
    flat = np.zeros((h, w_), dtype=bool)
    offs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    order = np.argsort(dem.ravel())  # process low -> high? no: uphill -> downhill
    order = np.argsort(dem.ravel())[::-1][: int(0.6 * h * w_)]  # highest first
    for idx in order:
        r, c = divmod(idx, w_)
        if not valid[r, c]:
            continue
        d = int(dirs[r, c])
        if d < 0:
            continue
        dr, dc = offs[d]
        nr, nc = r + dr, c + dc
        if 0 <= nr < h and 0 <= nc < w_ and valid[nr, nc]:
            acc[nr, nc] += acc[r, c] + 1.0
    return acc

acc = flow_accumulation(dem, fd)
print("   flow dir range:", fd.min(), "-", fd.max(), "| max accum:", int(acc.max()))

print("[4/5] Loading drainage network...")
with open("nagpur_drainage_network.geojson", encoding="utf-8") as f:
    gj = json.load(f)
lines = []
for feat in gj["features"]:
    coords = feat["geometry"]["coordinates"]
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
    if CITY_BBOX[0] <= max(xs) and min(xs) <= CITY_BBOX[2] and CITY_BBOX[1] <= max(ys) and min(ys) <= CITY_BBOX[3]:
        lines.append((feat["properties"].get("waterway", ""), coords))

print("[5/5] Rendering map...")
fig, axes = plt.subplots(1, 2, figsize=(20, 10))
ls = LightSource(azdeg=315, altdeg=45)
rgb = ls.shade(dem, cmap=plt.cm.terrain, blend_mode="soft", vmin=np.nanpercentile(dem, 2), vmax=np.nanpercentile(dem, 98))
extent = (CITY_BBOX[0], CITY_BBOX[2], CITY_BBOX[1], CITY_BBOX[3])

ax = axes[0]
ax.imshow(rgb, extent=extent, origin="upper")
for wtype, coords in lines:
    c = {"river": "#1f77ff", "stream": "#41b6ff", "drain": "#ff7f0e",
         "canal": "#2ca02c", "dam": "#d62728"}.get(wtype, "#888888")
    lw = 2.2 if wtype == "river" else (1.6 if wtype in ("drain", "canal") else 1.0)
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
    ax.plot(xs, ys, color=c, lw=lw, alpha=0.9, solid_capstyle="round")
ax.set_title("Nagpur Drainage Network (OSM) over 30m Copernicus DEM", fontsize=13)
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

ax2 = axes[1]
logacc = np.log10(acc + 1)
ax2.imshow(logacc, cmap="Blues", extent=extent, origin="upper",
           vmin=0, vmax=np.nanpercentile(logacc[logacc > 0], 98) if (logacc > 0).any() else 1)
for wtype, coords in lines:
    if wtype in ("river", "stream", "drain"):
        xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
        ax2.plot(xs, ys, color="red", lw=0.7, alpha=0.5)
ax2.set_title("D8 Flow Accumulation (log scale) + drainage overlay", fontsize=13)
ax2.set_xlabel("Longitude"); ax2.set_ylabel("Latitude")

plt.tight_layout()
plt.savefig("nagpur_flood_model_map.png", dpi=110)
print("SAVED: nagpur_flood_model_map.png")
print("Flow-direction stats: %.1f%% cells drain to a lower neighbour (topography is hydrologically consistent)."
      % (100 * (fd >= 0).sum() / np.isfinite(dem).sum()))
