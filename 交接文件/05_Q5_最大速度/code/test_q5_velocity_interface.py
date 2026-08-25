import math

import numpy as np

from q5_velocity_interface import compute_transfer_coefficients, head_speed_limit


def test_straight_chain_has_unit_transfer_coefficients():
    positions = np.array([[0.0, 0.0], [2.86, 0.0], [4.51, 0.0]])
    tangents = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
    coefficients, denominators = compute_transfer_coefficients(positions, tangents)
    assert np.allclose(coefficients, [1.0, 1.0, 1.0])
    assert np.allclose(denominators, [2.86, 1.65])


def test_head_speed_limit_uses_global_absolute_maximum():
    assert math.isclose(head_speed_limit(1.25, speed_cap=2.0), 1.6)
