#!/usr/bin/env python3
"""Pipeline reprodutível da Bateria 3 para as runs 001--030.

As janelas são usadas somente em diagnósticos temporais. Toda inferência entre
schedulers usa rngRun como unidade amostral e preserva o pareamento.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from analisar_bateria_test_3 import QUALITY_METRICS, paired_tests, quality_row  # noqa: E402
from bateria_test_3 import SCHEDULERS, half_width  # noqa: E402
from config_graficos import (  # noqa: E402
    SCHEDULER_COLORS, SCHEDULER_LABELS, SCHEDULER_MARKERS, setup_style,
)

SUFFIX = "Run1-30"
PRIMARY = ("throughput_mbps", "jain", "window_throughput_mean_mbps", "window_jain_mean")
LABELS = {
    "throughput_mbps": "Vazão agregada (Mbps)",
    "jain": "Índice de Jain",
    "window_throughput_mean_mbps": "Vazão média por janela (Mbps)",
    "window_jain_mean": "Jain médio por janela",
    "throughput_ue_p5_mbps": "P5 da vazão por UE (Mbps)",
    "throughput_ue_p10_mbps": "P10 da vazão por UE (Mbps)",
    "zero_throughput_share": "Proporção de UEs sem vazão",
    "pdr_mean_pct": "PDR médio (%)",
    "delay_p99_p95_ms": "P95 do atraso p99 entre UEs (ms)",
}


def output_dirs(root: Path) -> dict[str, Path]:
    names = {
        "tables": "00_Tabelas_Dados",
        "audit": "01_Auditoria_Integridade",
        "descriptive": "02_Estatistica_Descritiva",
        "convergence": "03_Convergencia_IC95",
        "distributions": "04_Distribuicoes_ECDF",
        "paired": "05_Comparacoes_Pareadas",
        "pareto": "06_Pareto_Nash",
        "distance": "07_Desempenho_Distancia",
        "pdr_delay": "08_PDR_Atraso_Cauda",
        "wins": "09_Matriz_Vitorias_Regret",
        "jmin": "10_Jmin_Otimo",
        "temporal": "11_Analise_Temporal",
        "outliers": "12_Outliers_Diagnostico",
        "report": "13_Relatorio_Final",
    }
    result = {key: root / value for key, value in names.items()}
    for path in result.values():
        path.mkdir(parents=True, exist_ok=True)
    return result


def savefig(path: Path) -> None:
    plt.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close()


def read_executions(path: Path, first: int, last: int) -> pd.DataFrame:
    data = pd.read_csv(path)
    required = {
        "scenario", "scheduler", "rng_run", "status", "output_dir",
        "throughput_mbps", "jain", "window_throughput_mean_mbps",
        "window_jain_mean", "position_hash",
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"executions.csv sem colunas: {sorted(missing)}")
    data = data[data["rng_run"].between(first, last)].copy()
    for column in PRIMARY:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data


def audit(executions: pd.DataFrame, first: int, last: int) -> tuple[pd.DataFrame, list[str]]:
    records, errors = [], []
    expected = set(SCHEDULERS)
    for run in range(first, last + 1):
        group = executions[executions["rng_run"] == run]
        ok = group[group["status"] == "OK"]
        schedulers = set(ok["scheduler"])
        duplicate = bool(ok.duplicated(["scheduler"], keep=False).any())
        hash_values = ok["position_hash"].dropna().astype(str)
        hash_values = hash_values[hash_values.str.len() > 0]
        hashes = hash_values.nunique()
        complete = schedulers == expected and len(ok) == len(expected) and not duplicate
        paired = complete and hashes == 1
        problems = []
        if not complete:
            problems.append(f"schedulers={sorted(schedulers)}")
        if duplicate:
            problems.append("duplicata")
        if complete and not paired:
            problems.append(f"hashes={hashes}")
        if ok[list(PRIMARY)].isna().any().any():
            problems.append("métrica não numérica")
        if not ok["jain"].dropna().between(0, 1).all():
            problems.append("Jain fora de [0,1]")
        records.append({
            "rng_run": run, "rows": len(group), "ok": len(ok),
            "schedulers": ",".join(sorted(schedulers)), "hashes": hashes,
            "complete": complete, "paired": paired,
            "problems": "; ".join(problems),
        })
        if problems:
            errors.append(f"run {run:03d}: {'; '.join(problems)}")
    return pd.DataFrame(records), errors


def complete_runs(audit_data: pd.DataFrame) -> set[int]:
    return set(audit_data.loc[audit_data["paired"], "rng_run"].astype(int))


def quality_data(executions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in executions[executions["status"] == "OK"].to_dict("records"):
        rows.append(quality_row({key: str(value) for key, value in row.items()}))
    return pd.DataFrame(rows)


def ue_data(executions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    from analisar_bateria_test_3 import resolve_output_dir
    for row in executions[executions["status"] == "OK"].to_dict("records"):
        path = resolve_output_dir(str(row["output_dir"])) / "ue_summary.csv"
        frame = pd.read_csv(path)
        frame["scenario"] = row["scenario"]
        frame["scheduler"] = row["scheduler"]
        frame["rng_run"] = int(row["rng_run"])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def window_data(executions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    from analisar_bateria_test_3 import resolve_output_dir
    for row in executions[executions["status"] == "OK"].to_dict("records"):
        path = resolve_output_dir(str(row["output_dir"])) / "window_log.csv"
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path)
        frame["scheduler"] = row["scheduler"]
        frame["rng_run"] = int(row["rng_run"])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def descriptive(data: pd.DataFrame, metrics: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for scheduler, group in data.groupby("scheduler"):
        for metric in metrics:
            values = group[metric].dropna().astype(float)
            mean = values.mean()
            width = half_width(values.tolist())
            rows.append({
                "scheduler": scheduler, "metric": metric, "n": len(values),
                "mean": mean, "median": values.median(), "minimum": values.min(),
                "maximum": values.max(), "std": values.std(ddof=1),
                "cv": values.std(ddof=1) / abs(mean) if mean else math.inf,
                "p05": values.quantile(.05), "p10": values.quantile(.10),
                "p90": values.quantile(.90), "p95": values.quantile(.95),
                "iqr": values.quantile(.75) - values.quantile(.25),
                "ic95_half_width": width, "ic95_low": mean - width,
                "ic95_high": mean + width,
            })
    return pd.DataFrame(rows)


def block_statistics(data: pd.DataFrame, metrics: tuple[str, ...]) -> pd.DataFrame:
    result = data.copy()
    result["block"] = pd.cut(result["rng_run"], [0, 10, 20, 30],
                             labels=["1-10", "11-20", "21-30"])
    rows = []
    for (scheduler, block), group in result.groupby(["scheduler", "block"], observed=True):
        for metric in metrics:
            values = group[metric].dropna()
            rows.append({"scheduler": scheduler, "block": str(block), "metric": metric,
                         "n": len(values), "mean": values.mean(), "median": values.median(),
                         "best": values.max(), "worst": values.min(),
                         "std": values.std(ddof=1),
                         "cv": values.std(ddof=1) / abs(values.mean()) if values.mean() else math.inf})
    return pd.DataFrame(rows)


def cumulative_statistics(data: pd.DataFrame, metrics: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for scheduler, group in data.sort_values("rng_run").groupby("scheduler"):
        for metric in metrics:
            values = []
            for _, row in group.iterrows():
                values.append(float(row[metric]))
                if len(values) < 2:
                    continue
                width = half_width(values)
                mean = float(np.mean(values))
                rows.append({"scheduler": scheduler, "metric": metric,
                             "n": len(values), "rng_run": int(row["rng_run"]),
                             "mean": mean, "median": float(np.median(values)),
                             "half_width": width,
                             "relative_half_width": width / abs(mean) if mean else math.inf})
    return pd.DataFrame(rows)


def paired_frame(data: pd.DataFrame, metric: str) -> pd.DataFrame:
    pivot = data.pivot(index="rng_run", columns="scheduler", values=metric)
    rows = []
    for left, right in combinations(SCHEDULERS, 2):
        differences = (pivot[left] - pivot[right]).dropna().tolist()
        mean = float(np.mean(differences))
        width = half_width(differences)
        sd = float(np.std(differences, ddof=1))
        rows.append({"comparison": f"{left}-{right}", "metric": metric,
                     "n_pairs": len(differences), "mean_difference": mean,
                     "ic95_half_width": width, "ic95_low": mean - width,
                     "ic95_high": mean + width,
                     "cohen_dz": mean / sd if sd else math.inf if mean else 0.0,
                     "left_win_share": float(np.mean(np.array(differences) > 0)),
                     "ties": int(np.sum(np.array(differences) == 0))})
    return pd.DataFrame(rows)


def pareto_nash(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for run, group in data.groupby("rng_run"):
        tmin, tmax = group["throughput_mbps"].min(), group["throughput_mbps"].max()
        jmin, jmax = group["jain"].min(), group["jain"].max()
        for index, point in group.iterrows():
            dominated = any(
                other["throughput_mbps"] >= point["throughput_mbps"]
                and other["jain"] >= point["jain"]
                and (other["throughput_mbps"] > point["throughput_mbps"]
                     or other["jain"] > point["jain"])
                for _, other in group.drop(index).iterrows()
            )
            tn = ((point["throughput_mbps"] - tmin) / (tmax - tmin)
                  if tmax > tmin else 1.0)
            jn = ((point["jain"] - jmin) / (jmax - jmin)
                  if jmax > jmin else 1.0)
            rows.append({"rng_run": run, "scheduler": point["scheduler"],
                         "throughput_mbps": point["throughput_mbps"],
                         "jain": point["jain"], "pareto": not dominated,
                         "nash_score": tn * jn})
    result = pd.DataFrame(rows)
    result["nash_winner"] = result.groupby("rng_run")["nash_score"].transform("max").eq(result["nash_score"])
    return result


def diagnostics(data: pd.DataFrame, ue: pd.DataFrame,
                windows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame,
                                                pd.DataFrame, pd.DataFrame]:
    regret = data[["rng_run", "scheduler", "throughput_mbps", "jain"]].copy()
    regret["throughput_regret"] = (
        regret.groupby("rng_run")["throughput_mbps"].transform("max")
        - regret["throughput_mbps"]
    )
    regret["jain_regret"] = regret.groupby("rng_run")["jain"].transform("max") - regret["jain"]
    outlier_rows = []
    for (scheduler, metric), group in data.melt(
        id_vars=["rng_run", "scheduler"], value_vars=list(PRIMARY),
        var_name="metric", value_name="value"
    ).groupby(["scheduler", "metric"]):
        q1, q3 = group.value.quantile([.25, .75]); iqr = q3 - q1
        flagged = group[(group.value < q1 - 1.5*iqr) | (group.value > q3 + 1.5*iqr)]
        for _, row in flagged.iterrows():
            outlier_rows.append({"rng_run": row.rng_run, "scheduler": scheduler,
                                 "metric": metric, "value": row.value,
                                 "lower_fence": q1-1.5*iqr, "upper_fence": q3+1.5*iqr,
                                 "action": "investigar; não excluir automaticamente"})
    if not ue.empty:
        ue = ue.copy()
        ue["distance_bin_m"] = pd.cut(ue.distance_gnb_m, [10,100,200,300,400,500], include_lowest=True)
        distance = ue.groupby(["scheduler", "distance_bin_m"], observed=True).agg(
            n_ues=("ue_id", "count"), throughput_mean_mbps=("throughput_mbps", "mean"),
            throughput_median_mbps=("throughput_mbps", "median"),
            pdr_mean_pct=("pdr_pct", "mean"), plr_mean_pct=("plr_pct", "mean"),
            zero_throughput_share=("throughput_mbps", lambda values: float((values <= 0).mean())),
        ).reset_index()
    else:
        distance = pd.DataFrame()
    temporal = pd.DataFrame()
    if not windows.empty:
        temporal = windows.groupby(["rng_run", "scheduler"]).agg(
            throughput_window_mean=("aggregate_thr_mbps", "mean"),
            throughput_window_std=("aggregate_thr_mbps", "std"),
            throughput_window_p05=("aggregate_thr_mbps", lambda values: values.quantile(.05)),
            jain_window_mean=("jain_throughput", "mean"),
            jain_window_min=("jain_throughput", "min"),
            jain_window_p05=("jain_throughput", lambda values: values.quantile(.05)),
        ).reset_index()
        temporal["throughput_window_cv"] = temporal.throughput_window_std / temporal.throughput_window_mean.abs()
    return regret, pd.DataFrame(outlier_rows), distance, temporal


def jmin_curve(data: pd.DataFrame, quality: pd.DataFrame, candidates: np.ndarray) -> pd.DataFrame:
    merged = data.merge(quality, on=["scenario", "rng_run", "scheduler"], how="left")
    unrestricted = merged.groupby("rng_run")["throughput_mbps"].max().mean()
    rows = []
    for threshold in candidates:
        selected = []
        for _, group in merged.groupby("rng_run"):
            feasible = group[group["jain"] >= threshold]
            if not feasible.empty:
                selected.append(feasible.loc[feasible["throughput_mbps"].idxmax()])
        if not selected:
            rows.append({"jmin": threshold, "feasible_runs": 0,
                         "feasibility": 0.0, "throughput_mean": math.nan,
                         "throughput_loss": math.nan})
            continue
        chosen = pd.DataFrame(selected)
        record = {"jmin": threshold, "feasible_runs": len(chosen),
                  "feasibility": len(chosen) / merged["rng_run"].nunique(),
                  "throughput_mean": chosen["throughput_mbps"].mean(),
                  "throughput_loss": 1 - chosen["throughput_mbps"].mean() / unrestricted,
                  "jain_mean": chosen["jain"].mean()}
        for metric in ("throughput_ue_p5_mbps", "zero_throughput_share",
                       "pdr_mean_pct", "delay_p99_p95_ms"):
            record[metric] = chosen[metric].mean()
        counts = Counter(chosen["scheduler"])
        for scheduler in SCHEDULERS:
            record[f"selected_{scheduler}_share"] = counts[scheduler] / len(chosen)
        rows.append(record)
    return pd.DataFrame(rows)


def select_jmin(curve: pd.DataFrame) -> dict[str, float]:
    valid = curve.dropna(subset=["throughput_mean"]).copy()
    if valid.empty:
        raise ValueError("nenhum candidato Jmin produziu solução viável")
    conservative = valid[(valid["feasibility"] >= .95) & (valid["throughput_loss"] <= .05)]
    conservative_value = conservative["jmin"].max() if not conservative.empty else math.nan
    x = (valid["jmin"] - valid["jmin"].min()) / max(valid["jmin"].max() - valid["jmin"].min(), 1e-12)
    y = ((valid["throughput_mean"] - valid["throughput_mean"].min())
         / max(valid["throughput_mean"].max() - valid["throughput_mean"].min(), 1e-12))
    # Maior distância à corda entre os extremos.
    x1, y1, x2, y2 = x.iloc[0], y.iloc[0], x.iloc[-1], y.iloc[-1]
    distance = abs((y2-y1)*x - (x2-x1)*y + x2*y1 - y2*x1) / math.hypot(y2-y1, x2-x1)
    knee = float(valid.loc[distance.idxmax(), "jmin"])
    return {"jmin_conservative": float(conservative_value), "jmin_knee": knee}


def bootstrap_jmin(data: pd.DataFrame, quality: pd.DataFrame, candidates: np.ndarray,
                   repetitions: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    runs = np.array(sorted(data["rng_run"].unique()))
    rows = []
    for iteration in range(repetitions):
        sampled = rng.choice(runs, size=len(runs), replace=True)
        pieces_data, pieces_quality = [], []
        for new_run, old_run in enumerate(sampled, start=1):
            a = data[data["rng_run"] == old_run].copy(); a["rng_run"] = new_run
            q = quality[quality["rng_run"] == old_run].copy(); q["rng_run"] = new_run
            pieces_data.append(a); pieces_quality.append(q)
        curve = jmin_curve(pd.concat(pieces_data), pd.concat(pieces_quality), candidates)
        rows.append({"bootstrap": iteration, **select_jmin(curve)})
    return pd.DataFrame(rows)


def plot_run_and_cumulative(data: pd.DataFrame, cumulative: pd.DataFrame, metric: str, path: Path) -> None:
    plt.figure(figsize=(12, 7))
    for scheduler in SCHEDULERS:
        raw = data[data["scheduler"] == scheduler]
        acc = cumulative[(cumulative["scheduler"] == scheduler) & (cumulative["metric"] == metric)]
        color = SCHEDULER_COLORS[scheduler]
        plt.scatter(raw["rng_run"], raw[metric], color=color, alpha=.35, s=24)
        plt.plot(acc["rng_run"], acc["mean"], color=color, label=SCHEDULER_LABELS[scheduler])
        plt.fill_between(acc["rng_run"], acc["mean"]-acc["half_width"],
                         acc["mean"]+acc["half_width"], color=color, alpha=.08)
    plt.xlabel("rngRun"); plt.ylabel(LABELS.get(metric, metric)); plt.legend(ncol=2)
    plt.title(f"{LABELS.get(metric, metric)} por run e média acumulada")
    savefig(path)


def plots(data: pd.DataFrame, quality: pd.DataFrame, ue: pd.DataFrame,
          windows: pd.DataFrame, cumulative: pd.DataFrame, paired: pd.DataFrame,
          pareto: pd.DataFrame, curve: pd.DataFrame, bootstrap: pd.DataFrame,
          selections: dict[str, float], dirs: dict[str, Path]) -> None:
    setup_style()
    for metric in PRIMARY:
        plot_run_and_cumulative(data, cumulative, metric,
                                dirs["convergence"] / f"Media_Acumulada_{metric}_{SUFFIX}")
    plt.figure(figsize=(11, 6))
    for scheduler in SCHEDULERS:
        part = cumulative[(cumulative.scheduler == scheduler) & (cumulative.metric == "throughput_mbps")]
        plt.plot(part.n, 100*part.relative_half_width, label=SCHEDULER_LABELS[scheduler],
                 color=SCHEDULER_COLORS[scheduler])
    plt.axhline(5, color="black", ls="--", label="5%"); plt.axhline(2, color="gray", ls=":", label="2%")
    plt.xlabel("Número de runs"); plt.ylabel("Meia largura relativa do IC95% (%)"); plt.legend()
    savefig(dirs["convergence"] / f"Precisao_IC95_{SUFFIX}")
    block_data = data.copy()
    block_data["Bloco"] = pd.cut(block_data.rng_run, [0,10,20,30],
                                  labels=["1–10", "11–20", "21–30"])
    plt.figure(figsize=(11, 6))
    sns.pointplot(data=block_data, x="Bloco", y="throughput_mbps", hue="scheduler",
                  palette=SCHEDULER_COLORS, dodge=.25, errorbar=("ci", 95), capsize=.08)
    plt.ylabel(LABELS["throughput_mbps"])
    savefig(dirs["convergence"] / f"Convergencia_Blocos_Throughput_{SUFFIX}")

    for metric in ("throughput_mbps", "jain"):
        plt.figure(figsize=(10, 6)); sns.boxplot(data=data, x="scheduler", y=metric, hue="scheduler", palette=SCHEDULER_COLORS, legend=False)
        sns.stripplot(data=data, x="scheduler", y=metric, color="black", alpha=.45)
        savefig(dirs["distributions"] / f"Boxplot_{metric}_{SUFFIX}")
        plt.figure(figsize=(10, 6))
        for scheduler in SCHEDULERS:
            sns.ecdfplot(data=data[data.scheduler == scheduler], x=metric,
                         label=SCHEDULER_LABELS[scheduler], color=SCHEDULER_COLORS[scheduler])
        plt.legend(); savefig(dirs["distributions"] / f"ECDF_{metric}_{SUFFIX}")

    for metric, part in paired.groupby("metric"):
        part = part.sort_values("mean_difference")
        plt.figure(figsize=(10, 6)); y=np.arange(len(part))
        plt.errorbar(part.mean_difference, y, xerr=part.ic95_half_width, fmt="o", capsize=4)
        plt.axvline(0, color="black", ls="--"); plt.yticks(y, part.comparison)
        plt.xlabel(f"Diferença pareada — {LABELS.get(metric, metric)}")
        savefig(dirs["paired"] / f"Forest_Pareado_{metric}_{SUFFIX}")

    plt.figure(figsize=(10, 7))
    for scheduler in SCHEDULERS:
        part = pareto[pareto.scheduler == scheduler]
        plt.scatter(part.throughput_mbps, part.jain, color=SCHEDULER_COLORS[scheduler],
                    marker=SCHEDULER_MARKERS[scheduler], label=SCHEDULER_LABELS[scheduler],
                    alpha=.75, s=np.where(part.nash_winner, 110, 45),
                    edgecolors=np.where(part.pareto, "black", "none"))
    plt.xlabel(LABELS["throughput_mbps"]); plt.ylabel(LABELS["jain"]); plt.legend()
    savefig(dirs["pareto"] / f"Pareto_Cloud_{SUFFIX}")

    if not ue.empty:
        plt.figure(figsize=(11, 7)); sns.scatterplot(data=ue, x="distance_gnb_m", y="throughput_mbps",
                                                     hue="scheduler", palette=SCHEDULER_COLORS, alpha=.25, s=18)
        sns.lineplot(data=ue, x="distance_gnb_m", y="throughput_mbps", hue="scheduler",
                     palette=SCHEDULER_COLORS, estimator="mean", errorbar=None, legend=False)
        savefig(dirs["distance"] / f"Throughput_UE_Distancia_{SUFFIX}")
        plt.figure(figsize=(10, 7)); sns.scatterplot(data=ue, x="pdr_pct", y="delay_p99_ms",
                                                     hue="scheduler", palette=SCHEDULER_COLORS, alpha=.35)
        savefig(dirs["pdr_delay"] / f"PDR_vs_AtrasoP99_{SUFFIX}")

    pivot = data.pivot(index="rng_run", columns="scheduler", values="throughput_mbps")
    matrix = pd.DataFrame(index=SCHEDULERS, columns=SCHEDULERS, dtype=float)
    for left in SCHEDULERS:
        for right in SCHEDULERS:
            matrix.loc[left, right] = .5 if left == right else (pivot[left] > pivot[right]).mean()
    plt.figure(figsize=(7, 6)); sns.heatmap(matrix.astype(float), annot=True, fmt=".2f", vmin=0, vmax=1, cmap="RdBu_r")
    savefig(dirs["wins"] / f"Matriz_Vitorias_Throughput_{SUFFIX}")
    plt.figure(figsize=(8, 10)); sns.heatmap(pivot[list(SCHEDULERS)], cmap="viridis")
    plt.xlabel("Scheduler"); plt.ylabel("rngRun")
    savefig(dirs["wins"] / f"Heatmap_Run_Scheduler_Throughput_{SUFFIX}")

    regret = data[["rng_run", "scheduler", "throughput_mbps"]].copy()
    regret["regret"] = regret.groupby("rng_run").throughput_mbps.transform("max") - regret.throughput_mbps
    plt.figure(figsize=(9, 6)); sns.boxplot(data=regret, x="scheduler", y="regret", hue="scheduler",
                                            palette=SCHEDULER_COLORS, legend=False)
    plt.ylabel("Regret de vazão (Mbps)")
    savefig(dirs["wins"] / f"Regret_Throughput_{SUFFIX}")

    plt.figure(figsize=(11, 7)); plt.plot(curve.jmin, curve.throughput_mean, marker="o", label="Vazão selecionada")
    for name, value in selections.items():
        if math.isfinite(value): plt.axvline(value, ls="--", label=f"{name}={value:.3f}")
    plt.xlabel("Jmin"); plt.ylabel("Vazão esperada (Mbps)"); plt.legend()
    savefig(dirs["jmin"] / f"Jmin_Throughput_{SUFFIX}")
    plt.figure(figsize=(11, 7)); plt.plot(curve.jmin, curve.feasibility, label="Viabilidade")
    plt.plot(curve.jmin, curve.throughput_loss, label="Perda de vazão")
    plt.axhline(.95, color="black", ls="--"); plt.axhline(.05, color="gray", ls=":")
    plt.xlabel("Jmin"); plt.ylabel("Proporção"); plt.legend()
    savefig(dirs["jmin"] / f"Jmin_Viabilidade_Perda_{SUFFIX}")
    plt.figure(figsize=(10, 6))
    if bootstrap.jmin_conservative.notna().any():
        sns.histplot(bootstrap.jmin_conservative.dropna(), bins=20, kde=True)
    else:
        plt.text(.5, .5, "Nenhum Jmin conservador nas reamostragens",
                 ha="center", va="center", transform=plt.gca().transAxes)
    plt.xlabel("Jmin conservador no bootstrap")
    savefig(dirs["jmin"] / f"Jmin_Bootstrap_{SUFFIX}")

    if not windows.empty and {"time_s", "aggregate_thr_mbps"}.issubset(windows.columns):
        run_means = data.groupby("rng_run").throughput_mbps.mean()
        representative = int((run_means-run_means.median()).abs().idxmin())
        selected = windows[windows.rng_run == representative]
        plt.figure(figsize=(12, 7)); sns.lineplot(data=selected, x="time_s", y="aggregate_thr_mbps",
                                                  hue="scheduler", palette=SCHEDULER_COLORS)
        savefig(dirs["temporal"] / f"Serie_Temporal_Run{representative:03d}_{SUFFIX}")
        if "jain_throughput" in selected.columns:
            plt.figure(figsize=(12, 7)); sns.lineplot(data=selected, x="time_s", y="jain_throughput",
                                                      hue="scheduler", palette=SCHEDULER_COLORS)
            savefig(dirs["temporal"] / f"Jain_Temporal_Run{representative:03d}_{SUFFIX}")


def report(path: Path, audit_data: pd.DataFrame, desc: pd.DataFrame,
           selections: dict[str, float], curve: pd.DataFrame, bootstrap: pd.DataFrame,
           assumptions: list[str]) -> None:
    lines = ["# Relatório automático — Bateria 3 Runs 001–030", "", "## Premissas"]
    lines += [f"- {item}" for item in assumptions]
    lines += ["", "## Auditoria", f"- Runs pareadas válidas: **{int(audit_data.paired.sum())}/30**.",
              f"- Runs com problemas: **{int((~audit_data.paired).sum())}**.", "", "## Resultados descritivos", "",
              "| Scheduler | Throughput médio (IC95%) | Jain médio (IC95%) |",
              "|---|---:|---:|"]
    for scheduler in SCHEDULERS:
        t = desc[(desc.scheduler == scheduler) & (desc.metric == "throughput_mbps")].iloc[0]
        j = desc[(desc.scheduler == scheduler) & (desc.metric == "jain")].iloc[0]
        lines.append(f"| {scheduler.upper()} | {t['mean']:.4f} ± {t['ic95_half_width']:.4f} | {j['mean']:.5f} ± {j['ic95_half_width']:.5f} |")
    lines += ["", "## Jmin", f"- Joelho: **{selections['jmin_knee']:.3f}**.",
              f"- Conservador (viabilidade ≥95% e perda ≤5%): **{selections['jmin_conservative']:.3f}**."]
    value = selections["jmin_conservative"]
    if math.isfinite(value):
        chosen = curve.iloc[(curve.jmin-value).abs().argsort()[:1]].iloc[0]
        lines += [f"- Depois da restrição: vazão={chosen.throughput_mean:.4f} Mbps, "
                  f"perda={100*chosen.throughput_loss:.2f}%, viabilidade={100*chosen.feasibility:.1f}%."]
    if bootstrap.jmin_conservative.notna().any():
        q = bootstrap.jmin_conservative.quantile([.025,.5,.975])
        lines += [f"- Bootstrap Jmin conservador: mediana={q.loc[.5]:.3f}, IC95%=[{q.loc[.025]:.3f}, {q.loc[.975]:.3f}]."]
    lines += ["", "## Observação", "As janelas temporais não foram tratadas como replicações independentes."]
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("pesquisa/resultados/3_bateria_test_3/executions.csv"))
    parser.add_argument("--output", type=Path, default=Path("pesquisa/resultados/3_bateria_test_3/Analise_Completa_Run1-30"))
    parser.add_argument("--first-run", type=int, default=1)
    parser.add_argument("--last-run", type=int, default=30)
    parser.add_argument("--jmin-start", type=float, default=.80)
    parser.add_argument("--jmin-stop", type=float, default=.999)
    parser.add_argument("--jmin-step", type=float, default=.001)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    if args.first_run != 1 or args.last_run != 30:
        raise SystemExit("Este artefato é identificado como Run1-30; use exatamente --first-run 1 --last-run 30")
    dirs = output_dirs(args.output)
    executions = read_executions(args.input, args.first_run, args.last_run)
    audit_data, errors = audit(executions, args.first_run, args.last_run)
    audit_data.to_csv(dirs["audit"] / f"Auditoria_{SUFFIX}.csv", index=False)
    if errors and not args.allow_incomplete:
        raise SystemExit("Auditoria falhou:\n" + "\n".join(errors))
    valid_runs = complete_runs(audit_data)
    data = executions[(executions.status == "OK") & executions.rng_run.isin(valid_runs)].copy()
    quality = quality_data(data); ue = ue_data(data); windows = window_data(data)
    divergent = quality[quality["jain_abs_difference"] > 1e-6]
    if not divergent.empty:
        divergent.to_csv(dirs["audit"] / f"Jain_Divergente_{SUFFIX}.csv", index=False)
        raise SystemExit("Jain recalculado diverge do executions.csv; consulte a auditoria")
    quality.to_csv(dirs["tables"] / f"Qualidade_UE_por_Run_{SUFFIX}.csv", index=False)
    ue.to_csv(dirs["tables"] / f"UE_Consolidado_{SUFFIX}.csv", index=False)
    if not windows.empty: windows.to_csv(dirs["tables"] / f"Janelas_Consolidadas_{SUFFIX}.csv", index=False)
    desc = descriptive(data, PRIMARY); blocks = block_statistics(data, PRIMARY)
    cumulative = cumulative_statistics(data, PRIMARY)
    desc.to_csv(dirs["descriptive"] / f"Resumo_Descritivo_{SUFFIX}.csv", index=False)
    blocks.to_csv(dirs["convergence"] / f"Convergencia_Blocos_{SUFFIX}.csv", index=False)
    cumulative.to_csv(dirs["convergence"] / f"Convergencia_Acumulada_{SUFFIX}.csv", index=False)
    paired = pd.concat([paired_frame(data, metric) for metric in PRIMARY], ignore_index=True)
    paired.to_csv(dirs["paired"] / f"Comparacoes_Pareadas_{SUFFIX}.csv", index=False)
    quality_tests = pd.DataFrame(paired_tests(quality.to_dict("records")))
    quality_tests.to_csv(dirs["paired"] / f"Comparacoes_Pareadas_UE_{SUFFIX}.csv", index=False)
    pareto = pareto_nash(data); pareto.to_csv(dirs["pareto"] / f"Pareto_Nash_por_Run_{SUFFIX}.csv", index=False)
    regret, outliers, distance, temporal = diagnostics(data, ue, windows)
    regret.to_csv(dirs["wins"] / f"Regret_por_Run_{SUFFIX}.csv", index=False)
    outliers.to_csv(dirs["outliers"] / f"Outliers_IQR_{SUFFIX}.csv", index=False)
    if not distance.empty: distance.to_csv(dirs["distance"] / f"Resumo_Faixas_Distancia_{SUFFIX}.csv", index=False)
    if not temporal.empty: temporal.to_csv(dirs["temporal"] / f"Resumo_Temporal_{SUFFIX}.csv", index=False)
    candidates = np.arange(args.jmin_start, args.jmin_stop + args.jmin_step/2, args.jmin_step)
    calibration_data=data[data.rng_run <= 15]; calibration_quality=quality[quality.rng_run <= 15]
    curve = jmin_curve(calibration_data, calibration_quality, candidates)
    selections = select_jmin(curve)
    bootstrap = bootstrap_jmin(calibration_data, calibration_quality, candidates, args.bootstrap, args.seed)
    curve.to_csv(dirs["jmin"] / f"Sensibilidade_Jmin_Calibracao_Run1-15.csv", index=False)
    bootstrap.to_csv(dirs["jmin"] / f"Bootstrap_Jmin_Calibracao_Run1-15.csv", index=False)
    before_after = []
    validation_data=data[data.rng_run >= 16]; validation_quality=quality[quality.rng_run >= 16]
    validation_curve=jmin_curve(validation_data, validation_quality, candidates)
    validation_merged = validation_data.merge(
        validation_quality, on=["scenario", "rng_run", "scheduler"], how="left"
    )
    unrestricted = validation_merged.loc[
        validation_merged.groupby("rng_run")["throughput_mbps"].idxmax()
    ]
    before_after.append({
        "method": "sem_restricao", "selected_on": "não aplicável",
        "validated_on": "runs 16-30", "jmin": math.nan,
        "feasibility": 1.0, "throughput_mean": unrestricted.throughput_mbps.mean(),
        "throughput_loss": 0.0, "jain_mean": unrestricted.jain.mean(),
        "throughput_ue_p5_mbps": unrestricted.throughput_ue_p5_mbps.mean(),
        "zero_throughput_share": unrestricted.zero_throughput_share.mean(),
        "pdr_mean_pct": unrestricted.pdr_mean_pct.mean(),
        "delay_p99_p95_ms": unrestricted.delay_p99_p95_ms.mean(),
    })
    for method, value in selections.items():
        if math.isfinite(value):
            row=validation_curve.iloc[(validation_curve.jmin-value).abs().argsort()[:1]].iloc[0].to_dict()
            before_after.append({"method":method,"selected_on":"runs 1-15","validated_on":"runs 16-30",**row})
    pd.DataFrame(before_after).to_csv(dirs["jmin"] / f"Antes_Depois_Jmin_{SUFFIX}.csv", index=False)
    plots(data, quality, ue, windows, cumulative, paired, pareto, curve, bootstrap, selections, dirs)
    assumptions = [
        "T1..T4 foram interpretados como schedulers alternativos e não somados.",
        "rngRun é a unidade amostral; janelas são diagnósticos temporais.",
        "Jmin foi calibrado nas runs 1–15 e validado sem reajuste nas runs 16–30.",
        "Jmin conservador é o maior limiar com viabilidade ≥95% e perda de vazão ≤5%.",
    ]
    report(dirs["report"] / f"Relatorio_Resultados_{SUFFIX}.md", audit_data, desc,
           selections, curve, bootstrap, assumptions)
    metadata={"input":str(args.input.resolve()),"runs":[1,30],"valid_runs":sorted(valid_runs),
              "assumptions":assumptions,"jmin":selections,"bootstrap":args.bootstrap,"seed":args.seed}
    (dirs["report"] / f"Metadata_{SUFFIX}.json").write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+"\n")
    print(f"Análise completa gerada em: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
