from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
TABLES = HERE.parent / "tables"
FIGURES = HERE.parent / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

rows = []
with (TABLES / "q5_p0450342_coarse_scan.csv").open(encoding="utf-8-sig", newline="") as stream:
    rows = list(csv.DictReader(stream))
times = [float(row["time_s"]) for row in rows]
values = [float(row["max_k"]) for row in rows]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(7.0, 3.5), dpi=180)
ax.plot(times, values, color="#245a8d", linewidth=1.3, label="coarse scan")
peak_index = max(range(len(values)), key=values.__getitem__)
ax.scatter([times[peak_index]], [values[peak_index]], color="#c44e52", s=24, zorder=3)
ax.set_xlabel("Head time t / s")
ax.set_ylabel("Maximum speed multiplier")
ax.set_title("Q5: p=0.450342 m path-wide speed multiplier")
ax.grid(axis="y", color="#dddddd", linewidth=0.5)
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(FIGURES / "图1_Q5_p0450342_速度倍率全时段.png", dpi=300)
fig.savefig(FIGURES / "图1_Q5_p0450342_速度倍率全时段.svg")
plt.close(fig)
