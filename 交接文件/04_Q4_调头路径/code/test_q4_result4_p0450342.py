import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from q4_result4_p0450342 import (
    PITCH,
    build_boundary_geometry,
    configure_pitch,
    state_at,
)


def test_selected_pitch_is_the_six_decimal_upward_rounding_of_q3_upper_bound():
    q3_feasible_upper = 0.450341796875
    assert PITCH == 0.450342
    assert PITCH > q3_feasible_upper
    assert PITCH - q3_feasible_upper < 1e-6


def test_boundary_geometry_at_selected_pitch_is_tangent_and_inside_disk():
    configure_pitch(PITCH)
    geometry = build_boundary_geometry(PITCH)
    assert geometry.circle_tangency_residual < 1e-8
    assert geometry.endpoint_tangent_error < 1e-8
    assert geometry.joint_tangent_error < 1e-8
    assert geometry.maximum_radius() <= 4.5 + 1e-8
    assert math.isclose(geometry.radius_large, 2.0 * geometry.radius_small, rel_tol=0.0, abs_tol=1e-12)


def test_state_at_minus_zero_and_plus_zero_has_finite_chain_and_speed():
    configure_pitch(PITCH)
    geometry = build_boundary_geometry(PITCH)
    for time_s in (-100.0, 0.0, 100.0):
        state = state_at(geometry, time_s, n_handles=224)
        assert len(state.positions) == 224
        assert len(state.speeds) == 224
        assert np.isfinite(np.asarray(state.positions)).all()
        assert np.isfinite(np.asarray(state.velocities)).all()
        assert np.isfinite(np.asarray(state.speeds)).all()
        assert state.minimum_speed_denominator > 1e-10
