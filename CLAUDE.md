# CLAUDE.md — FlowGuard AI Agent Operating Guide

This document serves as the primary reference for AI coding agents working on the FlowGuard project. Read this before making any changes to the codebase.

---

## Project Overview

**FlowGuard** is a physics-based drain blockage detection and flood early warning system designed for urban drainage networks in smart cities.

**Core Value Proposition:**
- Real-time blockage detection using IoT sensors + calibrated hydraulic physics
- ML confirmation layer to distinguish genuine blockages from sensor noise
- Network cascade modeling to predict downstream flood impacts
- Complete audit trail for civic accountability

**Target Use Case:** Nagpur, Maharashtra drainage network (generalizable to any city)

**Hardware:** ESP32 microcontroller + HC-SR04 ultrasonic sensor (~$5-10 per node)

---

## Architecture

### Core Physics

FlowGuard uses the **orifice equation**:

```
Q = Cd × A × √(2gh)
```

Where:
- Q = flow rate (cm³/s) — rainfall inflow rate, entered in dashboard sidebar (mL/s; 1 mL = 1 cm³)
- Cd = discharge coefficient (dimensionless, field-calibrated)
- A = drainage pipe cross-sectional area (cm²) — **fixed: π × (1.90/2)² ≈ 2.8353 cm²**
- g = gravity (981 cm/s²)
- h = water height in inlet box (cm) — measured live by HC-SR04

**Hardware geometry (hardcoded constants):**
- Drainage pipe: round, diameter **1.90 cm**, area **2.8353 cm²** (`PIPE_AREA_CM2` in `blockage_detector.py`)
- Inlet box: rectangular, base area **308 cm²** (`INLET_BOX_BASE_AREA_CM2` in `blockage_detector.py`)

**Key insight:** Field calibration of Cd eliminates assumptions about viscosity, channel roughness, and turbulence. The system learns the real-world behavior of each specific drainage point.

### Blockage Detection Logic

1. **Expected flow (clean pipe):** Q_expected = Cd × A_pipe × √(2gh), where A_pipe = 2.8353 cm²
2. **Observed flow (current reading):** Q_observed = inflow rate entered in dashboard sidebar (mL/s)
3. **Blockage percentage:** (Q_expected - Q_observed) / Q_expected × 100%

Higher water height with same inflow → obstruction reducing effective pipe area → blockage detected.

### ML Confirmation Layer

**Algorithm:** Isolation Forest (scikit-learn)

**Purpose:** Filter sensor noise and transient fluctuations from genuine blockage trends.

**How it works:**
- Trains on rolling window of recent blockage % readings
- Flags sustained rising trends as anomalies
- Single noisy spikes are NOT flagged
- Requires ~15-20 readings minimum for reliable operation

**Why Isolation Forest?**
- Unsupervised (no labeled blockage training data needed)
- Handles non-Gaussian distributions
- Effective for detecting drift/trend patterns

### Network Cascade Modeling

**Algorithm:** Muskingum routing

**Purpose:** Model how a flood pulse propagates through drainage network (upstream → downstream).

**Equation:**
```
O_t+1 = C₁×I_t+1 + C₂×I_t + C₃×O_t
```

Where:
- I = inflow to segment
- O = outflow from segment
- C₁, C₂, C₃ = routing coefficients derived from K (travel time) and X (weighting factor)

**Physical meaning:**
- **K (hours):** Travel time through channel segment
- **X (0-0.5):** Weighting between inflow and storage; X=0 is pure reservoir, X=0.5 is kinematic wave
- **Effect:** Downstream flood peaks arrive later and smaller (attenuation)

---

## Repository Structure

