"""Run the formal Q3 pitch search and write reproducible evidence tables."""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[4]
CODE = Path(__file__).resolve().parent
Q2_CODE = ROOT / "建模总控" / "03-deliverables" / "02_Q2_碰撞模型" / "code"
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(Q2_CODE))

from q3_solver import (  # noqa: E402
    BODY_HANDLE_GAP,
    HEAD_HANDLE_GAP,
    INITIAL_THETA,
    TURNING_RADIUS,
    bisect_monotone_boundary,
    boundary_theta,
    build_chain,
    evaluate_path,
    evaluate_state,
    normal_turn_spacing,
    normal_turn_spacing_derivative,
    spiral_scale,
)
from collision_q2 import benches_from_handles  # noqa: E402


OUT = Path(__file__).resolve().parents[1]
TABLES = OUT / "tables"
FIGURES = OUT / "figures"
TABLES.mkdir(parents=True, exist_ok=True)
FIGURES.mkdir(parents=True, exist_ok=True)


def _as_dict(result):
    return {
        "pitch_m": result.pitch,
        "feasible": result.feasible,
        "global_min_margin_m": result.global_min_margin,
        "critical_head_theta": result.critical_head_theta,
        "critical_head_radius_m": result.critical_head_radius,
        "witness_pair_zero_based": list(result.witness_pair) if result.witness_pair else None,
        "witness_pair_paper_numbering": [x + 1 for x in result.witness_pair] if result.witness_pair else None,
        "collision_pairs_zero_based": [list(pair) for pair in result.collision_pairs],
        "sampled_states": result.sampled_states,
        "refined_states": result.refined_states,
        "tested_pairs": result.min_evaluation.tested_pairs,
        "circle_rejected_pairs": result.min_evaluation.circle_rejected_pairs,
        "total_forbidden_pairs": result.min_evaluation.total_forbidden_pairs,
    }


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _corners(rectangle):
    cx, cy = rectangle.centre
    ux, uy = rectangle.axis
    vx, vy = rectangle.normal
    return [
        (
            cx + su * rectangle.half_length * ux + sv * rectangle.half_width * vx,
            cy + su * rectangle.half_length * uy + sv * rectangle.half_width * vy,
        )
        for su, sv in ((1, 1), (-1, 1), (-1, -1), (1, -1))
    ]


def independent_pair_check(pitch: float, theta: float, pair: tuple[int, int] | None) -> dict:
    if pair is None:
        return {"available": False}
    _, handles = build_chain(pitch, theta)
    benches = benches_from_handles(handles)
    left, right = pair
    left_polygon = Polygon(_corners(benches[left]))
    right_polygon = Polygon(_corners(benches[right]))
    return {
        "available": True,
        "pair_zero_based": [left, right],
        "pair_paper_numbering": [left + 1, right + 1],
        "shapely_intersects": bool(left_polygon.intersects(right_polygon)),
        "shapely_intersection_area_m2": float(left_polygon.intersection(right_polygon).area),
        "shapely_distance_m": float(left_polygon.distance(right_polygon)),
    }


