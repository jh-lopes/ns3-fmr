#!/usr/bin/env python3
"""Configurações de estilo para geração de gráficos da Bateria 3."""

import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# ============================================================================
# CONFIGURAÇÕES GLOBAIS
# ============================================================================

# Tema e estilo
PLT_STYLE = "seaborn-v0_8-darkgrid"  # Estilo padrão
FIGURE_DPI = 300
FIGURE_FIGSIZE = (12, 8)

# Cores para schedulers
SCHEDULER_COLORS = {
    "rr": "#2E86C1",      # Azul
    "pf": "#28B463",      # Verde
    "mr": "#E74C3C",      # Vermelho
    "qos": "#8E44AD"      # Roxo
}

SCHEDULER_MARKERS = {
    "rr": "o",
    "pf": "s",
    "mr": "^",
    "qos": "D"
}

SCHEDULER_LABELS = {
    "rr": "Round Robin",
    "pf": "Proportional Fair",
    "mr": "Max Rate",
    "qos": "QoS"
}

# Cores para fronteira de Pareto
PARETO_COLOR = "#F39C12"      # Laranja
NASH_COLOR = "#E74C3C"        # Vermelho

# Paleta de cores para heatmaps
HEATMAP_CMAP = "viridis"
HEATMAP_CMAP_DIVERGING = "RdBu_r"

# ============================================================================
# FUNÇÕES DE CONFIGURAÇÃO
# ============================================================================

def setup_style() -> None:
    """Configura estilo global para todos os gráficos."""
    try:
        plt.style.use(PLT_STYLE)
    except OSError:
        plt.style.use("seaborn-v0_8")
    
    # Configurações do seaborn
    sns.set_context("paper", font_scale=1.2)
    sns.set_palette("Set2")
    
    # Configurações do matplotlib
    plt.rcParams['figure.dpi'] = FIGURE_DPI
    plt.rcParams['savefig.dpi'] = FIGURE_DPI
    plt.rcParams['figure.figsize'] = FIGURE_FIGSIZE
    plt.rcParams['font.size'] = 11
    plt.rcParams['axes.labelsize'] = 12
    plt.rcParams['axes.titlesize'] = 14
    plt.rcParams['legend.fontsize'] = 11
    plt.rcParams['xtick.labelsize'] = 10
    plt.rcParams['ytick.labelsize'] = 10
    plt.rcParams['lines.linewidth'] = 2
    plt.rcParams['lines.markersize'] = 8
    plt.rcParams['figure.autolayout'] = True


def create_output_dirs(base_dir: Path) -> dict:
    """Cria estrutura de diretórios para os gráficos."""
    dirs = {
        "root": base_dir,
        "classica": base_dir / "01_analise_classica",
        "avancada": base_dir / "02_analise_avancada",
        "animacoes": base_dir / "02_analise_avancada" / "animacoes"
    }
    
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    
    return dirs


def get_scheduler_color(scheduler: str) -> str:
    """Retorna a cor de um scheduler."""
    return SCHEDULER_COLORS.get(scheduler, "#808080")  # Cinza se não encontrado


def get_scheduler_label(scheduler: str) -> str:
    """Retorna o label amigável de um scheduler."""
    return SCHEDULER_LABELS.get(scheduler, scheduler)


# ============================================================================
# FUNÇÕES AUXILIARES DE PLOTAGEM
# ============================================================================

def add_pareto_frontier(ax, pareto_points: list, label: str = "Fronteira de Pareto",
                        color: str = PARETO_COLOR) -> None:
    """Adiciona a fronteira de Pareto a um gráfico."""
    if pareto_points and len(pareto_points) > 1:
        # Ordena por throughput (x)
        sorted_points = sorted(pareto_points, key=lambda p: p[0])
        x_vals, y_vals = zip(*sorted_points)
        ax.plot(x_vals, y_vals, '--', linewidth=2.5, color=color, 
                label=label, zorder=10)


def add_nash_point(ax, nash_point: tuple, label: str = "Solução de Nash",
                   color: str = NASH_COLOR) -> None:
    """Adiciona o ponto de Nash a um gráfico."""
    if nash_point:
        ax.scatter(nash_point[0], nash_point[1], s=200, color=color,
                   marker='*', edgecolors='white', linewidth=1.5,
                   label=label, zorder=15)


def compute_pareto_frontier(x: list, y: list) -> list:
    """
    Calcula a fronteira de Pareto para maximização de x e y.
    Retorna lista de pontos (x, y) na fronteira.
    """
    if len(x) != len(y) or len(x) == 0:
        return []
    
    # Pontos repetidos não acrescentam informação à fronteira e podem
    # produzir linhas e legendas sobrepostas.
    points = sorted(set(zip(x, y)))
    pareto = []
    
    for i, (xi, yi) in enumerate(points):
        dominated = False
        for j, (xj, yj) in enumerate(points):
            if i != j and xj >= xi and yj >= yi and (xj > xi or yj > yi):
                dominated = True
                break
        if not dominated:
            pareto.append((xi, yi))
    
    return sorted(pareto, key=lambda p: p[0])


def compute_nash_point(pareto_points: list) -> tuple:
    """
    Calcula a solução de Nash para a fronteira de Pareto.
    Maximiza o produto (T * J) normalizado.
    """
    if not pareto_points:
        return None

    pareto_points = sorted(set(pareto_points))
    
    # Normaliza os valores
    t_vals = [p[0] for p in pareto_points]
    j_vals = [p[1] for p in pareto_points]
    
    t_min, t_max = min(t_vals), max(t_vals)
    j_min, j_max = min(j_vals), max(j_vals)
    
    # Sem variação em uma das métricas não há barganha bidimensional. O
    # desempate preserva primeiro a maior justiça e depois a maior vazão.
    if t_max == t_min or j_max == j_min:
        return max(pareto_points, key=lambda p: (p[1], p[0]))
    
    nash_scores = []
    for t, j in pareto_points:
        t_norm = (t - t_min) / (t_max - t_min)
        j_norm = (j - j_min) / (j_max - j_min)
        nash_scores.append((t_norm * j_norm, j, t, (t, j)))
    
    if nash_scores:
        # Em caso de empate, escolhe maior Jain e depois maior vazão.
        return max(nash_scores, key=lambda x: (x[0], x[1], x[2]))[3]
    
    return pareto_points[-1]