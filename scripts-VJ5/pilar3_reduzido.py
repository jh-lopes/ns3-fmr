#!/usr/bin/env python3
# ============================================================
# pilar3_reduzido.py
#
# Prova de conceito do Pilar 3 (matriz de cenários), com escopo
# reduzido pra caber no prazo de 15/ago — ver conversa no projeto
# "Simulação Dissertação" (Claude), decisão tomada em 11/ago/2026.
#
# Matriz original do Pilar 3 (ver registro-sessao-alfa-dinamico-
# vj5g.md, Parte 4): 10/50/100 dispositivos × múltiplos níveis de
# degradação de sinal × schedulers (RR, PF, MR, +FMR se possível),
# perfil eMBB fixo.
#
# Redução para esta prova de conceito:
#   - Dispositivos: 10 e 50 (pula 100 — reservado pra expandir
#     depois da entrega de 15/ago, antes da defesa de 30/set)
#   - Degradação de sinal: 2 níveis, espelhando os cenários C2 e
#     C3 já documentados nos achados (não inventa parâmetro novo):
#       moderado  = C2 (20MHz, 30dBm)
#       degradado = C3 (10MHz, 23dBm)
#   - Schedulers: RR, PF, MR (FMR fica de fora — exige orquestrar
#     o agente ns3-ai em paralelo, fora de escopo pro prazo atual)
#
# Cada combinação (dispositivos × nível de sinal × scheduler) é
# UMA simulação de 5s, sem mobilidade (posições aleatórias via
# seed, não manuais — inviável definir --ueDistances à mão pra 50
# UEs). O lambda do perfil eMBB NÃO é sobrescrito aqui: com 10-50
# UEs competindo, a demanda agregada já satura o canal sozinha,
# então a rede fica naturalmente limitada por canal sem precisar
# de --lambdaOverride (diferente do cenário C3 com só 3 UEs, onde
# isso era necessário).
#
# Para cada combinação, marca quais schedulers ficam na fronteira
# de Pareto (não-dominados) entre os 3 testados — mesma lógica do
# Pilar 2, mas aqui a "amostra" é a matriz de cenários, não janelas
# de tempo.
#
# Uso (de dentro de ~/ns3-fmr/scripts-VJ5/):
#   python3 pilar3_reduzido.py
#
# Saída: ~/ns3-fmr/pesquisa/resultados/pilar3_reduzido/
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
    print("  pip install pandas --break-system-packages")
    sys.exit(1)

# computar_rbg_por_ue.py precisa estar na mesma pasta deste script
# (scripts-VJ5/) — adiciona ao path pra poder importar a função direto,
# sem precisar chamar via subprocess.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from computar_rbg_por_ue import computar as computar_rbg_por_ue
except ImportError:
    print("[pilar3] AVISO: computar_rbg_por_ue.py não encontrado na mesma pasta — "
          "as colunas de RBG por UE (rbg_total_alocados etc) NÃO serão adicionadas "
          "aos ue_summary.csv desta rodada.")
    computar_rbg_por_ue = None

# ------------------------------------------------------------
# Configuração
# ------------------------------------------------------------

NS3_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = NS3_ROOT / "pesquisa/resultados/pilar3_reduzido"
NS3_SCRIPT = "scratch/simulacao-vj5g"

SCHEDULERS = ["rr", "pf", "mr"]
DISPOSITIVOS = [10, 50]

NIVEIS_SINAL = [
    {"nome": "moderado", "bandwidth": 20_000_000, "totalTxPower": 30},   # espelha C2
    {"nome": "degradado", "bandwidth": 10_000_000, "totalTxPower": 23},  # espelha C3
]

SIM_TIME = "5s"
SEED = 1
TRAFFIC_PROFILE = "embb"


# ------------------------------------------------------------
# Etapa 1 — rodar a matriz
# ------------------------------------------------------------
def rodar_simulacao(scheduler_mode: str, dispositivos: int, nivel: dict, ue_csv: Path) -> None:
    # slot_csv: log nativo do 5G-LENA com RBG alocado por UE por slot
    # (--EnableCommonSlotCsv). Funciona pra rr/pf/mr (os únicos usados
    # aqui) — não funciona pra fmr_rl, que sobrescreve a alocação nativa
    # (ver comentário no simulacao-vj5g.cc, linha ~148).
    slot_csv = ue_csv.with_name(ue_csv.stem + "_slotlog.csv")

    cmd = [
        "./ns3", "run",
        (
            f"{NS3_SCRIPT} "
            f"--schedulerMode={scheduler_mode} "
            f"--trafficProfile={TRAFFIC_PROFILE} "
            f"--ueNumPergNb={dispositivos} "
            f"--simTime={SIM_TIME} "
            f"--seed={SEED} "
            f"--bandwidth={nivel['bandwidth']} "
            f"--totalTxPower={nivel['totalTxPower']} "
            f"--EnableUeSummaryCsv=true "
            f"--UeSummaryCsvPath={ue_csv} "
            f"--EnableCommonSlotCsv=true "
            f"--CommonSlotCsvPath={slot_csv}"
        ),
    ]

    print(f"\n[pilar3] Rodando scheduler={scheduler_mode} dispositivos={dispositivos} "
          f"nivel={nivel['nome']} ...")
    resultado = subprocess.run(cmd, capture_output=True, text=True, cwd=NS3_ROOT)

    if resultado.returncode != 0:
        print(f"[pilar3] ERRO ao rodar scheduler={scheduler_mode} dispositivos={dispositivos} "
              f"nivel={nivel['nome']}:")
        print(resultado.stdout[-2000:])
        print(resultado.stderr[-2000:])
        raise SystemExit(1)

    for linha in resultado.stdout.splitlines():
        if linha.startswith("[RESULT]"):
            print(f"[pilar3] {linha}")

    if not ue_csv.exists():
        print(f"[pilar3] AVISO: {ue_csv} não foi criado. "
              "Verifique se --EnableUeSummaryCsv chegou até o binário.")
        raise SystemExit(1)

    # Cruza o log nativo de RBG com o ue_summary.csv desta rodada,
    # adicionando as colunas rbg_total_alocados, pct_slots_com_alocacao
    # etc — direto no mesmo ue_csv (sobrescreve, adicionando colunas).
    if computar_rbg_por_ue is not None:
        if slot_csv.exists():
            computar_rbg_por_ue(ue_csv, slot_csv, ue_csv)
        else:
            print(f"[pilar3] AVISO: {slot_csv} não foi criado — colunas de RBG "
                  f"não adicionadas para scheduler={scheduler_mode} "
                  f"dispositivos={dispositivos} nivel={nivel['nome']}.")


