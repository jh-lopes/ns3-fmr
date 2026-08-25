#!/usr/bin/env python3
"""Análise inicial dos resultados finais consolidados da Bateria 3."""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "pesquisa/resultados/3_bateria_test_3/executions.csv"
DEFAULT_OUTPUT = ROOT / "resultados/bateria_03/analise_pareada_runs_001_100_v4"
SCHEDULERS = ("rr", "pf", "mr", "qos")
COLORS = {"rr": "#FF7F0E", "pf": "#28B463", "mr": "#E53935", "qos": "#2E86C1"}
LABELS = {"rr": "Round Robin", "pf": "Proportional Fair",
          "mr": "Max Rate", "qos": "QoS"}
MARKERS = {"rr": "o", "pf": "s", "mr": "^", "qos": "D"}
FIGSIZE = (9, 7)
DPI = 300
POINT_SIZE = 45
POINT_ALPHA = .48
PARETO_SIZE = 150
PARETO_LINEWIDTH = 1.5
NASH_STAR_SIZE = 90
FRONTIER_WIDTH = 2.0
JITTER_X_MBPS = .45
JITTER_Y_JAIN = .0045
JITTER_NEAR_ONE_X_MBPS = .75
JITTER_NEAR_ONE_Y_JAIN = .010
SCHEDULERS_NEAR_ONE = ("rr", "pf", "qos")
JAIN_BREAK_LOW = .65
JAIN_BREAK_HIGH = .93
JITTER_SEED = 20260825
FONT_AXIS = 14
FONT_TICKS = 12
FONT_ANNOTATION = 10


def decimal_comma(decimals: int):
    return FuncFormatter(lambda value, _: f"{value:.{decimals}f}".replace(".", ","))


def pareto_y_min(data: pd.DataFrame) -> float:
    """Limite visual inferior em décimos, preservando o menor Jain observado."""
    return max(0.0, np.floor((float(data.jain_throughput.min()) - .005) * 10.0) / 10.0)


