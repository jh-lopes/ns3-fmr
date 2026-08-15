#!/usr/bin/env python3
"""Consolida IC95%, diferenças pareadas, Pareto e Nash da Bateria Test 2."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import fmean, stdev

from bateria_test_2 import ROOT, SCHEDULERS, half_width


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def is_dominated(point: dict[str, str], points: list[dict[str, str]]) -> bool:
    throughput = float(point["window_throughput_mean_mbps"])
    jain = float(point["window_jain_mean"])
    return any(
        float(other["window_throughput_mean_mbps"]) >= throughput
        and float(other["window_jain_mean"]) >= jain
        and (float(other["window_throughput_mean_mbps"]) > throughput
             or float(other["window_jain_mean"]) > jain)
        for other in points if other is not point
    )


def nash_scores(points: list[dict[str, str]]) -> dict[str, float]:
    throughput = [float(row["window_throughput_mean_mbps"]) for row in points]
    jain = [float(row["window_jain_mean"]) for row in points]
    t_min, t_max = min(throughput), max(throughput)
    j_min, j_max = min(jain), max(jain)
    return {
        row["scheduler"]: (
            (float(row["window_throughput_mean_mbps"]) - t_min) / (t_max - t_min)
            if t_max > t_min else 1.0
        ) * (
            (float(row["window_jain_mean"]) - j_min) / (j_max - j_min)
            if j_max > j_min else 1.0
        )
        for row in points
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=ROOT / "pesquisa/resultados/bateria_test_2/executions.csv")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "pesquisa/resultados/bateria_test_2/analysis")
    args = parser.parse_args()
    rows = [row for row in read_csv(args.input) if row["status"] == "OK"]
    args.output.mkdir(parents=True, exist_ok=True)

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_run: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["scenario"], row["scheduler"])].append(row)
        by_run[(row["scenario"], int(row["rng_run"]))].append(row)

    summary: list[dict[str, object]] = []
    for (scenario, scheduler), group in sorted(grouped.items()):
        throughput = [float(row["window_throughput_mean_mbps"]) for row in group]
        jain = [float(row["window_jain_mean"]) for row in group]
        summary.append({
            "scenario": scenario, "scheduler": scheduler, "n": len(group),
            "throughput_mean_mbps": fmean(throughput),
            "throughput_ic95_half_width": half_width(throughput),
            "throughput_ic95_relative": half_width(throughput) / abs(fmean(throughput)),
            "jain_mean": fmean(jain), "jain_ic95_half_width": half_width(jain),
            "epsilon_jain_mean": 1.0 - fmean(jain),
        })
    write_csv(args.output / "summary_ic95.csv", summary)

    pareto_nash: list[dict[str, object]] = []
    paired: list[dict[str, object]] = []
    for (scenario, rng_run), points in sorted(by_run.items()):
        if {row["scheduler"] for row in points} != set(SCHEDULERS):
            continue
        scores = nash_scores(points)
        winner = max(scores, key=scores.get)
        lookup = {row["scheduler"]: row for row in points}
        for row in points:
            pareto_nash.append({
                "scenario": scenario, "rng_run": rng_run, "scheduler": row["scheduler"],
                "throughput_mbps": row["window_throughput_mean_mbps"],
                "jain": row["window_jain_mean"], "pareto": not is_dominated(row, points),
                "nash_score": scores[row["scheduler"]], "nash_winner": row["scheduler"] == winner,
            })
        for left, right in (("pf", "rr"), ("mr", "rr"), ("mr", "pf")):
            paired.append({
                "scenario": scenario, "rng_run": rng_run, "comparison": f"{left}-{right}",
                "throughput_difference_mbps":
                    float(lookup[left]["window_throughput_mean_mbps"])
                    - float(lookup[right]["window_throughput_mean_mbps"]),
                "jain_difference": float(lookup[left]["window_jain_mean"])
                    - float(lookup[right]["window_jain_mean"]),
            })
    write_csv(args.output / "pareto_nash_by_run.csv", pareto_nash)
    write_csv(args.output / "paired_differences.csv", paired)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
