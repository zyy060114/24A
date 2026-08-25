"""Q5 full solver using the supplied p=0.450342 Q4 path implementation."""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from openpyxl import Workbook
from scipy.optimize import minimize_scalar

HERE = Path(__file__).resolve().parent
Q4_CODE = HERE.parents[1] / "04_Q4_调头路径_p0450342扩展" / "code"
if str(Q4_CODE) not in sys.path:
    sys.path.insert(0, str(Q4_CODE))
import q4_result4_p0450342 as q4  # noqa: E402

PITCH = 0.450342
SPEED_CAP = 2.0
N_HANDLES = 224


def head_speed_from_kmax(k_max: float, speed_cap: float = SPEED_CAP) -> float:
    if not math.isfinite(k_max) or k_max <= 0.0:
        raise ValueError("k_max must be finite and positive")
    return float(speed_cap) / float(k_max)


def evaluate_time(geometry, path, time_s: float) -> dict:
    path_coordinates = q4.handle_coordinates(path, float(time_s), n_handles=N_HANDLES)
    positions = tuple(path.point(s) for s in path_coordinates)
    tangents = tuple(q4.path_tangent(path, s) for s in path_coordinates)
    coefficients, min_denominator = q4.speed_coefficients(positions, tangents)
    values = np.abs(np.asarray(coefficients, dtype=float))
    node = int(np.argmax(values))
    return {
        "time_s": float(time_s),
        "coefficients": coefficients,
        "max_k": float(values[node]),
        "max_node": node,
        "min_denominator": float(min_denominator),
        "positions": positions,
        "tangents": tangents,
    }


def run_q5(
    coarse_step: float = 0.25,
    local_window: float = 0.75,
    local_step: float = 0.01,
) -> dict:
    geometry = q4.build_boundary_geometry(PITCH)
    path = q4.sm.build_turn_path(geometry)
    coarse_times = np.arange(-100.0, 100.0 + coarse_step * 0.5, coarse_step)
    coarse_rows = [evaluate_time(geometry, path, float(t)) for t in coarse_times]
    coarse_best = max(coarse_rows, key=lambda row: row["max_k"])

    local_times = np.arange(
        coarse_best["time_s"] - local_window,
        coarse_best["time_s"] + local_window + local_step * 0.5,
        local_step,
    )
    local_rows = [evaluate_time(geometry, path, float(t)) for t in local_times]
    local_candidates = []
    for node in range(N_HANDLES):
        node_values = np.asarray([abs(row["coefficients"][node]) for row in local_rows])
        index = int(np.argmax(node_values))
        left = float(local_times[max(0, index - 1)])
        right = float(local_times[min(len(local_times) - 1, index + 1)])

        def objective(t):
            return -abs(evaluate_time(geometry, path, float(t))["coefficients"][node])

        result = minimize_scalar(objective, bounds=(left, right), method="bounded", options={"xatol": 1e-9, "maxiter": 80})
        local_candidates.append({
            "node": node,
            "time_s": float(result.x),
            "k": float(-result.fun),
            "bracket_s": [left, right],
        })
    peak = max(local_candidates, key=lambda row: row["k"])
    peak_state = evaluate_time(geometry, path, peak["time_s"])
    k_max = float(peak["k"])
    head_speed = head_speed_from_kmax(k_max)
    scaled_peak = np.abs(np.asarray(peak_state["coefficients"])) * head_speed

    # Independent central difference of velocity vectors at the continuous peak.
    h = 1e-5
    before = q4.state_at(geometry, peak["time_s"] - h)
    after = q4.state_at(geometry, peak["time_s"] + h)
    analytic = peak_state["tangents"]
    # Q4's state_at positions are parameterised with unit head speed, so the
    # independent difference must be compared with unit-speed coefficient
    # vectors. The final 2 m/s cap is checked separately by back-substitution.
    analytic_vectors = [
        peak_state["coefficients"][i] * np.asarray(analytic[i])
        for i in range(N_HANDLES)
    ]
    difference_errors = []
    for i in range(N_HANDLES):
        finite_difference = (np.asarray(after.positions[i]) - np.asarray(before.positions[i])) / (2.0 * h)
        difference_errors.append(float(np.linalg.norm(finite_difference - analytic_vectors[i])))

    result = {
        "run_id": datetime.now().astimezone().strftime("Q5-P0450342-%Y%m%d-%H%M%S"),
        "pitch_m": PITCH,
        "official_q4_pitch_m": 1.7,
        "scenario": "user-directed Q3-to-Q4 extension; not original Q4 pitch",
        "q4_collision_warning": {
            "collision_state_count": 88,
            "first_continuous_collision_s": 12.829297347006513,
            "integer_minimum_margin_m": -0.37119495113439094,
            "integer_minimum_margin_time_s": 30,
            "integer_minimum_margin_pair": [1, 17],
            "first_continuous_contact_pair": [1, 15],
            "speed_scaling_cannot_remove_geometry_collision": True,
        },
        "search": {
            "coarse_step_s": coarse_step,
            "coarse_state_count": len(coarse_rows),
            "local_step_s": local_step,
            "local_state_count": len(local_rows),
            "local_candidate_count": len(local_candidates),
            "coarse_k_max": coarse_best["max_k"],
            "coarse_peak_time_s": coarse_best["time_s"],
            "coarse_peak_node": coarse_best["max_node"],
            "continuous_k_max": k_max,
            "peak_time_s": peak["time_s"],
            "peak_node": peak["node"],
            "head_speed_max_m_per_s": head_speed,
            "max_back_substituted_speed_m_per_s": float(np.max(scaled_peak)),
            "minimum_speed_denominator": min(row["min_denominator"] for row in coarse_rows),
            "peak_state_minimum_speed_denominator": peak_state["min_denominator"],
            "coarse_to_continuous_k_difference": k_max - coarse_best["max_k"],
        },
        "independent_difference": {
            "step_s": h,
            "max_velocity_vector_error_m_per_s": max(difference_errors),
        },
    }
    _write_outputs(result, coarse_rows, local_candidates, peak_state)
    return result


