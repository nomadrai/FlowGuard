"""Convert Nagpur drainage GeoJSON into compact scene data for the 3D city simulation.

Projection: equirectangular around Nagpur's centre, scaled so the scene is
visual-scale friendly. Output is a small JSON file consumed by citysim.html.

Usage:
    python scripts/build_city_sim_data.py
"""

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "flowguard", "webviewer", "nagpur_drainage_network.geojson")
OUT_DIR = os.path.join(ROOT, "src", "flowguard", "webviewer", "citysim")
OUT = os.path.join(OUT_DIR, "city_data.js")

# Nagpur centre / projection reference
LON0 = 79.05
LAT0 = 21.13
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))
SCALE = 1.0 / 160.0  # metres -> scene units (~a few hundred units wide)

# Ambazari Lake (real location) - a small approximation polygon
AMB_LAT, AMB_LON = 21.1282, 79.0311
AMB_RADIUS_M = 350.0


def to_scene(lon, lat):
    x = (lon - LON0) * M_PER_DEG_LON * SCALE
    z = -(lat - LAT0) * M_PER_DEG_LAT * SCALE  # north = -z so scene looks natural
    return [round(x, 2), round(z, 2)]


def simplify(pts, tol=0.5):
    """Douglas-Peucker-lite: keep a point if it moves more than tol scene units."""
    if len(pts) <= 2:
        return pts
    keep = {0, len(pts) - 1}
    changed = True
    while changed:
        changed = False
        new_keep = set(keep)
        for i in range(len(pts)):
            if i in keep:
                continue
            best = float("inf")
            for j in range(len(pts) - 1):
                if j in keep or j + 1 in keep:
                    best = min(best, point_seg_dist(pts[i], pts[j], pts[j + 1]))
            if best > tol:
                new_keep.add(i)
                changed = True
        keep = new_keep
    return [p for i, p in enumerate(pts) if i in keep]


def point_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def main():
    with open(SRC, encoding="utf-8") as f:
        gj = json.load(f)

    waterways = []
    for feat in gj["features"]:
        props = feat["properties"]
        wtype = props.get("waterway", "")
        geom = feat["geometry"]
        if geom["type"] == "LineString":
            coord_sets = [geom["coordinates"]]
        else:
            coord_sets = []
            for part in geom["coordinates"]:
                coord_sets.append(part)
        for cs in coord_sets:
            pts = [to_scene(lon, lat) for lon, lat, *rest in cs]
            pts = simplify(pts)
            if len(pts) >= 2:
                waterways.append({
                    "type": wtype,
                    "name": props.get("name", ""),
                    "pts": pts,
                })

    # Clickable drain nodes: spread endpoints / midpoints of drain+stream lines
    drains = [w for w in waterways if w["type"] in ("drain", "stream")]
    nodes = []
    used = set()
    step = 0
    for w in drains:
        pts = w["pts"]
        if len(pts) < 2:
            continue
        candidates = [pts[0], pts[len(pts) // 2], pts[-1]]
        for p in candidates:
            key = (int(p[0]), int(p[1]))
            if key in used:
                continue
            used.add(key)
            nodes.append({
                "pos": p,
                "name": w["name"] or f"Drain node {step + 1}",
                "type": w["type"],
            })
            step += 1
            if step >= 22:
                break
        if step >= 22:
            break

    lake_pts = []
    for a in range(0, 360, 8):
        ang = math.radians(a)
        dl = AMB_RADIUS_M * math.cos(ang) / M_PER_DEG_LON
        dlat = AMB_RADIUS_M * math.sin(ang) / M_PER_DEG_LAT
        lake_pts.append(to_scene(AMB_LON + dl, AMB_LAT + dlat))
    lake_pts = simplify(lake_pts, tol=1.5)

    # Lake outflow point -> where the river starts draining the lake
    outflow = to_scene(AMB_LON + 0.0009, AMB_LAT + 0.0004)

    data = {
        "projection": {"lon0": LON0, "lat0": LAT0, "scale": SCALE},
        "lake": {"center": to_scene(AMB_LON, AMB_LAT), "pts": lake_pts, "outflow": outflow},
        "waterways": waterways,
        "drain_nodes": nodes,
        "stats": {
            "waterway_count": len(waterways),
            "node_count": len(nodes),
            "bbox": [
                to_scene(78.90, 21.00),
                to_scene(79.25, 21.28),
            ],
        },
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.CITY_DATA = ")
        json.dump(data, f, separators=(",", ":"))
        f.write(";")
    print(f"Wrote {OUT}")
    print(f"  waterways: {len(waterways)}")
    print(f"  drain nodes: {len(nodes)}")
    print(f"  bbox scene: {data['stats']['bbox']}")


if __name__ == "__main__":
    main()