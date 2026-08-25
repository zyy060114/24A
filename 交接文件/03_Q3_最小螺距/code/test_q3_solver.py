import math

import pytest

from q3_solver import (
    TURNING_RADIUS,
    boundary_theta,
    bisect_monotone_boundary,
    build_chain,
    certify_boolean_monotonicity,
    evaluate_path,
    evaluate_state,
    normal_turn_spacing,
    normal_turn_spacing_derivative,
    spiral_point,
)


def test_boundary_theta_places_head_on_fixed_turning_circle():
    pitch = 0.45
    theta = boundary_theta(pitch)
    x, y = spiral_point(theta, pitch)
    assert math.hypot(x, y) == pytest.approx(TURNING_RADIUS, abs=1e-12)


def test_normal_turn_spacing_strictly_increases_with_pitch():
    radius = TURNING_RADIUS
    pitches = (0.35, 0.45, 0.55)
    spacings = [normal_turn_spacing(radius, pitch) for pitch in pitches]
    assert spacings[0] < spacings[1] < spacings[2]
    assert all(normal_turn_spacing_derivative(radius, pitch) > 0 for pitch in pitches)


def test_build_chain_satisfies_required_handle_gaps():
    pitch = 0.45
    _, points = build_chain(pitch, boundary_theta(pitch), n_handles=12)
    gaps = [math.dist(a, b) for a, b in zip(points, points[1:])]
    assert gaps[0] == pytest.approx(2.86, abs=1e-9)
    assert max(abs(value - 1.65) for value in gaps[1:]) < 1e-9


def test_boolean_monotonicity_accepts_only_zero_then_one_sequence():
    assert certify_boolean_monotonicity([False, False, True, True]).passed
    failed = certify_boolean_monotonicity([False, True, False, True])
    assert not failed.passed
    assert failed.violations == ((1, 2),)


def test_bisection_keeps_infeasible_lower_and_feasible_upper():
    result = bisect_monotone_boundary(
        predicate=lambda pitch: pitch >= 0.45,
        lower=0.40,
        upper=0.50,
        tolerance=1e-5,
    )
    assert result.lower < 0.45 <= result.upper
    assert result.upper - result.lower <= 1e-5
    assert result.lower_feasible is False
    assert result.upper_feasible is True


def test_bisection_rejects_invalid_initial_bracket():
    with pytest.raises(ValueError, match="lower endpoint must be infeasible"):
        bisect_monotone_boundary(lambda _: True, 0.40, 0.50, 1e-4)


def test_state_evaluation_uses_q2_collision_chain_and_reports_all_counts():
    result = evaluate_state(0.45, boundary_theta(0.45), n_handles=12)
    assert result.total_forbidden_pairs == 45
    assert result.global_margin > 0
    assert result.collision_flag == 0


def test_path_evaluation_is_whole_path_and_returns_critical_state():
    result = evaluate_path(0.45, samples=9, refine_xtol=1e-5)
    assert result.sampled_states == 9
    assert result.refined_states >= result.sampled_states
    assert result.critical_head_radius >= TURNING_RADIUS - 1e-9
    assert result.critical_head_radius <= 16.0 * 0.45 + 1e-9
