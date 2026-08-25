"""Q2 collision model: topology exclusion -> circle broad phase -> SAT."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import hypot, sqrt
from typing import Sequence
import numpy as np

Vec2 = tuple[float, float]


def _sub(a: Vec2, b: Vec2) -> Vec2:
    return a[0] - b[0], a[1] - b[1]


def _dot(a: Vec2, b: Vec2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _norm(a: Vec2) -> float:
    return hypot(a[0], a[1])


def _unit(a: Vec2) -> Vec2:
    n = _norm(a)
    if n == 0:
        raise ValueError("bench handle centres must be distinct")
    return a[0] / n, a[1] / n


def _perp(a: Vec2) -> Vec2:
    return -a[1], a[0]


@dataclass(frozen=True)
class OrientedRectangle:
    centre: Vec2
    half_length: float
    half_width: float
    axis: Vec2
    normal: Vec2

    @property
    def circumradius(self) -> float:
        return sqrt(self.half_length**2 + self.half_width**2)


def bench_from_handles(previous: Vec2, current: Vec2, *, bench_length: float, bench_width: float = 0.30) -> OrientedRectangle:
    axis = _unit(_sub(current, previous))
    return OrientedRectangle(
        ((previous[0] + current[0]) / 2, (previous[1] + current[1]) / 2),
        bench_length / 2,
        bench_width / 2,
        axis,
        _perp(axis),
    )


def benches_from_handles(handles: Sequence[Vec2], *, head_length: float = 3.41, body_length: float = 2.20, bench_width: float = 0.30) -> list[OrientedRectangle]:
    if len(handles) < 2:
        raise ValueError("at least two handles are required")
    lengths = [head_length] + [body_length] * (len(handles) - 2)
    return [bench_from_handles(a, b, bench_length=L, bench_width=bench_width) for (a, b), L in zip(zip(handles[:-1], handles[1:]), lengths)]


def projection_radius(rect: OrientedRectangle, direction: Vec2) -> float:
    return rect.half_length * abs(_dot(rect.axis, direction)) + rect.half_width * abs(_dot(rect.normal, direction))


def sat_margin(first: OrientedRectangle, second: OrientedRectangle) -> float:
    """g_ij=max_e(|(Cj-Ci)e|-rho_i(e)-rho_j(e)); g<=0 is contact/collision."""
    d = _sub(second.centre, first.centre)
    axes = (first.axis, first.normal, second.axis, second.normal)
    return max(abs(_dot(d, e)) - projection_radius(first, e) - projection_radius(second, e) for e in axes)


def outer_circle_disjoint(first: OrientedRectangle, second: OrientedRectangle) -> bool:
    return _norm(_sub(second.centre, first.centre)) > first.circumradius + second.circumradius


def forbidden_pairs(count: int, adjacency: int = 1):
    for i in range(count):
        for j in range(i + adjacency + 1, count):
            yield i, j


@lru_cache(maxsize=None)
def _pair_indices(count: int, adjacency: int = 1):
    pairs = np.asarray(list(forbidden_pairs(count, adjacency)), dtype=int)
    if not len(pairs):
        return np.asarray([], dtype=int), np.asarray([], dtype=int)
    return pairs[:, 0], pairs[:, 1]


@dataclass(frozen=True)
class CollisionReport:
    collision_flag: int
    collision_pairs: tuple[tuple[int, int], ...]
    witness_pair: tuple[int, int] | None
    global_margin: float
    tested_pairs: int
    circle_rejected_pairs: int
    total_forbidden_pairs: int


def collision_report(rectangles: Sequence[OrientedRectangle], *, tolerance: float = 1e-10) -> CollisionReport:
    count = len(rectangles)
    ii, jj = _pair_indices(count)
    if not len(ii):
        return CollisionReport(0, (), None, float("inf"), 0, 0, 0)
    centres = np.asarray([r.centre for r in rectangles], dtype=float)
    axes = np.asarray([r.axis for r in rectangles], dtype=float)
    normals = np.asarray([r.normal for r in rectangles], dtype=float)
    half_lengths = np.asarray([r.half_length for r in rectangles], dtype=float)
    half_widths = np.asarray([r.half_width for r in rectangles], dtype=float)
    radii = np.hypot(half_lengths, half_widths)
    d = centres[jj] - centres[ii]
    circle_disjoint = np.linalg.norm(d, axis=1) > radii[ii] + radii[jj]

    def sat_margins_for(iidx, jidx):
        dd = centres[jidx] - centres[iidx]
        margins_by_axis = []
        for e in (axes[iidx], normals[iidx], axes[jidx], normals[jidx]):
            centre_projection = np.abs(np.einsum("ij,ij->i", dd, e))
            rho_i = half_lengths[iidx] * np.abs(np.einsum("ij,ij->i", axes[iidx], e)) + half_widths[iidx] * np.abs(np.einsum("ij,ij->i", normals[iidx], e))
            rho_j = half_lengths[jidx] * np.abs(np.einsum("ij,ij->i", axes[jidx], e)) + half_widths[jidx] * np.abs(np.einsum("ij,ij->i", normals[jidx], e))
            margins_by_axis.append(centre_projection - rho_i - rho_j)
        return np.max(np.vstack(margins_by_axis), axis=0)

    # Strict event path: topology has already been removed, then the outer
    # circle rejects safe pairs, and SAT is evaluated only for survivors.
    survivors = ~circle_disjoint
    sat_survivor = sat_margins_for(ii[survivors], jj[survivors])
    hit_mask_survivor = sat_survivor <= tolerance
    si, sj = ii[survivors], jj[survivors]
    hits = tuple((int(i), int(j)) for i, j in zip(si[hit_mask_survivor], sj[hit_mask_survivor]))
    # Exact global-minimum audit is intentionally separate from the event path:
    # it evaluates all pairs only to report the requested numerical G(t).
    all_margins = sat_margins_for(ii, jj)
    tested = int(np.count_nonzero(~circle_disjoint))
    rejected = int(np.count_nonzero(circle_disjoint))
    return CollisionReport(int(bool(hits)), hits, hits[0] if hits else None, float(np.min(all_margins)), tested, rejected, len(ii))


def global_safety_margin(rectangles: Sequence[OrientedRectangle]) -> float:
    return collision_report(rectangles).global_margin
