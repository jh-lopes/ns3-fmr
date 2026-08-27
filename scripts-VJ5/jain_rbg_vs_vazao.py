#!/usr/bin/env python3
# ============================================================
# jain_rbg_symbol_units_vs_vazao.py
#
# Compara, janela a janela, o Índice de Jain calculado sobre
# RBG (estilo Diego — equidade na ALOCAÇÃO de recursos) com o
# Índice de Jain calculado sobre vazão (contribuição original
# desta dissertação — equidade na EXPERIÊNCIA do usuário).
#
# Usa dois logs que já existem no simulacao-vj5g.cc:
#   --EnableWindowCsv        (Bloco 6B) → Jain sobre vazão por
#                               janela de 100ms
#   --EnableCommonSlotCsv    (atributo nativo de
#                               NrMacSchedulerOfdma) → RBG
#                               alocado por UE por SLOT (~1ms)
#
# Como os dois logs têm granularidades diferentes (janela de
# 100ms vs slot de ~1ms), este script agrupa os slots do
# CommonSlotCsv nas mesmas janelas de 100ms do WindowCsv antes
# de calcular o Jain sobre RBG — assim os dois números
# comparados são da mesma fatia de tempo.
#
# Cenário: C3 ESTÁTICO (sem mobilidade) — mesmo cenário do
# Achado 3 já documentado (achados-pesquisa-vj5g.md): UEs fixos
# em 10/256/500m. Escolhido estático de propósito aqui, porque
# o objetivo é isolar o efeito "mesmo RBG, MCS diferente" sem
# ruído de canal variando no tempo (mobilidade fica pro Pilar 1).
#
# Uso:
#   cd ~/ns3-fmr
#   python3 jain_rbg_symbol_units_vs_vazao.py
#
# Requer: pandas
# ============================================================

import subprocess
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Este script precisa do pandas. Instale com:")
    print("  pip install pandas   (ou use o .venv do projeto)")
    sys.exit(1)

# ------------------------------------------------------------
# Configuração
# ------------------------------------------------------------

OUTPUT_DIR = Path("pesquisa/resultados/jain_rbg_symbol_units_vs_vazao")
NS3_SCRIPT = "scratch/simulacao-vj5g"

# udpAppStartTime é fixo em 400ms no simulacao-vj5g.cc (não é
# exposto via CLI) — usado aqui para bucketizar os slots do RBG
# nas mesmas janelas do WindowCsv (ver RegistrarJanela em
# simulacao-vj5g-utils.h, que agenda a primeira janela em
# udpAppStartTime + windowSizeMs).
UDP_APP_START_S = 0.4

# Cenário C3 estático — mesmo cenário do Achado 3 documentado
CENARIO_C3 = {
    "trafficProfile": "embb",
    "ueNumPergNb": 3,
    "simTime": "5s",
    "seed": 1,
    "bandwidth": 10000000,
    "totalTxPower": 23,
    "ueDistances": "10,256,500",
    "lambdaOverride": 5000,
    "WindowSizeMs": 100,
}

SCHEDULERS = ["rr", "pf", "mr"]


# ------------------------------------------------------------
# Etapa 1 — rodar as simulações com os dois logs ligados
# ------------------------------------------------------------
def rodar_simulacao(scheduler_mode: str, window_csv: Path, rbg_csv: Path) -> None:
    cmd = [
        "./ns3", "run",
        (
            f"{NS3_SCRIPT} "
            f"--schedulerMode={scheduler_mode} "
            f"--trafficProfile={CENARIO_C3['trafficProfile']} "
            f"--ueNumPergNb={CENARIO_C3['ueNumPergNb']} "
            f"--simTime={CENARIO_C3['simTime']} "
            f"--seed={CENARIO_C3['seed']} "
            f"--bandwidth={CENARIO_C3['bandwidth']} "
            f"--totalTxPower={CENARIO_C3['totalTxPower']} "
            f"--ueDistances={CENARIO_C3['ueDistances']} "
            f"--lambdaOverride={CENARIO_C3['lambdaOverride']} "
            f"--EnableWindowCsv=true "
            f"--WindowCsvPath={window_csv} "
            f"--WindowSizeMs={CENARIO_C3['WindowSizeMs']} "
            f"--EnableCommonSlotCsv=true "
            f"--CommonSlotCsvPath={rbg_csv}"
        ),
    ]

    print(f"\n[jain_cmp] Rodando scheduler={scheduler_mode} ...")
    resultado = subprocess.run(cmd, capture_output=True, text=True)

    if resultado.returncode != 0:
        print(f"[jain_cmp] ERRO ao rodar scheduler={scheduler_mode}:")
        print(resultado.stdout[-2000:])
        print(resultado.stderr[-2000:])
        raise SystemExit(1)

    for linha in resultado.stdout.splitlines():
        if linha.startswith("[RESULT]"):
            print(f"[jain_cmp] {linha}")

    if not window_csv.exists() or not rbg_csv.exists():
        print(f"[jain_cmp] AVISO: CSV esperado não foi criado "
              f"(window={window_csv.exists()}, rbg={rbg_csv.exists()})")
        raise SystemExit(1)


