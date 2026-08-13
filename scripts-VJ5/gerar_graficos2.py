#!/usr/bin/env python3
# ============================================================
# gerar_graficos.py
#
# Gera os gráficos dos achados já calculados, lendo os CSVs
# que os scripts anteriores já salvaram em disco:
#
#   pesquisa/resultados/jain_rbg_vs_vazao/
#       jain_rbg_vs_vazao_por_janela.csv   (Achado 1 e 3, cenário
#                                            estático C3)
#       resumo_jain_rbg_vs_vazao.csv       (Achado 3, agregado)
#
#   pesquisa/resultados/pilar1_2_prototipo/
#       window_log_com_pareto.csv          (Pilar 1/2, com
#                                            mobilidade)
#       ranking_pilar2.csv                 (Pilar 2, ranking)
#       alfa_dinamico_por_janela.csv       (Pilar 1, vencedor
#                                            por janela)
#
#   pesquisa/resultados/pilar3_reduzido/
#       matriz_pilar3_com_pareto.csv       (Achado 8, matriz
#                                            10/50 dispositivos ×
#                                            sinal, com marcação
#                                            de dominância)
#       ranking_pilar3.csv                 (Achado 8, ranking)
#
# Nenhuma simulação é rodada aqui — só leitura dos CSVs que já
# existem (gerados por jain_rbg_vs_vazao.py, pilar1_2_prototipo.py
# e pilar3_reduzido.py). Se algum CSV não existir, o gráfico
# correspondente é pulado com um aviso (não interrompe os
# outros).
#
# Cobertura por achado (ver achados-pesquisa-vj5g.md no projeto
# Claude "Simulação Dissertação"):
#   Achado 1 → achado1_pareto_estatico.png
#   Achado 2 → achado2_starvation_mr.png (dados fixos — rodada
#              manual única já documentada, sem CSV próprio)
#   Achado 3 → achado3_agregado.png, achado3_por_janela.png
#   Achado 4 → NÃO gerado: é uma condição-limiar (fórmula), não
#              um conjunto de pontos comparáveis
#   Achado 5 → NÃO gerado: é um relato de bug (NS_ASSERT), não
#              dado de desempenho
#   Achado 6 → achado6_matriz_compatibilidade.png (dados fixos —
#              matriz ainda incompleta, "?" vira cinza no gráfico)
#   Achado 7 → NÃO gerado: é a tabela de definição dos cenários
#              C1-C4, não resultado de simulação
#   Achado 8 → achado8_matriz_barras.png,
#              achado8_fronteira_por_combinacao.png,
#              achado8_ranking.png
#   Pilar 1  → pilar1_vencedor_por_janela.png,
#              pilar1_trajetoria_mobilidade.png,
#              pilar1_fronteira_janelas_exemplo.png
#   Pilar 2  → pilar2_ranking.png
#
# Uso (assume que este arquivo está em ~/ns3-fmr/scripts-VJ5/):
#   cd ~/ns3-fmr/scripts-VJ5 && python3 gerar_graficos.py
#   -- ou, de qualquer diretório --
#   python3 ~/ns3-fmr/scripts-VJ5/gerar_graficos.py
#
# Saída: PNGs em ~/ns3-fmr/pesquisa/resultados/graficos/,
# independente de onde o comando acima foi chamado.
#
# Requer: pandas, matplotlib
#   pip install matplotlib --break-system-packages
# ============================================================

import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")  # sem display no servidor
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    import numpy as np
except ImportError as e:
    print(f"Dependência faltando: {e}")
    print("Instale com: pip install pandas matplotlib --break-system-packages")
    sys.exit(1)

# ------------------------------------------------------------
# Configuração
# ------------------------------------------------------------

# Raiz do repositório ns3-fmr, calculada a partir da localização
# deste script (assume scripts-VJ5/ um nível abaixo de ns3-fmr/).
NS3_ROOT = Path(__file__).resolve().parent.parent

DIR_JAIN_CMP = NS3_ROOT / "pesquisa/resultados/jain_rbg_vs_vazao"
DIR_PILAR12 = NS3_ROOT / "pesquisa/resultados/pilar1_2_prototipo"
DIR_PILAR3 = NS3_ROOT / "pesquisa/resultados/pilar3_reduzido"

# Cada execução do script grava numa subpasta própria, carimbada com
# data/hora, dentro de graficos/ — assim rodar de novo não sobrescreve
# nem mistura com PNGs de execuções anteriores.
DIR_GRAFICOS_BASE = NS3_ROOT / "pesquisa/resultados/graficos"
_CARIMBO_EXECUCAO = datetime.now().strftime("%Y-%m-%d_%H%Mh")
DIR_SAIDA = DIR_GRAFICOS_BASE / f"execucao_{_CARIMBO_EXECUCAO}"