```
FlowGuard/
├── firmware/
│   └── flowguard_hcsr04/
│       └── flowguard_hcsr04.ino    # ESP32 firmware: HC-SR04 → CSV over Serial
├── src/
│   └── flowguard/                  # Main Python package
│       ├── __init__.py
│       ├── blockage_detector.py    # Orifice physics + ML + trend forecasting
│       ├── network_simulation.py   # Muskingum routing
│       ├── storage.py              # SQLite audit trail
│       ├── flowguard_dashboard.py  # Streamlit dashboard (main entry point)
│       └── webviewer/              # Flask app for flood risk map visualization
│           ├── app.py
│           ├── templates/
│           └── static/
├── scripts/                        # Analysis and simulation scripts
│   ├── hydro.py                    # DEM processing, flow direction/accumulation
│   ├── flood_simulation.py         # Grid-based flood water clearance model
│   ├── flood_risk_analysis.py      # Citywide risk assessment
│   ├── flood_model_demo.py         # Demo visualization
│   └── convert_overpass_to_geojson.py  # OSM data processing
├── data/                           # Data directory (Git-ignored except structure)
│   ├── nagpur_drainage/            # GeoJSON, DEM, simulation outputs
│   └── flowguard_history.db        # SQLite database (not in Git)
├── docs/                           # Project documentation
│   ├── COMPLETE_BUILD_STEPS.md     # Step-by-step setup guide
│   ├── PS_AND_SOLUTION.md          # Problem statement and solution
│   ├── HARDWARE_ASSEMBLY.md        # ESP32 + sensor wiring
│   ├── CALIBRATION_GUIDE.md        # Cd calibration procedures
│   └── ...
├── tests/                          # Test suite (currently minimal)
├── assets/                         # Presentation materials (PPTX, PDF)
├── .venv/                          # Python virtual environment (Git-ignored)
├── .gitignore
├── pyproject.toml                  # Project metadata and dependencies
├── README.md                       # User-facing documentation
└── CLAUDE.md                       # This file
```

### Key File Purposes

**blockage_detector.py:**
- `calibrate_cd()`: Field calibration from pour experiment measurements
- `compute_blockage_pct()`: Core orifice equation calculation
- `ml_confirm_blockage()`: Isolation Forest anomaly detection
- `forecast_days_to_critical()`: Linear trend extrapolation

**network_simulation.py:**
- `Node`: Represents drainage point with inflow/outflow/storage
- `muskingum_route()`: Routes flood pulse from upstream to downstream node
- `build_sample_network()`: Ambazari Lake → Nag River example topology
- `simulate_rainfall_pulse()`: Models rainfall event propagating through network

**storage.py:**
- SQLite schema: `calibrations`, `readings`, `blockage_events`, `network_simulations`
- Thread-safe connection handling
- Audit trail for civic compliance

**flowguard_dashboard.py:**
- Streamlit multi-page interface
- Integrates all components: calibration, monitoring, simulation, audit
- Main entry point: `streamlit run src/flowguard/flowguard_dashboard.py`

**scripts/hydro.py:**
- DEM loading and processing (Rasterio)
- D8 flow direction algorithm
- Flow accumulation calculation
- Drainage network rasterization
- Used by flood simulation and risk analysis scripts

---

## Technology Stack

### Core Dependencies

```
numpy>=1.24.0          # Numerical computing
pandas>=2.0.0          # Data structures
scikit-learn>=1.3.0    # ML (Isolation Forest)
streamlit>=1.28.0      # Dashboard interface
```

### Analysis Dependencies (optional)

```
rasterio>=1.3.0        # DEM/GeoTIFF processing
scipy>=1.11.0          # Hydrological modeling
matplotlib>=3.7.0      # Visualization
```

### Web Viewer Dependencies (optional)

```
flask>=3.0.0           # Web framework
folium>=0.15.0         # Interactive maps
```

### Development Dependencies (optional)

```
pytest>=7.4.0          # Testing framework
black>=23.0.0          # Code formatter
ruff>=0.1.0            # Fast linter
mypy>=1.7.0            # Type checking
```

**Python Version:** 3.10+ (uses modern type hints, pattern matching)

---

## Development Environment

### Setup

```bash
# Create virtual environment
python3 -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\Activate.ps1

# Install core dependencies
pip install -e .

# Install with all optional dependencies
pip install -e ".[analysis,webviewer,dev]"
```

### Running the Project

**Main dashboard:**
```bash
streamlit run src/flowguard/flowguard_dashboard.py
```

**Standalone tests:**
```bash
python src/flowguard/blockage_detector.py
python src/flowguard/network_simulation.py
```

**Analysis scripts (from project root):**
```bash
cd scripts
python flood_simulation.py        # Outputs: flood_animation.gif, flood_peak_depth.png
python flood_risk_analysis.py     # Outputs: flood_risk_map.png
```

**Web viewer:**
```bash
python src/flowguard/webviewer/app.py
```

---

## Testing

**Current state:** Minimal test coverage. Core modules have self-test functionality in `if __name__ == "__main__"` blocks.