# ------------------------------------------------------------
# Etapa 2 — Jain sobre RBG por janela
# ------------------------------------------------------------
def calcular_jain(valores) -> float:
    """Mesma fórmula usada em CalcularJainVazao() no C++:
    J = (Σx)² / (n × Σx²). Dimensionless — funciona igual para
    throughput (Mbps) ou RBG (contagem inteira)."""
    valores = list(valores)
    if not valores:
        return 0.0
    soma = sum(valores)
    soma_quadrados = sum(v * v for v in valores)
    if soma_quadrados == 0:
        return 0.0
    n = len(valores)
    return (soma ** 2) / (n * soma_quadrados)


def jain_rbg_symbol_units_por_janela(rbg_csv: Path, window_size_ms: int) -> pd.DataFrame:
    """Lê o CommonSlotCsv (uma linha por RNTI por slot), agrupa
    os slots nas mesmas janelas de 100ms do WindowCsv, soma o
    RBG alocado por RNTI dentro de cada janela, e calcula o
    Jain sobre esse vetor de RBG por janela."""

    df = pd.read_csv(rbg_csv)
    if "allocated_rbg_symbol_units" not in df.columns:
        if "alloc_rbg" in df.columns:
            print(f"[aviso] {rbg_csv} usa o nome legado alloc_rbg; "
                  "interpretando como unidades RBG×símbolo")
            df = df.rename(columns={"alloc_rbg": "allocated_rbg_symbol_units"})
        else:
            raise ValueError(
                f"{rbg_csv} sem allocated_rbg_symbol_units")
    window_size_s = window_size_ms / 1000.0

    # Mesmo critério de bucketização usado por RegistrarJanela():
    # a primeira janela fecha em udpAppStartTime + windowSizeMs,
    # cobrindo os slots com time_s em
    # [udpAppStartTime, udpAppStartTime + windowSizeMs).
    df = df[df["time_s"] >= UDP_APP_START_S].copy()
    df["window_id"] = (
        (df["time_s"] - UDP_APP_START_S) // window_size_s
    ).astype(int)

    # Soma RBG por RNTI dentro de cada janela
    rbg_por_janela_rnti = (
        df.groupby(["window_id", "rnti"])["allocated_rbg_symbol_units"].sum().reset_index()
    )

    linhas = []
    for window_id, grupo in rbg_por_janela_rnti.groupby("window_id"):
        jain = calcular_jain(grupo["allocated_rbg_symbol_units"].tolist())
        linhas.append({
            "window_id": window_id,
            "jain_rbg_symbol_units": jain,
            "rbg_symbol_units_total_window": grupo["allocated_rbg_symbol_units"].sum(),
            "num_ues_with_rbg_symbol_units": len(grupo),
        })

    return pd.DataFrame(linhas)


# ------------------------------------------------------------
# main
# ------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    comparacoes = []

    for scheduler in SCHEDULERS:
        window_csv = OUTPUT_DIR / f"window_log_{scheduler}.csv"
        rbg_csv = OUTPUT_DIR / f"rbg_log_{scheduler}.csv"

        rodar_simulacao(scheduler, window_csv, rbg_csv)

        df_vazao = pd.read_csv(window_csv)[["window_id", "time_s", "jain_throughput",
                                              "aggregate_thr_mbps"]]
        df_rbg = jain_rbg_symbol_units_por_janela(rbg_csv, CENARIO_C3["WindowSizeMs"])

        comparacao = df_vazao.merge(df_rbg, on="window_id", how="inner")
        comparacao.insert(0, "scheduler", scheduler)
        comparacoes.append(comparacao)

    dados = pd.concat(comparacoes, ignore_index=True)
    comparacao_path = OUTPUT_DIR / "jain_rbg_symbol_units_vs_vazao_por_janela.csv"
    dados.to_csv(comparacao_path, index=False)
    print(f"\n[jain_cmp] Comparação por janela salva em: {comparacao_path}")

    print("\n" + "=" * 70)
    print("JAIN SOBRE RBG vs JAIN SOBRE VAZÃO — MÉDIA POR SCHEDULER (C3, eMBB)")
    print("=" * 70)
    resumo = (
        dados.groupby("scheduler")
        .agg(
            jain_rbg_symbol_units_medio=("jain_rbg_symbol_units", "mean"),
            jain_vazao_medio=("jain_throughput", "mean"),
            throughput_medio_mbps=("aggregate_thr_mbps", "mean"),
        )
        .round(4)
        .reset_index()
    )
    resumo["divergencia"] = (
        resumo["jain_rbg_symbol_units_medio"] - resumo["jain_vazao_medio"]
    ).round(4)
    print(resumo.to_string(index=False))

    resumo_path = OUTPUT_DIR / "resumo_jain_rbg_symbol_units_vs_vazao.csv"
    resumo.to_csv(resumo_path, index=False)
    print(f"\n[jain_cmp] Resumo salvo em: {resumo_path}")

    print("\nInterpretação: 'divergencia' alta e positiva = o scheduler")
    print("parece mais justo do que realmente é, se você só olhar o Jain")
    print("sobre RBG (como no trabalho do Diego). Essa é a lacuna que a")
    print("métrica original desta dissertação (Jain sobre vazão) revela.")


if __name__ == "__main__":
    main()