def coletar_matriz() -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    linhas = []

    for dispositivos in DISPOSITIVOS:
        for nivel in NIVEIS_SINAL:
            for scheduler in SCHEDULERS:
                ue_csv = OUTPUT_DIR / f"ue_summary_{scheduler}_{dispositivos}ue_{nivel['nome']}.csv"
                rodar_simulacao(scheduler, dispositivos, nivel, ue_csv)

                df_ue = pd.read_csv(ue_csv)
                if df_ue.empty:
                    print(f"[pilar3] AVISO: {ue_csv} veio vazio — pulando esta combinação.")
                    continue

                linhas.append({
                    "dispositivos": dispositivos,
                    "nivel_sinal": nivel["nome"],
                    "bandwidth_mhz": nivel["bandwidth"] / 1e6,
                    "scheduler": scheduler,
                    "throughput_mbps": df_ue["throughput_agregado_mbps"].iloc[0],
                    "jain_vazao": df_ue["jain_vazao"].iloc[0],
                })

    dados = pd.DataFrame(linhas)
    dados_path = OUTPUT_DIR / "matriz_pilar3_reduzida.csv"
    dados.to_csv(dados_path, index=False)
    print(f"\n[pilar3] Matriz completa salva em: {dados_path}")
    return dados


# ------------------------------------------------------------
# Etapa 2 — Pareto por combinação (dispositivos × nível de sinal)
# ------------------------------------------------------------
def eh_dominado(ponto, outros_pontos):
    """Mesma definição usada em pilar1_2_prototipo.py: um ponto
    (T, J) é dominado se existe outro ponto igual ou melhor nos
    dois eixos, e estritamente melhor em pelo menos um."""
    t, j = ponto
    for outro_t, outro_j in outros_pontos:
        if (outro_t, outro_j) == (t, j):
            continue
        melhor_ou_igual = outro_t >= t and outro_j >= j
        estritamente_melhor = outro_t > t or outro_j > j
        if melhor_ou_igual and estritamente_melhor:
            return True
    return False


def marcar_pareto_por_combinacao(dados: pd.DataFrame) -> pd.DataFrame:
    linhas_marcadas = []

    for (dispositivos, nivel), grupo in dados.groupby(["dispositivos", "nivel_sinal"]):
        pontos = list(zip(grupo["throughput_mbps"], grupo["jain_vazao"]))

        for _, row in grupo.iterrows():
            ponto = (row["throughput_mbps"], row["jain_vazao"])
            dominado = eh_dominado(ponto, pontos)
            linha = row.to_dict()
            linha["pareto_nao_dominado"] = not dominado
            linhas_marcadas.append(linha)

    return pd.DataFrame(linhas_marcadas)


def calcular_ranking(dados_marcados: pd.DataFrame) -> pd.DataFrame:
    total_combinacoes = dados_marcados.groupby(["dispositivos", "nivel_sinal"]).ngroups

    ranking = (
        dados_marcados[dados_marcados["pareto_nao_dominado"]]
        .groupby("scheduler")
        .size()
        .rename("aparicoes_na_fronteira")
        .reindex(SCHEDULERS, fill_value=0)
        .reset_index()
    )
    ranking["pct_das_combinacoes"] = (
        ranking["aparicoes_na_fronteira"] / total_combinacoes * 100
    ).round(1)
    return ranking.sort_values("pct_das_combinacoes", ascending=False)


# ------------------------------------------------------------
# main
# ------------------------------------------------------------
def main():
    dados = coletar_matriz()

    if dados.empty:
        print("[pilar3] Nenhum dado coletado — verifique os erros acima.")
        raise SystemExit(1)

    print("\n" + "=" * 70)
    print("MATRIZ COMPLETA (Pilar 3 reduzido)")
    print("=" * 70)
    print(dados.to_string(index=False))

    dados_marcados = marcar_pareto_por_combinacao(dados)
    marcados_path = OUTPUT_DIR / "matriz_pilar3_com_pareto.csv"
    dados_marcados.to_csv(marcados_path, index=False)

    print("\n" + "=" * 70)
    print("RANKING — aparições na fronteira de Pareto por combinação")
    print("=" * 70)
    ranking = calcular_ranking(dados_marcados)
    print(ranking.to_string(index=False))
    ranking_path = OUTPUT_DIR / "ranking_pilar3.csv"
    ranking.to_csv(ranking_path, index=False)

    print(f"\n[pilar3] Dados com marcação de Pareto: {marcados_path}")
    print(f"[pilar3] Ranking: {ranking_path}")
    print("\nEscopo desta prova de conceito: 10/50 dispositivos × moderado/degradado "
          "× RR/PF/MR. Para expandir até a defesa: adicionar 100 dispositivos, mais "
          "níveis de degradação, e o FMR.")


if __name__ == "__main__":
    main()