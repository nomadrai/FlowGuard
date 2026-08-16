"""
expected_rate.py — learn the depth-dependent NORMAL water-rise rate.

The inlet container widens with depth, so a constant rainfall inflow produces
a SLOWER rise at higher water levels. The ML pipeline must therefore never
compare the current rise rate against a single global threshold — it compares
it against the expected rate AT THE CURRENT DEPTH:

    expected_rise_rate = f(water_depth)

learned from experiments 1-4 (normal rainfall, no blockage). The ML signal is
then the deviation:

    rate_deviation = actual_rise_rate - expected_rise_rate

    positive deviation -> rising faster than normal at this depth -> BLOCKAGE
    zero/negative      -> normal rise, or falling water (blockage cleared)

Implementation: median rise rate per depth bin + linear interpolation
(a binned median is robust to the HC-SR04's ~±0.3 cm noise and makes no
parametric assumption about the container geometry). Predictions are clamped
at the trained depth range.
"""

import numpy as np


class ExpectedRateModel:
    """f(depth) = expected normal rise rate (cm/s), learned from clean experiments."""

    def __init__(self, n_bins=8):
        self.n_bins = n_bins
        self.bin_centers_ = None
        self.bin_rates_ = None

    def fit(self, water_depth, rate):
        """
        Fit on (water_depth, rate) pairs drawn from normal-rainfall, no-blockage
        experiments only (experiments 1-4).

        Fixed-width depth bins (0.5 cm) with a per-bin median: the level spends
        most time near equilibrium, so quantile bins would cram nearly all
        samples into the top depths and drown out the shallow rising phase.
        """
        depth = np.asarray(water_depth, dtype=float)
        rate = np.asarray(rate, dtype=float)
        mask = np.isfinite(depth) & np.isfinite(rate)
        depth, rate = depth[mask], rate[mask]
        if len(depth) < 4:
            raise ValueError("need at least 4 clean (depth, rate) samples to learn expected rate")

        width = 0.5  # cm — fixed bin width, ~2x the sensor noise floor
        min_samples = max(3, len(depth) // 100)  # drop sparsely visited depth bands
        bin_idx = np.floor(depth / width).astype(int)
        centers, rates = [], []
        for i in range(int(bin_idx.min()), int(bin_idx.max()) + 1):
            sel = bin_idx == i
            if sel.sum() >= min_samples:
                centers.append((i + 0.5) * width)
                rates.append(float(np.median(rate[sel])))

        if len(centers) < 2:
            # Not enough populated depth bands — fall back to a constant rate.
            centers, rates = [depth.min(), depth.max()], [float(np.median(rate))] * 2

        self.bin_centers_ = np.asarray(centers)
        self.bin_rates_ = np.asarray(rates)
        return self

    def predict(self, water_depth):
        """Expected rise rate at the given depths (cm/s)."""
        depth = np.asarray(water_depth, dtype=float)
        if self.bin_centers_ is None:
            raise RuntimeError("ExpectedRateModel.fit() must be called before predict()")
        return np.interp(depth, self.bin_centers_, self.bin_rates_)


if __name__ == "__main__":
    # Self-check: a widening container means the normal rate DECREASES with depth.
    rng = np.random.default_rng(7)
    depth = np.linspace(0.5, 8.0, 400)
    true_rate = 0.9 - 0.06 * depth  # slower rise at higher depth
    noisy = true_rate + rng.normal(0, 0.1, len(depth))
    model = ExpectedRateModel(n_bins=6).fit(depth, noisy)

    assert model.predict(np.array([1.0])) > model.predict(
        np.array([7.0])
    ), "expected rate must fall with depth (wider container)"
    assert abs(model.predict(np.array([4.0])) - 0.9 - (-0.06 * 4.0)) < 0.15
    print(
        f"expected_rate self-check passed: f(1cm)={model.predict([1.0])[0]:.3f} "
        f"f(7cm)={model.predict([7.0])[0]:.3f} cm/s"
    )
