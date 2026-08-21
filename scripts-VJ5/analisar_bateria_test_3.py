#!/usr/bin/env python3
"""Analisa justiça e qualidade por UE da Bateria 3 com contrastes pareados."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import fmean, median, stdev

from bateria_test_3 import ROOT, SCHEDULERS, half_width, student_t_cdf


QUALITY_METRICS = (
    "throughput_ue_mean_mbps", "throughput_ue_median_mbps",
    "throughput_ue_p5_mbps", "throughput_ue_p10_mbps",
    "zero_throughput_share", "pdr_mean_pct", "pdr_p5_pct",
    "plr_mean_pct", "plr_p95_pct", "delay_mean_p95_ms", "delay_p99_p95_ms",
    "jain_recomputed",
)


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


def percentile(values: list[float], probability: float) -> float:
    """Percentil linear (tipo 7), incluindo interpolação entre observações."""
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def jain(values: list[float]) -> float:
    denominator = len(values) * sum(value * value for value in values)
    return sum(values) ** 2 / denominator if denominator else 0.0


def resolve_output_dir(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def quality_row(execution: dict[str, str]) -> dict[str, object]:
    ue_path = resolve_output_dir(execution["output_dir"]) / "ue_summary.csv"
    rows = read_csv(ue_path)
    if not rows:
        raise RuntimeError(f"{ue_path} não contém UEs")
    throughput = [float(row["throughput_mbps"]) for row in rows]
    pdr = [float(row["pdr_pct"]) for row in rows]
    plr = [float(row["plr_pct"]) for row in rows]
    delay_mean = [float(row["delay_mean_ms"]) for row in rows]
    delay_p99 = [float(row["delay_p99_ms"]) for row in rows]
    recomputed = jain(throughput)
    reported = float(execution["jain"])
    return {
        "scenario": execution["scenario"],
        "rng_run": int(execution["rng_run"]),
        "scheduler": execution["scheduler"],
        "n_ues": len(rows),
        "throughput_ue_mean_mbps": fmean(throughput),
        "throughput_ue_median_mbps": median(throughput),
        "throughput_ue_p5_mbps": percentile(throughput, 0.05),
        "throughput_ue_p10_mbps": percentile(throughput, 0.10),
        "zero_throughput_count": sum(value <= 0.0 for value in throughput),
        "zero_throughput_share": sum(value <= 0.0 for value in throughput) / len(rows),
        "pdr_mean_pct": fmean(pdr),
        "pdr_p5_pct": percentile(pdr, 0.05),
        "plr_mean_pct": fmean(plr),
        "plr_p95_pct": percentile(plr, 0.95),
        "delay_mean_p95_ms": percentile(delay_mean, 0.95),
        "delay_p99_p95_ms": percentile(delay_p99, 0.95),
        "jain_reported": reported,
        "jain_recomputed": recomputed,
        "jain_abs_difference": abs(reported - recomputed),
        "ue_summary": str(ue_path.relative_to(ROOT) if ue_path.is_relative_to(ROOT) else ue_path),
    }


def summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["scenario"]), str(row["scheduler"]))].append(row)
    result = []
    for (scenario, scheduler), group in sorted(grouped.items()):
        record: dict[str, object] = {
            "scenario": scenario, "scheduler": scheduler, "n_runs": len(group)
        }
        for metric in QUALITY_METRICS:
            values = [float(row[metric]) for row in group]
            record[f"{metric}_mean"] = fmean(values)
            record[f"{metric}_ic95_half_width"] = half_width(values)
        result.append(record)
    return result


def paired_tests(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    lookup = {
        (str(row["scenario"]), int(row["rng_run"]), str(row["scheduler"])): row
        for row in rows
    }
    scenarios = sorted({str(row["scenario"]) for row in rows})
    tests: list[dict[str, object]] = []
    for scenario in scenarios:
        runs = sorted({int(row["rng_run"]) for row in rows if row["scenario"] == scenario})
        for left, right in combinations(SCHEDULERS, 2):
            for metric in QUALITY_METRICS:
                differences = [
                    float(lookup[(scenario, run, left)][metric])
                    - float(lookup[(scenario, run, right)][metric])
                    for run in runs
                    if (scenario, run, left) in lookup and (scenario, run, right) in lookup
                ]
                n = len(differences)
                mean_difference = fmean(differences) if differences else math.nan
                standard_deviation = stdev(differences) if n >= 2 else math.nan
                if n >= 2 and standard_deviation > 0:
                    statistic = mean_difference / (standard_deviation / math.sqrt(n))
                    p_value = 2.0 * (1.0 - student_t_cdf(abs(statistic), n - 1))
                    effect = mean_difference / standard_deviation
                elif n >= 2:
                    statistic = math.inf if mean_difference else 0.0
                    p_value = 0.0 if mean_difference else 1.0
                    effect = math.inf if mean_difference else 0.0
                else:
                    statistic = p_value = effect = math.nan
                tests.append({
                    "scenario": scenario, "comparison": f"{left}-{right}",
                    "metric": metric, "n_pairs": n,
                    "mean_difference": mean_difference,
                    "ic95_half_width": half_width(differences),
                    "cohen_dz": effect, "t_statistic": statistic,
                    "p_value": p_value,
                    "left_win_share": sum(value > 0 for value in differences) / n if n else math.nan,
                    "ties": sum(value == 0 for value in differences),
                })
    # Holm controla o erro familiar sobre todos os testes produzidos.
    ordered = sorted(range(len(tests)), key=lambda index: float(tests[index]["p_value"]))
    running = 0.0
    total = len(ordered)
    for rank, index in enumerate(ordered):
        adjusted = min(1.0, (total - rank) * float(tests[index]["p_value"]))
        running = max(running, adjusted)
        tests[index]["p_value_holm"] = running
    return tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="executions.csv da bateria concluída")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executions = [row for row in read_csv(args.input) if row["status"] == "OK"]
    args.output.mkdir(parents=True, exist_ok=True)
    quality = [quality_row(row) for row in executions]
    write_csv(args.output / "qualidade_ue_por_run.csv", quality)
    write_csv(args.output / "qualidade_ue_resumo_ic95.csv", summarize(quality))
    write_csv(args.output / "comparacoes_pareadas_ue.csv", paired_tests(quality))
    if any(float(row["jain_abs_difference"]) > 1e-6 for row in quality):
        raise RuntimeError("Jain recalculado diverge do executions.csv; verifique os CSVs")
    print(f"Análise gravada em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