**Test strategy:**
- `blockage_detector.py` self-test: physics calculation, ML confirmation, trend forecasting
- `network_simulation.py` self-test: Muskingum routing, peak arrival ordering

**Future testing:**
```bash
pytest tests/                      # Run test suite
pytest tests/ -v                   # Verbose output
pytest tests/ --cov=src/flowguard  # Coverage report
```

---

## Code Quality

### Formatting

```bash
black src/ tests/ scripts/         # Auto-format (line length: 100)
```

### Linting

```bash
ruff check src/ tests/ scripts/    # Fast linting
ruff check --fix src/              # Auto-fix safe issues
```

### Type Checking

```bash
mypy src/flowguard/                # Static type checking
```

**Note:** Current codebase has minimal type hints. Incremental typing encouraged but not required.

---

## Coding Standards

### Python Style

- **PEP 8** compliance (enforced by Black and Ruff)
- **Line length:** 100 characters
- **Naming:**
  - Functions: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
  - Private: `_leading_underscore`

### Import Organization

```python
# Standard library
import os
import sys
from typing import List, Dict

# Third-party
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

# Local
from flowguard.storage import log_calibration
from flowguard.network_simulation import muskingum_route
```

### Documentation

- **Docstrings:** Use for public functions and classes
- **Comments:** Explain *why*, not *what* (code should be self-explanatory)
- **Physical equations:** Always comment with formula and units

Example:
```python
def compute_blockage_pct(cd: float, clean_area: float, height: float, inflow: float) -> float:
    """
    Compute blockage percentage using orifice equation.
    
    Q_expected = Cd × A × √(2gh)
    blockage% = (Q_expected - Q_observed) / Q_expected × 100
    
    Args:
        cd: Discharge coefficient (dimensionless, field-calibrated)
        clean_area: Clean pipe cross-section (cm²) — use PIPE_AREA_CM2 = 2.8353 cm²
        height: Water height in inlet box (cm)
        inflow: Observed inflow rate (cm³/s) — entered as mL/s in dashboard sidebar
    
    Returns:
        Blockage percentage (0-100+)
    """
```

### Error Handling

- Use specific exceptions (`ValueError`, `FileNotFoundError`, etc.)
- Validate inputs at function boundaries
- Fail fast: catch errors early rather than propagating bad data

### Logging

- Streamlit uses `st.write()`, `st.success()`, `st.error()` for user feedback
- Scripts use `print()` for progress updates
- Future: Consider `logging` module for production deployment

---

## Git Workflow

### Before Making Changes

```bash
git status                         # Check current state
git pull origin main               # Get latest changes
git checkout -b feature/your-feature-name  # Create branch
```

### After Making Changes

```bash
# Verify changes
python src/flowguard/blockage_detector.py     # Run self-tests
python src/flowguard/network_simulation.py    # Run self-tests
black src/ scripts/                            # Format code
ruff check src/ scripts/                       # Lint code

# Review diff
git status
git diff

# Commit
git add <specific files>                       # Stage intentionally
git commit -m "Clear description of changes"

# Push
git push -u origin feature/your-feature-name
```

### Commit Messages

- Use imperative mood: "Add feature" not "Added feature"
- First line <70 chars, detailed explanation in body if needed
- Reference issues: "Fix #123: Correct Muskingum routing coefficients"

### What NOT to Commit

❌ **Never commit:**
- `.venv/` (virtual environment)
- `__pycache__/`, `*.pyc` (Python bytecode)
- `*.db` (SQLite databases with user data)
- `.env`, `.env.local` (environment variables)
- Large data files: `*.tif`, `*.png`, `*.gif` outputs
- API keys, credentials, secrets
- IDE config: `.vscode/`, `.idea/`

✅ **Always commit:**
- Source code: `*.py`
- Configuration: `pyproject.toml`, `.gitignore`
- Documentation: `*.md`, `docs/*`
- Small reference data: `*.geojson` network topology
- `.env.example` (template, no secrets)

---

## Important Rules for AI Agents

### 1. Inspect Before Modifying

❌ **Don't:**
```python
# Blindly change imports without checking usage
from flowguard import old_function  # Might break existing code
```

✅ **Do:**
```bash
# Check where function is used
grep -r "old_function" src/
# Verify no external scripts depend on it
```

### 2. Preserve Existing Functionality

- **The physics works:** Don't "simplify" the orifice equation or Muskingum routing unless you're fixing a proven bug
- **Calibration is critical:** Never bypass or hardcode Cd values
- **ML threshold tuned:** `contamination=0.15` in Isolation Forest was chosen empirically

