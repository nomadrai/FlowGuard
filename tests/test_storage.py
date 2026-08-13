"""
Tests for storage module (SQLite audit trail).

Uses pytest's tmp_path + monkeypatch to redirect storage.DB_NAME to a
throwaway database, so these tests never touch the real
data/flowguard_history.db.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from flowguard import storage


def _use_temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_flowguard_history.db")
    monkeypatch.setattr(storage, "DB_NAME", db_path)
    storage.init_db()
    return db_path


def test_init_db_creates_all_tables(tmp_path, monkeypatch):
    db_path = _use_temp_db(tmp_path, monkeypatch)

    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()

    expected = {"calibration_log", "blockage_readings", "blockage_events", "network_simulation_runs"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_log_and_get_calibration(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    storage.log_calibration(cd=0.0543, pour_volume_ml=500.0, pour_time_sec=10.0,
                             steady_h_cm=8.0, a_clean_cm2=12.0)
    df = storage.get_calibration_log()

    assert len(df) == 1
    assert abs(df.iloc[0]["cd"] - 0.0543) < 1e-9


def test_log_and_get_readings(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    storage.log_reading("Physical_Node_1", water_level_cm=8.0, inflow_q_cm3s=50.0,
                         calculated_area_cm2=12.0, blockage_pct=0.0)
    storage.log_reading("Physical_Node_1", water_level_cm=10.0, inflow_q_cm3s=50.0,
                         calculated_area_cm2=9.3, blockage_pct=22.5)

    all_readings = storage.get_readings()
    assert len(all_readings) == 2

    node_readings = storage.get_readings("Physical_Node_1")
    assert len(node_readings) == 2

    other_node = storage.get_readings("Nonexistent_Node")
    assert len(other_node) == 0


def test_log_and_get_blockage_events(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    storage.log_blockage_event("Physical_Node_1", blockage_pct=22.5,
                                ml_confirmed=1, forecast_days_to_critical=6.9)
    df = storage.get_blockage_events()

    assert len(df) == 1
    assert df.iloc[0]["ml_confirmed"] == 1
    assert abs(df.iloc[0]["forecast_days_to_critical"] - 6.9) < 1e-9


def test_log_and_get_network_runs(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    storage.log_network_run(rainfall_peak=100.0, num_nodes=3,
                             downstream_peak_outflow=80.1, downstream_peak_delay_steps=10)
    df = storage.get_network_runs()

    assert len(df) == 1
    assert df.iloc[0]["num_nodes"] == 3


def test_readings_ordered_most_recent_first(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    storage.log_reading("N1", 1.0, 10.0, 1.0, 0.0)
    storage.log_reading("N1", 2.0, 10.0, 1.0, 5.0)
    storage.log_reading("N1", 3.0, 10.0, 1.0, 10.0)

    df = storage.get_readings("N1")
    assert list(df["blockage_pct"]) == [10.0, 5.0, 0.0], "Most recent reading should be first"
