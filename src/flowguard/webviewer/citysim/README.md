# FlowGuard — Nagpur 3D City Drainage Simulation

An interactive, real-world-like 3D simulation of **Nagpur's actual drainage
network** (from OpenStreetMap data): Ambazari Lake feeding the Nag River,
plus the city's drains, streams, canals, dams and weirs.

## Run

Just open `index.html` in a browser (works from `file://` — no server needed,
all libraries are bundled locally).

```bash
start src/flowguard/webviewer/citysim/index.html
```

Or serve it:

```bash
cd src/flowguard/webviewer/citysim
python -m http.server 8899
# -> http://127.0.0.1:8899
```

Append `?auto=1` to auto-dismiss the intro (kiosk/demo mode).

## How to demo

1. **Enter** the simulation.
2. **Click any glowing orange drain marker** — a control panel opens.
3. **Simulate Rain** 🌧️ — sky darkens, clouds roll in, rain falls, the lake fills
   and river flow speeds up. Lightning flashes during heavy rain.
4. **Place an Obstacle** 🧱 — a debris pile appears at the drain, blockage rises,
   drain capacity collapses, the lake overflows and **flood water spreads**.
5. Watch **houses flood** (they darken), **people flee** the flooded homes, and the
   live damage counter tick up in the top-right HUD.
6. **Clear This Node** or **Reset City** to restore the flow.

## Files

| File | Purpose |
|------|---------|
| `index.html` | The whole 3D simulation (Three.js scene + UI) |
| `city_data.js` | Generated scene data (projected Nagpur drainage network, drain nodes, lake) |
| `three.min.js` | Three.js r128 (bundled, offline-capable) |
| `OrbitControls.js` | Camera controls (bundled) |

## Regenerating the scene data

The scene data is produced from the real OSM Nagpur drainage GeoJSON by:

```bash
python scripts/build_city_sim_data.py
```

This projects lon/lat → scene coordinates, simplifies polylines, and picks
clickable drain nodes. The river flow path (lake → downstream) is chained at
runtime in `index.html`.

## What the physics models

- **Rain** raises the lake level; outflow capacity drops as drain blockages
  accumulate.
- **Overflow** (lake level > 88%) triggers a flood wave that spreads radially
  from the lake and downstream along the river path.
- **Houses** near the flood zone get flooded and damaged; displaced people
  (3 per home) are counted in the HUD — mirroring the real Sept 2023 Nagpur
  flood (Ambazari overflow → Nag River → ~10,000 homes affected).