"""Shared hydrology helpers: DEM loading/clipping, D8 flow direction,
flow accumulation, and drainage-line rasterization."""

import json
import numpy as np
import rasterio
from rasterio.merge import merge
from scipy.ndimage import zoom

CITY_BBOX = (78.95, 21.00, 79.20, 21.25)  # west, south, east, north (degrees)

D8_OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
D8_DIST = [1.0, 1.0, 1.0, 1.0, np.sqrt(2), np.sqrt(2), np.sqrt(2), np.sqrt(2)]


def load_dem(downsample=1.0):
    """Merge the two Copernicus tiles, clip to city bbox, return (dem, bounds).
    bounds = (west, south, east, north). Optionally downsample (<=1)."""
    srcs = [rasterio.open(f"dem_N21E07{t}.tif") for t in (8, 9)]
    mosaic, transform = merge(srcs)
    nodata = srcs[0].nodata
    for s in srcs:
        s.close()
    x0, y0, x1, y1 = rasterio.transform.array_bounds(
        mosaic.shape[1], mosaic.shape[2], transform)
    xs = max(0, int((CITY_BBOX[0] - x0) / transform.a))
    xe = min(mosaic.shape[2], int(np.ceil((CITY_BBOX[2] - x0) / transform.a)) + 1)
    ys = max(0, int((CITY_BBOX[1] - y0) / (-transform.e)))
    ye = min(mosaic.shape[1], int(np.ceil((CITY_BBOX[3] - y0) / (-transform.e))) + 1)
    dem = mosaic[0, ys:ye, xs:xe].astype(np.float64)
    if nodata is not None:
        dem[dem == nodata] = np.nan
    if downsample < 1.0:
        dem = zoom(dem, downsample, order=1, mode="nearest")
    return dem, CITY_BBOX


def flow_direction(dem):
    """D8 steepest-downslope direction per cell (code 0..7), -1 for pits/nodata."""
    h, w = dem.shape
    dirs = np.full((h, w), -1, dtype=np.int8)
    max_slope = np.full((h, w), -np.inf)
    for i, ((dy, dx), d) in enumerate(zip(D8_OFFSETS, D8_DIST)):
        nb = np.roll(np.roll(dem, -dy, axis=0), -dx, axis=1)
        slope = (dem - nb) / d
        better = slope > max_slope
        max_slope = np.where(better, slope, max_slope)
        dirs = np.where(better, i, dirs)
    dirs[np.isnan(dem)] = -1
    return dirs


def flow_accumulation(dem, dirs):
    """D8 flow accumulation (number of upstream cells). High -> drainage channel."""
    h, w = dem.shape
    acc = np.zeros((h, w), dtype=np.float64)
    valid = ~np.isnan(dem)
    order = np.argsort(dem.ravel())[::-1]
    for idx in order:
        r, c = divmod(idx, w)
        if not valid[r, c]:
            continue
        d = int(dirs[r, c])
        if d < 0:
            continue
        dr, dc = D8_OFFSETS[d]
        nr, nc = r + dr, c + dc
        if 0 <= nr < h and 0 <= nc < w and valid[nr, nc]:
            acc[nr, nc] += acc[r, c] + 1.0
    return acc


def load_drainage_lines(path="nagpur_drainage_network.geojson", bbox=CITY_BBOX):
    """Load OSM drainage GeoJSON, return list of (waterway_type, coords)."""
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    lines = []
    for feat in gj["features"]:
        coords = feat["geometry"]["coordinates"]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if (bbox[0] <= max(xs) and min(xs) <= bbox[2]
                and bbox[1] <= max(ys) and min(ys) <= bbox[3]):
            lines.append((feat["properties"].get("waterway", ""), coords))
    return lines


def rasterize_lines(lines, shape, bounds):
    """Burn drainage lines into a mask grid (1 = channel cell).
    Lines are walked vertex-by-vertex; nearest cell per vertex + densified segments."""
    h, w = shape
    west, south, east, north = bounds
    dx = (east - west) / w
    dy = (north - south) / h
    mask = np.zeros((h, w), dtype=bool)

    def mark(lon, lat):
        c = int((lon - west) / dx)
        r = int((north - lat) / dy)
        if 0 <= r < h and 0 <= c < w:
            mask[r, c] = True

    for _, coords in lines:
        if len(coords) < 2:
            continue
        for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:]):
            seg_len = np.hypot((lon2 - lon1) / dx, (lat1 - lat2) / dy)
            steps = max(2, int(np.ceil(seg_len)))
            for s in range(steps + 1):
                t = s / steps
                mark(lon1 + (lon2 - lon1) * t, lat1 + (lat2 - lat1) * t)
    return mask
