#!/usr/bin/env python3
# ============================================================
# pilar1_2_prototipo.py
#
# Protótipo dos Pilares 1 e 2 do alfa dinâmico via Fronteira de
# Pareto (dissertação VJ5G — ver registro-sessao-alfa-dinamico-
# vj5g.md no projeto Claude "Simulação Dissertação").
#
# O que este script faz:
#   1. Roda o binário simulacao-vj5g para os escalonadores RR,
#      PF e MR no cenário C3 (10MHz, 23dBm, UEs em 10/256/500m),
#      com --EnableWindowCsv ativo (Bloco 6B, já validado).
#   2. Junta os window_log.csv de cada scheduler num único
#      DataFrame.
#   3. Para cada janela (window_id), calcula quais schedulers
#      atingem um ponto NÃO-DOMINADO no plano T×J daquela janela
#      — isso é o Pilar 2 (ranqueamento por aparições na
#      fronteira).
#   4. Entre os pontos não-dominados de cada janela, aplica o
#      critério de Barganha de Nash (produto das métricas
#      normalizadas) para identificar qual seria o "ponto ótimo"
#      daquela janela — isso é o protótipo do Pilar 1 (alfa
#      dinâmico), feito em Python ANTES de portar para um
#      scheduler C++ novo no contrib/nr.
#
# Este script é um protótipo de validação, não o orquestrador
# final de 105 simulações (run_simulacao.py, ainda não construído
# — ver tabela de pendentes do projeto). Escopo aqui: 3
# schedulers x 1 cenário (C3) x eMBB, só para provar a lógica
# dos Pilares 1 e 2 com dados reais antes de escalar.
#
# FMR fica de fora por enquanto — exige o agente Python do
# ns3-ai rodando em paralelo (EnableNs3Ai=true), o que este
# script não orquestra ainda.
#
# Uso:
#   cd ~/ns3-fmr
#   python3 pilar1_2_prototipo.py
#
# Requer: pandas (pip install pandas --break-system-packages,
# se ainda não estiver instalado no ambiente do servidor)
# ============================================================

import subprocess
import sys
import os
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Este script precisa do pandas. Instale com:")
    print("  pip install pandas --break-system-packages")
    sys.exit(1)

# ------------------------------------------------------------
# Configuração
# ------------------------------------------------------------

# Diretório onde os CSVs de janela de cada scheduler serão
# salvos. Criado automaticamente se não existir.
OUTPUT_DIR = Path("pesquisa/resultados/pilar1_2_prototipo")

# Binário compilado (mesmo nome usado no comando manual que já
# funcionou: build/scratch/ns3.46-simulacao-vj5g-default)
NS3_SCRIPT = "scratch/simulacao-vj5g"