def run() -> dict:
    started = time.perf_counter()
    # The scan is deliberately wider than the exploratory old file.  It is a
    # new formal run and its results are the only numerical evidence used below.
    # Cover the full geometric domain above p_geom=4.5/16=0.28125 m;
    # 0.285 m is the first positive-length practical scan point.
    scan_pitches = [round(0.285 + 0.005 * index, 6) for index in range(56)]
    scan_results = []
    cache: dict[float, object] = {}

    def evaluate_pitch(pitch: float, samples: int = 33):
        key = (round(float(pitch), 10), samples)
        if key not in cache:
            cache[key] = evaluate_path(
                float(pitch),
                samples=samples,
                refine_xtol=2e-6,
            )
        return cache[key]

    for pitch in scan_pitches:
        result = evaluate_pitch(pitch, samples=17)
        row = _as_dict(result)
        row["scan_samples"] = 17
        scan_results.append(row)

    boolean_values = [bool(row["feasible"]) for row in scan_results]
    violations = [
        [scan_results[index]["pitch_m"], scan_results[index + 1]["pitch_m"]]
        for index, (left, right) in enumerate(zip(boolean_values, boolean_values[1:]))
        if left and not right
    ]
    transitions = [
        [scan_results[index]["pitch_m"], scan_results[index + 1]["pitch_m"]]
        for index, (left, right) in enumerate(zip(boolean_values, boolean_values[1:]))
        if (not left) and right
    ]
    if not transitions:
        raise RuntimeError("formal pitch scan did not locate an infeasible-to-feasible bracket")
    lower0, upper0 = transitions[0]

    bisect_cache: dict[float, object] = {}

    def predicate(pitch: float) -> bool:
        key = round(float(pitch), 10)
        if key not in bisect_cache:
            bisect_cache[key] = evaluate_path(
                float(pitch),
                samples=65,
                refine_xtol=5e-7,
            )
        return bool(bisect_cache[key].feasible)

    bisection = bisect_monotone_boundary(predicate, lower0, upper0, tolerance=1e-5)
    lower_result = bisect_cache[round(bisection.lower, 10)]
    upper_result = bisect_cache[round(bisection.upper, 10)]

    # Sampling-convergence audit at the reported feasible upper endpoint.
    convergence = []
    for samples in (33, 65, 129):
        result = evaluate_path(
            bisection.upper,
            samples=samples,
            refine_xtol=2e-7,
        )
        convergence.append({"samples": samples, **_as_dict(result)})

    # Critical-before / critical-after evidence uses the final bracket.
    # The lower and upper bracket endpoints are the cleanest critical
    # evidence: one is independently infeasible and the other feasible.
    before_pitch = bisection.lower
    after_pitch = bisection.upper
    before = evaluate_path(before_pitch, samples=129, refine_xtol=2e-7)
    after = evaluate_path(after_pitch, samples=129, refine_xtol=2e-7)
    independent = {
        "lower_endpoint": independent_pair_check(
            bisection.lower,
            lower_result.critical_head_theta,
            lower_result.witness_pair,
        ),
        "upper_endpoint": independent_pair_check(
            bisection.upper,
            upper_result.critical_head_theta,
            lower_result.witness_pair,
        ),
    }

    spacing_rows = []
    for pitch in (0.40, 0.45, 0.50, 0.55):
        spacing_rows.append(
            {
                "pitch_m": pitch,
                "normal_spacing_at_R_m": normal_turn_spacing(TURNING_RADIUS, pitch),
                "derivative_m_per_m": normal_turn_spacing_derivative(TURNING_RADIUS, pitch),
            }
        )

    _write_csv(
        TABLES / "q3_pitch_scan.csv",
        scan_results,
        list(scan_results[0].keys()),
    )
    _write_csv(TABLES / "q3_sampling_convergence.csv", convergence, list(convergence[0].keys()))
    _write_csv(TABLES / "q3_normal_spacing_monotonicity.csv", spacing_rows, list(spacing_rows[0].keys()))

    summary = {
        "started": datetime.now().astimezone().isoformat(timespec="seconds"),
        "release_id": "R-Q3-MIN-PITCH-001",
        "turning_radius_m": TURNING_RADIUS,
        "initial_theta": INITIAL_THETA,
        "search_variable": "pitch_p_m",
        "pitch_scan_range_m": [scan_pitches[0], scan_pitches[-1]],
        "pitch_scan_step_m": 0.005,
        "scan_pitch_count": len(scan_pitches),
        "scan_path_samples_per_pitch": 17,
        "monotonicity_passed": not violations,
        "monotonicity_violations": violations,
        "infeasible_to_feasible_brackets": transitions,
        "initial_bracket_m": [lower0, upper0],
        "bisection": {
            "lower_infeasible_m": bisection.lower,
            "upper_feasible_m": bisection.upper,
            "width_m": bisection.upper - bisection.lower,
            "iterations": bisection.iterations,
            "lower": _as_dict(lower_result),
            "upper": _as_dict(upper_result),
        },
        "sampling_convergence": convergence,
        "critical_before": {"pitch_m": before_pitch, **_as_dict(before)},
        "critical_after": {"pitch_m": after_pitch, **_as_dict(after)},
        "independent_shapely_checks": independent,
        "normal_spacing_rows": spacing_rows,
        "elapsed_s": time.perf_counter() - started,
        "pass": bool(
            not violations
            and not lower_result.feasible
            and upper_result.feasible
            and before.global_min_margin < 0
            and after.feasible
            and (bisection.upper - bisection.lower <= 1e-5 + 1e-12)
        ),
    }
    (TABLES / "q3_result_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    plt.figure(figsize=(8.2, 4.8), dpi=160)
    plt.axhline(0.0, color="#333333", linewidth=1.0)
    plt.plot(
        [row["pitch_m"] for row in scan_results],
        [row["global_min_margin_m"] for row in scan_results],
        marker="o",
        markersize=3.5,
        color="#1f77b4",
        label="minimum SAT margin along full path",
    )
    plt.axvspan(bisection.lower, bisection.upper, color="#f2a900", alpha=0.22, label="bisection bracket")
    plt.xlabel("pitch p / m")
    plt.ylabel("minimum clearance / m")
    plt.title("Q3 pitch feasibility scan and bisection")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES / "图1_Q3_螺距可行性与二分夹逼.png", bbox_inches="tight")
    plt.close()
    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