def _write_outputs(result, coarse_rows, local_candidates, peak_state):
    tables = HERE.parent / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    (tables / "q5_p0450342_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (tables / "q5_p0450342_coarse_scan.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["time_s", "max_k", "max_node", "min_denominator"])
        writer.writeheader()
        for row in coarse_rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})
    with (tables / "q5_p0450342_local_extrema.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["node", "time_s", "k", "bracket_s"])
        writer.writeheader()
        for row in sorted(local_candidates, key=lambda item: item["k"], reverse=True):
            writer.writerow(row)
    wb = Workbook()
    ws = wb.active
    ws.title = "最大速度结论"
    ws.append(["字段", "数值", "单位"])
    ws.append(["扩展场景螺距", result["pitch_m"], "m"])
    ws.append(["连续最大速度倍率 K_max", result["search"]["continuous_k_max"], "无量纲"])
    ws.append(["峰值时刻", result["search"]["peak_time_s"], "s"])
    ws.append(["峰值把手", f"P_{result['search']['peak_node']}", "—"])
    ws.append(["最大允许龙头速度", result["search"]["head_speed_max_m_per_s"], "m/s"])
    ws.append(["Q4整数时刻碰撞状态数", result["q4_collision_warning"]["collision_state_count"], "状态"])
    ws.append(["Q4首次连续碰撞时刻", result["q4_collision_warning"]["first_continuous_collision_s"], "s"])
    ws.append(["Q4整数时刻最小裕度", result["q4_collision_warning"]["integer_minimum_margin_m"], "m"])
    ws2 = wb.create_sheet("峰值状态倍率")
    ws2.append(["把手", "速度倍率K_i", "按最大龙头速度回代后的速度/m/s"])
    for index, coefficient in enumerate(peak_state["coefficients"]):
        ws2.append([f"P_{index}", abs(float(coefficient)), abs(float(coefficient)) * result["search"]["head_speed_max_m_per_s"]])
    wb.save(tables / "result5_p0450342.xlsx")
    lines = _handoff_markdown(result)
    (HERE.parent / "02_Q5_p0450342_最大速度_论文手交接.md").write_text(lines, encoding="utf-8")
    (HERE.parent / "README.md").write_text("# Q5：p=0.450342 m 扩展场景最大允许龙头速度\n\n正式交接稿：`02_Q5_p0450342_最大速度_论文手交接.md`。\n\n机器结果：`tables/q5_p0450342_evidence.json`、`tables/result5_p0450342.xlsx`。\n", encoding="utf-8")


def _handoff_markdown(result):
    s = result["search"]
    q = result["q4_collision_warning"]
    v = result["independent_difference"]
    return f'''# 问题5：p=0.450342 m 扩展场景下的最大允许龙头速度

## 1. 本问目标

在用户指定的 Q3→Q4 扩展口径 (p=0.450342\\,\\mathrm{{m}}) 下，沿 Q4 已给出的严格2:1、与内螺线外圆相切的 S 形双圆弧基线，求使全部把手速度不超过 (2\\,\\mathrm{{m/s}}) 的最大恒定龙头速度。

必须区分题面与扩展口径：题面 Q4 原始螺距是 (1.7\\,\\mathrm{{m}})；本结果不是原题 Q4/Q5 唯一官方参数下的结论，而是用户指定的 Q3→Q4 扩展场景结果。

## 2. 继承与新增

本问继承公共几何模型的224个把手、223根定长杆、板凳实体和统一坐标口径；继承问题1的刚杆约束速度递推；接收 Q4 的 p=0.450342 双圆弧路径及其速度接口。本问新增的是全路径、全节点速度倍率的最大值搜索和速度上限回代。

| 模块 | 输入 | 输出 | 作用 |
|---|---|---|---|
| Q4路径状态 | 龙头时刻、分段路径 | (P_i,\\boldsymbol\\tau_i) | 还原几何状态 |
| 刚杆速度递推 | 相邻位置、相邻切向 | (k_i,K_i) | 得到速度倍率 |
| 连续极值搜索 | 粗扫峰值区间 | (K_{{\\max}}) | 避免只看整数时刻 |
| 速度上限回代 | (2/K_{{\\max}}) | 全部把手速度 | 核对上限 |

## 3. 为什么这样建模

定长约束为

\\[
\\|P_i-P_{{i-1}}\\|^2=L_i^2.
\\]

对时间求导并令 (V_i=w_i\\boldsymbol\\tau_i)，得到

\\[
w_i=w_{{i-1}}\\frac{{(P_i-P_{{i-1}})\\cdot\\boldsymbol\\tau_{{i-1}}}}{{(P_i-P_{{i-1}})\\cdot\\boldsymbol\\tau_i}}.
\\]

定义

\\[
k_i=\\frac{{(P_i-P_{{i-1}})\\cdot\\boldsymbol\\tau_{{i-1}}}}{{(P_i-P_{{i-1}})\\cdot\\boldsymbol\\tau_i}},\\qquad K_i=\\prod_{{j=1}}^i k_j.
\\]

当龙头速度为 (U) 时，(v_i=|K_i|U)。因此

\\[
U_{{\\max}}=\\frac{{2}}{{K_{{\\max}}}},\\qquad K_{{\\max}}=\\max_{{t,i}}|K_i(t)|.
\\]

这说明速度上限是固定几何状态下的线性缩放问题，不需要再对龙头速度做二分搜索。

## 4. 完整求解过程

`Q4 p=0.450342路径 → 0.25 s全时段粗扫 → 保留峰值附近时间区间 → 0.01 s局部加密 → 对224个把手分别做一维有界极值优化 → 取全局K_max → 计算2/K_max → 回代全部把手速度 → 中心差分复核`

粗扫覆盖 (-100) s 至 (100) s，共 {s['coarse_state_count']} 个状态；局部搜索使用 (0.01) s 网格，并对全部224个节点逐一做连续局部极值优化。

## 5. 结果及其实际含义

| 指标 | 结果 |
|---|---:|
| 扩展场景螺距 | {result['pitch_m']:.6f} m |
| 连续最大速度倍率 (K_{{\\max}}) | {s['continuous_k_max']:.12f} |
| 峰值时刻 | {s['peak_time_s']:.9f} s |
| 峰值把手 | P_{s['peak_node']} |
| 最大允许龙头速度 | {s['head_speed_max_m_per_s']:.12f} m/s |
| 论文建议报告值 | {s['head_speed_max_m_per_s']:.3f} m/s |
| 回代最大把手速度 | {s['max_back_substituted_speed_m_per_s']:.12f} m/s |

因此，在这条固定 Q4 双圆弧基线上，速度约束给出的数学上限为

\\[
\\boxed{{U_{{\\max}}\\approx {s['head_speed_max_m_per_s']:.6f}\\,\\mathrm{{m/s}}}}.
\\]

但 Q4 基线本身存在几何碰撞：201个整数时刻中有 {q['collision_state_count']} 个碰撞状态；首次连续碰撞约为 (t={q['first_continuous_collision_s']:.9f}) s；整数时刻全局最小裕度为 {q['integer_minimum_margin_m']:.12f} m，发生在 (t={q['integer_minimum_margin_time_s']}) s，危险板凳对为 ((1,17))。首次连续接触对应的板凳对是 ((1,15))。

所以降低龙头速度只能降低速度数值，不能消除几何碰撞。上述 (U_{{\\max}}) 是“在当前碰撞基线上的速度约束上限”，不是“已经保证整条龙无碰撞运动”的最终安全速度。

## 6. 模型检验、局限与下一问接口

- Q4路径几何和速度递推由 `04_Q4_调头路径_p0450342扩展` 提供；Q4证据文件确认半径比、相切残差、速度分母和碰撞状态。
- 粗扫与局部极值结果已保存；粗扫最大倍率与连续局部最大倍率之差为 {s['coarse_to_continuous_k_difference']:.3e}。
- 速度上限回代后最大把手速度为 {s['max_back_substituted_speed_m_per_s']:.12f} m/s，与2 m/s约束一致。
- 独立中心差分步长为 (h={v['step_s']}) s，最大速度向量误差为 {v['max_velocity_vector_error_m_per_s']:.3e} m/s。
- 最小速度递推分母为 {s['minimum_speed_denominator']:.12f}，未出现速度递推奇异。
- 局限是当前 Q4 路径有碰撞；若 Q4 后续更换为无碰撞路径，必须重新计算 (K_{{\\max}})，不能复用本数值。

文字流程图：

`Q4固定路径 → 全路径位置恢复 → 切向量 → k_i/K_i → 连续极值 → K_max → 2/K_max → 回代验证`

证据文件：`tables/q5_p0450342_evidence.json`、`tables/q5_p0450342_coarse_scan.csv`、`tables/q5_p0450342_local_extrema.csv`、`tables/result5_p0450342.xlsx`。
'''


if __name__ == "__main__":
    print(json.dumps(run_q5(), ensure_ascii=False, indent=2))