SIGLAS = {"rr": "RR", "pf": "PF", "mr": "MR", "qos": "QoS", "fmr": "FMR"}

# Cores fixas por scheduler — consistentes em todos os gráficos
CORES = {
    "rr": "#4C72B0",
    "pf": "#DD8452",
    "mr": "#C44E52",
    "qos": "#55A868",
    "fmr": "#8172B2",
}
NOMES = {"rr": "Round Robin", "pf": "Proportional Fair", "mr": "Maximum Rate",
          "qos": "QoS", "fmr": "FMR"}


def cor(scheduler: str) -> str:
    return CORES.get(scheduler, "#777777")


def nome(scheduler: str) -> str:
    return NOMES.get(scheduler, scheduler.upper())


def avisar_arquivo_faltando(caminho: Path) -> None:
    print(f"[graficos] AVISO: {caminho} não encontrado — pulando gráfico "
          f"que depende dele. Rode o script correspondente primeiro.")


# ------------------------------------------------------------
# Achado 1 — Fronteira de Pareto (T x J), cenário C3 estático
# ------------------------------------------------------------
def grafico_achado1_pareto_estatico():
    caminho = DIR_JAIN_CMP / "jain_rbg_vs_vazao_por_janela.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho)

    fig, ax = plt.subplots(figsize=(8, 6))
    for scheduler, grupo in df.groupby("scheduler"):
        ax.scatter(
            grupo["aggregate_thr_mbps"], grupo["jain_throughput"],
            color=cor(scheduler), alpha=0.35, s=35, label=None,
        )
        media_t = grupo["aggregate_thr_mbps"].mean()
        media_j = grupo["jain_throughput"].mean()
        ax.scatter(
            [media_t], [media_j], color=cor(scheduler), s=260,
            edgecolor="black", linewidth=1.5, zorder=5,
            label=f"{nome(scheduler)} (média)",
        )
        ax.annotate(
            nome(scheduler), (media_t, media_j),
            textcoords="offset points", xytext=(10, 8), fontsize=10,
            fontweight="bold",
        )

    ax.set_xlabel("Throughput agregado (Mbps)")
    ax.set_ylabel("Jain sobre vazão")
    ax.set_title("Achado 1 — Tradeoff Vazão × Justiça (Cenário C3 estático, eMBB)\n"
                  "Pontos claros = janelas individuais · pontos grandes = média")
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    saida = DIR_SAIDA / "achado1_pareto_estatico.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Achado 3 — Jain-RBG vs Jain-vazão, agregado por scheduler
# ------------------------------------------------------------
def grafico_achado3_agregado():
    caminho = DIR_JAIN_CMP / "resumo_jain_rbg_vs_vazao.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho).set_index("scheduler")
    # ordena rr, pf, mr se existirem, mantém os demais no fim
    ordem_preferida = [s for s in ["rr", "pf", "mr"] if s in df.index]
    outros = [s for s in df.index if s not in ordem_preferida]
    df = df.loc[ordem_preferida + outros]

    x = range(len(df))
    largura = 0.35

    fig, ax = plt.subplots(figsize=(8, 6))
    barras_rbg = ax.bar(
        [i - largura / 2 for i in x], df["jain_rbg_medio"], largura,
        label="Jain sobre RBG (estilo Diego)", color="#8DA0CB",
    )
    barras_vazao = ax.bar(
        [i + largura / 2 for i in x], df["jain_vazao_medio"], largura,
        label="Jain sobre vazão (original)", color="#FC8D62",
    )

    for i, scheduler in enumerate(df.index):
        divergencia = df.loc[scheduler, "divergencia"]
        y_topo = max(df.loc[scheduler, "jain_rbg_medio"], df.loc[scheduler, "jain_vazao_medio"])
        ax.annotate(
            f"Δ={divergencia:+.3f}", (i, y_topo + 0.03),
            ha="center", fontsize=9, fontweight="bold",
        )

    ax.set_xticks(list(x))
    ax.set_xticklabels([nome(s) for s in df.index])
    ax.set_ylabel("Índice de Jain")
    ax.set_ylim(0, 1.15)
    ax.set_title("Achado 3 — Jain-RBG vs Jain-vazão por scheduler\n"
                  "(Cenário C3 estático, eMBB)", fontsize=12)
    fig.text(0.5, 0.01,
              "Δ = divergência (RBG − vazão): quanto maior, mais a métrica de RBG mascara a injustiça real",
              ha="center", fontsize=8.5, style="italic")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    saida = DIR_SAIDA / "achado3_agregado.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Achado 3 detalhado — evolução por janela
