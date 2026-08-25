#!/usr/bin/env python3
"""Bateria 4: métricas de aplicação, drain de filas e topologias uniformes em área."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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

ROOT = Path(__file__).resolve().parent.parent
SCHEDULERS = ("rr", "pf", "mr", "qos")
DEFAULT_LAMBDA_PPS = 500
RESULT_RE = re.compile(
    r"\[RESULT\].*?throughput_mbps=([0-9.eE+-]+).*?"
    r"jain_vazao=([0-9.eE+-]+).*?rng_run=([0-9]+)"
)
FIELDS = (
    "scenario", "application_mode", "ue_count", "flows_per_ue", "radius_m", "bandwidth_hz", "lambda_pps",
    "offered_load_mbps", "traffic_stop_s", "drain_time_s", "total_stop_s",
    "flow_max_per_hop_delay_s", "window_ms", "channel_scenario",
    "channel_condition", "channel_model", "shadowing_enabled", "rb_per_rbg",
    "scheduler", "seed", "rng_run",
    "app_throughput_traffic_mbps", "app_goodput_total_mbps",
    "app_jain_traffic", "app_jain_total", "flowmon_throughput_mbps",
    "flowmon_jain", "traffic_window_throughput_mean_mbps",
    "traffic_window_jain_mean", "drain_window_throughput_mean_mbps",
    "app_rx_packets_total", "flowmon_rx_packets_total",
    "app_flowmon_packet_delta", "position_hash", "metadata_sha256",
    "ues_with_cqi", "ues_with_measurements", "ues_with_rsrq",
    "cqi_mean", "mcs_recommended_mean",
    "rank_mean", "rsrp_mean_dbm", "rsrq_mean_db",
    "status", "elapsed_s", "output_dir", "error",
)


@dataclass(frozen=True)
class Scenario:
    ue_count: int
    radius_m: int
    application_mode: str = "udp"
    channel_scenario: str = "UMa"
    channel_condition: str = "Default"
    channel_model: str = "ThreeGpp"
    shadowing_enabled: bool = True
    flows_per_ue: int = 1

    @property
    def name(self) -> str:
        shadowing = "shadowing" if self.shadowing_enabled else "no_shadowing"
        return (f"{self.application_mode}_static_uniform_area_"
                f"{self.ue_count}ues_{self.radius_m}m_"
                f"{self.flows_per_ue}flows_per_ue_"
                f"{self.channel_scenario}_{self.channel_condition}_"
                f"{self.channel_model}_{shadowing}")


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


def scenarios(ue_count: int, radius_m: int,
              application_modes: tuple[str, ...] = ("udp",),
              channel_scenario: str = "UMa",
              channel_condition: str = "Default",
              channel_model: str = "ThreeGpp",
              shadowing_enabled: bool = True,
              flows_per_ue: int = 1) -> list[Scenario]:
    """Cria cenários pareados separados para UDP, HTTP e tráfego misto."""
    return [Scenario(ue_count, radius_m, mode, channel_scenario,
                     channel_condition, channel_model, shadowing_enabled,
                     flows_per_ue)
            for mode in application_modes]


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


def csv_mean(path: Path, column: str, phase: str | None = None) -> float:
    with path.open(newline="", encoding="utf-8") as handle:
        values = [float(row[column]) for row in csv.DictReader(handle)
                  if phase is None or row.get("phase") == phase]
    if not values:
        raise RuntimeError(f"{path} não contém dados")
    return fmean(values)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def udp_offered_load_mbps(scenario: Scenario, lambda_pps: int,
                          flows_per_ue: int = 1) -> float | None:
    """Carga UDP determinística; HTTP 3GPP é estocástico e não usa lambda."""
    if scenario.application_mode == "http":
        return None
    udp_ues = (scenario.ue_count if scenario.application_mode == "udp"
               else (scenario.ue_count + 1) // 2)
    return udp_ues * flows_per_ue * lambda_pps * 1500 * 8 / 1e6


def read_csv_required(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"{path.name} ausente ou vazio")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise RuntimeError(f"{path.name} sem colunas: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise RuntimeError(f"{path.name} sem registros")
    return rows


def validate_corrected_outputs(ue_path: Path, window_path: Path,
                               expected_run: int, expected_ues: int,
                               radius_m: float,
                               expected_flows_per_ue: int = 1,
                               application_mode: str = "udp",
                               channel_scenario: str = "UMa",
                               channel_condition: str = "Default",
                               channel_model: str = "ThreeGpp",
                               shadowing_enabled: bool = True) -> dict[str, float]:
    ue_rows = read_csv_required(ue_path, {
        "rng_run", "application_mode", "flows_per_ue", "ue_id", "x_initial_m", "y_initial_m", "z_initial_m",
        "distance_gnb_m", "app_throughput_traffic_mbps",
        "app_goodput_total_mbps", "app_jain_traffic", "app_jain_total",
        "flowmon_throughput_mbps", "flowmon_jain", "app_rx_packets_total",
        "flowmon_rx_packets", "flowmon_observed_downlink_flows",
        "app_duplicate_packets", "app_malformed_packets",
        "cqi_mean", "cqi_samples", "mcs_recommended_mean", "rank_mean",
        "rsrp_mean_dbm", "rsrq_mean_db", "rsrq_available", "measurement_samples",
        "rb_per_rbg", "channel_scenario", "channel_condition",
        "channel_model", "shadowing_enabled",
        "app_throughput_traffic_aggregate_mbps",
        "app_goodput_total_aggregate_mbps",
        "flowmon_throughput_aggregate_mbps",
    })
    if len(ue_rows) != expected_ues:
        raise RuntimeError(f"ue_summary: {len(ue_rows)} UEs; esperado {expected_ues}")
    if {int(row["ue_id"]) for row in ue_rows} != set(range(expected_ues)):
        raise RuntimeError("ue_summary contém ue_id ausente ou duplicado")
    if any(int(row["flows_per_ue"]) != expected_flows_per_ue for row in ue_rows):
        raise RuntimeError("flows_per_ue divergente no ue_summary")

    for row in ue_rows:
        if int(row["rng_run"]) != expected_run:
            raise RuntimeError("rng_run divergente no ue_summary")
        if row["application_mode"] != application_mode:
            raise RuntimeError("application_mode divergente no ue_summary")
        expected_channel = (channel_scenario, channel_condition, channel_model)
        actual_channel = (row["channel_scenario"], row["channel_condition"],
                          row["channel_model"])
        if actual_channel != expected_channel:
            raise RuntimeError("configuração de canal divergente no ue_summary")
        if row["shadowing_enabled"].lower() != str(shadowing_enabled).lower():
            raise RuntimeError("shadowing divergente no ue_summary")
        if int(row["rb_per_rbg"]) <= 0:
            raise RuntimeError("rb_per_rbg deve ser positivo")
        x, y, z = (float(row[name]) for name in
                   ("x_initial_m", "y_initial_m", "z_initial_m"))
        radius = math.hypot(x, y)
        expected_distance = math.sqrt(x*x + y*y + (z - 25.0)**2)
        if not 10.0 - 1e-6 <= radius <= radius_m + 1e-6:
            raise RuntimeError(f"UE {row['ue_id']} fora do anel espacial")
        if abs(float(row["distance_gnb_m"]) - expected_distance) > 0.002:
            raise RuntimeError(f"UE {row['ue_id']} com distância inconsistente")
        if int(row["app_duplicate_packets"]) != 0:
            raise RuntimeError(f"UE {row['ue_id']} recebeu duplicatas na aplicação")
        if int(row["app_malformed_packets"]) != 0:
            raise RuntimeError(f"UE {row['ue_id']} recebeu pacote sem SeqTsHeader")
        if (application_mode == "udp" and
                int(row["flowmon_observed_downlink_flows"]) != expected_flows_per_ue):
            raise RuntimeError(f"UE {row['ue_id']} sem todos os fluxos UDP no FlowMonitor")

    windows = read_csv_required(window_path, {
        "rng_run", "flows_per_ue", "window_id", "start_time_s", "end_time_s", "duration_s",
        "phase", "aggregate_thr_mbps", "jain_throughput", "app_rx_packets",
    })
    ids = [int(row["window_id"]) for row in windows]
    if ids != list(range(len(ids))):
        raise RuntimeError("window_log possui lacunas ou IDs duplicados")
    if any(int(row["rng_run"]) != expected_run for row in windows):
        raise RuntimeError("rng_run divergente no window_log")
    if any(int(row["flows_per_ue"]) != expected_flows_per_ue for row in windows):
        raise RuntimeError("flows_per_ue divergente no window_log")
    if not {row["phase"] for row in windows}.issubset({"traffic", "drain"}):
        raise RuntimeError("window_log contém fase desconhecida")
    if any(float(row["duration_s"]) <= 0 for row in windows):
        raise RuntimeError("window_log contém duração não positiva")
    for previous, current in zip(windows, windows[1:]):
        if abs(float(previous["end_time_s"]) -
               float(current["start_time_s"])) > 1e-9:
            raise RuntimeError("window_log contém lacuna temporal")
    if any(not 0.0 <= float(row["jain_throughput"]) <= 1.0 for row in windows):
        raise RuntimeError("window_log contém Jain fora de [0,1]")

    app_rx = sum(int(row["app_rx_packets_total"]) for row in ue_rows)
    flow_rx = sum(int(row["flowmon_rx_packets"]) for row in ue_rows)
    # Com MaxPerHopDelay maior que toda a simulação, os instrumentos devem
    # concordar em contagem. Divergência revela nova censura/instrumentação.
    # UDP oferece equivalência pacote a pacote. HTTP/TCP entrega segmentos ao
    # trace da aplicação, portanto sua reconciliação correta é por bytes e não
    # pela quantidade de eventos Rx/segmentos do FlowMonitor.
    if application_mode == "udp" and app_rx != flow_rx:
        raise RuntimeError(
            f"UdpServer/FlowMonitor divergem: app={app_rx}, flowmon={flow_rx}")

    cqi_rows = [row for row in ue_rows if int(row["cqi_samples"]) > 0]
    measurement_rows = [row for row in ue_rows
                        if int(row["measurement_samples"]) > 0]
    rsrq_rows = [row for row in measurement_rows
                 if row["rsrq_available"].lower() == "true"]
    mean_or_nan = lambda rows, column: (
        fmean(float(row[column]) for row in rows) if rows else math.nan)
    return {
        "app_throughput_traffic_mbps": float(ue_rows[0]["app_throughput_traffic_aggregate_mbps"]),
        "app_goodput_total_mbps": float(ue_rows[0]["app_goodput_total_aggregate_mbps"]),
        "app_jain_traffic": float(ue_rows[0]["app_jain_traffic"]),
        "app_jain_total": float(ue_rows[0]["app_jain_total"]),
        "flowmon_throughput_mbps": float(ue_rows[0]["flowmon_throughput_aggregate_mbps"]),
        "flowmon_jain": float(ue_rows[0]["flowmon_jain"]),
        "app_rx_packets_total": app_rx,
        "flowmon_rx_packets_total": flow_rx,
        "app_flowmon_packet_delta": app_rx - flow_rx,
        "ues_with_cqi": len(cqi_rows),
        "ues_with_measurements": len(measurement_rows),
        "ues_with_rsrq": len(rsrq_rows),
        "cqi_mean": mean_or_nan(cqi_rows, "cqi_mean"),
        "mcs_recommended_mean": mean_or_nan(cqi_rows, "mcs_recommended_mean"),
        "rank_mean": mean_or_nan(cqi_rows, "rank_mean"),
        "rsrp_mean_dbm": mean_or_nan(measurement_rows, "rsrp_mean_dbm"),
        "rsrq_mean_db": mean_or_nan(rsrq_rows, "rsrq_mean_db"),
        "channel_scenario": channel_scenario,
        "channel_condition": channel_condition,
        "channel_model": channel_model,
        "shadowing_enabled": str(shadowing_enabled).lower(),
        "rb_per_rbg": int(ue_rows[0]["rb_per_rbg"]),
    }


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
        "--trafficProfile=embb", f"--applicationMode={scenario.application_mode}",
        f"--ueNumPergNb={scenario.ue_count}",
        f"--simTime={args.sim_time}s", f"--seed={args.seed}",
        f"--drainTime={args.drain_time}s",
        f"--FlowMaxPerHopDelay={args.flow_max_per_hop_delay}s",
        f"--rngRun={rng_run}", "--enableMobility=false",
        "--positionMode=random_disc_static",
        f"--mobilityBounds={scenario.radius_m}",
        f"--bandwidth={args.bandwidth}",
        f"--centralFrequency={args.central_frequency}",
        f"--totalTxPower={args.tx_power_dbm}",
        f"--numerology={args.numerology}",
        f"--channelScenario={args.channel_scenario}",
        f"--channelCondition={args.channel_condition}",
        f"--channelModel={args.channel_model}",
        f"--enableShadowing={'true' if args.enable_shadowing else 'false'}",
        f"--lambdaOverride={args.lambda_pps}",
        f"--flowsPerUe={scenario.flows_per_ue}",
        "--EnableConsoleDetails=false", "--EnableWindowCsv=true",
        f"--WindowSizeMs={args.window_ms}", f"--WindowCsvPath={window}",
        "--EnableUeSummaryCsv=true", f"--UeSummaryCsvPath={ue}",
        "--EnableFlowSummaryCsv=true", f"--FlowSummaryCsvPath={flow}",
    ]
    (output / "command.txt").write_text(
        subprocess.list2cmdline(command) + "\n", encoding="utf-8")
    metadata = {
        "battery": 4,
        "scenario": scenario.name,
        "scheduler": scheduler,
        "application_mode": scenario.application_mode,
        "seed": args.seed,
        "rng_run": rng_run,
        "ue_count": scenario.ue_count,
        "flows_per_ue": scenario.flows_per_ue,
        "radius_m": scenario.radius_m,
        "spatial_distribution": "uniform_area_annulus",
        "bandwidth_hz": args.bandwidth,
        "central_frequency_hz": args.central_frequency,
        "tx_power_dbm": args.tx_power_dbm,
        "numerology": args.numerology,
        "channel_scenario": args.channel_scenario,
        "channel_condition": args.channel_condition,
        "channel_model": args.channel_model,
        "shadowing_enabled": args.enable_shadowing,
        "packet_size_bytes": 1500,
        "lambda_pps": args.lambda_pps,
        "offered_load_mbps": udp_offered_load_mbps(
            scenario, args.lambda_pps, scenario.flows_per_ue),
        "traffic_stop_s": args.sim_time,
        "drain_time_s": args.drain_time,
        "total_stop_s": args.sim_time + args.drain_time,
        "flow_max_per_hop_delay_s": args.flow_max_per_hop_delay,
        "window_ms": args.window_ms,
        "command": command,
        "binary": str(args.sim_binary),
        "binary_sha256": sha256_file(args.sim_binary),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True).stdout.strip(),
    }
    metadata_path = output / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    started = time.monotonic()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    elapsed = time.monotonic() - started
    console = proc.stdout + proc.stderr
    (output / "console.log").write_text(console, encoding="utf-8")
    row: dict[str, object] = {
        "scenario": scenario.name, "application_mode": scenario.application_mode,
        "ue_count": scenario.ue_count,
        "flows_per_ue": scenario.flows_per_ue,
        "radius_m": scenario.radius_m, "bandwidth_hz": args.bandwidth,
        "lambda_pps": args.lambda_pps,
        "offered_load_mbps": udp_offered_load_mbps(
            scenario, args.lambda_pps, scenario.flows_per_ue),
        "traffic_stop_s": args.sim_time, "drain_time_s": args.drain_time,
        "total_stop_s": args.sim_time + args.drain_time,
        "flow_max_per_hop_delay_s": args.flow_max_per_hop_delay,
        "window_ms": args.window_ms, "scheduler": scheduler,
        "channel_scenario": args.channel_scenario,
        "channel_condition": args.channel_condition,
        "channel_model": args.channel_model,
        "shadowing_enabled": str(args.enable_shadowing).lower(),
        "rb_per_rbg": "",
        "seed": args.seed, "rng_run": rng_run,
        "app_throughput_traffic_mbps": "", "app_goodput_total_mbps": "",
        "app_jain_traffic": "", "app_jain_total": "",
        "flowmon_throughput_mbps": "", "flowmon_jain": "",
        "traffic_window_throughput_mean_mbps": "",
        "traffic_window_jain_mean": "", "drain_window_throughput_mean_mbps": "",
        "app_rx_packets_total": "", "flowmon_rx_packets_total": "",
        "app_flowmon_packet_delta": "", "position_hash": "",
        "metadata_sha256": sha256_file(metadata_path), "status": "ERROR",
        "ues_with_cqi": "", "ues_with_measurements": "", "ues_with_rsrq": "",
        "cqi_mean": "",
        "mcs_recommended_mean": "", "rank_mean": "", "rsrp_mean_dbm": "",
        "rsrq_mean_db": "",
        "elapsed_s": f"{elapsed:.3f}", "output_dir": output.relative_to(ROOT),
        "error": "",
    }
    match = RESULT_RE.search(console)
    try:
        if proc.returncode != 0 or not match:
            raise RuntimeError(" | ".join(console.strip().splitlines()[-8:]))
        if int(match.group(3)) != rng_run:
            raise RuntimeError("rng_run divergente na linha [RESULT]")
        metrics = validate_corrected_outputs(
            ue, window, rng_run, scenario.ue_count, scenario.radius_m,
            scenario.flows_per_ue, scenario.application_mode, args.channel_scenario,
            args.channel_condition, args.channel_model, args.enable_shadowing)
        if abs(float(match.group(1)) - metrics["app_throughput_traffic_mbps"]) > 1e-3:
            raise RuntimeError("throughput da linha [RESULT] diverge do ue_summary")
        if abs(float(match.group(2)) - metrics["app_jain_traffic"]) > 1e-5:
            raise RuntimeError("Jain da linha [RESULT] diverge do ue_summary")
        row.update(metrics)
        row.update(
            traffic_window_throughput_mean_mbps=csv_mean(
                window, "aggregate_thr_mbps", "traffic"),
            traffic_window_jain_mean=csv_mean(window, "jain_throughput", "traffic"),
            drain_window_throughput_mean_mbps=csv_mean(
                window, "aggregate_thr_mbps", "drain"),
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
        throughput = [float(row["traffic_window_throughput_mean_mbps"])
                      for row in selected]
        jain = [float(row["traffic_window_jain_mean"]) for row in selected]
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
        throughput = [float(row["app_throughput_traffic_mbps"])
                      for row in selected]
        jain = [float(row["app_jain_traffic"]) for row in selected]
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
        args.drain_time = 1.0
        args.min_runs = 1
        args.max_runs = 1
        args.batch_size = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "pesquisa/resultados/4_bateria_test_4")
    parser.add_argument("--sim-binary", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ue-count", type=int, default=50)
    parser.add_argument("--radius-m", type=int, default=500)
    parser.add_argument(
        "--application-modes", default="udp,http,mixed",
        help="Lista separada por vírgulas: udp,http,mixed (padrão: todos)."
    )
    parser.add_argument("--bandwidth", type=int, default=100_000_000)
    parser.add_argument("--central-frequency", type=float, default=4e9)
    parser.add_argument("--tx-power-dbm", type=float, default=43.0)
    parser.add_argument("--numerology", type=int, default=1)
    parser.add_argument("--channel-scenario", choices=("UMa", "UMi", "RMa", "InH"),
                        default="UMa")
    parser.add_argument("--channel-condition",
                        choices=("Default", "LOS", "NLOS", "Buildings"),
                        default="Default")
    parser.add_argument("--channel-model",
                        choices=("ThreeGpp", "NYU", "TwoRay"),
                        default="ThreeGpp")
    parser.add_argument("--disable-shadowing", dest="enable_shadowing",
                        action="store_false",
                        help="Desativa shadowing no modelo de perda de percurso.")
    parser.set_defaults(enable_shadowing=True)
    parser.add_argument(
        "--lambda-pps", type=int, default=DEFAULT_LAMBDA_PPS,
        help="Taxa por fluxo. 500 pps com 1500 bytes equivale a 6 Mbps/fluxo."
    )
    parser.add_argument("--flows-per-ue", type=int, default=1,
                        help="Número de fluxos UDP independentes por UE.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--sim-time", type=float, default=30.0)
    parser.add_argument("--drain-time", type=float, default=15.0)
    parser.add_argument("--flow-max-per-hop-delay", type=float, default=60.0)
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
    args.application_modes = tuple(
        mode.strip().lower() for mode in args.application_modes.split(",")
        if mode.strip())
    args.output = args.output.resolve()
    args.sim_binary = resolve_binary(args.sim_binary)
    if (args.workers < 1 or args.ue_count < 2 or args.radius_m <= 10
            or args.bandwidth <= 0 or args.lambda_pps <= 0 or args.flows_per_ue <= 0
            or args.ue_count * args.flows_per_ue > 65536 - 1234
            or args.sim_time <= 0.4 or args.drain_time < 0
            or args.flow_max_per_hop_delay <= args.sim_time + args.drain_time
            or args.central_frequency <= 0 or args.numerology not in (0, 1, 2, 3, 4)
            or not args.application_modes
            or not set(args.application_modes).issubset({"udp", "http", "mixed"})
            or not 1 <= args.min_runs <= args.max_runs):
        parser.error("parâmetros físicos/estatísticos inválidos")
    return args


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ledger = args.output / "executions.csv"
    for scenario in scenarios(
            args.ue_count, args.radius_m, args.application_modes,
            args.channel_scenario, args.channel_condition,
            args.channel_model, args.enable_shadowing, args.flows_per_ue):
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
