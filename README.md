# FlowGuard

**Physics-based drain blockage detection and flood early warning system for smart cities.**

FlowGuard combines IoT sensors, hydraulic physics, machine learning, and network cascade modeling to detect drainage blockages in real-time and predict downstream flood impacts across urban drainage networks.

---

## Problem

Urban flooding in cities like Nagpur causes:
- Infrastructure damage
- Traffic disruption  
- Public health risks
- Economic losses

**Root cause:** Drain blockages from debris accumulation go undetected until flooding occurs. Current inspection methods (manual checks, CCTV) are reactive, labor-intensive, and cannot scale citywide.

---

## Solution

FlowGuard deploys low-cost IoT sensors at strategic drainage points to:

1. **Detect blockages** using calibrated orifice equation physics
2. **Confirm with ML** (Isolation Forest) to filter sensor noise from genuine blockages
3. **Forecast trends** to estimate days until critical blockage
4. **Model cascade effects** using Muskingum routing to predict downstream flood timing and magnitude
5. **Maintain audit trail** for civic accountability and compliance

---

## Key Features

- **Physics-first approach:** Orifice equation with field-calibrated discharge coefficient (Cd)
- **ML confirmation layer:** Isolation Forest distinguishes genuine blockage trends from sensor noise
- **Network simulation:** Muskingum hydrological routing models flood wave propagation through drainage network
- **Real-time dashboard:** Streamlit interface for monitoring, calibration, and network simulation
- **Complete audit trail:** SQLite database logs every calibration, reading, and confirmed event
- **Low-cost hardware:** ESP32 + HC-SR04 ultrasonic sensor (~$5-10 USD per node)

---

## Technology Stack

**Hardware:**
- ESP32 microcontroller
- HC-SR04 ultrasonic distance sensor

**Core Application:**
- Python 3.10+
- NumPy, Pandas (numerical computing)
- scikit-learn (ML anomaly detection)
- Streamlit (dashboard)
- SQLite (audit trail)

**Analysis Tools:**
- Rasterio (DEM processing)
- SciPy (hydrological modeling)
- Matplotlib (visualization)
- Flask + Folium (web mapping)

---

## Project Structure

```
FlowGuard/
├── src/
│   └── flowguard/
│       ├── __init__.py
│       ├── blockage_detector.py    # Orifice physics + ML + forecasting
│       ├── network_simulation.py   # Muskingum routing for cascade modeling
│       ├── storage.py               # SQLite audit trail
│       ├── flowguard_dashboard.py  # Streamlit dashboard
│       └── webviewer/              # Flask web viewer for flood risk maps
├── scripts/
│   ├── hydro.py                     # DEM processing utilities
│   ├── flood_simulation.py          # Grid-based flood simulation
│   ├── flood_risk_analysis.py       # Citywide risk assessment
│   └── ...
├── data/
│   ├── nagpur_drainage/             # Nagpur drainage network data
│   └── flowguard_history.db         # Audit trail database
├── docs/                            # Project documentation
├── tests/                           # Test suite
├── assets/                          # Presentation materials
├── .venv/                           # Python virtual environment (not in Git)
├── .gitignore
├── pyproject.toml                   # Project configuration
├── README.md                        # Setup Guide
└── CLAUDE.md                        # AI agent operating guide
```

---

## Prerequisites

- **Python 3.10 or higher**
- **Git**
- **pip** (Python package manager)

