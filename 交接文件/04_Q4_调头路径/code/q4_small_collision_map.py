"""Exploratory Q4 5x5 cut-point map with the approved Q2 collision model.

This module is deliberately limited to R-Q4-SMALL-TRIAL-001.  It does not
perform global optimisation and does not write result4.xlsx.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import brentq


HERE = Path(__file__).resolve().parent
CONTROL_ROOT = HERE.parents[2]
Q2_CODE = CONTROL_ROOT / "03-deliverables" / "02_Q2_碰撞模型" / "code"
sys.path.insert(0, str(Q2_CODE))

from collision_q2 import benches_from_handles, collision_report  # noqa: E402


PITCH = 1.7
SPIRAL_A = PITCH / (2.0 * math.pi)
TURN_RADIUS = 4.5
THETA_BOUNDARY = TURN_RADIUS / SPIRAL_A
RADIUS_RATIO = 2.0


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length == 0.0:
        raise ValueError("zero vector has no direction")
    return vector / length


def _left_normal(vector: np.ndarray) -> np.ndarray:
    return np.array([-vector[1], vector[0]], dtype=float)


def _rotate(vector: np.ndarray, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c * vector[0] - s * vector[1], s * vector[0] + c * vector[1]])


def _positive_angle(value: float) -> float:
    return value % (2.0 * math.pi)


def spiral(theta: float) -> np.ndarray:
    radius = SPIRAL_A * theta
    return np.array([radius * math.cos(theta), radius * math.sin(theta)], dtype=float)


def spiral_derivative(theta: float) -> np.ndarray:
    return np.array(
        [
            SPIRAL_A * (math.cos(theta) - theta * math.sin(theta)),
            SPIRAL_A * (math.sin(theta) + theta * math.cos(theta)),
        ],
        dtype=float,
    )


def inward_tangent(theta: float) -> np.ndarray:
    return -_unit(spiral_derivative(theta))


def outgoing_point(theta: float) -> np.ndarray:
    return -spiral(theta)


def outgoing_tangent(theta: float) -> np.ndarray:
    return -_unit(spiral_derivative(theta))


def _arc_tangent(center: np.ndarray, point: np.ndarray, curvature_sign: int) -> np.ndarray:
    return curvature_sign * _left_normal(_unit(point - center))


def _arc_point(center: np.ndarray, start: np.ndarray, curvature_sign: int, radius: float, distance: float) -> np.ndarray:
    return center + _rotate(start - center, curvature_sign * distance / radius)


@dataclass(frozen=True)
class TurnGeometry:
    theta_in: float
    theta_out: float
    curvature_sign: int
    point_in: np.ndarray
    point_out: np.ndarray
    tangent_in: np.ndarray
    tangent_out: np.ndarray
    center_large: np.ndarray
    center_small: np.ndarray
    join: np.ndarray
    radius_large: float
    radius_small: float
    sweep_large: float
    sweep_small: float
    length_large: float
    length_small: float
    length: float
    circle_tangency_residual: float
    endpoint_tangent_error: float
    joint_tangent_error: float

    def maximum_radius(self, samples_per_arc: int = 2001) -> float:
        first = [
            _arc_point(
                self.center_large,
                self.point_in,
                self.curvature_sign,
                self.radius_large,
                self.length_large * i / (samples_per_arc - 1),
            )
            for i in range(samples_per_arc)
        ]
        second = [
            _arc_point(
                self.center_small,
                self.join,
                -self.curvature_sign,
                self.radius_small,
                self.length_small * i / (samples_per_arc - 1),
            )
            for i in range(samples_per_arc)
        ]
        return max(float(np.linalg.norm(p)) for p in first + second)


def _positive_radius_roots(theta_in: float, theta_out: float, curvature_sign: int) -> list[float]:
    point_in = spiral(theta_in)
    point_out = outgoing_point(theta_out)
    normal_in = _left_normal(inward_tangent(theta_in))
    normal_out = _left_normal(outgoing_tangent(theta_out))
    displacement = point_out - point_in
    coefficient = -curvature_sign * normal_out - 2.0 * curvature_sign * normal_in
    qa = float(coefficient @ coefficient) - 9.0
    qb = 2.0 * float(displacement @ coefficient)
    qc = float(displacement @ displacement)
    if abs(qa) < 1e-14:
        if abs(qb) < 1e-14:
            return []
        roots = [-qc / qb]
    else:
        discriminant = qb * qb - 4.0 * qa * qc
        if discriminant < -1e-12:
            return []
        discriminant = max(0.0, discriminant)
        root = math.sqrt(discriminant)
        roots = [(-qb - root) / (2.0 * qa), (-qb + root) / (2.0 * qa)]
    return sorted({float(r) for r in roots if math.isfinite(r) and r > 1e-8})


def build_turn_geometry(
    theta_in: float,
    theta_out: float,
    curvature_sign: int = -1,
    allow_semicircle: bool = False,
) -> TurnGeometry:
    if curvature_sign not in (-1, 1):
        raise ValueError("curvature_sign must be -1 or 1")
    if theta_in <= 0.0 or theta_out <= 0.0:
        raise ValueError("spiral parameters must be positive")

    point_in = spiral(theta_in)
    point_out = outgoing_point(theta_out)
    tangent_in = inward_tangent(theta_in)
    tangent_out = outgoing_tangent(theta_out)
    candidates: list[TurnGeometry] = []
    for radius_small in _positive_radius_roots(theta_in, theta_out, curvature_sign):
        radius_large = RADIUS_RATIO * radius_small
        center_large = point_in + curvature_sign * radius_large * _left_normal(tangent_in)
        center_small = point_out - curvature_sign * radius_small * _left_normal(tangent_out)
        join = center_large + (radius_large / (radius_large + radius_small)) * (center_small - center_large)

        angle_in = math.atan2(*(point_in - center_large)[::-1])
        angle_join_large = math.atan2(*(join - center_large)[::-1])
        angle_join_small = math.atan2(*(join - center_small)[::-1])
        angle_out = math.atan2(*(point_out - center_small)[::-1])
        sweep_large = _positive_angle(curvature_sign * (angle_join_large - angle_in))
        sweep_small = _positive_angle(-curvature_sign * (angle_out - angle_join_small))
        length_large = radius_large * sweep_large
        length_small = radius_small * sweep_small

        tangent_at_start = _arc_tangent(center_large, point_in, curvature_sign)
        tangent_at_join_first = _arc_tangent(center_large, join, curvature_sign)
        tangent_at_join_second = _arc_tangent(center_small, join, -curvature_sign)
        tangent_at_end = _arc_tangent(center_small, point_out, -curvature_sign)
        candidates.append(
            TurnGeometry(
                theta_in=float(theta_in),
                theta_out=float(theta_out),
                curvature_sign=curvature_sign,
                point_in=point_in,
                point_out=point_out,
                tangent_in=tangent_in,
                tangent_out=tangent_out,
                center_large=center_large,
                center_small=center_small,
                join=join,
                radius_large=radius_large,
                radius_small=radius_small,
                sweep_large=sweep_large,
                sweep_small=sweep_small,
                length_large=length_large,
                length_small=length_small,
                length=length_large + length_small,
                circle_tangency_residual=abs(float(np.linalg.norm(center_small - center_large)) - 3.0 * radius_small),
                endpoint_tangent_error=max(
                    float(np.linalg.norm(tangent_at_start - tangent_in)),
                    float(np.linalg.norm(tangent_at_end - tangent_out)),
                ),
                joint_tangent_error=float(np.linalg.norm(tangent_at_join_first - tangent_at_join_second)),
            )
        )

    sweep_upper = math.pi + 1e-10 if allow_semicircle else math.pi
    short_s = [
        c
        for c in candidates
        if 1e-10 < c.sweep_large <= sweep_upper
        and 1e-10 < c.sweep_small <= sweep_upper
        and c.circle_tangency_residual < 1e-8
        and c.endpoint_tangent_error < 1e-8
        and c.joint_tangent_error < 1e-8
    ]
    if not short_s:
        raise ValueError("no positive-radius short-arc S branch for these cut points")
    return min(short_s, key=lambda item: item.length)


def _spiral_primitive(theta: float) -> float:
    return 0.5 * SPIRAL_A * (theta * math.sqrt(theta * theta + 1.0) + math.asinh(theta))


def _theta_from_primitive(target: float, initial: float) -> float:
    theta = max(1e-10, float(initial))
    for _ in range(14):
        residual = _spiral_primitive(theta) - target
        derivative = SPIRAL_A * math.sqrt(theta * theta + 1.0)
        step = residual / derivative
        trial = theta - step
        if trial <= 0.0:
            trial = theta / 2.0
        theta = trial
        if abs(step) < 1e-13:
            return theta
    if abs(_spiral_primitive(theta) - target) > 1e-9:
        raise ArithmeticError("spiral arclength inversion failed")
    return theta


@dataclass(frozen=True)
class TurnPath:
    geometry: TurnGeometry

    def point(self, s: float) -> tuple[float, float]:
        s = float(s)
        g = self.geometry
        if s < 0.0:
            target = _spiral_primitive(g.theta_in) - s
            guess = g.theta_in + (-s) / max(SPIRAL_A * g.theta_in, 0.5)
            point = spiral(_theta_from_primitive(target, guess))
        elif s <= g.length_large:
            point = _arc_point(g.center_large, g.point_in, g.curvature_sign, g.radius_large, s)
        elif s <= g.length:
            point = _arc_point(
                g.center_small,
                g.join,
                -g.curvature_sign,
                g.radius_small,
                s - g.length_large,
            )
        else:
            distance = s - g.length
            target = _spiral_primitive(g.theta_out) + distance
            guess = g.theta_out + distance / max(SPIRAL_A * g.theta_out, 0.5)
            point = outgoing_point(_theta_from_primitive(target, guess))
        return float(point[0]), float(point[1])


def build_turn_path(geometry: TurnGeometry) -> TurnPath:
    return TurnPath(geometry)


def _previous_handle_coordinate(path: TurnPath, current_s: float, gap: float, scan_step: float = 0.05) -> float:
    current_point = path.point(current_s)

    def residual(candidate_s: float) -> float:
        return math.dist(current_point, path.point(candidate_s)) - gap

    right = current_s - gap
    f_right = residual(right)
    if abs(f_right) <= 1e-13:
        return right
    if f_right > 1e-10:
        return brentq(residual, right, current_s, xtol=1e-12, rtol=1e-13)

    left = right
    for _ in range(2000):
        next_left = left - scan_step
        f_left = residual(next_left)
        if f_left >= 0.0:
            return brentq(residual, next_left, left, xtol=1e-12, rtol=1e-13)
        left = next_left
    raise RuntimeError("no nearest valid handle intersection found within scan range")


def handles_behind_head(path: TurnPath, head_s: float, n_handles: int = 224) -> list[tuple[float, float]]:
    if n_handles < 2:
        raise ValueError("at least two handles are required")
    coordinates = [path.point(head_s)]
    current_s = float(head_s)
    gaps = [2.86] + [1.65] * (n_handles - 2)
    for gap in gaps:
        current_s = _previous_handle_coordinate(path, current_s, gap)
        coordinates.append(path.point(current_s))
    return coordinates


def _minimum_margin_and_pair(rectangles) -> tuple[float, tuple[int, int]]:
    count = len(rectangles)
    pairs = np.asarray([(i, j) for i in range(count) for j in range(i + 2, count)], dtype=int)
    if not len(pairs):
        return float("inf"), (-1, -1)
    ii, jj = pairs[:, 0], pairs[:, 1]
    centres = np.asarray([r.centre for r in rectangles], dtype=float)
    axes = np.asarray([r.axis for r in rectangles], dtype=float)
    normals = np.asarray([r.normal for r in rectangles], dtype=float)
    half_lengths = np.asarray([r.half_length for r in rectangles], dtype=float)
    half_widths = np.asarray([r.half_width for r in rectangles], dtype=float)
    displacement = centres[jj] - centres[ii]
    by_axis = []
    for direction in (axes[ii], normals[ii], axes[jj], normals[jj]):
        centre_projection = np.abs(np.einsum("ij,ij->i", displacement, direction))
        first_radius = half_lengths[ii] * np.abs(np.einsum("ij,ij->i", axes[ii], direction)) + half_widths[ii] * np.abs(np.einsum("ij,ij->i", normals[ii], direction))
        second_radius = half_lengths[jj] * np.abs(np.einsum("ij,ij->i", axes[jj], direction)) + half_widths[jj] * np.abs(np.einsum("ij,ij->i", normals[jj], direction))
        by_axis.append(centre_projection - first_radius - second_radius)
    margins = np.max(np.vstack(by_axis), axis=0)
    index = int(np.argmin(margins))
    return float(margins[index]), (int(ii[index]), int(jj[index]))


def evaluate_candidate(
    delta_in: float,
    delta_out: float,
    coarse_head_positions: Sequence[float],
    n_handles: int = 224,
) -> dict:
    theta_in = THETA_BOUNDARY - float(delta_in)
    theta_out = THETA_BOUNDARY - float(delta_out)
    base = {
        "delta_in_rad": float(delta_in),
        "delta_out_rad": float(delta_out),
        "theta_in": theta_in,
        "theta_out": theta_out,
        "curvature_sign": -1,
    }
    try:
        geometry = build_turn_geometry(theta_in, theta_out, curvature_sign=-1)
    except Exception as exc:
        return {
            **base,
            "geometry_feasible": False,
            "failure_reason": f"geometry: {type(exc).__name__}: {exc}",
            "collision_safe": False,
        }

    max_radius = geometry.maximum_radius()
    geometry_feasible = max_radius <= TURN_RADIUS + 1e-8
    result = {
        **base,
        "geometry_feasible": geometry_feasible,
        "failure_reason": None if geometry_feasible else "turning arcs leave the 4.5 m disk",
        "radius_large_m": geometry.radius_large,
        "radius_small_m": geometry.radius_small,
        "sweep_large_rad": geometry.sweep_large,
        "sweep_small_rad": geometry.sweep_small,
        "length_large_m": geometry.length_large,
        "length_small_m": geometry.length_small,
        "total_length_m": geometry.length,
        "maximum_path_radius_m": max_radius,
        "circle_tangency_residual_m": geometry.circle_tangency_residual,
        "endpoint_tangent_error": geometry.endpoint_tangent_error,
        "joint_tangent_error": geometry.joint_tangent_error,
    }
    if not geometry_feasible:
        result["collision_safe"] = False
        return result

    path = build_turn_path(geometry)
    state_rows = []
    for head_s in coarse_head_positions:
        handles = handles_behind_head(path, float(head_s), n_handles=n_handles)
        rectangles = benches_from_handles(handles)
        report = collision_report(rectangles)
        margin, pair = _minimum_margin_and_pair(rectangles)
        if not math.isclose(margin, report.global_margin, rel_tol=1e-10, abs_tol=1e-10):
            raise ArithmeticError("experimental witness margin disagrees with the approved Q2 global margin")
        state_rows.append(
            {
                "head_s_m": float(head_s),
                "global_margin_m": margin,
                "witness_pair": [pair[0] + 1, pair[1] + 1],
                "collision_flag": int(report.collision_flag),
                "sat_tested_pairs": int(report.tested_pairs),
                "circle_rejected_pairs": int(report.circle_rejected_pairs),
            }
        )
    minimum = min(state_rows, key=lambda row: row["global_margin_m"])
    result.update(
        {
            "collision_safe": minimum["global_margin_m"] > 1e-10,
            "minimum_margin_m": minimum["global_margin_m"],
            "minimum_head_s_m": minimum["head_s_m"],
            "minimum_witness_pair": minimum["witness_pair"],
            "evaluated_head_states": len(state_rows),
            "state_rows": state_rows,
        }
    )
    return result


def _serialisable_geometry(geometry: TurnGeometry) -> dict:
    raw = asdict(geometry)
    return {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in raw.items()}


def run_small_map(
    deltas: Iterable[float] = (0.0, 0.2, 0.4, 0.6, 0.8),
    coarse_step_m: float = 10.0,
    refine_step_m: float = 2.0,
    refine_count: int = 3,
) -> dict:
    started = time.perf_counter()
    delta_values = [float(value) for value in deltas]
    coarse_positions = np.arange(-100.0, 100.0 + 0.5 * coarse_step_m, coarse_step_m)
    candidates = [
        evaluate_candidate(di, do, coarse_positions, n_handles=224)
        for di in delta_values
        for do in delta_values
    ]
    feasible = [row for row in candidates if row.get("geometry_feasible") and row.get("collision_safe")]
    selected = sorted(feasible, key=lambda row: row["total_length_m"])[:refine_count]
    refined = []
    refine_positions = np.arange(-100.0, 100.0 + 0.5 * refine_step_m, refine_step_m)
    for row in selected:
        refined.append(
            evaluate_candidate(
                row["delta_in_rad"],
                row["delta_out_rad"],
                refine_positions,
                n_handles=224,
            )
        )

    baseline = next(row for row in candidates if row["delta_in_rad"] == 0.0 and row["delta_out_rad"] == 0.0)
    best_refined = min(
        (row for row in refined if row.get("collision_safe")),
        key=lambda row: row["total_length_m"],
        default=None,
    )
    result = {
        "run_id": datetime.now().astimezone().strftime("Q4SMALL-%Y%m%d-%H%M%S"),
        "status": "exploratory",
        "release_id": "R-Q4-SMALL-TRIAL-001",
        "delta_values_rad": delta_values,
        "coarse_head_range_m": [-100.0, 100.0],
        "coarse_step_m": coarse_step_m,
        "refine_step_m": refine_step_m,
        "candidate_count": len(candidates),
        "geometry_feasible_count": sum(bool(row.get("geometry_feasible")) for row in candidates),
        "coarse_collision_safe_count": len(feasible),
        "baseline": baseline,
        "refined": refined,
        "best_refined": best_refined,
        "elapsed_s": time.perf_counter() - started,
        "candidates": candidates,
    }
    _write_outputs(result)
    return result


def _write_outputs(result: dict) -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "q4_small_collision_map.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    columns = [
        "delta_in_rad",
        "delta_out_rad",
        "geometry_feasible",
        "radius_large_m",
        "radius_small_m",
        "total_length_m",
        "maximum_path_radius_m",
        "collision_safe",
        "minimum_margin_m",
        "minimum_head_s_m",
        "minimum_witness_pair",
        "failure_reason",
    ]
    with (HERE / "q4_small_collision_map.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in result["candidates"]:
            copy = dict(row)
            copy["minimum_witness_pair"] = "-".join(map(str, row.get("minimum_witness_pair", [])))
            writer.writerow(copy)

    baseline = result["baseline"]
    best = result["best_refined"]
    lines = [
        "# Q4 小范围碰撞地图试验结果",
        "",
        f"- 运行编号：`{result['run_id']}`",
        "- 状态：探索性，不进入Q4正式论文结论。",
        f"- 网格：{len(result['delta_values_rad'])}×{len(result['delta_values_rad'])}；切点向调头圆内部偏移。",
        f"- 龙头检查范围：{result['coarse_head_range_m'][0]:.0f} 至 {result['coarse_head_range_m'][1]:.0f} m，粗步长 {result['coarse_step_m']:.1f} m。",
        f"- 几何可行候选：{result['geometry_feasible_count']}/{result['candidate_count']}。",
        f"- 粗扫描碰撞安全候选：{result['coarse_collision_safe_count']}/{result['candidate_count']}。",
        "",
        "## 基准候选",
        "",
        f"- 总弧长：{baseline.get('total_length_m', float('nan')):.9f} m。",
        f"- 粗扫描最小SAT裕度：{baseline.get('minimum_margin_m', float('nan')):.9e} m。",
        f"- 危险板对：{baseline.get('minimum_witness_pair')}。",
    ]
    if best:
        lines.extend(
            [
                "",
                "## 当前加密复核中的最短安全候选",
                "",
                f"- 切点偏移：delta_in={best['delta_in_rad']:.3f} rad，delta_out={best['delta_out_rad']:.3f} rad。",
                f"- 总弧长：{best['total_length_m']:.9f} m。",
                f"- 相对基准缩短：{baseline['total_length_m'] - best['total_length_m']:.9f} m。",
                f"- 加密扫描最小SAT裕度：{best['minimum_margin_m']:.9e} m。",
                f"- 危险板对：{best['minimum_witness_pair']}，龙头路径坐标 {best['minimum_head_s_m']:.3f} m。",
            ]
        )
    else:
        lines.extend(["", "## 加密复核", "", "当前小范围内没有得到通过加密SAT复核的候选。"])
    lines.extend(
        [
            "",
            "## 证据边界",
            "",
            "该结果只覆盖一个S形分支和给定5×5切点偏移范围。粗扫描不能证明采样点之间不存在短暂碰撞，也不能证明全局最优；正式Q4若继续，必须对可行边界自适应加密并进行独立碰撞复核。",
            "",
        ]
    )
    (HERE / "Q4_小范围碰撞地图结果.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse-step", type=float, default=10.0)
    parser.add_argument("--refine-step", type=float, default=2.0)
    args = parser.parse_args()
    result = run_small_map(coarse_step_m=args.coarse_step, refine_step_m=args.refine_step)
    summary = {
        "run_id": result["run_id"],
        "candidate_count": result["candidate_count"],
        "geometry_feasible_count": result["geometry_feasible_count"],
        "coarse_collision_safe_count": result["coarse_collision_safe_count"],
        "best_refined": result["best_refined"],
        "elapsed_s": result["elapsed_s"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
