#!/usr/bin/env python3
"""Motor offline de análise Pareto--Nash dos experimentos VJ5G.

O módulo recebe o ``window_log`` combinado de dois ou mais escalonadores,
marca a fronteira vazão x justiça em cada janela, seleciona os vencedores da
Barganha de Nash e produz o ranking de aparições na fronteira.

Esta implementação é deliberadamente offline: a referência de vazão pode ser
obtida do conjunto completo. Ela não deve ser confundida com o futuro
controlador causal de alfa dinâmico dentro do scheduler.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


REQUIRED_COLUMNS = {
    "scheduler",
    "window_id",
    "aggregate_thr_mbps",
    "jain_throughput",
}
DEFAULT_GROUP_COLUMNS = (
    "traffic_profile",
    "num_ues",
    "seed",
    "bandwidth_mhz",
    "window_id",
)
DEFAULT_EPSILON = 1e-9


class AnalysisError(ValueError):
    """Erro de entrada ou configuração do motor de análise."""


def validate_window_data(data: pd.DataFrame, epsilon: float = DEFAULT_EPSILON) -> None:
    """Valida o schema e os domínios numéricos do log de janelas."""
    missing = sorted(REQUIRED_COLUMNS - set(data.columns))
    if missing:
        raise AnalysisError(f"Colunas obrigatórias ausentes: {', '.join(missing)}")
    if data.empty:
        raise AnalysisError("O arquivo de entrada não contém linhas")
    if data["scheduler"].isna().any() or (data["scheduler"].astype(str).str.strip() == "").any():
        raise AnalysisError("A coluna scheduler contém valores vazios")

    for column in ("window_id", "aggregate_thr_mbps", "jain_throughput"):
        converted = pd.to_numeric(data[column], errors="coerce")
        if converted.isna().any() or not converted.map(math.isfinite).all():
            raise AnalysisError(f"A coluna {column} contém valor não numérico ou não finito")

    throughput = pd.to_numeric(data["aggregate_thr_mbps"])
    fairness = pd.to_numeric(data["jain_throughput"])
    if (throughput < -epsilon).any():
        raise AnalysisError("aggregate_thr_mbps não pode ser negativo")
    if ((fairness < -epsilon) | (fairness > 1.0 + epsilon)).any():
        raise AnalysisError("jain_throughput deve estar no intervalo [0, 1]")


def available_group_columns(data: pd.DataFrame, requested: Sequence[str]) -> list[str]:
    """Retorna colunas de agrupamento existentes, exigindo ``window_id``."""
    columns = [column for column in requested if column in data.columns]
    if "window_id" not in columns:
        raise AnalysisError("O agrupamento precisa incluir window_id")
    return columns


def is_dominated(
    throughput: float,
    fairness: float,
    candidates: Iterable[tuple[float, float]],
    epsilon: float = DEFAULT_EPSILON,
) -> bool:
    """Informa se o ponto é Pareto-dominado, maximizando ambos os eixos."""
    for other_throughput, other_fairness in candidates:
        no_worse = (
            other_throughput >= throughput - epsilon
            and other_fairness >= fairness - epsilon
        )
        strictly_better = (
            other_throughput > throughput + epsilon
            or other_fairness > fairness + epsilon
        )
        if no_worse and strictly_better:
            return True
    return False


def mark_pareto_front(
    data: pd.DataFrame,
    group_columns: Sequence[str] = DEFAULT_GROUP_COLUMNS,
    epsilon: float = DEFAULT_EPSILON,
) -> pd.DataFrame:
    """Adiciona ``pareto_nao_dominado`` em cada grupo/janela."""
    validate_window_data(data, epsilon)
    groups = available_group_columns(data, group_columns)
    output = data.copy()
    output["aggregate_thr_mbps"] = pd.to_numeric(output["aggregate_thr_mbps"])
    output["jain_throughput"] = pd.to_numeric(output["jain_throughput"])
    output["pareto_nao_dominado"] = False

    for _, indexes in output.groupby(groups, dropna=False, sort=False).groups.items():
        group = output.loc[indexes]
        candidates = list(zip(group["aggregate_thr_mbps"], group["jain_throughput"]))
        output.loc[indexes, "pareto_nao_dominado"] = [
            not is_dominated(row.aggregate_thr_mbps, row.jain_throughput, candidates, epsilon)
            for row in group.itertuples()
        ]
    return output


def add_nash_scores(
    marked: pd.DataFrame,
    throughput_reference: float | None = None,
    fairness_reference: float = 1.0,
    throughput_disagreement: float = 0.0,
    fairness_disagreement: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Normaliza os objetivos e calcula o produto de Barganha de Nash."""
    output = marked.copy()
    if throughput_reference is None:
        throughput_reference = float(output["aggregate_thr_mbps"].max())
    references = {
        "throughput_reference": float(throughput_reference),
        "fairness_reference": float(fairness_reference),
        "throughput_disagreement": float(throughput_disagreement),
        "fairness_disagreement": float(fairness_disagreement),
    }
    if throughput_reference <= throughput_disagreement:
        raise AnalysisError("A referência de vazão deve superar o ponto de desacordo")
    if fairness_reference <= fairness_disagreement:
        raise AnalysisError("A referência de justiça deve superar o ponto de desacordo")

    output["throughput_normalized"] = (
        (output["aggregate_thr_mbps"] - throughput_disagreement)
        / (throughput_reference - throughput_disagreement)
    ).clip(0.0, 1.0)
    output["jain_normalized"] = (
        (output["jain_throughput"] - fairness_disagreement)
        / (fairness_reference - fairness_disagreement)
    ).clip(0.0, 1.0)
    output["nash_score"] = output["throughput_normalized"] * output["jain_normalized"]
    return output, references