For hardware deployment:
- ESP32 development board
- HC-SR04 ultrasonic sensor
- Physical drainage channel for calibration

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/nomadrai/FlowGuard.git
cd FlowGuard
```

### 2. Create and activate virtual environment

**Linux/macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

**Core application:**
```bash
pip install -e .
```

**With analysis tools:**
```bash
pip install -e ".[analysis]"
```

**With web viewer:**
```bash
pip install -e ".[webviewer]"
```

**Development (includes testing and linting):**
```bash
pip install -e ".[dev]"
```

---

## Running FlowGuard

### Dashboard (Primary Interface)

```bash
streamlit run src/flowguard/flowguard_dashboard.py
```

The dashboard opens the ESP32 serial port itself and streams readings live —
no separate terminal or data-entry step needed (see `Live Demo Workflow`
below). `python src/flowguard/serial_reader.py` still works standalone for a
terminal view of the same stream.

The dashboard provides:
- **Calibration panel:** Enter physical measurements to calculate discharge coefficient (Cd)
- **Physical node monitoring:** Submit real-time sensor readings
- **Blockage detection:** Physics-based calculation with ML confirmation
- **Trend forecasting:** Estimate days until critical blockage
- **Network cascade simulation:** Model flood propagation through drainage network
- **Audit trail:** Complete history of calibrations, readings, and events

### Standalone Testing

**Test blockage detector (physics + ML):**
```bash
python src/flowguard/blockage_detector.py
```

**Test network simulation:**
```bash
python src/flowguard/network_simulation.py
```

### Analysis Scripts

**Run flood simulation for Nagpur:**
```bash
cd scripts
python flood_simulation.py
```

**Run flood risk analysis:**
```bash
cd scripts
python flood_risk_analysis.py
```

**Launch web viewer for flood maps:**
```bash
python src/flowguard/webviewer/app.py
```

---

## Usage

### Hardware Setup

**Physical geometry (fixed — do not change these values):**
- Drainage pipe: round, diameter **1.90 cm** → clean area = π × (0.95)² ≈ **2.8353 cm²**
- Inlet box: rectangular, base area **308 cm²** (water collects here above the pipe exit)

### Hardware Calibration

1. **No area measurement needed** — the clean pipe area (2.8353 cm²) is pre-set in code.

2. **Perform calibration pour:**
   - Pour a known volume (e.g., 200 mL) into the inlet box at a steady rate
   - Time the pour duration
   - Record steady-state water height from the sensor
   - Repeat 3 times for accuracy

3. **Set inflow rate and calculate Cd in the dashboard:**
   - Enter the **rainfall inflow rate (mL/s)** in the sidebar — this is your pour rate (volume ÷ time). Set this once per session before submitting any readings.
   - Enter: pour volume, pour time, steady height (clean pipe area is auto-filled)
   - Click "Calibrate Cd"
   - System calculates your channel's discharge coefficient

### Real-time Monitoring

1. **Establish baseline (clean pipe):**
   - Set inflow rate in sidebar to match your current rainfall/pour rate
   - Submit 10-15 readings with clean (unblocked) pipe
   - Only enter water height per reading — inflow Q comes from the sidebar

2. **Monitor for blockages:**
   - Continue submitting water-height readings during operation
   - System calculates blockage % using sidebar inflow rate each time
   - ML layer confirms genuine blockage trends

3. **Respond to alerts:**
   - High blockage % + ML confirmation = maintenance needed
   - Trend forecast shows days until critical threshold
   - Network simulation predicts downstream flood impacts

### Network Cascade Simulation

1. Select upstream rainfall intensity
2. Click "Run network simulation"
3. View flood wave propagation:
   - Peak arrival delays (hydrograph lag)
   - Peak attenuation (flood smoothing)
   - Downstream impact timing

---

## Development

### Running Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black src/ tests/
```

### Linting

```bash
ruff check src/ tests/
```

### Type Checking

```bash
mypy src/
```

---

## Live Demo Workflow

**Suggested sequence for judging/presentation:**

1. **Show hardware setup:** ESP32, sensor, physical channel
2. **Demonstrate clean channel:** Run the dashboard (it opens the ESP32 port itself), pour water, watch readings stream in and show ~0% blockage
3. **Live blockage insertion:** Insert obstruction (e.g., sponge) in front of audience
4. **Show detection:** Pour again, watch the verdict flip to BLOCKAGE DETECTED and the rise rate jump above the normal rate
5. **Network cascade:** Run simulation to show citywide flood propagation
6. **Audit trail:** Display compliance/accountability features
7. **Close with value proposition:** Real-time detection + citywide prediction + civic accountability