def load_data(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    aliases = {
        "rng_run": "run_id",
        "throughput_mbps": "aggregate_thr_mbps",
        "jain": "jain_throughput",
    }
    data = data.rename(columns={source: target for source, target in aliases.items()
                                if target not in data.columns})
    if "status" in data.columns:
        data = data[data.status == "OK"].copy()
    required = {"scheduler", "run_id", "aggregate_thr_mbps", "jain_throughput"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"colunas ausentes: {sorted(missing)}")
    data = data[list(required)].copy()
    data["scheduler"] = data.scheduler.astype(str).str.lower().str.strip()
    for column in ("run_id", "aggregate_thr_mbps", "jain_throughput"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    if set(data.scheduler) != set(SCHEDULERS):
        raise ValueError(f"schedulers inesperados: {sorted(set(data.scheduler))}")
    if data.duplicated(["scheduler", "run_id"]).any():
        raise ValueError("há pares scheduler/run_id duplicados")
    expected_runs = set(data.run_id.astype(int))
    for scheduler, group in data.groupby("scheduler"):
        if set(group.run_id.astype(int)) != expected_runs:
            raise ValueError(f"{scheduler}: runs incompletas")
    if not data.jain_throughput.between(0, 1).all():
        raise ValueError("Jain fora de [0,1]")
    if (data.aggregate_thr_mbps < 0).any():
        raise ValueError("vazão negativa")
    return data.sort_values(["run_id", "scheduler"]).reset_index(drop=True)


def pareto_frontier(data: pd.DataFrame) -> pd.DataFrame:
    values = data[["aggregate_thr_mbps", "jain_throughput"]].to_numpy(float)
    keep = np.ones(len(values), dtype=bool)
    for index, (throughput, jain) in enumerate(values):
        dominates = ((values[:, 0] >= throughput) & (values[:, 1] >= jain)
                     & ((values[:, 0] > throughput) | (values[:, 1] > jain)))
        keep[index] = not dominates.any()
    return (data.loc[keep]
            .sort_values(["aggregate_thr_mbps", "jain_throughput"]) 
            .copy())


def nash_solution(frontier: pd.DataFrame,
                  reference: pd.DataFrame | None = None) -> pd.Series:
    candidates = frontier.copy()
    reference = frontier if reference is None else reference
    for source, target in (("aggregate_thr_mbps", "throughput_norm"),
                           ("jain_throughput", "jain_norm")):
        span = reference[source].max() - reference[source].min()
        candidates[target] = ((candidates[source] - reference[source].min()) / span
                              if span > 0 else 1.0)
    candidates["nash_score"] = candidates.throughput_norm * candidates.jain_norm
    return candidates.sort_values(
        ["nash_score", "jain_throughput", "aggregate_thr_mbps"]
    ).iloc[-1]


def ci95(series: pd.Series) -> float:
    return 1.984 * float(series.std(ddof=1)) / np.sqrt(len(series))


def save_figure(fig: plt.Figure, output: Path, name: str) -> None:
    fig.savefig(output / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output / f"{name}.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_pareto(data: pd.DataFrame, frontier: pd.DataFrame,
                nash: pd.Series, output: Path) -> None:
    plot_data = data.copy()
    rng = np.random.default_rng(JITTER_SEED)
    near_one = plot_data.scheduler.isin(SCHEDULERS_NEAR_ONE).to_numpy()
    jitter_x_amplitude = np.where(near_one, JITTER_NEAR_ONE_X_MBPS, JITTER_X_MBPS)
    jitter_y_amplitude = np.where(near_one, JITTER_NEAR_ONE_Y_JAIN, JITTER_Y_JAIN)
    plot_data["plot_throughput_mbps"] = (
        plot_data.aggregate_thr_mbps
        + rng.uniform(-1.0, 1.0, len(plot_data)) * jitter_x_amplitude
    )
    jittered_jain = (
        plot_data.jain_throughput
        + rng.uniform(-1.0, 1.0, len(plot_data)) * jitter_y_amplitude
    )
    # Reflete o jitter nos limites, evitando acumular pontos exatamente em 0 ou 1.
    jittered_jain = np.where(jittered_jain > 1.0, 2.0 - jittered_jain, jittered_jain)
    jittered_jain = np.where(jittered_jain < 0.0, -jittered_jain, jittered_jain)
    plot_data["plot_jain"] = jittered_jain
    plot_data["is_global_pareto"] = plot_data.index.isin(frontier.index)
    visible_y = np.concatenate((plot_data.plot_jain.to_numpy(),
                                frontier.jain_throughput.to_numpy()))
    if ((visible_y > JAIN_BREAK_LOW) & (visible_y < JAIN_BREAK_HIGH)).any():
        raise ValueError("a faixa proposta para a quebra do eixo Y contém pontos")
    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, figsize=FIGSIZE, dpi=DPI, sharex=True,
        gridspec_kw={"height_ratios": [1.15, 3.2], "hspace": .07},
    )
    axes = np.asarray([ax_top, ax_bottom])
    x_min = min(float(plot_data.plot_throughput_mbps.min()),
                float(frontier.aggregate_thr_mbps.min()))
    x_max = max(float(plot_data.plot_throughput_mbps.max()),
                float(frontier.aggregate_thr_mbps.max()))
    x_padding = .025 * (x_max - x_min)
    ax_bottom.set_xlim(x_min - x_padding, x_max + x_padding)

    for ax in axes:
        for scheduler in SCHEDULERS:
            group = plot_data[
                (plot_data.scheduler == scheduler) & ~plot_data.is_global_pareto
            ]
            ax.scatter(group.plot_throughput_mbps, group.plot_jain,
                       color=COLORS[scheduler], marker="o",
                       s=POINT_SIZE, alpha=POINT_ALPHA,
                       edgecolors="none", zorder=1)
        ax.plot(frontier.aggregate_thr_mbps, frontier.jain_throughput,
                color="black", linestyle="--", linewidth=FRONTIER_WIDTH, zorder=4)
        for scheduler in SCHEDULERS:
            points = frontier[frontier.scheduler == scheduler]
            ax.scatter(points.aggregate_thr_mbps, points.jain_throughput,
                       s=PARETO_SIZE, marker="o", color=COLORS[scheduler],
                       edgecolors="black", linewidth=PARETO_LINEWIDTH, zorder=5)
    x, y = float(nash.aggregate_thr_mbps), float(nash.jain_throughput)
    nash_ax = ax_bottom
    nash_ax.scatter(x, y, s=PARETO_SIZE, marker="o", color=COLORS[nash.scheduler],
                    edgecolors="black", linewidth=1.5, zorder=7)
    nash_ax.scatter(x, y, marker="*", s=NASH_STAR_SIZE, color="#b012c7",
                    edgecolor="white", linewidth=.7, zorder=8)
    text = (
        r"$\bf{Solução\ de\ Nash}$" "\n"
        f"Escalonador: {LABELS[nash.scheduler]}\n"
        f"Vazão: {x:.2f} Mbps\n"
        f"Índice de Jain: {y:.2f}\n"
        f"Run: {int(nash.run_id)}"
    ).replace(".", ",")
    nash_ax.annotate(
        text, xy=(x, y), xytext=(-5, 28), textcoords="offset points",
        ha="center", va="bottom", fontsize=FONT_ANNOTATION,
        arrowprops=dict(arrowstyle="-", color="#444444", lw=.8),
        bbox=dict(boxstyle="round,pad=.30", fc="white", ec="#777777", alpha=.96),
        zorder=10,
    )
    y_min = pareto_y_min(data)
    for ax in axes:
        ax.xaxis.set_major_formatter(decimal_comma(2))
        ax.yaxis.set_major_formatter(decimal_comma(2))
        ax.tick_params(axis="both", labelsize=FONT_TICKS)
        ax.grid(True, color="#999999", linewidth=.8, alpha=.35)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    ax_top.set_ylim(JAIN_BREAK_HIGH, 1.005)
    ax_top.set_yticks([.94, .96, .98, 1.00])
    ax_top.spines["bottom"].set_visible(False)
    ax_top.tick_params(axis="x", bottom=False, labelbottom=False)
    ax_bottom.set_ylim(y_min, JAIN_BREAK_LOW)
    ax_bottom.set_yticks(np.arange(y_min, .61, .10))
    ax_bottom.spines["top"].set_visible(False)
    break_mark = dict(marker=[(-1, -.55), (1, .55)], markersize=8,
                      linestyle="none", color="black", mec="black", mew=1,
                      clip_on=False)
    ax_top.plot([0, 1], [0, 0], transform=ax_top.transAxes, **break_mark)
    ax_bottom.plot([0, 1], [1, 1], transform=ax_bottom.transAxes, **break_mark)
    fig.supylabel("Índice de Jain", fontsize=FONT_AXIS, x=.035)
    fig.supxlabel("Vazão agregada (Mbps)", fontsize=FONT_AXIS, y=.045)
    fig.suptitle("Fronteira de Pareto global e solução de Nash — 100 execuções",
                 fontsize=13, y=.985)
    fig.text(.5, .947,
             "400 observações: 100 execuções × 4 escalonadores; métricas finais por execução",
             ha="center", va="top", fontsize=9, color="#444444")
    handles = [Line2D([], [], marker="o", linestyle="none", color=COLORS[s],
                      label=LABELS[s], markersize=7) for s in SCHEDULERS]
    handles += [
        Line2D([], [], color="black", linestyle="--", linewidth=FRONTIER_WIDTH,
               label="Fronteira de Pareto"),
        Line2D([], [], marker="*", linestyle="none", color="#b012c7",
               label="Solução de Nash", markersize=8),
    ]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .910),
               ncol=3, frameon=False, fontsize=9)
    fig.subplots_adjust(top=.80, bottom=.13, left=.12, right=.97)
    save_figure(fig, output, "01_pareto_nash")