### 3. Avoid Unnecessary Rewrites

- If code is working, readable, and maintainable → leave it alone
- "Modern syntax" or "better style" is not sufficient reason to rewrite
- Prioritize: bug fixes > missing features > documentation > refactoring

### 4. Don't Introduce Unnecessary Dependencies

- Check `pyproject.toml` for existing dependencies
- Use NumPy/Pandas/scikit-learn patterns already in codebase
- Don't add: TensorFlow, PyTorch, heavy frameworks unless absolutely necessary
- Avoid: duplicate libraries (e.g., don't add `requests` if `urllib` works)

### 5. Keep Changes Focused

- One logical change per commit/PR
- Don't mix: refactoring + new features + bug fixes
- Update related documentation in the same change

### 6. Run Relevant Tests After Changes

**Modified blockage_detector.py?**
```bash
python src/flowguard/blockage_detector.py  # Self-test must pass
```

**Modified network_simulation.py?**
```bash
python src/flowguard/network_simulation.py  # Self-test must pass
```

**Modified dashboard?**
```bash
streamlit run src/flowguard/flowguard_dashboard.py  # Smoke test UI
```

**Modified scripts/hydro.py?**
```bash
cd scripts
python flood_simulation.py  # Should complete without errors
```

### 7. Never Expose Secrets

- Search codebase for hardcoded credentials before committing
- Check for: API keys, passwords, tokens, private URLs
- Use `.env` + environment variables for configuration
- Provide `.env.example` with placeholders only

### 8. Never Commit `.env` or Credentials

```bash
# Check before committing
git status
cat .gitignore  # Verify .env is listed
```

### 9. Update Documentation When Architecture Changes

**Changed module structure?** → Update README.md "Project Structure" section

**Changed dependencies?** → Update README.md "Prerequisites" and pyproject.toml

**Changed CLI commands?** → Update README.md "Running FlowGuard" section

**Changed physics/ML algorithms?** → Update CLAUDE.md "Architecture" section

### 10. Check Git Diff Before Completing Work

```bash
git diff                    # Review unstaged changes
git diff --staged           # Review staged changes
git status                  # Check for untracked files
```

**Ask yourself:**
- Are all changes intentional?
- Any debug print statements left in?
- Any commented-out code that should be removed?
- Any temporary files staged by accident?

---

## Known Constraints

### Hardware Limitations

- **HC-SR04 sensor range:** 2cm - 400cm (practical: 5cm - 300cm)
- **HC-SR04 accuracy:** ±3mm (noise requires ML confirmation layer)
- **ESP32 Serial Monitor:** Manual data entry to dashboard (no auto-streaming yet)

### Software Limitations

- **ML requires baseline:** 15-20 readings minimum for Isolation Forest to work
- **Network simulation is simplified:** Doesn't model pipe capacity constraints, surcharge, or backwater effects
- **Database is local:** SQLite not suitable for multi-node distributed deployment
- **No real-time alerts:** Dashboard must be manually monitored

### Data Limitations

- **Nagpur DEM resolution:** ~30m (SRTM), limits fine-scale analysis
- **Drainage network completeness:** OSM data has gaps in unmapped nalas
- **No rainfall gauge integration:** Simulation uses manual rainfall input

### Future Improvements Needed

1. **Automated data pipeline:** ESP32 → WiFi → cloud → dashboard (no manual entry)
2. **Alert system:** SMS/email notifications for confirmed blockages
3. **Multi-node deployment:** Distributed database, centralized monitoring
4. **Advanced hydraulics:** SWMM/HEC-RAS integration for complex networks
5. **Real-time rainfall:** API integration with IMD/weather stations
6. **Mobile app:** Field technician interface for maintenance dispatch

---

## Troubleshooting Guide

### Issue: "ModuleNotFoundError: No module named 'flowguard'"

**Cause:** Package not installed or virtual environment not activated.

**Fix:**
```bash
source .venv/bin/activate  # Activate venv
pip install -e .            # Install in editable mode
```

### Issue: "sqlite3.OperationalError: no such table"

**Cause:** Database schema not initialized.

**Fix:**
```python
from flowguard.storage import init_db
init_db()  # Creates tables
```

Or run dashboard once (auto-initializes).

### Issue: Dashboard shows wrong blockage % or ML never confirms

**Cause:** 
1. Cd not calibrated correctly
2. Insufficient baseline readings
3. Sensor noise too high

**Fix:**
1. Re-run calibration with careful measurements (3+ trials)
2. Submit 20+ readings (mix of clean and blocked) before expecting ML confirmation
3. Check sensor mounting (perpendicular to water, stable position)

### Issue: Network simulation shows peaks arriving earlier upstream than downstream

**Cause:** Incorrect network topology (downstream node listed before upstream).

**Fix:** Ensure `build_sample_network()` orders nodes by hydrological flow direction.

### Issue: Scripts can't find `hydro` module

**Cause:** Path issues when running from wrong directory.

**Fix:**
```bash
cd scripts                  # Run from scripts directory
python flood_simulation.py
```

Or add to script:
```python
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

### Issue: Rasterio ImportError or DEM loading fails

**Cause:** Analysis dependencies not installed.

**Fix:**
```bash
pip install -e ".[analysis]"
```

---

## Security Considerations

### Sensor Data Integrity

- **No authentication yet:** Anyone with Serial Monitor can see raw readings
- **Future:** Implement ESP32 → HTTPS → cloud with API authentication

### Database Access

- **Local SQLite:** No access control, file-level security only
- **Deployment:** Use PostgreSQL with role-based access control

### Dashboard Deployment

- **Streamlit Community Cloud:** Public by default unless authentication added
- **Production:** Use Streamlit authentication or deploy behind auth proxy

### API Keys (if added)

- Store in `.env` (Git-ignored)
- Use environment variables: `os.getenv("API_KEY")`
- Never hardcode in source code

---

## Performance Considerations

### Blockage Detection

- **Fast:** O(1) orifice calculation per reading
- **ML overhead:** O(n) for n readings in window (typical n=50-100)
- **Bottleneck:** None for single-node real-time use

### Network Simulation

- **Complexity:** O(nodes × timesteps)
- **Typical:** 10 nodes × 500 timesteps = ~5,000 calculations (milliseconds)
- **Bottleneck:** Streamlit chart rendering, not computation

### Flood Simulation (Grid-Based)

- **Complexity:** O(cells × timesteps)
- **Typical:** 250×200 cells × 72 timesteps = ~3.6M calculations (seconds)
- **Bottleneck:** NumPy array operations (already optimized)

### Database Growth

- **Readings table:** ~100 KB per 1,000 readings (negligible)
- **Long-term:** Archive old data if > 1M readings (~100 MB)

---

## Deployment Scenarios

### Scenario 1: Hackathon Demo (Current State)

- **Hardware:** Single ESP32 + sensor in physical channel
- **Dashboard:** Streamlit running locally on laptop
- **Database:** Local SQLite file
- **Data entry:** Manual from Serial Monitor
- **Audience:** Judges, live demonstration

### Scenario 2: Pilot Deployment (5-10 Nodes)

- **Hardware:** ESP32 + WiFi → cloud MQTT broker
- **Dashboard:** Streamlit Community Cloud (public URL)
- **Database:** PostgreSQL on cloud (e.g., Railway, Render)
- **Data entry:** Automated via MQTT → webhook → database
- **Audience:** Municipal authorities, field testing

### Scenario 3: City-Scale Production (100+ Nodes)

- **Hardware:** Industrial IoT sensors + cellular/LoRaWAN
- **Dashboard:** Custom React/Vue frontend + FastAPI backend
- **Database:** PostgreSQL cluster with replication
- **Data entry:** Real-time streaming ingestion
- **Infrastructure:** Kubernetes, load balancers, monitoring
- **Audience:** Citizens, municipal control room, maintenance teams

---

## Contact and Support

**Primary Developer:** Aaditya Rai

**Repository:** https://github.com/nomadrai/FlowGuard

**Issues:** https://github.com/nomadrai/FlowGuard/issues

---

## Changelog

**v1.0.0 (2024-08-12):**
- Initial repository restructuring
- Standardized project layout (src/, tests/, docs/, scripts/)
- Created pyproject.toml with dependency management
- Professional README.md and CLAUDE.md documentation
- Python virtual environment setup
- .gitignore for Python projects
- Moved all markdown docs to docs/
- Moved analysis scripts to scripts/
- Updated import paths after restructuring

---

**End of CLAUDE.md**

When in doubt about any aspect of FlowGuard development, refer back to this document. Keep it updated as the project evolves.
