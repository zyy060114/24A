"""Dense precritical scan and local-minimum audit for Q2 collision leakage risk."""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "建模总控" / "01-shared" / "code"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spiral_chain import SpiralChain
from solve_q2_collision import evaluate, refine_first_collision

OUT = Path(__file__).resolve().parents[1]
TABLES = OUT / "tables"
LOG = OUT / "run_q2_dense_precritical.log"


def positive_to_nonpositive_intervals(rows: list[dict]) -> list[list[float]]:
    return [
        [a["time_s"], b["time_s"]]
        for a, b in zip(rows[:-1], rows[1:])
        if a["global_margin_m"] > 0 and b["global_margin_m"] <= 0
    ]


def local_minimum_indices(rows: list[dict]) -> list[int]:
    if not rows:
        return []
    values = [r["global_margin_m"] for r in rows]
    indices = []
    if len(values) == 1 or values[0] <= values[1]:
        indices.append(0)
    for i in range(1, len(values) - 1):
        if values[i] <= values[i - 1] and values[i] <= values[i + 1]:
            indices.append(i)
    if len(values) > 1 and values[-1] <= values[-2]:
        indices.append(len(values) - 1)
    return indices


def run(step: float = 0.1, t_end: float = 412.5) -> dict:
    started = time.perf_counter()
    model = SpiralChain(pitch=0.55, head_speed=1.0, n_handles=224)
    cache: dict[float, dict] = {}

    def ev(t: float) -> dict:
        key = round(float(t), 12)
        if key not in cache:
            cache[key] = evaluate(model, key)
        return cache[key]

    count = int(round(t_end / step)) + 1
    scan = [ev(k * step) for k in range(count)]
    transitions = positive_to_nonpositive_intervals(scan)
    refined = [refine_first_collision(model, a, b) for a, b in transitions]

    precritical = [r for r in scan if r["time_s"] <= 412.0 + 1e-12]
    minima_indices = local_minimum_indices(precritical)
    local_audit = []
    for idx in minima_indices:
        sample = precritical[idx]
        if idx == 0 or idx == len(precritical) - 1:
            local_audit.append({
                "sample_time_s": sample["time_s"],
                "sample_margin_m": sample["global_margin_m"],
                "left_time_s": precritical[max(0, idx - 1)]["time_s"],
                "left_margin_m": precritical[max(0, idx - 1)]["global_margin_m"],
                "right_time_s": precritical[min(len(precritical) - 1, idx + 1)]["time_s"],
                "right_margin_m": precritical[min(len(precritical) - 1, idx + 1)]["global_margin_m"],
                "refined_time_s": sample["time_s"],
                "refined_margin_m": sample["global_margin_m"],
                "endpoint": True,
            })
            continue
        left = precritical[idx - 1]["time_s"]
        right = precritical[idx + 1]["time_s"]
        opt = minimize_scalar(lambda x: ev(x)["global_margin_m"], bounds=(left, right), method="bounded", options={"xatol": 1e-9, "maxiter": 100})
        local_audit.append({
            "sample_time_s": sample["time_s"],
            "sample_margin_m": sample["global_margin_m"],
            "left_time_s": left,
            "left_margin_m": precritical[idx - 1]["global_margin_m"],
            "right_time_s": right,
            "right_margin_m": precritical[idx + 1]["global_margin_m"],
            "refined_time_s": float(opt.x),
            "refined_margin_m": float(opt.fun),
            "endpoint": False,
            "success": bool(opt.success),
        })

    # A second, offset 0.05 s grid checks every midpoint of the 0.1 s cells.
    midpoint_scan = [ev(0.05 + 0.1 * k) for k in range(int((412.45 - 0.05) / 0.1) + 1)]
    # The final two seconds are additionally scanned at 0.001 s to resolve the
    # approach to the first root without relying on coarse-grid shape.
    terminal_scan = [ev(410.0 + 0.001 * k) for k in range(2501)]
    terminal_transitions = positive_to_nonpositive_intervals(terminal_scan)

    min_pre_sample = min(precritical, key=lambda r: r["global_margin_m"])
    min_midpoint = min(midpoint_scan, key=lambda r: r["global_margin_m"])
    min_refined = min(local_audit, key=lambda r: r["refined_margin_m"])
    max_abs_step_change = max(abs(b["global_margin_m"] - a["global_margin_m"]) for a, b in zip(precritical[:-1], precritical[1:]))
    result = {
        "started": datetime.now().astimezone().isoformat(timespec="seconds"),
        "full_scan_step_s": step,
        "full_scan_range_s": [0.0, t_end],
        "full_scan_count": len(scan),
        "positive_to_nonpositive_intervals": transitions,
        "refined_roots": [{"time_s": r["time_s"], "margin_m": r["global_margin_m"], "pairs": r["collision_pairs"]} for r in refined],
        "precritical_range_s": [0.0, 412.0],
        "precritical_all_positive": all(r["global_margin_m"] > 0 for r in precritical),
        "precritical_sample_minimum": min_pre_sample,
        "precritical_local_minimum_count": len(local_audit),
        "precritical_refined_minimum": min_refined,
        "offset_grid_step_s": 0.1,
        "offset_grid_offset_s": 0.05,
        "offset_grid_count": len(midpoint_scan),
        "offset_grid_minimum": min_midpoint,
        "terminal_scan_step_s": 0.001,
        "terminal_scan_range_s": [410.0, 412.5],
        "terminal_scan_count": len(terminal_scan),
        "terminal_positive_to_nonpositive_intervals": terminal_transitions,
        "max_abs_0p1_step_margin_change_m": max_abs_step_change,
        "unique_evaluations": len(cache),
        "elapsed_s": time.perf_counter() - started,
    }
    result["pass"] = bool(
        transitions
        and transitions[0] == [412.4, 412.5]
        and result["precritical_all_positive"]
        and min_refined["refined_margin_m"] > 0
        and min_midpoint["global_margin_m"] > 0
        and terminal_transitions == [[412.473, 412.474]]
    )

    TABLES.mkdir(parents=True, exist_ok=True)
    with (TABLES / "q2_dense_0p1_scan.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "global_margin_m", "collision_flag", "candidate_pairs", "tested_pairs", "circle_rejected_pairs"])
        for r in scan:
            w.writerow([r["time_s"], f'{r["global_margin_m"]:.12e}', r["collision_flag"], ";".join(f"{i+1}-{j+1}" for i, j in r["collision_pairs"]), r["tested_pairs"], r["circle_rejected_pairs"]])
    with (TABLES / "q2_precritical_local_minima.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = list(local_audit[0].keys())
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(local_audit)
    (TABLES / "q2_dense_precritical_validation.json").write_text(json.dumps({"result": result, "local_minima": local_audit}, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))

