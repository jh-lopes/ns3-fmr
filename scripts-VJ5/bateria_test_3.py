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
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median, stdev

from csv_numeric_guard import validate_numeric_csv

ROOT = Path(__file__).resolve().parent.parent
SCHEDULERS = ("rr", "pf", "mr", "qos")
DEFAULT_LAMBDA_PPS = 500
RESULT_RE = re.compile(
    r"\[RESULT\].*?throughput_mbps=([0-9.eE+-]+).*?"
    r"jain_vazao=([0-9.eE+-]+).*?rng_run=([0-9]+)"
)
FIELDS = (
    "scenario", "ue_count", "flows_per_ue", "radius_m", "bandwidth_hz", "lambda_pps",
    "offered_load_mbps", "scheduler", "seed", "rng_run",
    "throughput_mbps", "jain", "window_throughput_mean_mbps",
    "window_jain_mean", "position_hash", "status", "elapsed_s",
    "output_dir", "error",
)


@dataclass(frozen=True)
class Scenario:
    ue_count: int
    radius_m: int
    flows_per_ue: int = 1

    @property
    def name(self) -> str:
        return (f"static_random_{self.ue_count}ues_{self.radius_m}m_"
                f"{self.flows_per_ue}flows_per_ue")


class ProgressPanel:
    """Painel de progresso para as execuções paralelas da bateria."""

    BAR_WIDTH = 20

    def __init__(self, tasks: list[tuple[Scenario, str, int]], enabled: bool,
                 force: bool = False):
        self.enabled = enabled and (sys.stdout.isatty() or force)
        self.lock = threading.Lock()
        self.rendered_lines = 0
        self.order = [(run, scheduler) for _, scheduler, run in tasks]
        self.states = {
            key: {
                "status": "WAITING", "started": None, "elapsed": 0.0,
                "result": "", "error": ""
            }
            for key in self.order
        }

    def start(self, run: int, scheduler: str) -> None:
        with self.lock:
            state = self.states[(run, scheduler)]
            state["status"] = "RUNNING"
            state["started"] = time.monotonic()

    def finish(self, run: int, scheduler: str, row: dict[str, object]) -> None:
        with self.lock:
            state = self.states[(run, scheduler)]
            started = state["started"] or time.monotonic()
            state["elapsed"] = time.monotonic() - started
            state["status"] = "DONE" if row["status"] == "OK" else "ERROR"
            state["result"] = str(row["status"])
            state["error"] = str(row.get("error", ""))

    @staticmethod
    def _duration(seconds: float) -> str:
        minutes, secs = divmod(int(seconds), 60)
        return f"{minutes:02d}:{secs:02d}"

    @classmethod
    def _bar(cls, fraction: float) -> str:
        fraction = min(1.0, max(0.0, fraction))
        filled = round(fraction * cls.BAR_WIDTH)
        return "█" * filled + "░" * (cls.BAR_WIDTH - filled)

    def _snapshot(self) -> tuple[list[tuple[tuple[int, str], dict]], float | None]:
        with self.lock:
            snapshot = [(key, dict(self.states[key])) for key in self.order]
        durations = [state["elapsed"] for _, state in snapshot
                     if state["status"] in {"DONE", "ERROR"}
                     and state["elapsed"] > 0]
        return snapshot, median(durations) if durations else None

    def render(self) -> None:
        if not self.enabled:
            return
        snapshot, estimate = self._snapshot()
        now = time.monotonic()
        completed = sum(state["status"] in {"DONE", "ERROR"}
                        for _, state in snapshot)
        total = len(snapshot)
        lines = [
            f"Progresso geral [{self._bar(completed / total)}] "
            f"{completed:>2}/{total:<2} ({100 * completed / total:5.1f}%)"
        ]

        for (run, scheduler), state in snapshot:
            status = state["status"]
            if status == "WAITING":
                bar = self._bar(0)
                detail = "aguardando"
            elif status == "RUNNING":
                elapsed = now - float(state["started"])
                if estimate:
                    fraction = min(elapsed / estimate, 0.95)
                    detail = f"executando ~{100 * fraction:4.0f}% {self._duration(elapsed)}"
                else:
                    # Até a primeira conclusão, a barra é indeterminada.
                    fraction = ((int(elapsed * 4) % self.BAR_WIDTH) + 1) / self.BAR_WIDTH
                    detail = f"executando       {self._duration(elapsed)}"
                bar = self._bar(fraction)
            elif status == "DONE":
                bar = self._bar(1)
                detail = f"OK               {self._duration(state['elapsed'])}"
            else:
                bar = self._bar(1)
                detail = f"ERRO             {self._duration(state['elapsed'])}"
            lines.append(
                f"run={run:03d} {scheduler:<4} [{bar}] {detail}"
            )

        if self.rendered_lines:
            sys.stdout.write(f"\x1b[{self.rendered_lines}F")
        for line in lines:
            sys.stdout.write("\x1b[2K" + line + "\n")
        for _ in range(max(0, self.rendered_lines - len(lines))):
            sys.stdout.write("\x1b[2K\n")
        sys.stdout.flush()
        self.rendered_lines = len(lines)

    def completed_message(self, row: dict[str, object]) -> None:
        if not self.enabled:
            print(f"  run={int(row['rng_run']):03d} "
                  f"{str(row['scheduler']):<4}: {row['status']} "
                  f"({float(row['elapsed_s']):.1f}s)")


