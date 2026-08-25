"""Formal Q3 geometry and monotone-boundary search utilities.

The decision variable is the Archimedean-spiral pitch ``p``.  The turning
space radius stays fixed at 4.5 m.  Collision evaluation is added below using
the already accepted Q2 rectangle/SAT module.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

from scipy.optimize import brentq


TURNING_RADIUS = 4.50
INITIAL_THETA = 32.0 * math.pi
HEAD_HANDLE_GAP = 2.86
BODY_HANDLE_GAP = 1.65

_Q2_CODE = Path(__file__).resolve().parents[2] / "02_Q2_碰撞模型" / "code"
if str(_Q2_CODE) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_Q2_CODE))
from collision_q2 import benches_from_handles, collision_report


def spiral_scale(pitch: float) -> float:
    if pitch <= 0:
        raise ValueError("pitch must be positive")
    return pitch / (2.0 * math.pi)


def spiral_point(theta: float, pitch: float) -> tuple[float, float]:
    scale = spiral_scale(pitch)
    radius = scale * theta
    return radius * math.cos(theta), radius * math.sin(theta)


def boundary_theta(pitch: float, radius: float = TURNING_RADIUS) -> float:
    if radius <= 0:
        raise ValueError("radius must be positive")
    return radius / spiral_scale(pitch)


def normal_turn_spacing(radius: float, pitch: float) -> float:
    """First-order normal distance between consecutive spiral turns."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    scale = spiral_scale(pitch)
    return pitch * radius / math.sqrt(radius * radius + scale * scale)


