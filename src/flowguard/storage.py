"""
storage.py — FlowGuard's persistent audit trail. Same reasoning as before:
this log is what lets you answer "prove it" to a civic body or court —
every calibration, every reading, every ML-confirmed blockage event is
timestamped and stored locally.
"""

import sqlite3
import pandas as pd
from datetime import datetime

import os

# Use data directory for database if it exists, otherwise use project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
DB_NAME = os.path.join(_DATA_DIR, "flowguard_history.db") if os.path.exists(_DATA_DIR) else "flowguard_history.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS calibration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            cd REAL,
            pour_volume_ml REAL,
            pour_time_sec REAL,
            steady_h_cm REAL,
            a_clean_cm2 REAL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS blockage_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            node TEXT,
            water_level_cm REAL,
            inflow_q_cm3s REAL,
            calculated_area_cm2 REAL,
            blockage_pct REAL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS blockage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            node TEXT,
            blockage_pct REAL,
            ml_confirmed INTEGER,
            forecast_days_to_critical REAL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS network_simulation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            rainfall_peak REAL,
            num_nodes INTEGER,
            downstream_peak_outflow REAL,
            downstream_peak_delay_steps INTEGER
        )
    ''')

    conn.commit()
    conn.close()


def log_calibration(cd, pour_volume_ml, pour_time_sec, steady_h_cm, a_clean_cm2):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO calibration_log (timestamp, cd, pour_volume_ml, pour_time_sec, steady_h_cm, a_clean_cm2) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), float(cd), float(pour_volume_ml),
         float(pour_time_sec), float(steady_h_cm), float(a_clean_cm2))
    )
    conn.commit()
    conn.close()


def log_reading(node, water_level_cm, inflow_q_cm3s, calculated_area_cm2, blockage_pct):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO blockage_readings (timestamp, node, water_level_cm, inflow_q_cm3s, calculated_area_cm2, blockage_pct) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), node, float(water_level_cm),
         float(inflow_q_cm3s), float(calculated_area_cm2) if calculated_area_cm2 is not None else None,
         float(blockage_pct) if blockage_pct is not None else None)
    )
    conn.commit()
    conn.close()


def log_blockage_event(node, blockage_pct, ml_confirmed, forecast_days_to_critical):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO blockage_events (timestamp, node, blockage_pct, ml_confirmed, forecast_days_to_critical) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), node, float(blockage_pct),
         int(ml_confirmed), float(forecast_days_to_critical) if forecast_days_to_critical is not None else None)
    )
    conn.commit()
    conn.close()


def log_network_run(rainfall_peak, num_nodes, downstream_peak_outflow, downstream_peak_delay_steps):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO network_simulation_runs (timestamp, rainfall_peak, num_nodes, downstream_peak_outflow, downstream_peak_delay_steps) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), float(rainfall_peak), int(num_nodes),
         float(downstream_peak_outflow), int(downstream_peak_delay_steps))
    )
    conn.commit()
    conn.close()


def get_calibration_log():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM calibration_log ORDER BY id DESC", conn)
    conn.close()
    return df


def get_readings(node=None):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    if node:
        df = pd.read_sql_query("SELECT * FROM blockage_readings WHERE node = ? ORDER BY id DESC", conn, params=(node,))
    else:
        df = pd.read_sql_query("SELECT * FROM blockage_readings ORDER BY id DESC", conn)
    conn.close()
    return df


def get_blockage_events():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM blockage_events ORDER BY id DESC", conn)
    conn.close()
    return df


def get_network_runs():
    init_db()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM network_simulation_runs ORDER BY id DESC", conn)
    conn.close()
    return df