def run_one_with_progress(args: argparse.Namespace, scenario: Scenario,
                          scheduler: str, rng_run: int,
                          panel: ProgressPanel) -> dict[str, object]:
    panel.start(rng_run, scheduler)
    row = run_one(args, scenario, scheduler, rng_run)
    panel.finish(rng_run, scheduler, row)
    return row


def scenarios(ue_count: int, radius_m: int, flows_per_ue: int = 1) -> list[Scenario]:
    """Retorna somente o cenário controlado solicitado para a Bateria 3."""
    return [Scenario(ue_count, radius_m, flows_per_ue)]


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


def validate_result_csvs(ue: Path, window: Path, flow: Path) -> None:
    """Impede que CSV decimalmente corrompido seja aceito pela campanha."""
    def headers(path: Path) -> set[str]:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return set(next(csv.reader(handle)))

    ue_headers = headers(ue)
    window_headers = headers(window)
    flow_headers = headers(flow)
    ue_throughput = ("app_throughput_traffic_mbps"
                     if "app_throughput_traffic_mbps" in ue_headers
                     else "throughput_mbps")
    ue_jains = ({"app_jain_traffic", "app_jain_total", "flowmon_jain"}
                if "app_jain_traffic" in ue_headers else {"jain_vazao"})
    ue_aggregate = ({"app_throughput_traffic_aggregate_mbps"}
                    if "app_throughput_traffic_aggregate_mbps" in ue_headers
                    else {"throughput_agregado_mbps"})
    validate_numeric_csv(
        ue,
        {"rng_run", "ue_id", "x_initial_m", "y_initial_m", "z_initial_m",
         ue_throughput, "sinr_mean_db", "distance_gnb_m"} | ue_jains | ue_aggregate,
        {"z_initial_m": (0.0, 100.0), "distance_gnb_m": (0.0, 10_000.0),
         "jain_vazao": (0.0, 1.0), "app_jain_traffic": (0.0, 1.0),
         "app_jain_total": (0.0, 1.0), "flowmon_jain": (0.0, 1.0)},
    )
    window_time = "end_time_s" if "end_time_s" in window_headers else "time_s"
    validate_numeric_csv(
        window,
        {"rng_run", "window_id", window_time, "aggregate_thr_mbps",
         "jain_throughput"},
        {window_time: (0.0, None), "aggregate_thr_mbps": (0.0, None),
         "jain_throughput": (0.0, 1.0)},
    )
    flow_throughput = ("flowmon_throughput_mbps"
                       if "flowmon_throughput_mbps" in flow_headers
                       else "throughput_mbps")
    flow_tx = "flowmon_tx_packets" if "flowmon_tx_packets" in flow_headers else "tx_packets"
    flow_rx = "flowmon_rx_packets" if "flowmon_rx_packets" in flow_headers else "rx_packets"
    flow_lost = ({"lost_packets"} if "lost_packets" in flow_headers
                 else {"flowmon_undelivered_at_stop_packets"})
    validate_numeric_csv(
        flow,
        {"rng_run", "ue_id", flow_tx, flow_rx, flow_throughput} | flow_lost,
        {flow_tx: (0.0, None), flow_rx: (0.0, None),
         next(iter(flow_lost)): (0.0, None), flow_throughput: (0.0, None)},
    )


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
        f"--flowsPerUe={scenario.flows_per_ue}",
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
        "flows_per_ue": scenario.flows_per_ue,
        "radius_m": scenario.radius_m, "bandwidth_hz": args.bandwidth,
        "lambda_pps": args.lambda_pps,
        "offered_load_mbps": (scenario.ue_count * scenario.flows_per_ue *
                              args.lambda_pps * 1500 * 8 / 1e6),
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
        validate_result_csvs(ue, window, flow)
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


