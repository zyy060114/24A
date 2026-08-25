"""Q4 full time-series calculation under the user-selected pitch p=0.450342 m.

This module keeps the Q2 rectangle/SAT collision model and the common rigid-link
speed recursion.  The default trajectory is the strict 2:1 biarc whose two
spiral endpoints are the intersections with the 4.5 m turning boundary.  The
module intentionally reports collisions instead of silently filtering them;
the selected pitch is a Q3-derived extension scenario and must be checked
again after the turn path is introduced.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE / "experiments") not in sys.path:
    sys.path.insert(0, str(HERE / "experiments"))

import q4_small_collision_map as sm  # noqa: E402


PITCH = 0.450342
N_HANDLES = 224
TURN_RADIUS = 4.5


@dataclass(frozen=True)
class Q4State:
    time_s: float
    path_coordinates: tuple[float, ...]
    positions: tuple[tuple[float, float], ...]
    tangents: tuple[tuple[float, float], ...]
    velocities: tuple[tuple[float, float], ...]
    speeds: tuple[float, ...]
    minimum_speed_denominator: float
    global_margin_m: float
    witness_pair: tuple[int, int]


def configure_pitch(pitch: float = PITCH) -> float:
    """Configure the legacy Q4 geometry module for one explicit pitch."""

    if pitch <= 0.0:
        raise ValueError("pitch must be positive")
    sm.PITCH = float(pitch)
    sm.SPIRAL_A = float(pitch) / (2.0 * math.pi)
    sm.THETA_BOUNDARY = TURN_RADIUS / sm.SPIRAL_A
    return float(pitch)


def build_boundary_geometry(pitch: float = PITCH):
    """Build the strict 2:1 boundary-endpoint S-biarc for ``pitch``."""

    configure_pitch(pitch)
    theta = float(sm.THETA_BOUNDARY)
    return sm.build_turn_geometry(theta, theta, curvature_sign=-1, allow_semicircle=True)


def _theta_from_incoming_s(geometry, s: float) -> float:
    target = sm._spiral_primitive(geometry.theta_in) - float(s)
    guess = geometry.theta_in + (-float(s)) / max(sm.SPIRAL_A * geometry.theta_in, 0.5)
    return sm._theta_from_primitive(target, guess)


def _theta_from_outgoing_s(geometry, s: float) -> float:
    distance = float(s) - geometry.length
    target = sm._spiral_primitive(geometry.theta_out) + distance
    guess = geometry.theta_out + distance / max(sm.SPIRAL_A * geometry.theta_out, 0.5)
    return sm._theta_from_primitive(target, guess)


def path_tangent(path, s: float) -> tuple[float, float]:
    """Unit tangent in the direction of increasing global path coordinate."""

    g = path.geometry
    s = float(s)
    if s < 0.0:
        return tuple(float(x) for x in sm.inward_tangent(_theta_from_incoming_s(g, s)))
    if s <= g.length_large:
        return tuple(float(x) for x in sm._arc_tangent(g.center_large, np.asarray(path.point(s)), g.curvature_sign))
    if s <= g.length:
        return tuple(float(x) for x in sm._arc_tangent(g.center_small, np.asarray(path.point(s)), -g.curvature_sign))
    return tuple(float(x) for x in sm.outgoing_tangent(_theta_from_outgoing_s(g, s)))


def handle_coordinates(path, head_s: float, n_handles: int = N_HANDLES) -> tuple[float, ...]:
    """Return arc-length coordinates of all handles behind the head."""

    if n_handles < 2:
        raise ValueError("at least two handles are required")
    coordinates = [float(head_s)]
    current = float(head_s)
    for gap in [2.86] + [1.65] * (n_handles - 2):
        current = sm._previous_handle_coordinate(path, current, gap)
        coordinates.append(float(current))
    return tuple(coordinates)


def speed_coefficients(
    positions: Iterable[tuple[float, float]],
    tangents: Iterable[tuple[float, float]],
    singular_tolerance: float = 1e-12,
) -> tuple[tuple[float, ...], float]:
    positions = [np.asarray(p, dtype=float) for p in positions]
    tangents = [np.asarray(t, dtype=float) for t in tangents]
    if len(positions) != len(tangents) or not positions:
        raise ValueError("positions and tangents must be nonempty and equally sized")
    coefficients = [1.0]
    denominators: list[float] = []
    for index in range(1, len(positions)):
        chord = positions[index] - positions[index - 1]
        numerator = float(chord @ tangents[index - 1])
        denominator = float(chord @ tangents[index])
        denominators.append(abs(denominator))
        if abs(denominator) <= singular_tolerance:
            raise ZeroDivisionError(f"speed recursion denominator is near zero at handle {index}")
        coefficients.append(coefficients[-1] * numerator / denominator)
    return tuple(float(value) for value in coefficients), min(denominators, default=float("inf"))


def state_at(geometry, time_s: float, n_handles: int = N_HANDLES) -> Q4State:
    """Compute one full-chain position, velocity, speed and collision state."""

    path = sm.build_turn_path(geometry)
    path_coordinates = handle_coordinates(path, float(time_s), n_handles=n_handles)
    positions = tuple(path.point(s) for s in path_coordinates)
    tangents = tuple(path_tangent(path, s) for s in path_coordinates)
    speeds, min_denominator = speed_coefficients(positions, tangents)
    velocities = tuple(
        (float(speed * tangent[0]), float(speed * tangent[1]))
        for speed, tangent in zip(speeds, tangents)
    )
    rectangles = sm.benches_from_handles(list(positions))
    margin, pair = sm._minimum_margin_and_pair(rectangles)
    return Q4State(
        time_s=float(time_s),
        path_coordinates=path_coordinates,
        positions=positions,
        tangents=tangents,
        velocities=velocities,
        speeds=speeds,
        minimum_speed_denominator=float(min_denominator),
        global_margin_m=float(margin),
        witness_pair=(int(pair[0] + 1), int(pair[1] + 1)),
    )


def compute_series(
    pitch: float = PITCH,
    times: Iterable[int | float] = range(-100, 101),
    n_handles: int = N_HANDLES,
):
    configure_pitch(pitch)
    geometry = build_boundary_geometry(pitch)
    states = [state_at(geometry, float(time_s), n_handles=n_handles) for time_s in times]
    return geometry, states
