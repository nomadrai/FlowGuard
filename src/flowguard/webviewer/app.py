"""Interactive Nagpur drainage & flood viewer (Flask + folium).

Run:  python app.py   ->  http://127.0.0.1:5000
"""

import json
import os
import sys

import folium
from flask import Flask, render_template

ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))
from hydro import CITY_BBOX  # noqa: E402

PARENT = os.path.dirname(ROOT) + "/nagpur_drainage_data"

app = Flask(__name__)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


drainage = load(os.path.join(ROOT, "nagpur_drainage_network.geojson"))
zones = load(os.path.join(ROOT, "flood_prone_zones.geojson"))
with open(os.path.join(ROOT, "flood_summary.json")) as f:
    summary = json.load(f)

BOUNDS = [[CITY_BBOX[1], CITY_BBOX[0]], [CITY_BBOX[3], CITY_BBOX[2]]]

STYLES = {
    "river": {"color": "#1565c0", "weight": 3.5},
    "stream": {"color": "#42a5f5", "weight": 2.0},
    "drain": {"color": "#ff8f00", "weight": 1.8},
    "canal": {"color": "#2e7d32", "weight": 1.8},
    "dam": {"color": "#c62828", "weight": 2.0},
    "weir": {"color": "#6a1b9a", "weight": 1.5},
    "riverbank": {"color": "#90caf9", "weight": 1.0},
}


def style_fn(feature):
    wtype = feature["properties"].get("waterway", "")
    return STYLES.get(wtype, {"color": "#9e9e9e", "weight": 1.0})


def zone_style(feature):
    color = feature["properties"].get("fill", "#ffd166")
    return {"fillColor": color, "color": color, "weight": 0.6,
            "fillOpacity": 0.55}


def build_map():
    m = folium.Map(location=[21.145, 79.07], zoom_start=12,
                   tiles="OpenStreetMap")

    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite").add_to(m)
    folium.TileLayer(
        "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap", name="OpenTopoMap").add_to(m)

    folium.GeoJson(drainage, name="Drainage network",
                   style_function=style_fn,
                   tooltip=folium.GeoJsonTooltip(
                       fields=["waterway", "name"], aliases=["Type", "Name"]),
                   highlight_function=lambda f: {"weight": 4}).add_to(m)

    folium.raster_layers.ImageOverlay(
        "static/flood_peak_web.png", BOUNDS, name="Peak flood depth",
        opacity=0.6).add_to(m)

    folium.raster_layers.ImageOverlay(
        "static/flood_risk_web.png", BOUNDS, name="Flood risk",
        opacity=0.55).add_to(m)

    folium.GeoJson(zones, name="Flood-prone zones",
                   style_function=zone_style,
                   tooltip=folium.GeoJsonTooltip(fields=["risk"], aliases=["Risk"]),
                   show=False).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


@app.route("/")
def index():
    return render_template("index.html", map_html=build_map().get_root().render(),
                           summary=summary)


if __name__ == "__main__":
    print("Nagpur Flood Viewer -> http://127.0.0.1:5000")
    app.run(debug=False, host="127.0.0.1", port=5000)
