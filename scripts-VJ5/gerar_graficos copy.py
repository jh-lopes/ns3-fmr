"""Geração de gráficos para análise da Bateria 3 - SOLUÇÃO DEFINITIVA.

Este script processa APENAS dados reais do executions.csv.
NUNCA gera dados sintéticos.
Uso: python3 scripts-VJ5/gerar_graficos.py --input pesquisa/resultados/teste_rapido
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from matplotlib.patches import Ellipse
from matplotlib.lines import Line2D
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
import seaborn as sns

# Importa configurações
from config_graficos import (
    setup_style, create_output_dirs, get_scheduler_color,
    get_scheduler_label, add_pareto_frontier, add_nash_point,
    compute_pareto_frontier, compute_nash_point,
    SCHEDULER_LABELS
)

# ============================================================================
# FUNÇÕES DE CARREGAMENTO - SEM DADOS SINTÉTICOS
# ============================================================================

def load_data(input_path: Path) -> pd.DataFrame:
    """Carrega APENAS dados reais do executions.csv."""
    csv_path = Path(input_path) / "executions.csv"
    
    if not csv_path.exists():
        print(f"❌ ERRO CRÍTICO: Arquivo não encontrado: {csv_path}")
        print(f"   Caminho atual: {input_path.resolve()}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(csv_path)
        print(f"✅ Arquivo encontrado: {csv_path}")
        print(f"   Registros brutos: {len(df)}")
        
        # Verifica colunas necessárias
        required_cols = ['scheduler', 'status', 'throughput_mbps', 'jain']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            print(f"❌ Colunas faltando: {missing}")
            print(f"   Colunas disponíveis: {list(df.columns)}")
            return pd.DataFrame()
        
        # Filtra apenas OK
        df_ok = df[df['status'] == 'OK'].copy()
        print(f"   Registros OK: {len(df_ok)}")
        
        if len(df_ok) == 0:
            print(f"❌ Nenhum registro com status 'OK'")
            print(f"   Status disponíveis: {df['status'].unique().tolist()}")
            return pd.DataFrame()
        
        # Converte para numérico
        df_ok['throughput_mbps'] = pd.to_numeric(df_ok['throughput_mbps'], errors='coerce')
        df_ok['jain'] = pd.to_numeric(df_ok['jain'], errors='coerce')
        
        # Remove NaN
        df_ok = df_ok.dropna(subset=['throughput_mbps', 'jain'])
        
        if len(df_ok) == 0:
            print(f"❌ Todos os valores de throughput/jain são NaN")
            return pd.DataFrame()
        
        # Converte outras colunas úteis
        for col in ['window_throughput_mean_mbps', 'window_jain_mean', 'rng_run', 'radius_m']:
            if col in df_ok.columns:
                df_ok[col] = pd.to_numeric(df_ok[col], errors='coerce')
        
        print(f"   Registros válidos: {len(df_ok)}")
        print(f"   Schedulers: {df_ok['scheduler'].unique().tolist()}")
        print(f"   Throughput: {df_ok['throughput_mbps'].min():.2f} - {df_ok['throughput_mbps'].max():.2f} Mbps")
        print(f"   Jain: {df_ok['jain'].min():.3f} - {df_ok['jain'].max():.3f}")

        invalid_jain = ~df_ok['jain'].between(0, 1)
        if invalid_jain.any():
            print(f"❌ {invalid_jain.sum()} valores de Jain estão fora de [0, 1]")
            return pd.DataFrame()

        print("\n📋 Diagnóstico por escalonador")
        summary = df_ok.groupby('scheduler').agg(
            n=('throughput_mbps', 'size'),
            t_mean=('throughput_mbps', 'mean'),
            t_std=('throughput_mbps', 'std'),
            t_unique=('throughput_mbps', 'nunique'),
            j_mean=('jain', 'mean'),
            j_std=('jain', 'std'),
            j_unique=('jain', 'nunique'),
        ).fillna(0)
        print(summary.to_string(float_format=lambda value: f"{value:.6f}"))

        if len(df_ok) < 12:
            print("⚠️ Poucas observações. Use pelo menos 30 runs por escalonador para apresentação.")
        if df_ok['throughput_mbps'].nunique() == 1:
            print("⚠️ Vazão constante. Boxplot, violino, KDE e covariância não são estimáveis.")
        if df_ok['jain'].nunique() == 1:
            print("⚠️ Jain constante. Não há compromisso vazão-justiça observável.")
        
        return df_ok
        
    except Exception as e:
        print(f"❌ ERRO ao ler o arquivo: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def has_variation(series: pd.Series, epsilon: float = 1e-9) -> bool:
    values = pd.to_numeric(series, errors='coerce').dropna()
    return len(values) >= 2 and values.nunique() >= 2 and values.std() > epsilon


def annotate_no_variation(ax, metric: str) -> None:
    ax.text(
        0.5, 0.08,
        f"Sem variação observada em {metric}",
        transform=ax.transAxes, ha='center', va='bottom',
        fontsize=10, color='#A93226',
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.9)
    )

# ============================================================================
# GRÁFICOS - ANÁLISE CLÁSSICA
# ============================================================================

def plot_dispersao_pareto(df: pd.DataFrame, output_dir: Path) -> bool:
    """Gráfico de dispersão com fronteira de Pareto."""
    try:
        fig, ax = plt.subplots(figsize=(12, 9))
        
        schedulers = df['scheduler'].unique()
        all_points = []
        
        for scheduler in schedulers:
            data = df[df['scheduler'] == scheduler]
            color = get_scheduler_color(scheduler)
            label = get_scheduler_label(scheduler)
            
            ax.scatter(data['throughput_mbps'], data['jain'],
                       c=color, label=label, alpha=0.6, s=40,
                       edgecolors='black', linewidth=1)
            
            all_points.extend(list(zip(data['throughput_mbps'], data['jain'])))
        
        # Fronteira de Pareto
        if all_points:
            pareto = compute_pareto_frontier(
                [p[0] for p in all_points],
                [p[1] for p in all_points]
            )
            if pareto:
                px, py = zip(*pareto)
                ax.plot(px, py, '--', linewidth=2.5, color='#F39C12', 
                        label='Fronteira de Pareto', zorder=10)
                nash = compute_nash_point(pareto)
                add_nash_point(ax, nash)
        
        ax.set_xlabel('Vazão Agregada (Mbps)', fontsize=13)
        ax.set_ylabel('Índice de Jain', fontsize=13)
        ax.set_title(f'Fronteira de Pareto\n{len(df)} observações | {len(schedulers)} schedulers', 
                     fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best', fontsize=11)
        ax.set_ylim(0, 1.05)
        
        plt.tight_layout()
        plt.savefig(output_dir / 'dispersao_pareto.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ dispersao_pareto.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_boxplot_distribuicao(df: pd.DataFrame, output_dir: Path) -> bool:
    """Boxplot da distribuição por scheduler."""
    try:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        
        # Boxplot throughput
        order = df.groupby('scheduler')['throughput_mbps'].mean().sort_values(ascending=False).index
        colors = [get_scheduler_color(s) for s in order]
        
        sns.boxplot(data=df, x='scheduler', y='throughput_mbps', hue='scheduler',
                    order=order, palette=colors, legend=False, ax=axes[0])
        axes[0].set_title('Distribuição da Vazão Agregada', fontsize=13, fontweight='bold')
        axes[0].set_xlabel('Escalonador', fontsize=12)
        axes[0].set_ylabel('Vazão (Mbps)', fontsize=12)
        axes[0].grid(True, alpha=0.2)
        sns.stripplot(data=df, x='scheduler', y='throughput_mbps', order=order,
                      color='black', alpha=0.45, size=3, ax=axes[0])
        if not has_variation(df['throughput_mbps']):
            annotate_no_variation(axes[0], 'vazão')
        
        # Boxplot jain
        order_jain = df.groupby('scheduler')['jain'].mean().sort_values(ascending=False).index
        colors_jain = [get_scheduler_color(s) for s in order_jain]
        
        sns.boxplot(data=df, x='scheduler', y='jain', hue='scheduler',
                    order=order_jain, palette=colors_jain, legend=False, ax=axes[1])
        axes[1].set_title('Distribuição do Índice de Jain', fontsize=13, fontweight='bold')
        axes[1].set_xlabel('Escalonador', fontsize=12)
        axes[1].set_ylabel('Índice de Jain', fontsize=12)
        axes[1].set_ylim(0, 1.05)
        axes[1].grid(True, alpha=0.2)
        sns.stripplot(data=df, x='scheduler', y='jain', order=order_jain,
                      color='black', alpha=0.45, size=3, ax=axes[1])
        if not has_variation(df['jain']):
            annotate_no_variation(axes[1], 'Jain')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'boxplot_distribuicao.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ boxplot_distribuicao.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_violin_distribuicao(df: pd.DataFrame, output_dir: Path) -> bool:
    """Violin plot da distribuição por scheduler."""
    try:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        
        order = df.groupby('scheduler')['throughput_mbps'].mean().sort_values(ascending=False).index
        colors = [get_scheduler_color(s) for s in order]
        
        if has_variation(df['throughput_mbps']):
            sns.violinplot(data=df, x='scheduler', y='throughput_mbps', hue='scheduler',
                           order=order, palette=colors, legend=False,
                           cut=0, inner='quartile', ax=axes[0])
        sns.stripplot(data=df, x='scheduler', y='throughput_mbps', hue='scheduler',
                      order=order, palette=colors, legend=False,
                      alpha=0.65, size=4, ax=axes[0])
        axes[0].set_title('Distribuição da Vazão Agregada (Violin)', fontsize=13, fontweight='bold')
        axes[0].set_xlabel('Escalonador', fontsize=12)
        axes[0].set_ylabel('Vazão (Mbps)', fontsize=12)
        axes[0].grid(True, alpha=0.2)
        if not has_variation(df['throughput_mbps']):
            annotate_no_variation(axes[0], 'vazão')
        
        order_jain = df.groupby('scheduler')['jain'].mean().sort_values(ascending=False).index
        colors_jain = [get_scheduler_color(s) for s in order_jain]
        
        if has_variation(df['jain']):
            sns.violinplot(data=df, x='scheduler', y='jain', hue='scheduler',
                           order=order_jain, palette=colors_jain, legend=False,
                           cut=0, inner='quartile', ax=axes[1])
        sns.stripplot(data=df, x='scheduler', y='jain', hue='scheduler',
                      order=order_jain, palette=colors_jain, legend=False,
                      alpha=0.65, size=4, ax=axes[1])
        axes[1].set_title('Distribuição do Índice de Jain (Violin)', fontsize=13, fontweight='bold')
        axes[1].set_xlabel('Escalonador', fontsize=12)
        axes[1].set_ylabel('Índice de Jain', fontsize=12)
        axes[1].set_ylim(0, 1.05)
        axes[1].grid(True, alpha=0.2)
        if not has_variation(df['jain']):
            annotate_no_variation(axes[1], 'Jain')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'violin_distribuicao.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ violin_distribuicao.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_elipses_confianca(df: pd.DataFrame, output_dir: Path) -> bool:
    """Elipses de confiança (95%) para cada scheduler."""
    try:
        fig, ax = plt.subplots(figsize=(12, 9))
        
        for scheduler in df['scheduler'].unique():
            data = df[df['scheduler'] == scheduler]
            color = get_scheduler_color(scheduler)
            label = get_scheduler_label(scheduler)
            
            ax.scatter(data['throughput_mbps'], data['jain'],
                       c=color, label=label, alpha=0.3, s=30,
                       edgecolors='black', linewidth=0.5)
            
            if (len(data) >= 3
                    and has_variation(data['throughput_mbps'])
                    and has_variation(data['jain'])):
                cov = np.cov(data['throughput_mbps'], data['jain'])
                eigenvalues, eigenvectors = np.linalg.eigh(cov)
                if np.all(eigenvalues > 1e-12):
                    order = eigenvalues.argsort()[::-1]
                    eigenvalues = eigenvalues[order]
                    eigenvectors = eigenvectors[:, order]
                    mean = [data['throughput_mbps'].mean(), data['jain'].mean()]
                    angle = np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))
                    width, height = 2 * np.sqrt(5.991 * eigenvalues)
                    ellipse = Ellipse(xy=mean, width=width, height=height,
                                      angle=angle, alpha=0.2, color=color)
                    ax.add_patch(ellipse)
        
        ax.set_xlabel('Vazão Agregada (Mbps)', fontsize=13)
        ax.set_ylabel('Índice de Jain', fontsize=13)
        ax.set_title('Regiões de Confiança (95%)', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.2)
        ax.legend(loc='best')
        ax.set_ylim(0, 1.05)
        if not (has_variation(df['throughput_mbps']) and has_variation(df['jain'])):
            annotate_no_variation(ax, 'uma ou ambas as métricas')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'elipses_confianca.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ elipses_confianca.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_densidade_heatmap(df: pd.DataFrame, output_dir: Path) -> bool:
    """Heatmap de densidade + dispersão."""
    try:
        fig, ax = plt.subplots(figsize=(12, 9))
        
        if has_variation(df['throughput_mbps']) and has_variation(df['jain']):
            sns.kdeplot(data=df, x='throughput_mbps', y='jain',
                        levels=15, cmap='viridis', alpha=0.3, 
                        fill=True, ax=ax, thresh=0.05)
        else:
            annotate_no_variation(ax, 'uma ou ambas as métricas')
        
        for scheduler in df['scheduler'].unique():
            data = df[df['scheduler'] == scheduler]
            color = get_scheduler_color(scheduler)
            label = get_scheduler_label(scheduler)
            ax.scatter(data['throughput_mbps'], data['jain'],
                       c=color, label=label, alpha=0.4, s=20,
                       edgecolors='black', linewidth=0.5)
        
        ax.set_xlabel('Vazão Agregada (Mbps)', fontsize=13)
        ax.set_ylabel('Índice de Jain', fontsize=13)
        ax.set_title('Densidade de Pontos', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.2)
        ax.legend(loc='best')
        ax.set_ylim(0, 1.05)
        
        plt.tight_layout()
        plt.savefig(output_dir / 'densidade_heatmap.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ densidade_heatmap.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

# ============================================================================
# GRÁFICOS - ANÁLISE AVANÇADA
# ============================================================================

def plot_radar_metricas(df: pd.DataFrame, output_dir: Path) -> bool:
    """Diagrama de radar com múltiplas métricas."""
    try:
        from math import pi
        
        metrics = ['throughput_mbps', 'jain']
        
        df_agg = df.groupby('scheduler')[metrics].mean()
        # A razão pelo melhor valor preserva 1 quando todos os métodos empatam.
        # A normalização min-max anterior transformava empates em zero.
        maxima = df_agg.max().replace(0, np.nan)
        df_norm = df_agg.divide(maxima).fillna(0)
        
        angles = [n / len(metrics) * 2 * pi for n in range(len(metrics))]
        angles += angles[:1]
        
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
        
        for scheduler in df_norm.index:
            values = df_norm.loc[scheduler].values.flatten().tolist()
            values += values[:1]
            color = get_scheduler_color(scheduler)
            label = get_scheduler_label(scheduler)
            ax.plot(angles, values, 'o-', linewidth=2, color=color, label=label)
            ax.fill(angles, values, alpha=0.1, color=color)
        
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(['Throughput', 'Jain'], fontsize=12)
        ax.set_ylim(0, 1.1)
        ax.set_title('Desempenho Multi-dimensional', fontsize=14, fontweight='bold')
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.0))
        ax.grid(True)
        
        plt.tight_layout()
        plt.savefig(output_dir / 'radar_metricas.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ radar_metricas.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_eficiencia_pareto(df: pd.DataFrame, output_dir: Path) -> bool:
    """Distribuição da eficiência de Pareto."""
    try:
        t_max = df['throughput_mbps'].max()
        j_max = df['jain'].max()
        df['efficiency'] = (df['throughput_mbps'] * df['jain']) / (t_max * j_max + 1e-10)
        
        fig, ax = plt.subplots(figsize=(12, 7))
        
        plotted_density = False
        for scheduler in df['scheduler'].unique():
            data = df[df['scheduler'] == scheduler]
            color = get_scheduler_color(scheduler)
            label = get_scheduler_label(scheduler)
            if len(data) >= 3 and has_variation(data['efficiency']):
                sns.kdeplot(data=data, x='efficiency', color=color, label=label,
                            fill=True, alpha=0.3, ax=ax, linewidth=2)
                plotted_density = True
            else:
                ax.scatter(data['efficiency'], np.zeros(len(data)), color=color,
                           label=label, alpha=0.65, s=35)
        
        ax.axvline(x=1, color='red', linestyle='--', alpha=0.5, label='Eficiência Máxima')
        ax.set_xlabel('Eficiência de Pareto', fontsize=12)
        ax.set_ylabel('Densidade', fontsize=12)
        ax.set_title('Distribuição da Eficiência de Pareto', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.2)
        ax.legend(loc='best')
        ax.set_xlim(0, 1.1)
        if not plotted_density:
            annotate_no_variation(ax, 'eficiência de Pareto')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'eficiencia_pareto.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ eficiencia_pareto.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_estabilidade_temporal(df: pd.DataFrame, output_dir: Path) -> bool:
    """Estabilidade dos schedulers ao longo do tempo."""
    try:
        if 'rng_run' not in df.columns:
            print(f"  ⚠️ Pulando estabilidade_temporal (sem rng_run)")
            return False
        
        fig, ax = plt.subplots(figsize=(12, 7))
        
        for scheduler in df['scheduler'].unique():
            data = df[df['scheduler'] == scheduler]
            color = get_scheduler_color(scheduler)
            label = get_scheduler_label(scheduler)
            data = data.sort_values('rng_run')
            ax.plot(data['rng_run'], data['throughput_mbps'],
                    'o-', color=color, label=label, linewidth=2, markersize=8)
        
        ax.set_xlabel('Run', fontsize=12)
        ax.set_ylabel('Throughput (Mbps)', fontsize=12)
        ax.set_title('Estabilidade dos Escalonadores por Run', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.2)
        ax.legend(loc='best')
        runs = sorted(df['rng_run'].dropna().unique())
        if len(runs) <= 20:
            ax.set_xticks(runs)
        
        plt.tight_layout()
        plt.savefig(output_dir / 'estabilidade_temporal.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ estabilidade_temporal.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_fronteira_por_cenario(df: pd.DataFrame, output_dir: Path) -> bool:
    """Comparação da fronteira de Pareto por raio."""
    try:
        if 'radius_m' not in df.columns:
            print(f"  ⚠️ Pulando fronteira_por_cenario (sem radius_m)")
            return False
        
        radii = sorted(df['radius_m'].unique())
        n_cols = min(3, len(radii))
        n_rows = (len(radii) + n_cols - 1) // n_cols
        
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, 5*n_rows))
        if n_rows == 1 and n_cols == 1:
            axes = np.array([axes])
        axes = axes.flatten()
        
        for idx, radius in enumerate(radii):
            ax = axes[idx]
            df_radius = df[df['radius_m'] == radius]
            
            for scheduler in df_radius['scheduler'].unique():
                data = df_radius[df_radius['scheduler'] == scheduler]
                color = get_scheduler_color(scheduler)
                label = get_scheduler_label(scheduler)
                ax.scatter(data['throughput_mbps'], data['jain'],
                           c=color, label=label, alpha=0.5, s=30,
                           edgecolors='black', linewidth=0.5)
            
            points = list(zip(df_radius['throughput_mbps'], df_radius['jain']))
            if points:
                pareto = compute_pareto_frontier(
                    [p[0] for p in points],
                    [p[1] for p in points]
                )
                if pareto:
                    px, py = zip(*pareto)
                    ax.plot(px, py, '--', linewidth=2, color='#F39C12')
            
            ax.set_title(f'Raio: {radius}m', fontsize=12, fontweight='bold')
            ax.set_xlabel('Vazão (Mbps)', fontsize=10)
            ax.set_ylabel('Jain', fontsize=10)
            ax.set_ylim(0, 1.05)
            ax.grid(True, alpha=0.2)
            ax.legend(loc='best', fontsize=8)
        
        for idx in range(len(radii), len(axes)):
            fig.delaxes(axes[idx])
        
        fig.suptitle('Fronteira de Pareto por Limite Espacial', fontsize=16, fontweight='bold')
        plt.tight_layout()
        plt.savefig(output_dir / 'fronteira_por_cenario.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ fronteira_por_cenario.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

def plot_regret_heatmap(df: pd.DataFrame, output_dir: Path) -> bool:
    """Heatmap do arrependimento (regret)."""
    try:
        if 'rng_run' not in df.columns:
            print(f"  ⚠️ Pulando regret_heatmap (sem rng_run)")
            return False
        
        t_max = df['throughput_mbps'].max()
        df['regret'] = (t_max - df['throughput_mbps']) / t_max * 100
        
        pivot = df.pivot_table(
            values='regret',
            index='rng_run',
            columns='scheduler',
            aggfunc='mean'
        )
        
        if len(pivot) <= 1:
            print(f"  ⚠️ Pulando regret_heatmap (dados insuficientes)")
            return False
        
        fig, ax = plt.subplots(figsize=(12, 8))
        sns.heatmap(pivot, cmap='RdYlGn_r', ax=ax, annot=True, fmt='.1f',
                    cbar_kws={'label': 'Regret (%)'})
        ax.set_xlabel('Escalonador', fontsize=12)
        ax.set_ylabel('rngRun', fontsize=12)
        ax.set_title('Arrependimento (Regret) por Escalonador', fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        plt.savefig(output_dir / 'regret_heatmap.png', dpi=300, bbox_inches='tight')
        plt.close()
        print(f"  ✅ regret_heatmap.png")
        return True
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return False

# ============================================================================
# MAIN
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Geração de gráficos - SOLUÇÃO DEFINITIVA (apenas dados reais)"
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Diretório com o arquivo executions.csv"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Diretório de saída (padrão: input/graficos)"
    )
    parser.add_argument(
        "--skip-classic",
        action="store_true",
        help="Pular gráficos de análise clássica"
    )
    parser.add_argument(
        "--skip-advanced",
        action="store_true",
        help="Pular gráficos de análise avançada"
    )
    
    args = parser.parse_args()
    
    if args.output is None:
        output_dir = args.input / "graficos"
    else:
        output_dir = args.output
    
    print("\n" + "="*80)
    print("📊 GERADOR DE GRÁFICOS - SOLUÇÃO DEFINITIVA")
    print("="*80)
    print(f"📁 Entrada: {args.input}")
    print(f"📁 Saída: {output_dir}")
    print("="*80 + "\n")
    
    # Carrega dados - APENAS REAIS
    print("📂 Carregando dados reais...")
    df = load_data(args.input)
    
    if df.empty:
        print("\n❌ NENHUM DADO VÁLIDO ENCONTRADO!")
        print("   Verifique se o arquivo executions.csv existe e tem dados.")
        print("   Execute: ls -la " + str(args.input / "executions.csv"))
        return 1
    
    # Configura estilo
    setup_style()
    
    # Cria diretórios
    print("\n📁 Criando diretórios...")
    dirs = create_output_dirs(output_dir)
    
    # Gera gráficos
    if not args.skip_classic:
        print("\n📈 Gerando gráficos - Análise Clássica...")
        classic_dir = dirs["classica"]
        
        plot_dispersao_pareto(df, classic_dir)
        plot_boxplot_distribuicao(df, classic_dir)
        plot_violin_distribuicao(df, classic_dir)
        plot_elipses_confianca(df, classic_dir)
        plot_densidade_heatmap(df, classic_dir)
    
    if not args.skip_advanced:
        print("\n🚀 Gerando gráficos - Análise Avançada...")
        advanced_dir = dirs["avancada"]
        
        plot_radar_metricas(df, advanced_dir)
        plot_eficiencia_pareto(df, advanced_dir)
        plot_estabilidade_temporal(df, advanced_dir)
        plot_fronteira_por_cenario(df, advanced_dir)
        plot_regret_heatmap(df, advanced_dir)
    
    print("\n" + "="*80)
    print("✅ PROCESSO CONCLUÍDO COM SUCESSO!")
    print(f"📁 Gráficos disponíveis em: {output_dir}")
    print("="*80 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())