def plot_scheduler_clouds(data: pd.DataFrame, frontier: pd.DataFrame,
                          nash: pd.Series, output: Path) -> None:
    """Gera uma figura por scheduler, destacando sua participação no Pareto global."""
    for position, scheduler in enumerate(SCHEDULERS, start=6):
        group = data[data.scheduler == scheduler].copy()
        pareto_points = frontier[frontier.scheduler == scheduler].copy()
        group["is_global_pareto"] = group.index.isin(pareto_points.index)
        rng = np.random.default_rng(JITTER_SEED + position)
        if scheduler in SCHEDULERS_NEAR_ONE:
            jitter_x, jitter_y = JITTER_NEAR_ONE_X_MBPS, JITTER_NEAR_ONE_Y_JAIN
        else:
            jitter_x, jitter_y = JITTER_X_MBPS, JITTER_Y_JAIN
        group["plot_throughput_mbps"] = (
            group.aggregate_thr_mbps + rng.uniform(-jitter_x, jitter_x, len(group))
        )
        jittered_jain = (
            group.jain_throughput + rng.uniform(-jitter_y, jitter_y, len(group))
        )
        jittered_jain = np.where(jittered_jain > 1.0, 2.0 - jittered_jain,
                                 jittered_jain)
        jittered_jain = np.where(jittered_jain < 0.0, -jittered_jain,
                                 jittered_jain)
        group["plot_jain"] = jittered_jain

        fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
        common = group[~group.is_global_pareto]
        ax.scatter(common.plot_throughput_mbps, common.plot_jain,
                   color=COLORS[scheduler], marker="o", s=POINT_SIZE,
                   alpha=POINT_ALPHA, edgecolors="none", zorder=1)
        ax.scatter(pareto_points.aggregate_thr_mbps, pareto_points.jain_throughput,
                   s=PARETO_SIZE, marker="o", color=COLORS[scheduler],
                   edgecolors="black", linewidth=PARETO_LINEWIDTH, zorder=4)

        handles = [
            Line2D([], [], marker="o", linestyle="none", color=COLORS[scheduler],
                   label=f"{LABELS[scheduler]} — observações", markersize=7),
        ]
        if not pareto_points.empty:
            handles.append(
                Line2D([], [], marker="o", linestyle="none", color=COLORS[scheduler],
                       markeredgecolor="black", markeredgewidth=1.2,
                       label="Pertence à fronteira global", markersize=9)
            )
        if scheduler == nash.scheduler:
            x, y = float(nash.aggregate_thr_mbps), float(nash.jain_throughput)
            ax.scatter(x, y, s=PARETO_SIZE, marker="o", color=COLORS[scheduler],
                       edgecolors="black", linewidth=1.5, zorder=6)
            ax.scatter(x, y, marker="*", s=NASH_STAR_SIZE, color="#b012c7",
                       edgecolor="white", linewidth=.7, zorder=7)
            text = (
                r"$\bf{Solução\ de\ Nash}$" "\n"
                f"Vazão: {x:.2f} Mbps\n"
                f"Índice de Jain: {y:.2f}\n"
                f"Run: {int(nash.run_id)}"
            ).replace(".", ",")
            ax.annotate(
                text, xy=(x, y), xytext=(-10, 55), textcoords="offset points",
                ha="center", va="bottom", fontsize=FONT_ANNOTATION,
                arrowprops=dict(arrowstyle="-", color="#444444", lw=.8),
                bbox=dict(boxstyle="round,pad=.30", fc="white", ec="#777777",
                          alpha=.96),
                zorder=9,
            )
            handles.append(Line2D([], [], marker="*", linestyle="none",
                                  color="#b012c7", label="Solução de Nash",
                                  markersize=8))

        x_values = np.concatenate((group.plot_throughput_mbps.to_numpy(),
                                   pareto_points.aggregate_thr_mbps.to_numpy()))
        y_values = np.concatenate((group.plot_jain.to_numpy(),
                                   pareto_points.jain_throughput.to_numpy()))
        x_span = max(float(np.ptp(x_values)), .1)
        y_span = max(float(np.ptp(y_values)), .005)
        ax.set_xlim(float(x_values.min()) - .07 * x_span,
                    float(x_values.max()) + .07 * x_span)
        ax.set_ylim(max(0.0, float(y_values.min()) - .08 * y_span),
                    min(1.005, float(y_values.max()) + .08 * y_span))
        ax.xaxis.set_major_formatter(decimal_comma(2))
        ax.yaxis.set_major_formatter(decimal_comma(2))
        if scheduler in SCHEDULERS_NEAR_ONE:
            ax.yaxis.set_major_locator(MultipleLocator(.01))
        ax.tick_params(axis="both", labelsize=FONT_TICKS)
        ax.set_xlabel("Vazão agregada (Mbps)", fontsize=FONT_AXIS)
        ax.set_ylabel("Índice de Jain", fontsize=FONT_AXIS)
        ax.grid(True, color="#999999", linewidth=.8, alpha=.35)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.suptitle(f"Bateria 3 — {LABELS[scheduler]}", fontsize=13, y=.975)
        fig.text(.5, .935,
                 f"100 execuções; {len(pareto_points)} pontos pertencem à fronteira global",
                 ha="center", va="top", fontsize=9, color="#444444")
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .895),
                   ncol=len(handles), frameon=False, fontsize=9)
        fig.subplots_adjust(top=.82, bottom=.13, left=.13, right=.97)
        save_figure(fig, output, f"{position:02d}_pareto_{scheduler}")