# Cenário C3 — já validado nos achados da pesquisa
#
# lambdaOverride=5000 (~60 Mbps de demanda ofertada por UE):
# necessário porque o perfil eMBB padrão (lambda=1000,
# flowsPorUe=1) oferece só ~12 Mbps por UE. Nesse nível, o MR
# fica limitado pela DEMANDA (ele entrega exatamente o que o
# UE0 pede, ~12.5 Mbps) e não pelo CANAL — o que mascara a
# diferenciação real entre schedulers e não bate com o pico de
# ~62 Mbps observado na Fronteira de Pareto do SEMISH (Slide 6).
# Com lambdaOverride mais alto, todos os schedulers passam a ser
# limitados pelo canal, que é o regime que interessa para
# comparar RR/PF/MR de forma justa e para o alfa dinâmico ter
# algo real para arbitrar. Ver investigação registrada na
# conversa — RR e PF já batiam com os achados documentados;
# só o MR estava artificialmente baixo por esse motivo.
#
# MOBILIDADE ATIVADA (enableMobility=true): com UEs em posição
# FIXA, o canal não muda de uma janela pra outra dentro da
# mesma rodada — as 45 janelas são amostras quase idênticas da
# mesma foto estática, então não há motivo físico pro vencedor
# do critério de Nash mudar entre janelas (foi exatamente o que
# aconteceu no teste anterior: MR venceu as 45/45). Com
# mobilidade real, o SINR de cada UE varia ao longo da simulação
# conforme eles se movem, e É esperado que o "ponto ótimo" mude
# de janela pra janela — essa variação real é o que o Pilar 1
# (alfa dinâmico) precisa para fazer sentido como mecanismo
# adaptativo. --ueDistances é ignorado quando enableMobility=true
# (o código usa RandomDiscPositionAllocator dentro de
# mobilityBounds em vez de posições manuais).
CENARIO_C3 = {
    "trafficProfile": "embb",
    "ueNumPergNb": 3,
    "simTime": "5s",
    "seed": 1,
    "bandwidth": 10000000,
    "totalTxPower": 23,
    "WindowSizeMs": 100,
    "lambdaOverride": 5000,
    "enableMobility": True,
    "mobilityModel": "random_walk",
    "mobilitySpeedMin": 1.0,
    "mobilitySpeedMax": 3.0,
    # mobilityBounds=500: mesmo raio máximo do C3 estático
    # (o UE mais distante testado antes estava a 500m), agora
    # como limite da área de movimento, não posição fixa.
    "mobilityBounds": 500,
}

# Escalonadores incluídos neste protótipo. FMR fica de fora
# (ver docstring acima).
SCHEDULERS = ["rr", "pf", "mr"]


# ------------------------------------------------------------
# Etapa 1 — rodar as simulações
# ------------------------------------------------------------
def rodar_simulacao(scheduler_mode: str, output_csv: Path) -> None:
    """Roda o binário ns-3 para um scheduler, salvando o
    window_log correspondente em output_csv."""

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
            f"--lambdaOverride={CENARIO_C3['lambdaOverride']} "
            f"--enableMobility={str(CENARIO_C3['enableMobility']).lower()} "
            f"--mobilityModel={CENARIO_C3['mobilityModel']} "
            f"--mobilitySpeedMin={CENARIO_C3['mobilitySpeedMin']} "
            f"--mobilitySpeedMax={CENARIO_C3['mobilitySpeedMax']} "
            f"--mobilityBounds={CENARIO_C3['mobilityBounds']} "
            f"--EnableWindowCsv=true "
            f"--WindowCsvPath={output_csv} "
            f"--WindowSizeMs={CENARIO_C3['WindowSizeMs']}"
        ),
    ]

    print(f"\n[pilar1_2] Rodando scheduler={scheduler_mode} ...")
    resultado = subprocess.run(cmd, capture_output=True, text=True)

    if resultado.returncode != 0:
        print(f"[pilar1_2] ERRO ao rodar scheduler={scheduler_mode}:")
        print(resultado.stdout[-2000:])
        print(resultado.stderr[-2000:])
        raise SystemExit(1)

    # Linha [RESULT] já vem estruturada — útil para conferência
    for linha in resultado.stdout.splitlines():
        if linha.startswith("[RESULT]"):
            print(f"[pilar1_2] {linha}")

    if not output_csv.exists():
        print(f"[pilar1_2] AVISO: {output_csv} não foi criado. "
              "Verifique se --EnableWindowCsv chegou até o binário.")
        raise SystemExit(1)


