"""
network_simulation.py — models Nagpur's connected water bodies (Ambazari
Lake -> Nag River segments -> downstream) as a graph, and uses the
Muskingum routing method (a standard, textbook hydrological flow-routing
technique) to predict how a rainfall pulse propagates and attenuates
through the network over time.

This is SOFTWARE-ONLY — it completes the citywide network story around
your one real physical hardware node, the same "real + simulated" pattern
used successfully before. No new hardware needed for this layer.

Muskingum routing, in plain terms: given an inflow hydrograph (how much
water enters a channel segment over time) and two channel-specific
constants (K = travel time through the segment, X = how much the segment
"smooths out" the flood peak), it predicts the outflow hydrograph — i.e.
how much water reaches the NEXT segment, and when.
"""

import numpy as np


def muskingum_route(inflow_series, k, x, dt):
    """
    inflow_series: list/array of inflow values over time
    k: storage time constant for this channel segment (same time units as dt)
    x: weighting factor, 0 <= x <= 0.5 (0 = maximum attenuation, 0.5 = minimum)
    dt: time step between inflow readings (same units as k)

    Returns: outflow_series, same length as inflow_series.
    """
    inflow = np.array(inflow_series, dtype=float)
    n = len(inflow)
    outflow = np.zeros(n)
    outflow[0] = inflow[0]  # assume steady state at t=0

    denom = (2 * k * (1 - x)) + dt
    c0 = (dt - 2 * k * x) / denom
    c1 = (dt + 2 * k * x) / denom
    c2 = (2 * k * (1 - x) - dt) / denom

    assert abs((c0 + c1 + c2) - 1.0) < 1e-6, "Muskingum coefficients don't sum to 1 — check k, x, dt"

    for i in range(1, n):
        outflow[i] = c0 * inflow[i] + c1 * inflow[i - 1] + c2 * outflow[i - 1]
        outflow[i] = max(outflow[i], 0)

    return outflow


class WaterNetworkNode:
    def __init__(self, name, k, x, node_type="drain"):
        self.name = name
        self.k = k
        self.x = x
        self.node_type = node_type
        self.inflow = None
        self.outflow = None


class WaterNetwork:
    def __init__(self):
        self.nodes = []

    def add_node(self, name, k, x, node_type="drain"):
        self.nodes.append(WaterNetworkNode(name, k, x, node_type))

    def simulate(self, rainfall_inflow_series, dt=1.0):
        current_inflow = np.array(rainfall_inflow_series, dtype=float)
        for node in self.nodes:
            node.inflow = current_inflow
            node.outflow = muskingum_route(current_inflow, node.k, node.x, dt)
            current_inflow = node.outflow
        return self.nodes


def generate_rainfall_pulse(duration_steps=30, peak_step=10, peak_value=100, base_value=5):
    t = np.arange(duration_steps)
    pulse = np.full(duration_steps, base_value, dtype=float)
    rising = t <= peak_step
    falling = t > peak_step
    pulse[rising] = base_value + (peak_value - base_value) * (t[rising] / peak_step)
    falling_len = duration_steps - peak_step - 1
    if falling_len > 0:
        pulse[falling] = peak_value - (peak_value - base_value) * ((t[falling] - peak_step) / falling_len)
    return pulse


if __name__ == "__main__":
    print("=== Building Nagpur-like water network ===")
    network = WaterNetwork()
    network.add_node("Ambazari Lake", k=2.0, x=0.2, node_type="lake")
    network.add_node("Nag River Segment 1", k=3.0, x=0.25, node_type="drain")
    network.add_node("Nag River Segment 2 (downstream)", k=4.0, x=0.3, node_type="drain")

    rainfall = generate_rainfall_pulse(duration_steps=30, peak_step=10, peak_value=100, base_value=5)
    print(f"Rainfall pulse peak: {rainfall.max():.1f} at step {rainfall.argmax()}")

    nodes = network.simulate(rainfall, dt=1.0)

    for node in nodes:
        peak_out = node.outflow.max()
        peak_time = node.outflow.argmax()
        print(f"{node.name}: peak outflow {peak_out:.1f} at step {peak_time} "
              f"(inflow peak was at step {node.inflow.argmax()})")

    print("\nExpected physical behaviour: peak outflow time should get LATER "
          "and peak magnitude should get LOWER at each downstream node "
          "(the flood wave arrives later and is smoothed out as it travels).")

    peak_times = [n.outflow.argmax() for n in nodes]
    times_increasing = all(peak_times[i] <= peak_times[i + 1] for i in range(len(peak_times) - 1))
    print(f"\nPeak arrival times are non-decreasing downstream: {times_increasing}")
    print("All self-tests ran without errors.")