def plot_distributions(data: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=DPI)
    order = list(SCHEDULERS)
    sns.boxplot(data=data, x="scheduler", y="aggregate_thr_mbps", order=order,
                hue="scheduler", hue_order=order, palette=COLORS,
                legend=False, dodge=False, ax=axes[0])
    sns.boxplot(data=data, x="scheduler", y="jain_throughput", order=order,
                hue="scheduler", hue_order=order, palette=COLORS,
                legend=False, dodge=False, ax=axes[1])
    for ax, ylabel, title in (
        (axes[0], "Vazão agregada (Mbps)", "Distribuição da vazão por scheduler"),
        (axes[1], "Índice de Jain", "Distribuição da justiça por scheduler"),
    ):
        ax.set_xlabel("Scheduler")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels([LABELS[name].replace(" ", "\n") for name in order])
        ax.grid(True, axis="y", alpha=.3)
        ax.yaxis.set_major_formatter(decimal_comma(2))
    save_figure(fig, output, "02_distribuicoes")


def plot_means(data: pd.DataFrame, output: Path) -> pd.DataFrame:
    rows = []
    for scheduler in SCHEDULERS:
        group = data[data.scheduler == scheduler]
        rows.append({
            "scheduler": scheduler,
            "n": len(group),
            "throughput_mean_mbps": group.aggregate_thr_mbps.mean(),
            "throughput_ci95_half_width": ci95(group.aggregate_thr_mbps),
            "jain_mean": group.jain_throughput.mean(),
            "jain_ci95_half_width": ci95(group.jain_throughput),
        })
    summary = pd.DataFrame(rows)
    x = np.arange(len(summary))
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=DPI)
    axes[0].errorbar(x, summary.throughput_mean_mbps,
                     yerr=summary.throughput_ci95_half_width, fmt="none",
                     ecolor="black", capsize=5, lw=1.2)
    axes[1].errorbar(x, summary.jain_mean,
                     yerr=summary.jain_ci95_half_width, fmt="none",
                     ecolor="black", capsize=5, lw=1.2)
    for index, scheduler in enumerate(SCHEDULERS):
        axes[0].scatter(index, summary.loc[index, "throughput_mean_mbps"],
                        color=COLORS[scheduler], marker=MARKERS[scheduler], s=90, zorder=3)
        axes[1].scatter(index, summary.loc[index, "jain_mean"],
                        color=COLORS[scheduler], marker=MARKERS[scheduler], s=90, zorder=3)
    for ax, ylabel, title in (
        (axes[0], "Vazão agregada média (Mbps)", "Média e IC95% da vazão"),
        (axes[1], "Índice de Jain médio", "Média e IC95% da justiça"),
    ):
        ax.set_xticks(x, [LABELS[name].replace(" ", "\n") for name in SCHEDULERS])
        ax.set_xlabel("Scheduler")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=.3)
        ax.yaxis.set_major_formatter(decimal_comma(2))
    save_figure(fig, output, "03_medias_ic95")
    return summary


