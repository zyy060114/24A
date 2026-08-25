from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "建模总控" / "01-shared" / "code"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from spiral_chain import SpiralChain
from collision_q2 import benches_from_handles, collision_report

OUT = Path(__file__).resolve().parents[1]
TABLES = OUT / "tables"
LOG = OUT / "run_q2_collision.log"


def evaluate(model: SpiralChain, t: float) -> dict:
    _, handles = model.positions_at(t)
    benches = benches_from_handles(handles)
    report = collision_report(benches)
    return {
        "time_s": float(t),
        "global_margin_m": report.global_margin,
        "collision_flag": report.collision_flag,
        "collision_pairs": [list(p) for p in report.collision_pairs],
        "witness_pair": list(report.witness_pair) if report.witness_pair else None,
        "tested_pairs": report.tested_pairs,
        "circle_rejected_pairs": report.circle_rejected_pairs,
        "total_forbidden_pairs": report.total_forbidden_pairs,
    }


def refine_first_collision(model: SpiralChain, left: float, right: float, tol_t: float = 1e-10, tol_g: float = 1e-9):
    cache = {}
    def g(t):
        key = round(float(t), 12)
        if key not in cache:
            cache[key] = evaluate(model, t)
        return cache[key]["global_margin_m"]
    # The first scan transition is safe (positive) -> collision (non-positive).
    root = brentq(g, left, right, xtol=tol_t, rtol=1e-12, maxiter=100)
    result = evaluate(model, root)
    result["refinement_left_s"] = left
    result["refinement_right_s"] = right
    result["refinement_time_tolerance_s"] = tol_t
    result["refinement_margin_abs_m"] = abs(result["global_margin_m"])
    result["refinement_evaluations"] = len(cache)
    result["refinement_pass"] = abs(result["global_margin_m"]) <= max(tol_g, 1e-7)
    return result


def run(scan_step: float = 0.5, t_start: float = 0.0, t_end: float = 442.0) -> dict:
    started = time.perf_counter()
    model = SpiralChain(pitch=0.55, head_speed=1.0, n_handles=224)
    times = []
    t = t_start
    while t <= t_end + 1e-12:
        times.append(round(t, 12)); t += scan_step
    eval_cache = {}
    def ev(t):
        key = round(float(t), 12)
        if key not in eval_cache:
            eval_cache[key] = evaluate(model, key)
        return eval_cache[key]
    scan = [ev(t) for t in times]
    transitions = []
    for a, b in zip(scan[:-1], scan[1:]):
        if a["global_margin_m"] > 0 and b["global_margin_m"] <= 0:
            transitions.append([a["time_s"], b["time_s"]])
    first = refine_first_collision(model, *transitions[0]) if transitions else None
    # Stability checks use coarser subgrids of the same complete scan. This
    # does not assume monotonicity: every sign transition on every grid is kept.
    stability = []
    for step in (1.0, 2.0):
        stride = int(round(step / scan_step))
        ss = scan[::stride]
        tr = [[u["time_s"], v["time_s"]] for u, v in zip(ss[:-1], ss[1:]) if u["global_margin_m"] > 0 and v["global_margin_m"] <= 0]
        rr = refine_first_collision(model, *tr[0]) if tr else None
        stability.append({"scan_step_s": step, "transitions": tr, "refined_time_s": rr["time_s"] if rr else None, "refined_margin_m": rr["global_margin_m"] if rr else None})
    result = {"started": datetime.now().astimezone().isoformat(timespec="seconds"), "scan_step_s": scan_step, "time_range_s": [t_start, t_end], "scan_count": len(scan), "transitions": transitions, "first_collision": first, "stability": stability, "unique_evaluations": len(eval_cache), "elapsed_s": time.perf_counter() - started, "pass": bool(first and first["refinement_pass"] and transitions)}
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / "q2_scan_results.json").write_text(json.dumps({"scan": scan, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    with (TABLES / "q2_scan_results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["time_s", "global_margin_m", "collision_flag", "candidate_pairs", "tested_pairs", "circle_rejected_pairs"])
        for r in scan: w.writerow([r["time_s"], f'{r["global_margin_m"]:.12e}', r["collision_flag"], ";".join(f"{i+1}-{j+1}" for i,j in r["collision_pairs"]), r["tested_pairs"], r["circle_rejected_pairs"]])
    (TABLES / "q2_first_collision.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