def normal_turn_spacing_derivative(radius: float, pitch: float) -> float:
    """Derivative of ``normal_turn_spacing`` with respect to pitch."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    scale = spiral_scale(pitch)
    return radius**3 / (radius * radius + scale * scale) ** 1.5


def _nearest_following_theta(theta: float, gap: float, pitch: float) -> float:
    anchor = spiral_point(theta, pitch)

    def residual(candidate: float) -> float:
        return math.dist(anchor, spiral_point(candidate, pitch)) - gap

    lo = theta
    flo = -gap
    step = 0.02
    for _ in range(5000):
        hi = lo + step
        fhi = residual(hi)
        if flo <= 0.0 <= fhi:
            return brentq(residual, lo, hi, xtol=1e-13, rtol=1e-13, maxiter=100)
        lo, flo = hi, fhi
    raise RuntimeError("nearest following spiral intersection was not bracketed")


def build_chain(
    pitch: float,
    head_theta: float,
    n_handles: int = 224,
) -> tuple[list[float], list[tuple[float, float]]]:
    if n_handles < 2:
        raise ValueError("n_handles must be at least 2")
    gaps = [HEAD_HANDLE_GAP] + [BODY_HANDLE_GAP] * (n_handles - 2)
    thetas = [float(head_theta)]
    for gap in gaps:
        thetas.append(_nearest_following_theta(thetas[-1], gap, pitch))
    return thetas, [spiral_point(theta, pitch) for theta in thetas]


@dataclass(frozen=True)
class StateEvaluation:
    pitch: float
    head_theta: float
    head_radius: float
    global_margin: float
    collision_flag: int
    collision_pairs: tuple[tuple[int, int], ...]
    witness_pair: tuple[int, int] | None
    tested_pairs: int
    circle_rejected_pairs: int
    total_forbidden_pairs: int


def evaluate_state(
    pitch: float,
    head_theta: float,
    *,
    n_handles: int = 224,
    contact_tolerance: float = 1e-10,
) -> StateEvaluation:
    _, handles = build_chain(pitch, head_theta, n_handles=n_handles)
    benches = benches_from_handles(handles)
    report = collision_report(benches, tolerance=contact_tolerance)
    return StateEvaluation(
        pitch=float(pitch),
        head_theta=float(head_theta),
        head_radius=spiral_scale(pitch) * head_theta,
        global_margin=float(report.global_margin),
        collision_flag=int(report.collision_flag),
        collision_pairs=report.collision_pairs,
        witness_pair=report.witness_pair,
        tested_pairs=int(report.tested_pairs),
        circle_rejected_pairs=int(report.circle_rejected_pairs),
        total_forbidden_pairs=int(report.total_forbidden_pairs),
    )


def sample_head_thetas(
    pitch: float,
    samples: int,
    *,
    start_theta: float = INITIAL_THETA,
    radius: float = TURNING_RADIUS,
) -> np.ndarray:
    if samples < 2:
        raise ValueError("samples must be at least 2")
    end_theta = boundary_theta(pitch, radius)
    if end_theta > start_theta:
        raise ValueError("the initial head state is already inside the turning boundary")
    return np.linspace(start_theta, end_theta, samples)


@dataclass(frozen=True)
class PathEvaluation:
    pitch: float
    feasible: bool
    global_min_margin: float
    critical_head_theta: float
    critical_head_radius: float
    witness_pair: tuple[int, int] | None
    collision_pairs: tuple[tuple[int, int], ...]
    sampled_states: int
    refined_states: int
    min_evaluation: StateEvaluation


def _state_to_scalar(
    pitch: float,
    theta: float,
    cache: dict[float, StateEvaluation],
    *,
    n_handles: int = 224,
    contact_tolerance: float = 1e-10,
) -> float:
    key = round(float(theta), 13)
    if key not in cache:
        cache[key] = evaluate_state(
            pitch,
            key,
            n_handles=n_handles,
            contact_tolerance=contact_tolerance,
        )
    return cache[key].global_margin


def evaluate_path(
    pitch: float,
    *,
    samples: int = 65,
    refine_half_width: int = 2,
    refine_xtol: float = 2e-7,
    contact_tolerance: float = 1e-10,
) -> PathEvaluation:
    """Evaluate the whole path and refine every coarse local minimum.

    The coarse grid is retained in the result for the sampling-convergence
    audit.  Candidate minima include both endpoints and all interior points
    no larger than their two neighbours; each interior candidate is refined
    on the neighbouring grid cell by bounded scalar minimization.
    """
    if samples < 5:
        raise ValueError("at least five path samples are required")
    thetas = sample_head_thetas(pitch, samples)
    cache: dict[float, StateEvaluation] = {}
    margins = np.array(
        [
            _state_to_scalar(
                pitch,
                theta,
                cache,
                contact_tolerance=contact_tolerance,
            )
            for theta in thetas
        ]
    )
    candidate_indices = {0, samples - 1}
    candidate_indices.update(
        index
        for index in range(1, samples - 1)
        if margins[index] <= margins[index - 1] and margins[index] <= margins[index + 1]
    )
    # Retain a few cells around the worst coarse points to guard against a
    # narrow switch of the active SAT witness between adjacent samples.
    for index in np.argsort(margins)[: max(3, refine_half_width + 1)]:
        candidate_indices.add(int(index))

    for index in sorted(candidate_indices):
        if index == 0 or index == samples - 1:
            continue
        left = float(thetas[index - 1])
        right = float(thetas[index + 1])
        # minimize_scalar assumes left < right; the path theta array is descending.
        lo, hi = min(left, right), max(left, right)
        result = minimize_scalar(
            lambda theta: _state_to_scalar(
                pitch,
                theta,
                cache,
                contact_tolerance=contact_tolerance,
            ),
            bounds=(lo, hi),
            method="bounded",
            options={"xatol": refine_xtol, "maxiter": 80},
        )
        _state_to_scalar(
            pitch,
            float(result.x),
            cache,
            contact_tolerance=contact_tolerance,
        )

    minimum = min(cache.values(), key=lambda state: state.global_margin)
    feasible = minimum.global_margin >= -contact_tolerance
    return PathEvaluation(
        pitch=float(pitch),
        feasible=bool(feasible),
        global_min_margin=float(minimum.global_margin),
        critical_head_theta=float(minimum.head_theta),
        critical_head_radius=float(minimum.head_radius),
        witness_pair=minimum.witness_pair,
        collision_pairs=minimum.collision_pairs,
        sampled_states=samples,
        refined_states=len(cache),
        min_evaluation=minimum,
    )


@dataclass(frozen=True)
class MonotonicityCertificate:
    passed: bool
    violations: tuple[tuple[int, int], ...]


def certify_boolean_monotonicity(values: Sequence[bool]) -> MonotonicityCertificate:
    violations = tuple(
        (index, index + 1)
        for index, (left, right) in enumerate(zip(values, values[1:]))
        if left and not right
    )
    return MonotonicityCertificate(not violations, violations)


@dataclass(frozen=True)
class BisectionResult:
    lower: float
    upper: float
    lower_feasible: bool
    upper_feasible: bool
    iterations: int


def bisect_monotone_boundary(
    predicate: Callable[[float], bool],
    lower: float,
    upper: float,
    tolerance: float,
) -> BisectionResult:
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    lower_feasible = bool(predicate(lower))
    upper_feasible = bool(predicate(upper))
    if lower_feasible:
        raise ValueError("lower endpoint must be infeasible")
    if not upper_feasible:
        raise ValueError("upper endpoint must be feasible")
    iterations = 0
    while upper - lower > tolerance:
        middle = (lower + upper) / 2.0
        if predicate(middle):
            upper = middle
        else:
            lower = middle
        iterations += 1
    return BisectionResult(lower, upper, False, True, iterations)
