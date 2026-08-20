#!/usr/bin/env python3
"""Bateria 3: topologias estáticas aleatórias, replicações pareadas e IC95%."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, stdev

ROOT = Path(__file__).resolve().parent.parent
SCHEDULERS = ("rr", "pf", "mr", "qos")
RESULT_RE = re.compile(
    r"\[RESULT\].*?throughput_mbps=([0-9.eE+-]+).*?"
    r"jain_vazao=([0-9.eE+-]+).*?rng_run=([0-9]+)"
)
FIELDS = (
    "scenario", "ue_count", "radius_m", "bandwidth_hz", "lambda_pps",
    "offered_load_mbps", "scheduler", "seed", "rng_run",
    "throughput_mbps", "jain", "window_throughput_mean_mbps",
    "window_jain_mean", "position_hash", "status", "elapsed_s",
    "output_dir", "error",
)


@dataclass(frozen=True)
class Scenario:
    ue_count: int
    radius_m: int

    @property
    def name(self) -> str:
        return f"static_random_{self.ue_count}ues_{self.radius_m}m"


def scenarios(ue_count: int, radius_m: int) -> list[Scenario]:
    """Retorna somente o cenário controlado solicitado para a Bateria 3."""
    return [Scenario(ue_count, radius_m)]


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


def resolve_binary(configured: Path | None) -> Path:
    candidates = [configured] if configured else [
        *sorted((ROOT / "build/scratch").glob("ns3.*-simulacao-vj5g-optimized")),
        *sorted((ROOT / "build/scratch").glob("ns3.*-simulacao-vj5g-default")),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise SystemExit("Binário simulacao-vj5g não encontrado; execute './ns3 build'.")


def csv_mean(path: Path, column: str) -> float:
    with path.open(newline="", encoding="utf-8") as handle:
        values = [float(row[column]) for row in csv.DictReader(handle)]
    if not values:
        raise RuntimeError(f"{path} não contém dados")
    return fmean(values)


def position_hash(path: Path, expected_run: int) -> str:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or any(int(row["rng_run"]) != expected_run for row in rows):
        raise RuntimeError("rng_run ausente ou divergente no ue_summary.csv")
    positions = [
        (int(row["ue_id"]), float(row["x_initial_m"]),
         float(row["y_initial_m"]), float(row["z_initial_m"]))
        for row in rows
    ]
    payload = "\n".join(f"{ue},{x:.12g},{y:.12g},{z:.12g}"
                        for ue, x, y, z in positions)
    return hashlib.sha256(payload.encode()).hexdigest()


def run_one(args: argparse.Namespace, scenario: Scenario, scheduler: str,
            rng_run: int) -> dict[str, object]:
    output = args.output / scenario.name / f"run_{rng_run:03d}" / scheduler
    output.mkdir(parents=True, exist_ok=True)
    window = output / "window_log.csv"
    ue = output / "ue_summary.csv"
    flow = output / "flow_summary.csv"
    command = [
        str(args.sim_binary), f"--schedulerMode={scheduler}",
        "--trafficProfile=embb", f"--ueNumPergNb={scenario.ue_count}",
        f"--simTime={args.sim_time}s", f"--seed={args.seed}",
        f"--rngRun={rng_run}", "--enableMobility=false",
        "--positionMode=random_disc_static",
        f"--mobilityBounds={scenario.radius_m}",
        f"--bandwidth={args.bandwidth}",
        f"--lambdaOverride={args.lambda_pps}",
        "--EnableConsoleDetails=false", "--EnableWindowCsv=true",
        f"--WindowSizeMs={args.window_ms}", f"--WindowCsvPath={window}",
        "--EnableUeSummaryCsv=true", f"--UeSummaryCsvPath={ue}",
        "--EnableFlowSummaryCsv=true", f"--FlowSummaryCsvPath={flow}",
    ]
    (output / "command.txt").write_text(
        subprocess.list2cmdline(command) + "\n", encoding="utf-8")
    started = time.monotonic()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    elapsed = time.monotonic() - started
    console = proc.stdout + proc.stderr
    (output / "console.log").write_text(console, encoding="utf-8")
    row: dict[str, object] = {
        "scenario": scenario.name, "ue_count": scenario.ue_count,
        "radius_m": scenario.radius_m, "bandwidth_hz": args.bandwidth,
        "lambda_pps": args.lambda_pps,
        "offered_load_mbps": scenario.ue_count * args.lambda_pps * 1500 * 8 / 1e6,
        "scheduler": scheduler,
        "seed": args.seed, "rng_run": rng_run, "throughput_mbps": "",
        "jain": "", "window_throughput_mean_mbps": "",
        "window_jain_mean": "", "position_hash": "", "status": "ERROR",
        "elapsed_s": f"{elapsed:.3f}", "output_dir": output.relative_to(ROOT),
        "error": "",
    }
    match = RESULT_RE.search(console)
    try:
        if proc.returncode != 0 or not match:
            raise RuntimeError(" | ".join(console.strip().splitlines()[-8:]))
        if int(match.group(3)) != rng_run:
            raise RuntimeError("rng_run divergente na linha [RESULT]")
        row.update(
            throughput_mbps=match.group(1), jain=match.group(2),
            window_throughput_mean_mbps=csv_mean(window, "aggregate_thr_mbps"),
            window_jain_mean=csv_mean(window, "jain_throughput"),
            position_hash=position_hash(ue, rng_run), status="OK",
        )
    except Exception as exc:  # o ledger preserva falhas auditáveis
        row["error"] = str(exc)[:2000]
    return row


def half_width(values: list[float]) -> float:
    if len(values) < 2:
        return math.inf
    # Conservador para n >= 30; converge a 1,984 até n=100.
    critical = 2.045 if len(values) <= 30 else 2.023 if len(values) <= 40 else 2.01
    return critical * stdev(values) / math.sqrt(len(values))


def converged(rows: list[dict[str, str]], scenario: Scenario,
              args: argparse.Namespace) -> bool:
    for scheduler in SCHEDULERS:
        selected = [row for row in rows if row["scenario"] == scenario.name
                    and row["scheduler"] == scheduler and row["status"] == "OK"]
        if len(selected) < args.min_runs:
            return False
        throughput = [float(row["window_throughput_mean_mbps"]) for row in selected]
        jain = [float(row["window_jain_mean"]) for row in selected]
        if half_width(throughput) / abs(fmean(throughput)) > args.throughput_error:
            return False
        if half_width(jain) > args.jain_error:
            return False
    return True


def validate_pairing(rows: list[dict[str, str]], scenario: Scenario,
                     rng_run: int) -> None:
    selected = [row for row in rows if row["scenario"] == scenario.name
                and int(row["rng_run"]) == rng_run and row["status"] == "OK"]
    if len(selected) == len(SCHEDULERS):
        hashes = {row["position_hash"] for row in selected}
        if len(hashes) != 1:
            raise RuntimeError(
                f"topologia não pareada em {scenario.name}, rngRun={rng_run}")


def validate_distinct_runs(rows: list[dict[str, str]], scenario: Scenario) -> None:
    """Impede que runs completas reutilizem acidentalmente a mesma topologia."""
    hashes_by_run: dict[int, str] = {}
    for row in rows:
        if row["scenario"] != scenario.name or row["status"] != "OK":
            continue
        rng_run = int(row["rng_run"])
        hashes_by_run.setdefault(rng_run, row["position_hash"])
    hashes = list(hashes_by_run.values())
    if len(hashes) != len(set(hashes)):
        raise RuntimeError(f"runs distintas reutilizaram topologia em {scenario.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "pesquisa/resultados/bateria_test_3")
    parser.add_argument("--sim-binary", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ue-count", type=int, default=50)
    parser.add_argument("--radius-m", type=int, default=500)
    parser.add_argument("--bandwidth", type=int, default=100_000_000)
    parser.add_argument("--lambda-pps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--sim-time", type=float, default=30.0)
    parser.add_argument("--window-ms", type=int, default=100)
    parser.add_argument("--min-runs", type=int, default=30)
    parser.add_argument("--max-runs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--throughput-error", type=float, default=0.05)
    parser.add_argument("--jain-error", type=float, default=0.01)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.sim_binary = resolve_binary(args.sim_binary)
    if (args.workers < 1 or args.ue_count < 2 or args.radius_m <= 10
            or args.bandwidth <= 0 or args.lambda_pps <= 0
            or not 2 <= args.min_runs <= args.max_runs):
        parser.error("parâmetros físicos/estatísticos inválidos")
    return args


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ledger = args.output / "executions.csv"
    for scenario in scenarios(args.ue_count, args.radius_m):
        while True:
            rows = read_rows(ledger)
            if converged(rows, scenario, args):
                break
            complete = {
                run for run in range(1, args.max_runs + 1)
                if all(any(row["scenario"] == scenario.name
                           and row["scheduler"] == scheduler
                           and int(row["rng_run"]) == run
                           and row["status"] == "OK" for row in rows)
                       for scheduler in SCHEDULERS)
            }
            if len(complete) >= args.max_runs:
                break
            first_missing = next(run for run in range(1, args.max_runs + 1)
                                 if run not in complete)
            target = min(args.max_runs,
                         max(args.min_runs, first_missing + args.batch_size - 1))
            tasks = [(scenario, scheduler, run)
                     for run in range(first_missing, target + 1)
                     for scheduler in SCHEDULERS
                     if not any(row["scenario"] == scenario.name
                                and row["scheduler"] == scheduler
                                and int(row["rng_run"]) == run
                                and row["status"] == "OK" for row in rows)]
            print(f"[{scenario.name}] rngRun {first_missing}..{target}: {len(tasks)}")
            if args.dry_run:
                return 0
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(run_one, args, *task) for task in tasks]
                batch_rows = []
                for future in as_completed(futures):
                    row = future.result()
                    batch_rows.append(row)
                    append_row(ledger, row)
                    print(f"  run={row['rng_run']} {row['scheduler']}: {row['status']}")
            rows = read_rows(ledger)
            for run in range(first_missing, target + 1):
                validate_pairing(rows, scenario, run)
            validate_distinct_runs(rows, scenario)
            if any(row["status"] != "OK" for row in batch_rows):
                print("Execução com erro; corrija e retome usando o mesmo output.")
                return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
