import json

with open("osm_waterways_raw.json", encoding="utf-8") as f:
    data = json.load(f)

features = []
TYPE_MAP = {
    "river": "river",
    "stream": "stream",
    "canal": "canal",
    "drain": "drain",
    "ditch": "ditch",
    "riverbank": "riverbank",
}

for el in data.get("elements", []):
    tags = el.get("tags", {})
    wtype = tags.get("waterway", "unknown")
    if el["type"] == "relation":
        continue
    geom = el.get("geometry")
    if not geom or len(geom) < 2:
        continue
    coords = [[round(p["lon"], 6), round(p["lat"], 6)] for p in geom]
    props = {
        "osm_id": el["id"],
        "waterway": wtype,
        "name": tags.get("name", ""),
        "name_en": tags.get("name:en", ""),
        "tunnel": tags.get("tunnel", ""),
        "intermittent": tags.get("intermittent", ""),
    }
    features.append({
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    })

geojson = {"type": "FeatureCollection", "features": features}

with open("nagpur_drainage_network.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False, indent=1)

from collections import Counter
counts = Counter(f["properties"]["waterway"] for f in features)
print(f"Total features: {len(features)}")
for k, v in sorted(counts.items()):
    print(f"  {k}: {v}")
named = [f for f in features if f["properties"]["name"]]
print(f"Named waterways: {len(named)}")
for f in named[:25]:
    print("   -", f["properties"]["name"], f"({f['properties']['waterway']})")
