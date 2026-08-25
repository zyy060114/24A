"""Q5 velocity-ratio interface for the p=0.450342 m extension scenario."""
from __future__ import annotations

import math
import numpy as np


def compute_transfer_coefficients(positions: np.ndarray, tangents: np.ndarray):
    positions = np.asarray(positions, dtype=float)
    tangents = np.asarray(tangents, dtype=float)
    if positions.shape != tangents.shape or positions.ndim != 2 or positions.shape[1] != 2:
        raise ValueError("positions and tangents must have shape (n, 2)")
    coefficients = np.ones(len(positions), dtype=float)
    denominators = np.empty(len(positions) - 1, dtype=float)
    for i in range(1, len(positions)):
        chord = positions[i] - positions[i - 1]
        numerator = float(np.dot(chord, tangents[i - 1]))
        denominator = float(np.dot(chord, tangents[i]))
        if abs(denominator) < 1e-12:
            raise ArithmeticError(f"near-singular velocity denominator at handle {i}")
        denominators[i - 1] = denominator
        coefficients[i] = coefficients[i - 1] * numerator / denominator
    return coefficients, denominators


def head_speed_limit(k_max: float, speed_cap: float = 2.0) -> float:
    if not math.isfinite(k_max) or k_max <= 0.0:
        raise ValueError("k_max must be finite and positive")
    return float(speed_cap) / float(k_max)