# ------------------------------------------------------------
def grafico_achado3_por_janela():
    caminho = DIR_JAIN_CMP / "jain_rbg_vs_vazao_por_janela.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho)
    schedulers = sorted(df["scheduler"].unique())

    fig, eixos = plt.subplots(len(schedulers), 1, figsize=(9, 3 * len(schedulers)), sharex=True)
    if len(schedulers) == 1:
        eixos = [eixos]

    for ax, scheduler in zip(eixos, schedulers):
        grupo = df[df["scheduler"] == scheduler].sort_values("window_id")
        ax.plot(grupo["window_id"], grupo["jain_rbg"], color="#8DA0CB",
                 marker="o", markersize=3, label="Jain-RBG")
        ax.plot(grupo["window_id"], grupo["jain_throughput"], color="#FC8D62",
                 marker="o", markersize=3, label="Jain-vazão")
        ax.set_title(nome(scheduler), fontsize=10, fontweight="bold", loc="left")
        ax.set_ylabel("Jain")
        ax.set_ylim(0, 1.05)
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=8)

    eixos[-1].set_xlabel("Janela (100ms cada)")
    fig.suptitle("Achado 3 detalhado — Jain-RBG vs Jain-vazão janela a janela (C3 estático, eMBB)",
                  fontsize=12, y=1.0)
    fig.tight_layout()

    saida = DIR_SAIDA / "achado3_por_janela.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Pilar 1 — vencedor do critério de Nash por janela (mobilidade)
#
# O painel de cima é uma FAIXA (não um gráfico de dispersão com
# categorias no eixo Y): cada fatia vertical é uma janela,
# colorida pelo scheduler que venceu o critério de Nash naquela
# janela. Evita o problema de esticar 1-2 categorias por uma
# altura de eixo grande (o que deixava um vão vazio enorme entre
# elas quando um scheduler — ex.: RR — nunca vence).
# ------------------------------------------------------------
def grafico_pilar1_vencedor_por_janela():
    caminho = DIR_PILAR12 / "alfa_dinamico_por_janela.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho).sort_values("window_id")
    vencedores_presentes = sorted(df["scheduler_vencedor"].unique())
    todos_schedulers = sorted(set(vencedores_presentes) | ({"rr", "pf", "mr"} & set(CORES)))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True,
                                     gridspec_kw={"height_ratios": [0.3, 1.4]})

    from matplotlib.colors import to_rgb
    faixa = np.array([to_rgb(cor(s)) for s in df["scheduler_vencedor"]]).reshape(1, -1, 3)
    w_min, w_max = df["window_id"].min(), df["window_id"].max()
    ax1.imshow(faixa, aspect="auto", extent=[w_min - 0.5, w_max + 0.5, 0, 1], interpolation="nearest")
    ax1.set_yticks([])

    itens_legenda = [Patch(facecolor=cor(s), label=nome(s)) for s in todos_schedulers]
    ax2.plot(df["window_id"], df["nash_score"], color="#555555", marker="o", markersize=3)
    ax2.set_xlabel("Janela (100ms cada)")
    ax2.set_ylabel("Score de Nash\n(do vencedor)")
    ax2.grid(alpha=0.3)

    titulo = ("Pilar 1 — Scheduler vencedor do critério de Nash por janela\n"
              "(cenário C3 com mobilidade, eMBB)")
    nunca_venceu = sorted(set(todos_schedulers) - set(vencedores_presentes))
    if nunca_venceu:
        titulo += (f"\n{', '.join(nome(s) for s in nunca_venceu)} nunca venceu nesta simulação "
                   "(vazão baixa demais mesmo penalizando o produto de Nash)")
    n_linhas_titulo = titulo.count("\n") + 1

    fig.subplots_adjust(top=0.99 - 0.05 * n_linhas_titulo - 0.08, hspace=0.35)
    fig.suptitle(titulo, fontsize=11, y=0.99)
    fig.legend(handles=itens_legenda, loc="upper center",
               bbox_to_anchor=(0.5, 0.99 - 0.05 * n_linhas_titulo),
               ncol=len(itens_legenda), fontsize=9, frameon=False)

    saida = DIR_SAIDA / "pilar1_vencedor_por_janela.png"
    fig.savefig(saida, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Pilar 2 — ranking por aparições na fronteira (mobilidade)
# ------------------------------------------------------------
def grafico_pilar2_ranking():
    caminho = DIR_PILAR12 / "ranking_pilar2.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho).sort_values("pct_das_janelas", ascending=True)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    cores_barras = [cor(s) for s in df["scheduler"]]
    barras = ax.barh(df["scheduler"].map(nome), df["pct_das_janelas"], color=cores_barras)

    for barra, valor in zip(barras, df["pct_das_janelas"]):
        ax.annotate(f"{valor:.1f}%", (barra.get_width() + 1, barra.get_y() + barra.get_height() / 2),
                     va="center", fontsize=10, fontweight="bold")

    ax.set_xlabel("% das janelas em que aparece na fronteira de Pareto")
    ax.set_xlim(0, 105)
    ax.set_title("Pilar 2 — Ranking de aparições na fronteira de Pareto\n"
                  "(cenário C3 com mobilidade, eMBB)")
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()

    saida = DIR_SAIDA / "pilar2_ranking.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Pilar 1 — nuvem geral T x J ao longo do tempo (mobilidade)
#
# IMPORTANTE: este gráfico é só uma visão geral de onde cada
# scheduler operou ao longo da simulação. Ele NÃO marca
# dominado/não-dominado, porque essa marcação foi calculada
# DENTRO DE CADA JANELA (só 3 pontos por vez — um por
# scheduler). Misturar pontos de janelas diferentes no mesmo
# plano e marcar dominância nele seria enganoso: um ponto
# "não-dominado" da janela 5 pode aparecer visualmente cercado
# por pontos de OUTRAS janelas que são melhores nos dois eixos,
# parecendo um erro quando não é. A fronteira de verdade, janela
# a janela, está no gráfico
# pilar1_fronteira_janelas_exemplo.png.
# ------------------------------------------------------------
def grafico_pilar1_trajetoria_mobilidade():
    caminho = DIR_PILAR12 / "window_log_com_pareto.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho)

    fig, ax = plt.subplots(figsize=(8, 6))
    for scheduler, grupo in df.groupby("scheduler"):
        grupo = grupo.sort_values("window_id")
        ax.scatter(grupo["aggregate_thr_mbps"], grupo["jain_throughput"],
                    color=cor(scheduler), alpha=0.55, s=35,
                    label=nome(scheduler), edgecolor="black", linewidth=0.3)

    ax.set_xlabel("Throughput agregado (Mbps)")
    ax.set_ylabel("Jain sobre vazão")
    ax.set_title("Pilar 1 — Visão geral: onde cada scheduler operou ao longo do\n"
                  "tempo (C3 com mobilidade, eMBB)", fontsize=12)
    fig.text(0.5, 0.01,
              "Visão geral, sem marcação de fronteira — dominância é local a cada "
              "janela (ver gráfico de janelas de exemplo)",
              ha="center", fontsize=8.5, style="italic")
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0.04, 1, 1])

    saida = DIR_SAIDA / "pilar1_trajetoria_mobilidade.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Pilar 1 — fronteira real, janela a janela, com o ponto ótimo