def report_data_quality(rows: list[dict[str, str]], scenario: Scenario) -> None:
    """Resume se a campanha produziu variação útil para comparação."""
    print(f"\n[DIAGNÓSTICO] {scenario.name}")
    scheduler_means: dict[str, tuple[float, float]] = {}
    for scheduler in SCHEDULERS:
        selected = [row for row in rows
                    if row["scenario"] == scenario.name
                    and row["scheduler"] == scheduler
                    and row["status"] == "OK"]
        throughput = [float(row["throughput_mbps"]) for row in selected]
        jain = [float(row["jain"]) for row in selected]
        if not throughput:
            print(f"  {scheduler}: sem execuções válidas")
            continue
        scheduler_means[scheduler] = (fmean(throughput), fmean(jain))
        t_std = stdev(throughput) if len(throughput) > 1 else 0.0
        j_std = stdev(jain) if len(jain) > 1 else 0.0
        print(
            f"  {scheduler}: n={len(selected)}, "
            f"T={fmean(throughput):.3f}±{t_std:.3f} Mbps, "
            f"J={fmean(jain):.4f}±{j_std:.4f}"
        )

    if len(set(scheduler_means.values())) <= 1:
        print(
            "  AVISO: os escalonadores produziram médias iguais. "
            "O cenário pode estar subcarregado e não discrimina as políticas."
        )


def apply_smoke_defaults(args: argparse.Namespace) -> None:
    """Reduz a campanha a uma run curta sem alterar o cenário de rádio."""
    if args.smoke:
        args.sim_time = 1.0
        args.min_runs = 1
        args.max_runs = 1
        args.batch_size = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "pesquisa/resultados/bateria_test_3")
    parser.add_argument("--sim-binary", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ue-count", type=int, default=50)
    parser.add_argument("--radius-m", type=int, default=500)
    parser.add_argument("--bandwidth", type=int, default=100_000_000)
    parser.add_argument(
        "--lambda-pps", type=int, default=DEFAULT_LAMBDA_PPS,
        help="Taxa por fluxo. 500 pps com 1500 bytes equivale a 6 Mbps/fluxo."
    )
    parser.add_argument("--flows-per-ue", type=int, default=1,
                        help="Número de fluxos UDP independentes por UE.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--sim-time", type=float, default=30.0)
    parser.add_argument("--window-ms", type=int, default=100)
    parser.add_argument("--min-runs", type=int, default=30)
    parser.add_argument("--max-runs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--throughput-error", type=float, default=0.05)
    parser.add_argument("--jain-error", type=float, default=0.01)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--smoke", action="store_true",
        help="Executa 1 run de 1 s para RR/PF/MR/QoS e valida o pareamento."
    )
    parser.add_argument(
        "--no-progress", action="store_true",
        help="Desativa o painel dinâmico e usa uma linha por execução concluída."
    )
    parser.add_argument(
        "--force-progress", action="store_true",
        help="Força o painel em ambientes sem TTY, como algumas células de notebook."
    )
    args = parser.parse_args()
    apply_smoke_defaults(args)
    args.output = args.output.resolve()
    args.sim_binary = resolve_binary(args.sim_binary)
    if (args.workers < 1 or args.ue_count < 2 or args.radius_m <= 10
            or args.bandwidth <= 0 or args.lambda_pps <= 0 or args.flows_per_ue <= 0
            or args.ue_count * args.flows_per_ue > 65536 - 1234
            or not 1 <= args.min_runs <= args.max_runs):
        parser.error("parâmetros físicos/estatísticos inválidos")
    return args


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ledger = args.output / "executions.csv"
    for scenario in scenarios(args.ue_count, args.radius_m, args.flows_per_ue):
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
            panel = ProgressPanel(
                tasks, enabled=not args.no_progress,
                force=args.force_progress
            )
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(run_one_with_progress, args, *task, panel)
                    for task in tasks
                }
                batch_rows = []
                pending = set(futures)
                panel.render()
                while pending:
                    done, pending = wait(
                        pending, timeout=0.25,
                        return_when=FIRST_COMPLETED
                    )
                    for future in done:
                        row = future.result()
                        batch_rows.append(row)
                        append_row(ledger, row)
                        panel.completed_message(row)
                    panel.render()
            rows = read_rows(ledger)
            for run in range(first_missing, target + 1):
                validate_pairing(rows, scenario, run)
            validate_distinct_runs(rows, scenario)
            if any(row["status"] != "OK" for row in batch_rows):
                print("Execução com erro; corrija e retome usando o mesmo output.")
                return 2
        rows = read_rows(ledger)
        report_data_quality(rows, scenario)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