**Pro tip:** Build 15-20 baseline readings (clean + blocked) *before* the presentation so ML confirmation works reliably during live demo.

---

## Documentation

See `docs/` directory for detailed documentation:

- **COMPLETE_BUILD_STEPS.md:** Step-by-step hardware and software setup
- **PS_AND_SOLUTION.md:** Problem statement and solution approach
- **HARDWARE_ASSEMBLY.md:** Physical sensor wiring and assembly
- **CALIBRATION_GUIDE.md:** Detailed calibration procedures
- **FULL_HARDWARE_BUILD.md:** Complete hardware build instructions
- **PROJECT_BRIEF_FOR_HANDOFF.md:** Project handoff documentation

---

## Architecture

### Core Components

1. **blockage_detector.py**
   - Orifice equation: Q = Cd × A × √(2gh)
   - Field-calibrated Cd removes viscosity assumptions
   - Isolation Forest ML detects genuine blockage trends
   - Linear trend forecasting for maintenance scheduling

2. **network_simulation.py**
   - Muskingum routing: cascade flood wave through network
   - Models hydrograph delay and attenuation
   - Simulates rainfall pulses and downstream impacts

3. **storage.py**
   - SQLite audit trail for compliance
   - Logs: calibrations, readings, confirmed events, simulations
   - Supports civic accountability requirements

4. **flowguard_dashboard.py**
   - Streamlit interface integrating all components
   - Real-time monitoring and simulation
   - Historical data visualization

### Data Flow

```
Sensor → ESP32 → Serial Monitor → Dashboard Input
                                      ↓
                         Orifice Physics Calculation
                                      ↓
                            ML Confirmation Layer
                                      ↓
                              Trend Forecasting
                                      ↓
                           Network Cascade Model
                                      ↓
                              Audit Trail Log
```

---

## Troubleshooting

**Issue: Dashboard shows "ModuleNotFoundError"**
- Ensure virtual environment is activated
- Run `pip install -e .` from project root

**Issue: Sensor readings unstable**
- Check HC-SR04 wiring (VCC→5V, Trig→GPIO, Echo→GPIO, GND→GND)
- Verify sensor is perpendicular to water surface
- Calibrate with multiple pour trials for robust Cd

**Issue: ML not confirming blockages**
- Insufficient baseline: need 15-20 readings minimum
- Build clean + blocked history before expecting confirmation
- ML requires trend pattern, not single anomalous point

**Issue: Network simulation shows unrealistic flood timing**
- Check Muskingum K (travel time) and X (weighting) parameters
- Verify network topology (upstream → downstream ordering)
- Ensure rainfall intensity is realistic for local conditions

**Issue: Analysis scripts fail**
- Install analysis dependencies: `pip install -e ".[analysis]"`
- Ensure DEM data exists in `data/nagpur_drainage/`
- Check file paths in script configuration

---

## Contributing

Contributions are welcome. Please:

1. Fork the repository
2. Create a feature branch
3. Make focused, well-tested changes
4. Run tests and linting before committing
5. Submit a pull request with clear description

---

## License

MIT License - see LICENSE file for details

---

## Acknowledgments

- Nagpur Municipal Corporation for drainage network data
- OpenStreetMap contributors for urban infrastructure data
- SRTM/ASTER for DEM elevation data
- Ambazari Lake and Nag River hydrological systems as case study

---

## Contact

For questions, issues, or collaboration inquiries:
- GitHub: [nomadrai/FlowGuard](https://github.com/nomadrai/FlowGuard)
- Issues: [GitHub Issues](https://github.com/nomadrai/FlowGuard/issues)

---

**FlowGuard** — *Detecting blockages before floods happen.*
