"""
Tests for network_simulation module (Muskingum flood routing).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
from flowguard.network_simulation import (
    muskingum_route, WaterNetwork, generate_rainfall_pulse,
)


def test_muskingum_route_output_shape():
    inflow = [5, 5, 10, 20, 30, 20, 10, 5, 5]
    outflow = muskingum_route(inflow, k=2.0, x=0.2, dt=1.0)

    assert len(outflow) == len(inflow), "Outflow series should match inflow length"
    assert outflow[0] == inflow[0], "Outflow should start at steady state (t=0)"


def test_muskingum_route_never_negative():
    # A sharply falling inflow can drive naive routing negative; the
    # implementation clamps outflow at 0.
    inflow = [100, 100, 0, 0, 0, 0]
    outflow = muskingum_route(inflow, k=5.0, x=0.0, dt=1.0)

    assert all(o >= 0 for o in outflow), "Outflow should never go negative"


def test_network_peaks_delayed_and_attenuated_downstream():
    network = WaterNetwork()
    network.add_node("Ambazari Lake", k=2.0, x=0.2, node_type="lake")
    network.add_node("Nag River Segment 1", k=3.0, x=0.25, node_type="drain")
    network.add_node("Nag River Segment 2 (downstream)", k=4.0, x=0.3, node_type="drain")

    rainfall = generate_rainfall_pulse(duration_steps=30, peak_step=10, peak_value=100, base_value=5)
    nodes = network.simulate(rainfall, dt=1.0)

    peak_times = [n.outflow.argmax() for n in nodes]
    peak_values = [n.outflow.max() for n in nodes]

    assert all(peak_times[i] <= peak_times[i + 1] for i in range(len(peak_times) - 1)), \
        "Each downstream node's peak should arrive no earlier than the previous node's"
    assert all(peak_values[i] >= peak_values[i + 1] for i in range(len(peak_values) - 1)), \
        "Each downstream node's peak should be no higher than the previous node's (attenuation)"


def test_generate_rainfall_pulse_shape():
    pulse = generate_rainfall_pulse(duration_steps=30, peak_step=10, peak_value=100, base_value=5)

    assert len(pulse) == 30
    assert pulse.argmax() == 10, "Pulse should peak at the configured peak_step"
    assert np.isclose(pulse.max(), 100), "Pulse should reach the configured peak_value"
    assert pulse[0] == 5, "Pulse should start at base_value"


if __name__ == "__main__":
    print("Running network_simulation tests...")
    test_muskingum_route_output_shape()
    print("✓ test_muskingum_route_output_shape passed")

    test_muskingum_route_never_negative()
    print("✓ test_muskingum_route_never_negative passed")

    test_network_peaks_delayed_and_attenuated_downstream()
    print("✓ test_network_peaks_delayed_and_attenuated_downstream passed")

    test_generate_rainfall_pulse_shape()
    print("✓ test_generate_rainfall_pulse_shape passed")

    print("\nAll tests passed!")