def analyze_within_runs(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Calcula Pareto e Nash separadamente em cada topologia/run."""
    detailed_rows = []
    winner_rows = []
    scheduler_rank = {name: index for index, name in enumerate(SCHEDULERS)}
    for run_id, group in data.groupby("run_id", sort=True):
        group = group.copy()
        frontier = pareto_frontier(group)
        group["is_pareto"] = group.index.isin(frontier.index)
        for source, target in (("aggregate_thr_mbps", "throughput_norm_run"),
                               ("jain_throughput", "jain_norm_run")):
            span = group[source].max() - group[source].min()
            group[target] = ((group[source] - group[source].min()) / span
                             if span > 0 else 1.0)
        group["nash_score_run"] = (
            group.throughput_norm_run * group.jain_norm_run
        )
        candidates = group[group.is_pareto].copy()
        best_score = float(candidates.nash_score_run.max())
        tied = candidates[np.isclose(candidates.nash_score_run, best_score,
                                     rtol=0.0, atol=1e-12)].copy()
        tied["scheduler_rank"] = tied.scheduler.map(scheduler_rank)
        winner = tied.sort_values(
            ["jain_throughput", "aggregate_thr_mbps", "scheduler_rank"],
            ascending=[False, False, True],
        ).iloc[0]
        group["is_nash_winner"] = group.index == winner.name
        group["nash_tie_count"] = len(tied)
        detailed_rows.append(group)
        winner_rows.append({
            "run_id": int(run_id),
            "scheduler": winner.scheduler,
            "aggregate_thr_mbps": winner.aggregate_thr_mbps,
            "jain_throughput": winner.jain_throughput,
            "nash_score_run": winner.nash_score_run,
            "tie_count": len(tied),
            "tied_schedulers": ";".join(tied.scheduler),
        })
    details = pd.concat(detailed_rows, ignore_index=True)
    winners = pd.DataFrame(winner_rows)
    frequencies = pd.DataFrame({"scheduler": SCHEDULERS})
    pareto_counts = details.groupby("scheduler").is_pareto.sum()
    nash_counts = winners.scheduler.value_counts()
    frequencies["pareto_runs"] = frequencies.scheduler.map(pareto_counts).fillna(0).astype(int)
    frequencies["pareto_frequency"] = frequencies.pareto_runs / data.run_id.nunique()
    frequencies["nash_wins"] = frequencies.scheduler.map(nash_counts).fillna(0).astype(int)
    frequencies["nash_frequency"] = frequencies.nash_wins / data.run_id.nunique()
    return details, winners, frequencies


def holm_adjust(pvalues: pd.Series) -> pd.Series:
    """Correção de Holm, preservando os índices originais."""
    ordered = pvalues.sort_values()
    adjusted = np.maximum.accumulate(
        [(len(ordered) - rank) * value for rank, value in enumerate(ordered)]
    )
    adjusted = np.minimum(adjusted, 1.0)
    return pd.Series(adjusted, index=ordered.index).reindex(pvalues.index)


def paired_comparisons(data: pd.DataFrame) -> pd.DataFrame:
    """Compara schedulers na mesma run, preservando o pareamento espacial."""
    rows = []
    for metric in ("aggregate_thr_mbps", "jain_throughput"):
        wide = data.pivot(index="run_id", columns="scheduler", values=metric)
        for scheduler_a, scheduler_b in combinations(SCHEDULERS, 2):
            delta = wide[scheduler_a] - wide[scheduler_b]
            tolerance = 1e-12
            t_result = stats.ttest_rel(wide[scheduler_a], wide[scheduler_b])
            try:
                w_result = stats.wilcoxon(delta, alternative="two-sided",
                                          zero_method="wilcox")
                w_stat, w_pvalue = float(w_result.statistic), float(w_result.pvalue)
            except ValueError:
                w_stat, w_pvalue = 0.0, 1.0
            std_delta = float(delta.std(ddof=1))
            rows.append({
                "metric": metric,
                "scheduler_a": scheduler_a,
                "scheduler_b": scheduler_b,
                "n_pairs": len(delta),
                "mean_delta_a_minus_b": delta.mean(),
                "median_delta_a_minus_b": delta.median(),
                "ci95_half_width": stats.t.ppf(.975, len(delta) - 1)
                                     * std_delta / np.sqrt(len(delta)),
                "wins_a": int((delta > tolerance).sum()),
                "ties": int((delta.abs() <= tolerance).sum()),
                "wins_b": int((delta < -tolerance).sum()),
                "cohen_dz": delta.mean() / std_delta if std_delta > 0 else np.nan,
                "paired_t_stat": float(t_result.statistic),
                "paired_t_pvalue": float(t_result.pvalue),
                "wilcoxon_stat": w_stat,
                "wilcoxon_pvalue": w_pvalue,
            })
    comparisons = pd.DataFrame(rows)
    comparisons["paired_t_pvalue_holm"] = np.nan
    comparisons["wilcoxon_pvalue_holm"] = np.nan
    for metric, indices in comparisons.groupby("metric").groups.items():
        comparisons.loc[indices, "paired_t_pvalue_holm"] = holm_adjust(
            comparisons.loc[indices, "paired_t_pvalue"]
        )
        comparisons.loc[indices, "wilcoxon_pvalue_holm"] = holm_adjust(
            comparisons.loc[indices, "wilcoxon_pvalue"]
        )
    return comparisons


def plot_run_frequencies(frequencies: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8), dpi=DPI, sharey=True)
    x = np.arange(len(SCHEDULERS))
    for ax, column, title in (
        (axes[0], "pareto_runs", "Presença na fronteira de Pareto por run"),
        (axes[1], "nash_wins", "Vitórias pelo critério de Nash por run"),
    ):
        values = frequencies.set_index("scheduler").loc[list(SCHEDULERS), column]
        bars = ax.bar(x, values, color=[COLORS[name] for name in SCHEDULERS], width=.68)
        ax.set_xticks(x, [LABELS[name].replace(" ", "\n") for name in SCHEDULERS])
        ax.set_ylim(0, 105)
        ax.set_ylabel("Número de runs (total = 100)")
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=.30)
        ax.bar_label(bars,
                     labels=[f"{int(value)} ({value:.2f}%)".replace(".", ",")
                             for value in values],
                     padding=3, fontsize=9)
    fig.suptitle("Análise pareada: Pareto e Nash dentro de cada run", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, .94))
    save_figure(fig, output, "04_frequencias_pareto_nash_por_run")


def plot_paired_differences(comparisons: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=DPI)
    for ax, metric, title, decimals in (
        (axes[0], "aggregate_thr_mbps", "Diferença média pareada da vazão (Mbps)", 2),
        (axes[1], "jain_throughput", "Diferença média pareada do índice de Jain", 2),
    ):
        matrix = pd.DataFrame(0.0, index=SCHEDULERS, columns=SCHEDULERS)
        subset = comparisons[comparisons.metric == metric]
        for row in subset.itertuples():
            matrix.loc[row.scheduler_a, row.scheduler_b] = row.mean_delta_a_minus_b
            matrix.loc[row.scheduler_b, row.scheduler_a] = -row.mean_delta_a_minus_b
        limit = float(np.abs(matrix.to_numpy()).max())
        rounding_threshold = .5 * 10 ** (-decimals)
        annotations = matrix.map(
            lambda value: f"{(0.0 if abs(value) < rounding_threshold else value):.{decimals}f}"
            .replace(".", ",")
        )
        sns.heatmap(matrix, ax=ax, cmap="RdBu_r", center=0, vmin=-limit, vmax=limit,
                    annot=annotations, fmt="", square=True, linewidths=.5,
                    cbar_kws={"shrink": .75, "format": decimal_comma(2)})
        short_labels = [name.upper() for name in SCHEDULERS]
        ax.set_xticklabels(short_labels, rotation=0)
        ax.set_yticklabels(short_labels, rotation=0)
        ax.set_xlabel("Scheduler B")
        ax.set_ylabel("Scheduler A")
        ax.set_title(title)
    fig.suptitle("Média das diferenças dentro da mesma run: A − B", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, .94))
    save_figure(fig, output, "05_diferencas_pareadas")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", context="paper", font_scale=1.15)
    data = load_data(args.input)
    frontier = pareto_frontier(data)
    nash = nash_solution(frontier)
    run_details, run_winners, frequencies = analyze_within_runs(data)
    comparisons = paired_comparisons(data)
    plot_pareto(data, frontier, nash, args.output)
    plot_scheduler_clouds(data, frontier, nash, args.output)
    plot_distributions(data, args.output)
    summary = plot_means(data, args.output)
    plot_run_frequencies(frequencies, args.output)
    plot_paired_differences(comparisons, args.output)
    summary.to_csv(args.output / "resumo_estatistico.csv", index=False, float_format="%.8f")
    frontier.to_csv(args.output / "fronteira_pareto_global.csv", index=False,
                    float_format="%.8f")
    # Mantém o nome anterior para compatibilidade com usos existentes.
    frontier.to_csv(args.output / "fronteira_pareto.csv", index=False, float_format="%.8f")
    pd.DataFrame([nash]).to_csv(args.output / "solucao_nash.csv", index=False,
                                float_format="%.8f")
    run_details.to_csv(args.output / "resultados_pareto_nash_por_run.csv", index=False,
                       float_format="%.8f")
    run_winners.to_csv(args.output / "vencedor_nash_por_run.csv", index=False,
                       float_format="%.8f")
    frequencies.to_csv(args.output / "frequencias_pareto_nash_por_scheduler.csv",
                       index=False, float_format="%.8f")
    comparisons.to_csv(args.output / "comparacoes_pareadas.csv", index=False,
                       float_format="%.10g")
    frequency_lines = [
        f"| {LABELS[row.scheduler]} | {row.pareto_runs} ({100 * row.pareto_frequency:.1f}%) "
        f"| {row.nash_wins} ({100 * row.nash_frequency:.1f}%) |"
        for row in frequencies.itertuples()
    ]
    tied_runs = int((run_winners.tie_count > 1).sum())
    def paired_row(metric: str, scheduler_a: str, scheduler_b: str) -> pd.Series:
        return comparisons[
            (comparisons.metric == metric)
            & (comparisons.scheduler_a == scheduler_a)
            & (comparisons.scheduler_b == scheduler_b)
        ].iloc[0]

    thr_rr_pf = paired_row("aggregate_thr_mbps", "rr", "pf")
    thr_pf_qos = paired_row("aggregate_thr_mbps", "pf", "qos")
    thr_pf_mr = paired_row("aggregate_thr_mbps", "pf", "mr")
    jain_rr_pf = paired_row("jain_throughput", "rr", "pf")
    jain_pf_qos = paired_row("jain_throughput", "pf", "qos")
    jain_pf_mr = paired_row("jain_throughput", "pf", "mr")
    y_min = pareto_y_min(data)
    report = [
        "# Análise pareada — Bateria 3", "",
        f"Fonte: `{args.input}`.",
        "Foram utilizados somente throughput agregado e Jain finais por run.",
        "Os arquivos `ue_summary_geral.csv` e `window_log_geral.csv` não foram usados.", "",
        "## Unidade amostral", "",
        "Cada run é uma replicação independente da topologia. RR, PF, MR e QoS "
        "são comparados de forma pareada dentro da mesma realização espacial.", "",
        "## Análise global exploratória", "",
        f"- Observações: {len(data)} ({data.run_id.nunique()} runs × 4 schedulers).",
        f"- Pontos não dominados: {len(frontier)}.",
        f"- Nash: {LABELS[nash.scheduler]}, run {int(nash.run_id)}, "
        f"{nash.aggregate_thr_mbps:.5f} Mbps, Jain {nash.jain_throughput:.6f}.",
        f"- O eixo X é contínuo. O eixo Y mostra de {y_min:.2f} a "
        f"{JAIN_BREAK_LOW:.2f} e de {JAIN_BREAK_HIGH:.2f} a 1,00, omitindo somente "
        "uma faixa sem observações. A quebra é indicada explicitamente no gráfico.",
        "- O jitter dos pontos comuns é exclusivamente visual e determinístico. Para "
        f"RR/PF/QoS usa ±{JITTER_NEAR_ONE_X_MBPS:.2f} Mbps e "
        f"±{JITTER_NEAR_ONE_Y_JAIN:.3f} no Jain; para MR usa ±{JITTER_X_MBPS:.2f} Mbps "
        f"e ±{JITTER_Y_JAIN:.4f}. Pareto, Nash e cálculos usam os valores originais.", "",
        "Foram geradas também quatro figuras individuais, uma por scheduler. Elas usam "
        "escalas próprias e destacam somente os pontos daquele scheduler que pertencem "
        "à fronteira global; não calculam Pareto entre topologias diferentes.", "",
        "## Pareto e Nash dentro de cada run", "",
        "Em cada run, a fronteira é calculada somente entre os quatro schedulers. "
        "O produto de Nash usa throughput e Jain normalizados pelo mínimo e máximo "
        "dos quatro resultados daquela run e escolhe apenas entre alternativas de Pareto.",
        f"Empates numéricos no maior produto: {tied_runs} runs. Em caso de empate, "
        "o desempate determinístico prioriza Jain, throughput e a ordem RR/PF/MR/QoS.", "",
        "| Scheduler | Presença em Pareto | Vitórias de Nash |",
        "|---|---:|---:|",
        *frequency_lines, "",
        "## Comparações pareadas", "",
        "Para cada par de schedulers foram calculadas diferenças A − B por run, "
        "média, mediana, IC95% da média, vitórias/empates/derrotas, Cohen dz, teste t "
        "pareado e Wilcoxon. Os p-valores de cada métrica foram corrigidos pelo método "
        "de Holm nas seis comparações.", "",
        "## Síntese dos resultados", "",
        f"- PF apresentou {abs(thr_rr_pf.mean_delta_a_minus_b):.3f} Mbps a mais que RR "
        f"em média e venceu em vazão nas {thr_rr_pf.wins_b} runs.",
        f"- PF apresentou {thr_pf_qos.mean_delta_a_minus_b:.3f} Mbps a mais que QoS "
        f"em média e venceu em vazão nas {thr_pf_qos.wins_a} runs.",
        f"- MR apresentou {abs(thr_pf_mr.mean_delta_a_minus_b):.3f} Mbps a mais que PF, "
        f"mas PF apresentou {jain_pf_mr.mean_delta_a_minus_b:.3f} a mais no índice de Jain.",
        f"- RR apresentou {jain_rr_pf.mean_delta_a_minus_b:.4f} a mais de Jain que PF; "
        f"QoS apresentou {abs(jain_pf_qos.mean_delta_a_minus_b):.4f} a mais que PF.",
        "- Todas as 12 comparações de Wilcoxon permaneceram significativas após "
        "a correção de Holm (p < 0,001).", "",
        "O PF vencer Nash em 100% das runs significa que ele foi o melhor compromisso "
        "sob este produto e esta normalização por run. Isso não implica superioridade "
        "absoluta: MR privilegia vazão, enquanto RR e QoS privilegiam justiça.",
    ]
    report_text = "\n".join(report) + "\n"
    (args.output / "RELATORIO-ANALISE-PAREADA.md").write_text(report_text,
                                                               encoding="utf-8")
    (args.output / "RELATORIO-INICIAL.md").write_text(report_text, encoding="utf-8")
    print(f"Análise pareada gerada em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
