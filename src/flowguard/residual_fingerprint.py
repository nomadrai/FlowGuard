"""
residual_fingerprint.py
------------------------
"Blockage Fingerprinting" layer for FlowGuard.

Extends the single-node Manning's-equation blockage detection
(blockage_detector.py) across the simulated drainage network
(network_simulation.py) using a predicted-vs-observed RESIDUAL:

    predicted = Muskingum-routed hydrograph assuming each segment
                is at its DESIGN (clean) capacity
    observed  = the hydrograph the network actually produces
                (real sensor data for the one physical node;
                 synthetic / operator-injected for demo nodes)

A sustained, statistically significant gap between predicted and
observed flow at a segment is evidence that segment's real open
area is smaller than its design area -> encroachment / blockage,
inferred continuously from data, no manual survey required.

IMPORTANT HONESTY NOTE (keep this in the pitch):
  - For the ONE real physical node, "observed" comes from live
    HC-SR04 readings run through Manning's equation. This part is real.
  - For every other node in the network, there is no hardware yet,
    so "observed" here is either (a) assumed equal to predicted
    (no blockage) or (b) a synthetic pulse you inject to DEMO the
    method. Never present (b) as a live detection to judges -
    present it as "this is how the same physics scales once more
    nodes are deployed."

Drop this file into src/flowguard/ alongside network_simulation.py
and blockage_detector.py. It imports from both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

# These come from your existing modules - adjust import paths as needed
# from .network_simulation import muskingum_route, WaterNetwork, WaterNetworkNode
# from .blockage_detector import calibrate_n, calculate_area_manning  # (post-Manning's-switch names)


# ---------------------------------------------------------------------------
# 1. Segment definition
# ---------------------------------------------------------------------------

@dataclass
class ChannelSegment:
    """Design (clean-channel) parameters for one drainage segment."""
    segment_id: str
    design_area_cm2: float       # cross-sectional area when NOT blocked
    manning_n: float              # design roughness coefficient
    slope: float                  # channel bed slope (m/m)
    muskingum_k: float            # Muskingum storage constant (hours)
    muskingum_x: float            # Muskingum weighting factor (0-0.5)
    has_real_sensor: bool = False # True only for your physical HC-SR04 node


# ---------------------------------------------------------------------------
# 2. Predicted hydrograph (clean-channel assumption)
# ---------------------------------------------------------------------------

def _call_muskingum_route(fn, inflow_series, segment, dt_hours):
    """
    Calls the real muskingum_route() regardless of its exact parameter
    names, by inspecting its signature and mapping our values onto
    whatever names it uses. Avoids hardcoding a signature that may not
    match your actual implementation.
    """
    import inspect
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())

    # candidate name -> value, tried in order of likelihood
    candidates = {
        "inflow": inflow_series, "inflow_series": inflow_series,
        "I": inflow_series, "Q_in": inflow_series, "inflows": inflow_series,
        "K": segment.muskingum_k, "k": segment.muskingum_k,
        "X": segment.muskingum_x, "x": segment.muskingum_x,
        "dt": dt_hours, "dt_hours": dt_hours, "delta_t": dt_hours, "timestep": dt_hours,
    }

    kwargs = {p: candidates[p] for p in params if p in candidates}
    missing = [p for p in params if p not in kwargs and sig.parameters[p].default is inspect.Parameter.empty]

    if missing:
        # Fall back to positional call in declared order using our best guesses,
        # for any required param we couldn't name-match.
        positional_guess = {
            0: inflow_series, 1: segment.muskingum_k,
            2: segment.muskingum_x, 3: dt_hours,
        }
        args = [positional_guess.get(i) for i in range(len(params))]
        print(f"[residual_fingerprint] Warning: could not name-match params {missing} "
              f"for muskingum_route{tuple(params)} - calling positionally instead. "
              f"If this is wrong, tell me the real signature and I'll hardcode it.")
        return fn(*args)

    return fn(**kwargs)


def predicted_hydrograph(inflow_series: np.ndarray, segment: ChannelSegment,
                          dt_hours: float = 1.0) -> np.ndarray:
    """
    Route an inflow pulse through this segment assuming it is at
    DESIGN capacity (no blockage). Auto-adapts to your real
    muskingum_route() signature - see _call_muskingum_route above.
    """
    try:
        from network_simulation import muskingum_route  # your real module
    except ImportError:
        muskingum_route = predicted_hydrograph.__globals__.get("muskingum_route")
        if muskingum_route is None:
            raise
    return _call_muskingum_route(muskingum_route, inflow_series, segment, dt_hours)


# ---------------------------------------------------------------------------
# 3. Observed hydrograph
# ---------------------------------------------------------------------------

def observed_hydrograph_real_node(water_levels_cm: np.ndarray, segment: ChannelSegment,
                                   n_calibrated: float) -> np.ndarray:
    """
    For the REAL physical node only. Converts a live series of
    HC-SR04 water-level readings into a flow series using Manning's
    equation with the CALIBRATED (possibly reduced) roughness/area,
    i.e. this reflects whatever the channel is actually doing right now.
    """
    calculate_area_manning = observed_hydrograph_real_node.__globals__.get("calculate_area_manning")
    if calculate_area_manning is None:
        try:
            from blockage_detector import calculate_area_manning
        except ImportError as e:
            raise ImportError(
                "Could not find calculate_area_manning() in blockage_detector.py. "
                "If you haven't renamed your orifice-equation function to a Manning's "
                "equation function yet, do that first - or tell me its current name "
                "and I'll match it here."
            ) from e
    return np.array([
        calculate_area_manning(h, n_calibrated, segment.slope) for h in water_levels_cm
    ])


def observed_hydrograph_demo_node(predicted: np.ndarray, injected_capacity_loss_pct: float
                                   ) -> np.ndarray:
    """
    For nodes WITHOUT hardware. Synthetically shrinks the predicted
    hydrograph to simulate what a blocked segment would look like,
    for demo purposes ONLY. Label this clearly as simulated in the UI.
    """
    factor = 1.0 - (injected_capacity_loss_pct / 100.0)
    return predicted * factor


# ---------------------------------------------------------------------------
# 4. Residual scoring
# ---------------------------------------------------------------------------

@dataclass
class ResidualResult:
    segment_id: str
    peak_delay_hours: float       # observed peak arrives later than predicted
    peak_attenuation_pct: float   # observed peak is lower than predicted, %
    mean_area_deficit_pct: float  # avg gap between predicted & observed area equivalent
    is_real_data: bool
    flagged: bool = False


def residual_score(predicted: np.ndarray, observed: np.ndarray, segment: ChannelSegment,
                    dt_hours: float = 1.0) -> ResidualResult:
    """
    Core comparison. Three signals, any one being large + sustained
    is evidence of blockage:
      1. Timing: does the observed peak arrive later than predicted?
         (blocked channels drain slower -> delayed peak)
      2. Magnitude: is the observed peak lower than predicted?
         (blocked channels pass less peak flow)
      3. Area-equivalent deficit: averaged gap, expressed as a %,
         directly comparable to your existing single-node blockage %.
    """
    pred_peak_idx = int(np.argmax(predicted))
    obs_peak_idx = int(np.argmax(observed))
    peak_delay_hours = (obs_peak_idx - pred_peak_idx) * dt_hours

    pred_peak = predicted[pred_peak_idx]
    obs_peak = observed[obs_peak_idx]
    peak_attenuation_pct = max(0.0, (pred_peak - obs_peak) / pred_peak * 100.0) if pred_peak > 0 else 0.0

    # area-equivalent deficit: treat flow ratio as a proxy for area ratio
    # (both scale with open cross-section under comparable head/slope)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(predicted > 0, observed / predicted, 1.0)
    mean_area_deficit_pct = max(0.0, (1.0 - float(np.mean(ratio))) * 100.0)

    return ResidualResult(
        segment_id=segment.segment_id,
        peak_delay_hours=round(peak_delay_hours, 2),
        peak_attenuation_pct=round(peak_attenuation_pct, 2),
        mean_area_deficit_pct=round(mean_area_deficit_pct, 2),
        is_real_data=segment.has_real_sensor,
    )


# ---------------------------------------------------------------------------
# 5. Sustained-signal check (reuse your Isolation Forest philosophy:
#    one noisy reading should never trigger a flag on its own)
# ---------------------------------------------------------------------------

def sustained_check(history: list[ResidualResult], threshold_pct: float = 15.0,
                     min_consecutive: int = 3) -> bool:
    """
    Only flag a segment once mean_area_deficit_pct has stayed above
    threshold for min_consecutive consecutive evaluation windows.
    Mirrors the "no single-splash false alarms" logic you already
    use for the real node's Isolation Forest confirmation layer.
    """
    if len(history) < min_consecutive:
        return False
    recent = history[-min_consecutive:]
    return all(r.mean_area_deficit_pct >= threshold_pct for r in recent)


# ---------------------------------------------------------------------------
# 6. Public entry point
# ---------------------------------------------------------------------------

def evaluate_segment(segment: ChannelSegment, inflow_series: np.ndarray,
                      history: list[ResidualResult],
                      real_water_levels_cm: np.ndarray | None = None,
                      real_n_calibrated: float | None = None,
                      demo_injected_loss_pct: float | None = None,
                      dt_hours: float = 1.0) -> ResidualResult:
    """
    Run one evaluation cycle for a segment and append to its history.
    Call this on a schedule (e.g. every reading interval) per segment.
    """
    predicted = predicted_hydrograph(inflow_series, segment, dt_hours)

    if segment.has_real_sensor:
        assert real_water_levels_cm is not None and real_n_calibrated is not None, \
            "Real node requires water_levels_cm and calibrated n"
        observed = observed_hydrograph_real_node(real_water_levels_cm, segment, real_n_calibrated)
    else:
        loss = demo_injected_loss_pct or 0.0
        observed = observed_hydrograph_demo_node(predicted, loss)

    result = residual_score(predicted, observed, segment, dt_hours)
    history.append(result)
    result.flagged = sustained_check(history)
    return result


if __name__ == "__main__":
    # Self-test, mirrors the style of your other modules
    seg_real = ChannelSegment("real_node_01", design_area_cm2=2.8353, manning_n=0.013,
                               slope=0.001, muskingum_k=2.0, muskingum_x=0.2, has_real_sensor=True)
    seg_demo = ChannelSegment("nag_river_seg_04", design_area_cm2=500.0, manning_n=0.03,
                               slope=0.0008, muskingum_k=3.0, muskingum_x=0.15, has_real_sensor=False)

    inflow = np.array([10, 15, 25, 40, 60, 55, 40, 25, 15, 10], dtype=float)

    # simple stand-in for muskingum_route/calculate_area_manning during self-test only
    def _mock_route(inflow, K, X, dt):
        return inflow * 0.9  # trivial attenuation stand-in

    def _mock_area(h, n, s):
        return h * 0.5

    predicted_hydrograph.__globals__["muskingum_route"] = _mock_route
    observed_hydrograph_real_node.__globals__["calculate_area_manning"] = _mock_area

    history_demo: list[ResidualResult] = []
    for cycle_loss in [5, 18, 22, 24]:  # simulate worsening blockage over time
        r = evaluate_segment(seg_demo, inflow, history_demo, demo_injected_loss_pct=cycle_loss)
        print(r, "FLAGGED" if r.flagged else "")

    print("\nSelf-test complete.")