def select_nash_winners(
    scored: pd.DataFrame,
    group_columns: Sequence[str] = DEFAULT_GROUP_COLUMNS,
    epsilon: float = DEFAULT_EPSILON,
) -> pd.DataFrame:
    """Retorna todos os vencedores empatados de Nash em cada fronteira."""
    groups = available_group_columns(scored, group_columns)
    winners: list[pd.DataFrame] = []
    for _, group in scored.groupby(groups, dropna=False, sort=False):
        candidates = group[group["pareto_nao_dominado"]]
        if candidates.empty:
            continue
        best = float(candidates["nash_score"].max())
        selected = candidates[(candidates["nash_score"] - best).abs() <= epsilon].copy()
        selected["nash_empate"] = len(selected) > 1
        selected["nash_num_vencedores"] = len(selected)
        winners.append(selected)
    if not winners:
        return scored.head(0).assign(nash_empate=pd.Series(dtype=bool), nash_num_vencedores=pd.Series(dtype=int))
    return pd.concat(winners, ignore_index=True)


def rank_schedulers(
    marked: pd.DataFrame,
    winners: pd.DataFrame,
    group_columns: Sequence[str] = DEFAULT_GROUP_COLUMNS,
) -> pd.DataFrame:
    """Cria ranking global, fracionando a vitória de Nash em empates."""
    schedulers = sorted(marked["scheduler"].astype(str).unique())
    groups = available_group_columns(marked, group_columns)
    total_groups = int(marked.groupby(groups, dropna=False).ngroups)
    appearances = (
        marked[marked["pareto_nao_dominado"]].groupby("scheduler").size()
    )
    if winners.empty:
        nash_credits = pd.Series(dtype=float)
    else:
        weighted = winners.assign(nash_credit=1.0 / winners["nash_num_vencedores"])
        nash_credits = weighted.groupby("scheduler")["nash_credit"].sum()

    ranking = pd.DataFrame({"scheduler": schedulers})
    ranking["aparicoes_na_fronteira"] = ranking["scheduler"].map(appearances).fillna(0).astype(int)
    ranking["pct_janelas_na_fronteira"] = (
        ranking["aparicoes_na_fronteira"] / total_groups * 100.0
    )
    ranking["vitorias_nash_equivalentes"] = ranking["scheduler"].map(nash_credits).fillna(0.0)
    ranking["pct_vitorias_nash"] = ranking["vitorias_nash_equivalentes"] / total_groups * 100.0
    return ranking.sort_values(
        ["aparicoes_na_fronteira", "vitorias_nash_equivalentes", "scheduler"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def run_analysis(
    input_path: Path,
    output_dir: Path,
    group_columns: Sequence[str] = DEFAULT_GROUP_COLUMNS,
    throughput_reference: float | None = None,
    epsilon: float = DEFAULT_EPSILON,
) -> dict[str, Path]:
    """Executa o pipeline completo e grava os artefatos científicos."""
    data = pd.read_csv(input_path)
    marked = mark_pareto_front(data, group_columns, epsilon)
    scored, references = add_nash_scores(marked, throughput_reference=throughput_reference)
    winners = select_nash_winners(scored, group_columns, epsilon)
    ranking = rank_schedulers(scored, winners, group_columns)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "pareto": output_dir / "window_log_com_pareto.csv",
        "nash": output_dir / "vencedores_nash_por_janela.csv",
        "ranking": output_dir / "ranking_escalonadores.csv",
        "metadata": output_dir / "metadata_analise.json",
    }
    scored.to_csv(paths["pareto"], index=False)
    winners.to_csv(paths["nash"], index=False)
    ranking.to_csv(paths["ranking"], index=False)
    metadata = {
        "input": str(input_path.resolve()),
        "rows": len(data),
        "schedulers": sorted(data["scheduler"].astype(str).unique()),
        "group_columns": available_group_columns(data, group_columns),
        "epsilon": epsilon,
        "normalization_scope": "offline_global",
        **references,
    }
    paths["metadata"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calcula Pareto, Nash e ranking nos logs VJ5G.")
    parser.add_argument("--input", required=True, type=Path, help="window_log combinado em CSV")
    parser.add_argument("--output", required=True, type=Path, help="diretório dos resultados")
    parser.add_argument(
        "--group-by",
        default=",".join(DEFAULT_GROUP_COLUMNS),
        help="colunas que identificam uma janela comparável, separadas por vírgula",
    )
    parser.add_argument("--throughput-reference", type=float, default=None)
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    groups = [column.strip() for column in args.group_by.split(",") if column.strip()]
    try:
        paths = run_analysis(
            args.input,
            args.output,
            group_columns=groups,
            throughput_reference=args.throughput_reference,
            epsilon=args.epsilon,
        )
    except (AnalysisError, OSError, pd.errors.ParserError) as error:
        raise SystemExit(f"[ERRO] {error}") from error
    for name, path in paths.items():
        print(f"[{name.upper()}] {path}")


if __name__ == "__main__":
    main()
