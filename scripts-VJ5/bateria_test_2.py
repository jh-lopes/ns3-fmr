#!/usr/bin/env python3
"""Bateria Test 2: replicações progressivas e pareadas para o VJ5G.

O mesmo ``rngRun`` é executado para RR, PF e MR em cada cenário. A bateria
avança em lotes até que todos os schedulers do cenário satisfaçam ambos os
critérios de IC95%, preservando o balanceamento necessário à análise pareada.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, stdev


ROOT = Path(__file__).resolve().parent.parent
NS3 = ROOT / "ns3"
PROGRAM = "simulacao-vj5g"
SCHEDULERS = ("rr", "pf", "mr")
RESULT_RE = re.compile(r"\[RESULT\].*?throughput_mbps=([0-9.eE+-]+).*?jain_vazao=([0-9.eE+-]+)")
FIELDS = (
    "phase", "scenario", "ue_count", "spatial_limit_m", "mobility",
    "scheduler", "seed", "rng_run", "throughput_mbps", "jain",
    "window_throughput_mean_mbps", "window_jain_mean", "window_jain_median",
    "status", "elapsed_s", "output_dir", "error",
)


@dataclass(frozen=True)
class Scenario:
    phase: str
    ue_count: int
    spatial_limit_m: int
    mobility: bool

    @property
    def name(self) -> str:
        mode = "mobile" if self.mobility else "static"
        return f"{self.phase}_{mode}_{self.ue_count}ues_{self.spatial_limit_m}m"


def scenarios(phase: str) -> list[Scenario]:
    result: list[Scenario] = []
    if phase in ("all", "static"):
        result.extend(Scenario("A", ues, limit, False)
                      for ues in (5, 10, 50) for limit in (100, 250, 500))
    if phase in ("all", "mobility"):
        result.extend(Scenario("B", ues, 250, True) for ues in (10, 50))
    return result


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def append_row(path: Path, row: dict[str, object]) -> None:
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def window_statistics(path: Path) -> tuple[float, float, float]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    throughput = [float(row["aggregate_thr_mbps"]) for row in rows]
    jain = sorted(float(row["jain_throughput"]) for row in rows)
    if not throughput:
        raise RuntimeError("window_log.csv não contém janelas")
    middle = len(jain) // 2
    median = jain[middle] if len(jain) % 2 else (jain[middle - 1] + jain[middle]) / 2
    return fmean(throughput), fmean(jain), median


def run_one(args: argparse.Namespace, scenario: Scenario, scheduler: str, rng_run: int) -> dict[str, object]:
    import time
    output_dir = args.output / scenario.name / f"run_{rng_run:03d}" / scheduler
    output_dir.mkdir(parents=True, exist_ok=True)
    window_csv = output_dir / "window_log.csv"
    ue_csv = output_dir / "ue_summary.csv"
    flow_csv = output_dir / "flow_summary.csv"
    temporal_csv = output_dir / "ue_temporal.csv"
    slot_csv = output_dir / "slot_log_common.csv"
    command = [
        args.python, str(NS3), "run", "--no-build",
        f"{PROGRAM} --schedulerMode={scheduler} --trafficProfile=embb"
        f" --ueNumPergNb={scenario.ue_count} --simTime={args.sim_time}s"
        f" --seed={args.seed} --rngRun={rng_run} --streamStart={args.stream_start}"
        f" --mobilityBounds={scenario.spatial_limit_m}"
        f" --enableMobility={'true' if scenario.mobility else 'false'}"
        f" --mobilityModel=random_walk"
        f" --mobilitySpeedMin={args.mobility_speed_mps}"
        f" --mobilitySpeedMax={args.mobility_speed_mps}"
        f" --EnableConsoleDetails=false --EnableWindowCsv=true"
        f" --WindowSizeMs={args.window_ms} --WindowCsvPath={window_csv}"
        f" --EnableUeSummaryCsv=true --UeSummaryCsvPath={ue_csv}"
        f" --EnableFlowSummaryCsv=true --FlowSummaryCsvPath={flow_csv}"
        f" --EnableUeSnapshotCsv=true --UeSnapshotCsvPath={temporal_csv}"
        f" --UeSnapshotPeriod={args.window_ms}ms"
        f" --EnableCommonSlotCsv={'true' if args.enable_rbg else 'false'}"
        f" --CommonSlotCsvPath={slot_csv}",
    ]
    started = time.monotonic()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    elapsed = time.monotonic() - started
    match = RESULT_RE.search(proc.stdout + proc.stderr)
    row: dict[str, object] = {
        "phase": scenario.phase, "scenario": scenario.name,
        "ue_count": scenario.ue_count, "spatial_limit_m": scenario.spatial_limit_m,
        "mobility": scenario.mobility, "scheduler": scheduler,
        "seed": args.seed, "rng_run": rng_run, "throughput_mbps": "",
        "jain": "", "window_throughput_mean_mbps": "", "window_jain_mean": "",
        "window_jain_median": "", "status": "ERROR", "elapsed_s": f"{elapsed:.3f}",
        "output_dir": (output_dir.relative_to(ROOT)
                       if output_dir.is_relative_to(ROOT) else output_dir),
        "error": "",
    }
    if proc.returncode == 0 and match:
        try:
            window_thr, window_jain, window_median = window_statistics(window_csv)
            row.update(throughput_mbps=match.group(1), jain=match.group(2),
                       window_throughput_mean_mbps=f"{window_thr:.9g}",
                       window_jain_mean=f"{window_jain:.9g}",
                       window_jain_median=f"{window_median:.9g}", status="OK")
        except Exception as exc:  # resultado incompleto deve permanecer auditável
            row["error"] = str(exc)
    else:
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-8:]
        row["error"] = " | ".join(tail)[:2000]
    (output_dir / "console.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    return row


def t_critical_95(df: int) -> float:
    # Valores conservadores suficientes para o desenho (n >= 30).
    table = ((29, 2.045), (39, 2.023), (49, 2.010), (59, 2.001),
             (69, 1.995), (79, 1.990), (89, 1.987), (99, 1.984))
    return next((value for limit, value in table if df <= limit), 1.984)


def half_width(values: list[float]) -> float:
    if len(values) < 2:
        return math.inf
    return t_critical_95(len(values) - 1) * stdev(values) / math.sqrt(len(values))


def convergence(rows: list[dict[str, str]], scenario: Scenario, args: argparse.Namespace) -> tuple[bool, list[dict[str, object]]]:
    report: list[dict[str, object]] = []
    converged = True
    for scheduler in SCHEDULERS:
        selected = [row for row in rows if row["scenario"] == scenario.name
                    and row["scheduler"] == scheduler and row["status"] == "OK"]
        throughput = [float(row["window_throughput_mean_mbps"]) for row in selected]
        jain = [float(row["window_jain_mean"]) for row in selected]
        enough = len(selected) >= args.min_runs
        h_thr = half_width(throughput) if len(throughput) > 1 else math.inf
        h_jain = half_width(jain) if len(jain) > 1 else math.inf
        mean_thr = fmean(throughput) if throughput else 0.0
        relative_thr = h_thr / abs(mean_thr) if mean_thr else math.inf
        scheduler_ok = enough and relative_thr <= args.throughput_error and h_jain <= args.jain_error
        converged &= scheduler_ok
        report.append({"scenario": scenario.name, "scheduler": scheduler, "n": len(selected),
                       "throughput_mean": mean_thr, "throughput_half_width": h_thr,
                       "throughput_relative_half_width": relative_thr,
                       "jain_mean": fmean(jain) if jain else math.nan,
                       "jain_half_width": h_jain, "converged": scheduler_ok})
    return converged, report


def write_convergence(path: Path, reports: list[dict[str, object]]) -> None:
    if not reports:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=reports[0].keys())
        writer.writeheader()
        writer.writerows(reports)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("all", "static", "mobility"), default="all")
    parser.add_argument("--output", type=Path, default=ROOT / "pesquisa/resultados/bateria_test_2")
    parser.add_argument("--python", default="python3.12", help="Python compatível usado para executar ./ns3")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--stream-start", type=int, default=1)
    parser.add_argument("--sim-time", type=float, default=30.0)
    parser.add_argument("--window-ms", type=int, default=100)
    parser.add_argument("--mobility-speed-mps", type=float, default=3.0 / 3.6)
    parser.add_argument("--min-runs", type=int, default=30)
    parser.add_argument("--max-runs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--throughput-error", type=float, default=0.05)
    parser.add_argument("--jain-error", type=float, default=0.01)
    parser.add_argument("--enable-rbg", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.min_runs < 2 or args.min_runs > args.max_runs or args.batch_size < 1:
        parser.error("use 2 <= min-runs <= max-runs e batch-size >= 1")
    return args


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ledger = args.output / "executions.csv"
    all_reports: list[dict[str, object]] = []
    for scenario in scenarios(args.phase):
        while True:
            rows = read_rows(ledger)
            converged, report = convergence(rows, scenario, args)
            successful_pairs = {(int(row["rng_run"]), row["scheduler"]) for row in rows
                                if row["scenario"] == scenario.name and row["status"] == "OK"}
            completed = {run for run in range(1, args.max_runs + 1)
                         if all((run, scheduler) in successful_pairs for scheduler in SCHEDULERS)}
            if converged or len(completed) >= args.max_runs:
                all_reports.extend(report)
                break
            first = len(completed) + 1
            target = min(args.max_runs, max(args.min_runs, first + args.batch_size - 1))
            tasks = [(scenario, scheduler, run) for run in range(first, target + 1)
                     for scheduler in SCHEDULERS
                     if not any(row["scenario"] == scenario.name
                                and row["scheduler"] == scheduler
                                and int(row["rng_run"]) == run and row["status"] == "OK"
                                for row in rows)]
            print(f"[{scenario.name}] runs {first}..{target}: {len(tasks)} execuções")
            if args.dry_run:
                break
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(run_one, args, *task) for task in tasks]
                for future in as_completed(futures):
                    row = future.result()
                    append_row(ledger, row)
                    print(f"  {row['scenario']} run={row['rng_run']} {row['scheduler']}: {row['status']}")
                    if row["status"] != "OK":
                        print(f"    {row['error']}", file=sys.stderr)
            if any(row["status"] != "OK" for row in read_rows(ledger)
                   if row["scenario"] == scenario.name and int(row["rng_run"]) >= first):
                print("Há execuções com erro; corrija o ambiente e retome a bateria.", file=sys.stderr)
                return 2
    write_convergence(args.output / "convergence.csv", all_reports)
    metadata = args.output / "metadata.txt"
    metadata.write_text(
        f"generated_utc={datetime.now(timezone.utc).isoformat()}\n"
        f"seed={args.seed}\nmin_runs={args.min_runs}\nmax_runs={args.max_runs}\n"
        f"batch_size={args.batch_size}\nthroughput_relative_half_width={args.throughput_error}\n"
        f"jain_absolute_half_width={args.jain_error}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