def coletar_dados() -> pd.DataFrame:
    """Roda todos os schedulers definidos em SCHEDULERS e retorna
    um único DataFrame com todas as janelas de todos eles."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = []

    for scheduler in SCHEDULERS:
        csv_path = OUTPUT_DIR / f"window_log_{scheduler}.csv"
        rodar_simulacao(scheduler, csv_path)
        df = pd.read_csv(csv_path)
        frames.append(df)

    dados = pd.concat(frames, ignore_index=True)
    dados_path = OUTPUT_DIR / "window_log_combinado.csv"
    dados.to_csv(dados_path, index=False)
    print(f"\n[pilar1_2] Dados combinados salvos em: {dados_path}")
    return dados


# ------------------------------------------------------------
# Etapa 2 — Pilar 2: fronteira de Pareto por janela + ranking
# ------------------------------------------------------------
def eh_dominado(ponto, outros_pontos):
    """Um ponto (T, J) é dominado se existe outro ponto igual ou
    melhor nos dois critérios, e estritamente melhor em pelo
    menos um — definição padrão de dominância de Pareto, mesma
    usada no Slide 4 do roteiro SEMISH."""
    t, j = ponto
    for outro_t, outro_j in outros_pontos:
        if (outro_t, outro_j) == (t, j):
            continue
        melhor_ou_igual = outro_t >= t and outro_j >= j
        estritamente_melhor = outro_t > t or outro_j > j
        if melhor_ou_igual and estritamente_melhor:
            return True
    return False


def calcular_pareto_por_janela(dados: pd.DataFrame) -> pd.DataFrame:
    """Para cada window_id, marca quais linhas (scheduler, T, J)
    são não-dominadas — ou seja, pertencem à fronteira de Pareto
    daquela janela especificamente."""

    linhas_marcadas = []

    for window_id, grupo in dados.groupby("window_id"):
        pontos = list(zip(grupo["aggregate_thr_mbps"], grupo["jain_throughput"]))

        for idx, row in grupo.iterrows():
            ponto = (row["aggregate_thr_mbps"], row["jain_throughput"])
            dominado = eh_dominado(ponto, pontos)
            linha = row.to_dict()
            linha["pareto_nao_dominado"] = not dominado
            linhas_marcadas.append(linha)

    return pd.DataFrame(linhas_marcadas)


def calcular_ranking_pilar2(dados_marcados: pd.DataFrame) -> pd.DataFrame:
    """Pilar 2: conta quantas vezes cada scheduler aparece como
    ponto não-dominado — essa contagem é o ranking proposto."""

    ranking = (
        dados_marcados[dados_marcados["pareto_nao_dominado"]]
        .groupby("scheduler")
        .size()
        .rename("aparicoes_na_fronteira")
        .reset_index()
        .sort_values("aparicoes_na_fronteira", ascending=False)
    )

    total_janelas = dados_marcados["window_id"].nunique()
    ranking["pct_das_janelas"] = (
        ranking["aparicoes_na_fronteira"] / total_janelas * 100
    ).round(1)

    return ranking


# ------------------------------------------------------------
# Etapa 3 — Pilar 1 (protótipo): critério de Nash por janela
# ------------------------------------------------------------
def calcular_alfa_dinamico_por_janela(dados_marcados: pd.DataFrame) -> pd.DataFrame:
    """Protótipo do Pilar 1: normaliza T e J pelos valores
    máximos observados em TODO o dataset coletado (todas as
    janelas, todos os schedulers) — não pelo máximo de cada
    janela individual. Depois, para cada janela, calcula o
    produto de Nash apenas entre os pontos não-dominados e
    escolhe o vencedor — o "ponto ótimo" que, na proposta,
    viraria o piso de justiça mínima (épsilon) para a próxima
    janela.

    Mesmo critério do Slide 7 do roteiro SEMISH: S = sqrt(J_norm
    * T_norm), com a MESMA base de normalização (dataset inteiro)
    usada lá — só que agora recalculado POR JANELA em vez de uma
    vez só para a simulação inteira. É essa diferença (recálculo
    por janela) que sustenta o Pilar 1 como contribuição original
    (ver Parte 2 do registro de sessão).

    CORREÇÃO (achada rodando com dados reais): a primeira versão
    normalizava T e J pelo máximo DENTRO de cada janela — mas
    cada janela só tem 3 pontos (um por scheduler). Isso inflava
    artificialmente o score do MR: como ele quase sempre tem o
    maior throughput bruto da janela, T_norm ficava sempre ~1.0,
    mesmo com Jain baixíssimo (0.333, starvation total). Resultado:
    o MR "vencia" 100% das janelas, o que não reflete um trade-off
    real entre eficiência e justiça — só reflete que normalizar
    por um grupo de 3 pontos deixa qualquer extremo artificialmente
    "bom" nos dois eixos. Normalizando pelo máximo global (como no
    SEMISH, com ~1880 pontos), a régua de comparação fica estável
    entre janelas e o resultado passa a diferenciar de verdade.
    """

    t_max_global = dados_marcados["aggregate_thr_mbps"].max()
    j_max_global = dados_marcados["jain_throughput"].max()

    vencedores = []

    for window_id, grupo in dados_marcados.groupby("window_id"):
        candidatos = grupo[grupo["pareto_nao_dominado"]]
        if candidatos.empty:
            continue

        melhor_scheduler = None
        melhor_score = -1.0
        melhor_t = None
        melhor_j = None

        for _, row in candidatos.iterrows():
            t_norm = (row["aggregate_thr_mbps"] / t_max_global
                       if t_max_global > 0 else 0.0)
            j_norm = (row["jain_throughput"] / j_max_global
                       if j_max_global > 0 else 0.0)
            score = (t_norm * j_norm) ** 0.5  # Barganha de Nash

            if score > melhor_score:
                melhor_score = score
                melhor_scheduler = row["scheduler"]
                melhor_t = row["aggregate_thr_mbps"]
                melhor_j = row["jain_throughput"]

        vencedores.append({
            "window_id": window_id,
            "scheduler_vencedor": melhor_scheduler,
            "throughput_mbps": melhor_t,
            "jain_throughput": melhor_j,
            "nash_score": round(melhor_score, 4),
        })

    return pd.DataFrame(vencedores)


# ------------------------------------------------------------
# main
# ------------------------------------------------------------
def main():
    dados = coletar_dados()

    print(f"\n[pilar1_2] Total de linhas coletadas: {len(dados)}")
    print(f"[pilar1_2] Schedulers: {sorted(dados['scheduler'].unique())}")
    print(f"[pilar1_2] Janelas por scheduler: "
          f"{dados.groupby('scheduler')['window_id'].nunique().to_dict()}")

    dados_marcados = calcular_pareto_por_janela(dados)
    marcados_path = OUTPUT_DIR / "window_log_com_pareto.csv"
    dados_marcados.to_csv(marcados_path, index=False)
    print(f"\n[pilar1_2] Dados com marcação de Pareto salvos em: {marcados_path}")

    print("\n" + "=" * 60)
    print("PILAR 2 — RANKING POR APARIÇÕES NA FRONTEIRA (eMBB, C3)")
    print("=" * 60)
    ranking = calcular_ranking_pilar2(dados_marcados)
    print(ranking.to_string(index=False))
    ranking_path = OUTPUT_DIR / "ranking_pilar2.csv"
    ranking.to_csv(ranking_path, index=False)
    print(f"\n[pilar1_2] Ranking salvo em: {ranking_path}")

    print("\n" + "=" * 60)
    print("PILAR 1 — PROTÓTIPO DO ALFA DINÂMICO (critério de Nash por janela)")
    print("=" * 60)
    alfa_dinamico = calcular_alfa_dinamico_por_janela(dados_marcados)
    print(alfa_dinamico.to_string(index=False))
    alfa_path = OUTPUT_DIR / "alfa_dinamico_por_janela.csv"
    alfa_dinamico.to_csv(alfa_path, index=False)
    print(f"\n[pilar1_2] Série do alfa dinâmico salva em: {alfa_path}")

    print("\n" + "=" * 60)
    print("RESUMO: quantas janelas cada scheduler venceria como")
    print("'ponto ótimo' se o alfa dinâmico estivesse ativo:")
    print("=" * 60)
    print(alfa_dinamico["scheduler_vencedor"].value_counts().to_string())


if __name__ == "__main__":
    main()