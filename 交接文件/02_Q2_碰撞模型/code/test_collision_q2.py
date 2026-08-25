import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "建模总控" / "01-shared" / "code"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collision_q2 import (  # noqa: E402
    OrientedRectangle,
    bench_from_handles,
    collision_report,
    outer_circle_disjoint,
    sat_margin,
)
from validate_dense_precritical import local_minimum_indices, positive_to_nonpositive_intervals  # noqa: E402


def test_touching_rectangles_are_critical_collision():
    a = OrientedRectangle((0.0, 0.0), 1.0, 0.15, (1.0, 0.0), (0.0, 1.0))
    b = OrientedRectangle((2.0, 0.0), 1.0, 0.15, (1.0, 0.0), (0.0, 1.0))
    filler = OrientedRectangle((100.0, 100.0), 1.0, 0.15, (1.0, 0.0), (0.0, 1.0))
    assert math.isclose(sat_margin(a, b), 0.0, abs_tol=1e-12)
    assert collision_report([a, filler, b]).collision_flag == 1


def test_directly_adjacent_benches_are_excluded():
    a = bench_from_handles((0.0, 0.0), (2.86, 0.0), bench_length=3.41)
    b = bench_from_handles((2.86, 0.0), (4.51, 0.0), bench_length=2.20)
    report = collision_report([a, b])
    assert report.tested_pairs == 0
    assert report.collision_pairs == ()


def test_outer_circle_rejects_a_far_pair_without_false_negative():
    a = OrientedRectangle((0.0, 0.0), 1.0, 0.15, (1.0, 0.0), (0.0, 1.0))
    b = OrientedRectangle((3.0, 0.0), 1.0, 0.15, (1.0, 0.0), (0.0, 1.0))
    assert outer_circle_disjoint(a, b)
    assert sat_margin(a, b) > 0
    filler = OrientedRectangle((100.0, 100.0), 1.0, 0.15, (1.0, 0.0), (0.0, 1.0))
    report = collision_report([a, filler, b])
    assert report.collision_flag == 0
    assert report.circle_rejected_pairs == 1


def test_sat_detects_rotated_corner_edge_contact():
    a = OrientedRectangle((0.0, 0.0), 1.0, 0.1, (1.0, 0.0), (0.0, 1.0))
    q = math.sqrt(0.5)
    # One corner of b is exactly the upper-right corner of a.
    b = OrientedRectangle((1.0 + 0.9 * q, 0.1 + 1.1 * q), 1.0, 0.1, (q, q), (-q, q))
    assert sat_margin(a, b) <= 1e-12


def test_dense_scan_helpers_keep_all_transitions_and_local_minima():
    rows = [
        {"time_s": 0.0, "global_margin_m": 1.0},
        {"time_s": 0.1, "global_margin_m": 0.2},
        {"time_s": 0.2, "global_margin_m": 0.5},
        {"time_s": 0.3, "global_margin_m": -0.1},
        {"time_s": 0.4, "global_margin_m": 0.3},
        {"time_s": 0.5, "global_margin_m": -0.2},
    ]
    assert local_minimum_indices(rows) == [1, 3, 5]
    assert positive_to_nonpositive_intervals(rows) == [[0.2, 0.3], [0.4, 0.5]]