# de Nash destacado (pequenos múltiplos, estilo Slide 6/7 do
# SEMISH). Esta é a representação CORRETA da fronteira dinâmica:
# cada painel usa só os 3 pontos daquela janela específica, com
# a linha da fronteira e o vencedor de Nash marcados dentro do
# mesmo referencial local.
# ------------------------------------------------------------
def grafico_pilar1_fronteira_janelas_exemplo(n_janelas: int = 6):
    caminho_pareto = DIR_PILAR12 / "window_log_com_pareto.csv"
    caminho_alfa = DIR_PILAR12 / "alfa_dinamico_por_janela.csv"
    if not caminho_pareto.exists():
        avisar_arquivo_faltando(caminho_pareto)
        return
    if not caminho_alfa.exists():
        avisar_arquivo_faltando(caminho_alfa)
        return

    df = pd.read_csv(caminho_pareto)
    alfa = pd.read_csv(caminho_alfa)

    janelas_disponiveis = sorted(df["window_id"].unique())

    # Prioriza janelas onde o vencedor de Nash foge do padrão
    # majoritário — são as mais interessantes de mostrar, porque
    # evidenciam que a fronteira realmente se move com o canal.
    vencedor_majoritario = alfa["scheduler_vencedor"].mode().iloc[0]
    janelas_atipicas = alfa[alfa["scheduler_vencedor"] != vencedor_majoritario]["window_id"].tolist()

    escolhidas = list(dict.fromkeys(janelas_atipicas))[: n_janelas // 2]
    restantes = [w for w in janelas_disponiveis if w not in escolhidas]
    passo = max(1, len(restantes) // (n_janelas - len(escolhidas)))
    escolhidas += restantes[::passo][: n_janelas - len(escolhidas)]
    escolhidas = sorted(set(escolhidas))[:n_janelas]

    n_col = 3
    n_lin = -(-len(escolhidas) // n_col)  # arredonda pra cima
    fig, eixos = plt.subplots(n_lin, n_col, figsize=(4.6 * n_col, 4.3 * n_lin))
    eixos = eixos.flatten() if len(escolhidas) > 1 else [eixos]

    for ax, window_id in zip(eixos, escolhidas):
        grupo = df[df["window_id"] == window_id].copy()
        nao_dominados = grupo[grupo["pareto_nao_dominado"]].sort_values("aggregate_thr_mbps")
        dominados = grupo[~grupo["pareto_nao_dominado"]]

        # Vencedor de Nash desta janela — desenhado primeiro, como um
        # "halo" dourado atrás do ponto (não substitui o ponto, só o
        # destaca), pra não esconder de qual scheduler é o ponto.
        vencedor = alfa[alfa["window_id"] == window_id]
        if not vencedor.empty:
            v = vencedor.iloc[0]
            ax.scatter([v["throughput_mbps"]], [v["jain_throughput"]],
                        marker="o", s=420, facecolor="none",
                        edgecolor="gold", linewidth=3, zorder=3)

        # Pontos dominados: menores, discretos, sem contorno preto —
        # deixam claro que NÃO fazem parte da fronteira desta janela.
        for _, row in dominados.iterrows():
            ax.scatter(row["aggregate_thr_mbps"], row["jain_throughput"],
                        color=cor(row["scheduler"]), s=70, alpha=0.4,
                        edgecolor="none", zorder=4)
            ax.annotate(SIGLAS.get(row["scheduler"], row["scheduler"]),
                         (row["aggregate_thr_mbps"], row["jain_throughput"]),
                         textcoords="offset points", xytext=(6, -9), fontsize=7.5,
                         color="#666666")

        # Pontos na fronteira: cheios, com contorno preto.
        for _, row in nao_dominados.iterrows():
            ax.scatter(row["aggregate_thr_mbps"], row["jain_throughput"],
                        color=cor(row["scheduler"]), s=130,
                        edgecolor="black", linewidth=0.8, zorder=5)
            ax.annotate(SIGLAS.get(row["scheduler"], row["scheduler"]),
                         (row["aggregate_thr_mbps"], row["jain_throughput"]),
                         textcoords="offset points", xytext=(7, 6), fontsize=9,
                         fontweight="bold")

        if len(nao_dominados) >= 2:
            ax.plot(nao_dominados["aggregate_thr_mbps"], nao_dominados["jain_throughput"],
                     "--", color="#999900", linewidth=1.6, zorder=2)

        subtitulo = ""
        if not vencedor.empty:
            v = vencedor.iloc[0]
            subtitulo = f"\nÓtimo (Nash): {SIGLAS.get(v['scheduler_vencedor'], v['scheduler_vencedor'])}"
        ax.set_title(f"Janela {window_id} (t≈{window_id * 0.1 + 0.4:.1f}s){subtitulo}",
                      fontsize=9.5)
        ax.grid(alpha=0.3)
        ax.set_xlabel("T (Mbps)", fontsize=8.5)
        ax.set_ylabel("J", fontsize=8.5)
        ax.tick_params(labelsize=8)
        margem_x = (grupo["aggregate_thr_mbps"].max() - grupo["aggregate_thr_mbps"].min()) * 0.18 + 1
        margem_y = (grupo["jain_throughput"].max() - grupo["jain_throughput"].min()) * 0.18 + 0.02
        ax.set_xlim(grupo["aggregate_thr_mbps"].min() - margem_x, grupo["aggregate_thr_mbps"].max() + margem_x)
        ax.set_ylim(grupo["jain_throughput"].min() - margem_y, grupo["jain_throughput"].max() + margem_y)

    for ax in eixos[len(escolhidas):]:
        ax.axis("off")

    # Legenda única, no nível da figura — evita repetir/esconder em
    # um subplot só.
    itens_legenda = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#888888",
               markeredgecolor="black", markersize=10, label="Ponto na fronteira (não-dominado)"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#888888", alpha=0.4,
               markeredgecolor="none", markersize=9, label="Ponto dominado (fora da fronteira)"),
        Line2D([0], [0], linestyle="--", color="#999900", linewidth=1.6, label="Fronteira de Pareto local"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none",
               markeredgecolor="gold", markeredgewidth=2.5, markersize=13, label="Vencedor do critério de Nash"),
    ]
    fig.legend(handles=itens_legenda, loc="upper center", ncol=2, fontsize=9,
               bbox_to_anchor=(0.5, 0.965))
    fig.suptitle("Pilar 1 — Fronteira de Pareto e ponto ótimo (Nash) por janela\n"
                  "(cenário C3 com mobilidade, eMBB — amostra de janelas)",
                  fontsize=12, y=1.04)
    fig.tight_layout(rect=[0, 0, 1, 0.86])

    saida = DIR_SAIDA / "pilar1_fronteira_janelas_exemplo.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Achado 2 — starvation do MR, detalhe por UE (C3, 3 UEs)
#
# Dados fixos: rodada manual única já documentada em
# achados-pesquisa-vj5g.md (não existe CSV próprio dela — foi um
# teste pontual anterior aos scripts de scripts-VJ5/). Mantidos
# aqui como constantes, não lidos de arquivo.
# ------------------------------------------------------------
ACHADO2_DADOS_MR = [
    {"ue": "UE0", "distancia_m": 25, "sinr_db": 69, "throughput_mbps": 24.36, "pdr_pct": 99.7},
    {"ue": "UE1", "distancia_m": 256, "sinr_db": -13, "throughput_mbps": 0.50, "pdr_pct": 2.1},
    {"ue": "UE2", "distancia_m": 500, "sinr_db": -20, "throughput_mbps": 0.00, "pdr_pct": 0.0},
]


def grafico_achado2_starvation_mr():
    df = pd.DataFrame(ACHADO2_DADOS_MR)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    barras1 = ax1.bar(df["ue"], df["throughput_mbps"], color=cor("mr"), edgecolor="black", linewidth=0.6)
    for barra, valor in zip(barras1, df["throughput_mbps"]):
        ax1.annotate(f"{valor:.2f}", (barra.get_x() + barra.get_width() / 2, valor + 0.5),
                      ha="center", fontsize=9, fontweight="bold")
    ax1.set_ylabel("Throughput (Mbps)")
    ax1.set_title("Vazão por UE", fontsize=11)
    ax1.grid(alpha=0.3, axis="y")

    barras2 = ax2.bar(df["ue"], df["pdr_pct"], color=cor("mr"), edgecolor="black", linewidth=0.6)
    for barra, valor in zip(barras2, df["pdr_pct"]):
        ax2.annotate(f"{valor:.1f}%", (barra.get_x() + barra.get_width() / 2, valor + 1.5),
                      ha="center", fontsize=9, fontweight="bold")
    ax2.set_ylabel("PDR — pacotes entregues (%)")
    ax2.set_ylim(0, 108)
    ax2.set_title("Taxa de entrega por UE", fontsize=11)
    ax2.grid(alpha=0.3, axis="y")

    for ax, df_ in [(ax1, df), (ax2, df)]:
        for i, row in df_.iterrows():
            ax.annotate(f"{row['distancia_m']}m, SINR={row['sinr_db']}dB",
                         (i, 0), textcoords="offset points", xytext=(0, -22),
                         ha="center", fontsize=7.5, color="#666666")

    fig.suptitle("Achado 2 — Starvation do Maximum Rate (cenário C3, 3 UEs, eMBB)",
                  fontsize=12.5)
    fig.text(0.5, 0.01,
              "UE2 (500m, SINR=-20dB) recebe 0 Mbps — starvation total, não aproximação",
              ha="center", fontsize=9, style="italic", color="#9C1F1F")
    fig.tight_layout(rect=[0, 0.08, 1, 0.90])

    saida = DIR_SAIDA / "achado2_starvation_mr.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Achado 6 — matriz de compatibilidade (bug PHY, múltiplos
# bearers). Dados fixos: tabela parcialmente preenchida em
# achados-pesquisa-vj5g.md — "?" (não testado) vira cinza aqui,
# não é tratado como falha nem sucesso.
# ------------------------------------------------------------
ACHADO6_STATUS = {
    3: {"rr": "ok", "pf": "ok", "mr": "ok", "qos": "ok"},
    5: {"rr": "ok", "pf": "?", "mr": "?", "qos": "?"},
    6: {"rr": "ok", "pf": "?", "mr": "?", "qos": "?"},
    7: {"rr": "?", "pf": "?", "mr": "?", "qos": "?"},
    8: {"rr": "?", "pf": "?", "mr": "?", "qos": "?"},
    9: {"rr": "ok", "pf": "falha", "mr": "falha", "qos": "falha"},
}


def grafico_achado6_matriz_compatibilidade():
    ues = sorted(ACHADO6_STATUS.keys())
    schedulers = ["rr", "pf", "mr", "qos"]

    cor_status = {"ok": "#4C9F4C", "falha": "#C44E52", "?": "#CCCCCC"}
    simbolo_status = {"ok": "OK", "falha": "FALHA", "?": "?"}

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for i, n_ues in enumerate(ues):
        for j, scheduler in enumerate(schedulers):
            status = ACHADO6_STATUS[n_ues].get(scheduler, "?")
            ax.add_patch(plt.Rectangle((j, len(ues) - 1 - i), 1, 1,
                                         facecolor=cor_status[status], edgecolor="white"))
            ax.text(j + 0.5, len(ues) - 1 - i + 0.5, simbolo_status[status],
                     ha="center", va="center", fontsize=8.5, fontweight="bold",
                     color="white" if status != "?" else "#555555")

    ax.set_xlim(0, len(schedulers))
    ax.set_ylim(0, len(ues))
    ax.set_xticks([j + 0.5 for j in range(len(schedulers))])
    ax.set_xticklabels([nome(s) for s in schedulers], fontsize=9)
    ax.set_yticks([len(ues) - 1 - i + 0.5 for i in range(len(ues))])
    ax.set_yticklabels([f"{n} UEs" for n in ues], fontsize=9)
    ax.set_title("Achado 6 — Matriz de compatibilidade\n"
                  "(bug PHY com múltiplos bearers simultâneos, eMBB)", fontsize=11)
    fig.text(0.5, 0.01,
              "Cinza = ainda não testado, não é \"funciona\"; falta completar com "
              "teste_completo_vj5g.sh",
              ha="center", fontsize=8, style="italic")
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    saida = DIR_SAIDA / "achado6_matriz_compatibilidade.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# Achado 8 — matriz do Pilar 3 reduzido (10/50 dispositivos ×
# sinal moderado/degradado × RR/PF/MR)
# ------------------------------------------------------------
def grafico_achado8_matriz_barras():
    caminho = DIR_PILAR3 / "matriz_pilar3_com_pareto.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho)
    combinacoes = sorted(df[["dispositivos", "nivel_sinal"]].drop_duplicates()
                          .itertuples(index=False, name=None),
                          key=lambda c: (c[0], c[1] != "moderado"))
    rotulos = [f"{d} disp.\n{n}" for d, n in combinacoes]
    schedulers = ["rr", "pf", "mr"]
    largura = 0.25
    x = np.arange(len(combinacoes))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7.5), sharex=True)

    for i, scheduler in enumerate(schedulers):
        valores_t, valores_j = [], []
        for disp, nivel in combinacoes:
            linha = df[(df["dispositivos"] == disp) & (df["nivel_sinal"] == nivel)
                       & (df["scheduler"] == scheduler)]
            valores_t.append(linha["throughput_mbps"].iloc[0] if not linha.empty else 0)
            valores_j.append(linha["jain_vazao"].iloc[0] if not linha.empty else 0)
        deslocamento = (i - 1) * largura
        ax1.bar(x + deslocamento, valores_t, largura, color=cor(scheduler), label=nome(scheduler))
        ax2.bar(x + deslocamento, valores_j, largura, color=cor(scheduler), label=nome(scheduler))

    ax1.set_ylabel("Throughput (Mbps)")
    ax1.set_title("Throughput por combinação", fontsize=10.5)
    ax1.grid(alpha=0.3, axis="y")
    ax1.legend(fontsize=8.5, loc="upper left")

    ax2.set_ylabel("Jain sobre vazão")
    ax2.set_title("Justiça por combinação", fontsize=10.5)
    ax2.set_ylim(0, 1.05)
    ax2.grid(alpha=0.3, axis="y")
    ax2.set_xticks(x)
    ax2.set_xticklabels(rotulos, fontsize=9)

    fig.suptitle("Achado 8 — Matriz do Pilar 3 (reduzida): throughput e justiça\n"
                  "por dispositivos × degradação de sinal × scheduler", fontsize=12)
    fig.subplots_adjust(top=0.88, hspace=0.28)

    saida = DIR_SAIDA / "achado8_matriz_barras.png"
    fig.savefig(saida, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


def grafico_achado8_fronteira_por_combinacao():
    caminho = DIR_PILAR3 / "matriz_pilar3_com_pareto.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho)
    combinacoes = sorted(df[["dispositivos", "nivel_sinal"]].drop_duplicates()
                          .itertuples(index=False, name=None),
                          key=lambda c: (c[0], c[1] != "moderado"))

    fig, eixos = plt.subplots(1, len(combinacoes), figsize=(4.3 * len(combinacoes), 4.3))
    if len(combinacoes) == 1:
        eixos = [eixos]

    for ax, (disp, nivel) in zip(eixos, combinacoes):
        grupo = df[(df["dispositivos"] == disp) & (df["nivel_sinal"] == nivel)]
        nao_dominados = grupo[grupo["pareto_nao_dominado"]].sort_values("throughput_mbps")
        dominados = grupo[~grupo["pareto_nao_dominado"]]

        for _, row in dominados.iterrows():
            ax.scatter(row["throughput_mbps"], row["jain_vazao"], color=cor(row["scheduler"]),
                        s=70, alpha=0.4, edgecolor="none", zorder=4)
            ax.annotate(SIGLAS.get(row["scheduler"], row["scheduler"]),
                         (row["throughput_mbps"], row["jain_vazao"]),
                         textcoords="offset points", xytext=(6, -9), fontsize=7.5, color="#666666")

        for _, row in nao_dominados.iterrows():
            ax.scatter(row["throughput_mbps"], row["jain_vazao"], color=cor(row["scheduler"]),
                        s=130, edgecolor="black", linewidth=0.8, zorder=5)
            ax.annotate(SIGLAS.get(row["scheduler"], row["scheduler"]),
                         (row["throughput_mbps"], row["jain_vazao"]),
                         textcoords="offset points", xytext=(7, 6), fontsize=9, fontweight="bold")

        if len(nao_dominados) >= 2:
            ax.plot(nao_dominados["throughput_mbps"], nao_dominados["jain_vazao"],
                     "--", color="#999900", linewidth=1.6, zorder=2)

        ax.set_title(f"{disp} dispositivos — {nivel}", fontsize=10.5)
        ax.set_xlabel("T (Mbps)", fontsize=9)
        ax.set_ylabel("J", fontsize=9)
        ax.grid(alpha=0.3)

    itens_legenda = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#888888",
               markeredgecolor="black", markersize=10, label="Não-dominado (fronteira)"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#888888", alpha=0.4,
               markeredgecolor="none", markersize=9, label="Dominado"),
        Line2D([0], [0], linestyle="--", color="#999900", linewidth=1.6, label="Fronteira de Pareto"),
    ]
    fig.legend(handles=itens_legenda, loc="upper center", ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, 1.06))
    fig.suptitle("Achado 8 — Fronteira de Pareto por combinação (RR/PF/MR, eMBB)",
                  fontsize=12, y=1.18)
    fig.tight_layout(rect=[0, 0, 1, 0.82])

    saida = DIR_SAIDA / "achado8_fronteira_por_combinacao.png"
    fig.savefig(saida, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


def grafico_achado8_ranking():
    caminho = DIR_PILAR3 / "ranking_pilar3.csv"
    if not caminho.exists():
        avisar_arquivo_faltando(caminho)
        return

    df = pd.read_csv(caminho).sort_values("pct_das_combinacoes", ascending=True)

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    cores_barras = [cor(s) for s in df["scheduler"]]
    barras = ax.barh(df["scheduler"].map(nome), df["pct_das_combinacoes"], color=cores_barras)

    for barra, valor in zip(barras, df["pct_das_combinacoes"]):
        ax.annotate(f"{valor:.0f}%", (barra.get_width() + 2, barra.get_y() + barra.get_height() / 2),
                     va="center", fontsize=10, fontweight="bold")

    ax.set_xlabel("% das combinações (dispositivos × sinal) em que aparece na fronteira")
    ax.set_xlim(0, 112)
    ax.set_title("Achado 8 — Ranking de aparições na fronteira\n(matriz reduzida do Pilar 3)")
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()

    saida = DIR_SAIDA / "achado8_ranking.png"
    fig.savefig(saida, dpi=150)
    plt.close(fig)
    print(f"[graficos] Salvo: {saida}")


# ------------------------------------------------------------
# main
# ------------------------------------------------------------
def main():
    DIR_SAIDA.mkdir(parents=True, exist_ok=True)

    print("[graficos] Gerando gráficos a partir dos CSVs já salvos em disco...")
    print(f"[graficos] Saída desta execução: {DIR_SAIDA}/")
    print(f"[graficos] (execuções anteriores continuam em outras subpastas de {DIR_GRAFICOS_BASE}/)\n")

    grafico_achado1_pareto_estatico()
    grafico_achado2_starvation_mr()
    grafico_achado3_agregado()
    grafico_achado3_por_janela()
    grafico_achado6_matriz_compatibilidade()
    grafico_pilar1_vencedor_por_janela()
    grafico_pilar2_ranking()
    grafico_pilar1_trajetoria_mobilidade()
    grafico_pilar1_fronteira_janelas_exemplo()
    grafico_achado8_matriz_barras()
    grafico_achado8_fronteira_por_combinacao()
    grafico_achado8_ranking()

    print("\n[graficos] Achados 4, 5 e 7 não geram gráfico de propósito — são condição-limiar, "
          "relato de bug, e tabela de definição de cenário, respectivamente (não dados "
          "comparáveis). Ver cabeçalho deste arquivo.")
    print(f"\n[graficos] Concluído. Veja os PNGs em: {DIR_SAIDA}/")


if __name__ == "__main__":
    main()