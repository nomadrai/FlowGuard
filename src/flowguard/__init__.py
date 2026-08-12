"""
FlowGuard — Physics-based drain blockage detection and flood early warning system.

Core modules:
- blockage_detector: Orifice equation physics, ML confirmation, trend forecasting
- network_simulation: Muskingum routing for cascade flood modeling
- storage: SQLite audit trail for calibration, readings, and events
- flowguard_dashboard: Streamlit dashboard integrating all components
"""

__version__ = "1.0.0"
