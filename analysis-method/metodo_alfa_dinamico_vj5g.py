
"""
Metodo do alfa dinamico via Fronteira de Pareto + Barganha de Nash
Dissertacao VJ5G - Julio Henrique da Silva Lopes

Decisoes incorporadas (rastreabilidade para o Capitulo 3):
  D1 - Janela de agregacao: 100ms (WindowSizeMs), ja validada no projeto.
  D2 - Ponto de desacordo do Nash: minimo de J e de T observados entre
       os escalonadores candidatos, DENTRO DA MESMA JANELA (pipeline Run1-30).
  D3 - Escopo desta versao: analise offline (Partes I-IV). Camada de
       controle em tempo real fica registrada como trabalho futuro,
       nao implementada aqui.
  D4 - Escalas temporais: roda em 100/500/1000/2000 ms, todas por
       reagregacao dos mesmos dados de janela (sem nova coleta no ns-3).
  D5 - Regra de desempate do produto de Nash, nesta ordem:
       1) maior indice de Jain
       2) maior vazao agregada
       3) ponto mais recente (maior window_id / time_s)
  D10 - Fonte oficial para Pareto-Nash: window_log.csv do esquema novo,
       calculado com bytes unicos recebidos pela aplicacao em cada janela.
       Logs legados da Bateria 3 sao aceitos apenas para diagnostico com
       autorizacao explicita: o callback antigo nao eliminava eventos Rx
       duplicados e a validacao ue_summary/flow_summary nao validava essa
       metrica temporal.
"""

import pandas as pd
import numpy as np
import warnings


# ---------------------------------------------------------------------------
# Parte I - Leitura e padronizacao do window_log (sem recalculo de metricas)
# ---------------------------------------------------------------------------

COLUNAS_BASE_WINDOW_LOG = [
    "scheduler", "traffic_profile", "num_ues", "seed", "rng_run",
    "bandwidth_mhz", "window_id", "aggregate_thr_mbps", "jain_throughput",
]
COLUNAS_ESPERADAS_WINDOW_LOG = COLUNAS_BASE_WINDOW_LOG + ["time_s"]


def carregar_window_log(window_log_df: pd.DataFrame, cenario: str,
                         run_id=None, colunas_metadados_extra: dict = None,
                         permitir_log_legado: bool = False) -> pd.DataFrame:
    """
    Le e padroniza um window_log.csv ja carregado em DataFrame.

    Responsabilidades desta funcao, e SOMENTE estas (D10 -- nenhuma
    metrica e recalculada aqui):
      1) Garantir que as colunas minimas existem (falha cedo e com
         mensagem clara se o arquivo estiver fora do formato esperado).
      2) Selecionar e padronizar os nomes de coluna usados pelo resto
         do pipeline: "aggregate_thr_mbps" e "jain_throughput" (esses
         ja sao os nomes nativos do window_log real, mas a padronizacao
         fica explicita aqui para blindar o pipeline caso o nome de
         origem mude).
      3) Acrescentar metadados de cenario (coluna "cenario") e,
         opcionalmente, de identificacao da execucao (coluna "run_id"),
         alem de qualquer metadado extra fornecido.

    Parametros:
      window_log_df: DataFrame carregado diretamente de um window_log.csv.
      cenario: identificador do cenario ao qual esta execucao pertence,
               usado depois na calibracao estratificada do Jmin (D8).
      run_id: identificador da execucao. Se None, tenta usar a
              combinacao (seed, rng_run) ja presente no arquivo.
      colunas_metadados_extra: dict opcional de colunas fixas adicionais
              a anexar.

    Retorna um DataFrame com as colunas de COLUNAS_ESPERADAS_WINDOW_LOG
    mais "cenario", "run_id" e quaisquer metadados extra.
    """
    faltantes = [c for c in COLUNAS_BASE_WINDOW_LOG if c not in window_log_df.columns]
    if faltantes:
        raise ValueError(
            "window_log fora do formato esperado -- colunas ausentes: "
            f"{faltantes}. Colunas presentes: {list(window_log_df.columns)}"
        )

    df_origem = window_log_df.copy()
    esquema_novo = {
        "start_time_s", "end_time_s", "duration_s", "app_rx_packets"
    }.issubset(df_origem.columns)

    if esquema_novo:
        df_origem["time_s"] = df_origem["end_time_s"]
        esquema = "app_rx_unique_v2"
        if "metric_source" in df_origem.columns:
            fontes = set(df_origem["metric_source"].dropna().astype(str))
            if fontes != {"app_rx_unique_payload"}:
                raise ValueError(
                    "metric_source inesperada no esquema novo: "
                    f"{sorted(fontes)}"
                )
        fonte_metrica = "app_rx_unique_payload"
    else:
        if "time_s" not in df_origem.columns:
            raise ValueError(
                "window_log sem 'time_s' (legado) nem 'end_time_s' (novo)"
            )
        if not permitir_log_legado:
            raise ValueError(
                "window_log legado detectado. A Bateria 3 foi gerada por um "
                "callback Rx sem deduplicacao e nao e fonte valida para "
                "resultados Pareto-Nash. Use permitir_log_legado=True apenas "
                "para testes estruturais/diagnosticos."
            )
        esquema = "rx_trace_legacy_v1"
        fonte_metrica = "app_rx_trace_nao_deduplicado"
        warnings.warn(
            "Log legado habilitado somente para diagnostico; throughput e "
            "Jain por janela podem estar inflados por eventos Rx duplicados.",
            RuntimeWarning,
            stacklevel=2,
        )

    df = df_origem[COLUNAS_ESPERADAS_WINDOW_LOG].copy()
    numericas = [
        "num_ues", "seed", "rng_run", "bandwidth_mhz", "window_id",
        "time_s", "aggregate_thr_mbps", "jain_throughput",
    ]
    for coluna in numericas:
        df[coluna] = pd.to_numeric(df[coluna], errors="raise")
    if (df["aggregate_thr_mbps"] < 0).any():
        raise ValueError("aggregate_thr_mbps contem valor negativo")
    if not df["jain_throughput"].between(0.0, 1.0).all():
        raise ValueError("jain_throughput deve estar no intervalo [0, 1]")

    df["window_schema"] = esquema
    df["metric_source"] = fonte_metrica

    df["cenario"] = cenario

    if run_id is not None:
        df["run_id"] = run_id
    elif {"seed", "rng_run"}.issubset(df.columns):
        df["run_id"] = df["seed"].astype(str) + "_" + df["rng_run"].astype(str)
    else:
        df["run_id"] = np.nan

    if colunas_metadados_extra:
        for nome_coluna, valor in colunas_metadados_extra.items():
            df[nome_coluna] = valor

    return df


def concatenar_window_logs(lista_window_logs: list) -> pd.DataFrame:
    """
    Concatena varios DataFrames ja padronizados por carregar_window_log
    (um por execucao/run) em um unico DataFrame, pronto para o resto do
    pipeline (Partes II, III e IV). Wrapper simples de pd.concat para
    deixar explicito o ponto de juncao entre "ler arquivos" e "processar
    metodo", sem logica adicional.
    """
    return pd.concat(lista_window_logs, ignore_index=True)




def reagregar_window_log(window_log_100ms: pd.DataFrame, window_ms: int,
                         permitir_media_jain_aproximada: bool = False) -> pd.DataFrame:
    """
    Pre-processamento (D4): gera um window_log em uma escala temporal
    diferente a partir do window_log base de 100ms, agrupando janelas
    consecutivas por (run_id, cenario, scheduler).

    Esta funcao e a UNICA responsavel por conhecer a nocao de escala
    temporal (100/500/1000/2000ms). A orquestracao principal (Parte IV)
    consome sempre um window_log ja pronto para a escala desejada e nao
    precisa saber que outras escalas existem -- isso mantem o metodo em
    si (Pareto + Nash + Jmin) independente da escala, podendo ser
    testado em qualquer uma delas sem alterar seu codigo.

    Regra de agregacao, coerente com D10 (fonte oficial e o window_log
    do simulador, sem recalculo de metricas a partir de dados mais
    granulares que ele):
      - aggregate_thr_mbps: MEDIA das janelas de 100ms que compoe a
        nova janela (media de vazao instantanea, nao soma, pois cada
        window_log ja reporta uma taxa em Mbps por janela de 100ms).
      - jain_throughput: o calculo exato em uma janela maior exige os
        totais por UE. Como esses dados nao existem no window_log, a
        media dos indices de 100ms e apenas uma aproximacao e precisa
        ser autorizada explicitamente.
      - time_s: o maior time_s do grupo (fim da nova janela).
      - window_id: recalculado com base no novo window_ms.

    Parametros:
      window_log_100ms: DataFrame ja padronizado (saida de
                         carregar_window_log/concatenar_window_logs),
                         na granularidade original de 100ms.
      window_ms: nova largura de janela em milissegundos (ex.: 500,
                 1000, 2000). Deve ser multiplo de 100.

    Retorna um DataFrame no mesmo formato de saida de carregar_window_log,
    porem com window_id/time_s reagregados e aggregate_thr_mbps /
    jain_throughput recalculados como media sobre a nova janela.
    """
    if window_ms % 100 != 0:
        raise ValueError(
            f"window_ms={window_ms} nao e multiplo de 100. O window_log "
            "base esta em janelas de 100ms (D1); a reagregacao exige um "
            "multiplo inteiro dessa granularidade."
        )

    if window_ms < 100:
        raise ValueError("window_ms deve ser maior ou igual a 100")

    if window_ms > 100 and not permitir_media_jain_aproximada:
        raise ValueError(
            "A reagregacao exata do indice de Jain exige vazao/bytes por UE. "
            "O window_log contem apenas o Jain agregado de 100ms. Para uma "
            "analise exploratoria, use permitir_media_jain_aproximada=True; "
            "para resultados metodologicos finais, forneca dados por UE."
        )

    if window_ms == 100:
        return window_log_100ms.copy()

    fator = window_ms // 100
    chaves_serie = ["run_id", "cenario", "scheduler"]
    df = window_log_100ms.sort_values(chaves_serie + ["time_s", "window_id"]).copy()
    # Usa a ordem das janelas, e nao aritmetica de ponto flutuante em time_s.
    # Assim, cada grupo contem exatamente `fator` janelas (salvo o ultimo).
    df["window_id"] = df.groupby(chaves_serie, sort=False).cumcount() // fator

    colunas_agrupamento = ["run_id", "cenario", "scheduler", "window_id"]
    colunas_meta_constantes = [
        c for c in df.columns
        if c not in colunas_agrupamento + ["time_s", "aggregate_thr_mbps", "jain_throughput"]
    ]

    agregados = df.groupby(colunas_agrupamento).agg(
        time_s=("time_s", "max"),
        aggregate_thr_mbps=("aggregate_thr_mbps", "mean"),
        jain_throughput=("jain_throughput", "mean"),
    ).reset_index()

    # Reanexa metadados constantes (scheduler, cenario, run_id ja estao nas
    # chaves de agrupamento; os demais -- traffic_profile, num_ues, seed,
    # rng_run, bandwidth_mhz -- sao repetidos identicos em todo o grupo).
    if colunas_meta_constantes:
        meta = df[colunas_agrupamento + colunas_meta_constantes].drop_duplicates(
            subset=colunas_agrupamento
        )
        agregados = agregados.merge(meta, on=colunas_agrupamento, how="left")

    saida = COLUNAS_ESPERADAS_WINDOW_LOG + ["cenario", "run_id"]
    saida += [c for c in ["window_schema", "metric_source"] if c in agregados.columns]
    return agregados[saida]


# ---------------------------------------------------------------------------
# Parte II - Fronteira de Pareto por janela
# ---------------------------------------------------------------------------

def fronteira_pareto(pontos: pd.DataFrame, tol: float = 1e-9) -> pd.DataFrame:
    """
    Recebe pontos (um por scheduler) de uma mesma janela, com colunas
    jain_throughput e aggregate_thr_mbps, e marca quais sao nao-dominados.

    Dominancia: (Jm, Tm) domina (Jk, Tk) se Jm >= Jk e Tm >= Tk,
    com pelo menos uma desigualdade estrita.

    D7 (caso de borda): pontos exatamente iguais nos dois eixos nunca se
    dominam, pois a dominancia exige desigualdade estrita em pelo menos
    um eixo. tol e uma tolerancia numerica para evitar falsa dominancia
    por erro de arredondamento de ponto flutuante.
    """
    vals = pontos[["jain_throughput", "aggregate_thr_mbps"]].values
    n = len(vals)
    dominado = np.zeros(n, dtype=bool)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            melhor_ou_igual = (vals[j][0] >= vals[i][0] - tol) and (vals[j][1] >= vals[i][1] - tol)
            estritamente_melhor = (vals[j][0] > vals[i][0] + tol) or (vals[j][1] > vals[i][1] + tol)
            if melhor_ou_igual and estritamente_melhor:
                dominado[i] = True
                break

    resultado = pontos.copy()
    resultado["nao_dominado"] = ~dominado
    return resultado


# ---------------------------------------------------------------------------
# Parte III - Criterio de Nash com ponto de desacordo pelo minimo (D2)
# e regra de desempate (D5)
# ---------------------------------------------------------------------------

def ponto_otimo_nash(pontos_janela: pd.DataFrame) -> pd.Series:
    """
    Recebe todos os pontos (um por scheduler) de uma unica janela e
    retorna o ponto vencedor pelo produto de Nash.

    D2: ponto de desacordo = (min Jain, min vazao) observados NESSA
    janela entre os escalonadores candidatos (nao um minimo teorico global).

    D5: desempate em caso de produto de Nash igual entre 2+ candidatos:
        1) maior jain_throughput
        2) maior aggregate_thr_mbps
        3) maior time_s (ponto mais recente)

    D7 - Casos de borda explicitos:
        a) Fronteira com ponto unico: se so ha um candidato na janela,
           ele e retornado diretamente, sem calcular produto de Nash
           (o ponto de desacordo coincidiria com o proprio candidato,
           zerando o produto de forma nao informativa).
        b) Empate total no ponto de desacordo: se todos os candidatos
           empatam no minimo de Jain e/ou no minimo de vazao, o produto
           de Nash zera para todos, e o vencedor e definido inteiramente
           pela regra de desempate D5 (Jain, depois vazao, depois mais
           recente) -- isso e uma consequencia esperada da formula, nao
           um erro, e fica documentado aqui por clareza.
    """
    # D7a: ponto unico na fronteira -- retorna direto, sem calcular Nash.
    if len(pontos_janela) == 1:
        return pontos_janela.iloc[0]

    j_min = pontos_janela["jain_throughput"].min()
    t_min = pontos_janela["aggregate_thr_mbps"].min()

    df = pontos_janela.copy()
    df["nash_product"] = (df["jain_throughput"] - j_min) * (df["aggregate_thr_mbps"] - t_min)

    # D7b: se nash_product empata (inclusive quando todos sao zero por
    # empate no ponto de desacordo), a ordenacao abaixo cai na regra D5.
    df_sorted = df.sort_values(
        by=["nash_product", "jain_throughput", "aggregate_thr_mbps", "time_s"],
        ascending=[False, False, False, False],
    )
    return df_sorted.iloc[0]


# ---------------------------------------------------------------------------
# Parte IV - Pipeline por escala temporal: calibracao (30 runs) + Jmin
# e validacao (70 runs) com frequencia / magnitude / persistencia de violacao
# ---------------------------------------------------------------------------

def calcular_jmin_calibracao(vencedores_por_run: pd.DataFrame, coluna_cenario: str = "cenario") -> pd.Series:
    """
    D8 - Calibracao ESTRATIFICADA POR CENARIO (nao global).

    Recebe o jain_throughput do ponto vencedor de Nash em cada uma das
    runs de calibracao (30 runs por cenario) e retorna, para cada
    cenario, a mediana desses valores como Jmin daquele cenario.

    Pressuposto metodologico (registrado no texto da dissertacao): as
    runs de calibracao de um mesmo cenario diferem apenas pela semente
    aleatoria, com os demais parametros experimentais fixos. A mediana
    e usada por ser um estimador robusto a valores extremos.

    Retorna uma Series indexada por cenario (ex.: jmin_por_cenario["C1"]).
    """
    if coluna_cenario not in vencedores_por_run.columns:
        raise ValueError(
            f"Coluna '{coluna_cenario}' nao encontrada. A calibracao do "
            "Jmin e estratificada por cenario (Decisao D8) -- forneca a "
            "coluna de cenario ou ajuste 'coluna_cenario'."
        )
    return vencedores_por_run.groupby(coluna_cenario)["jain_throughput"].median()


def avaliar_violacoes(vencedores_validacao: pd.DataFrame, j_min: float,
                      l_max_pcts: list = None) -> dict:
    """
    Aplica o Jmin calibrado sobre as runs de validacao (70 runs do MESMO
    cenario do j_min recebido) e mede:
      - frequencia: % de janelas com jain_throughput do vencedor < j_min
      - magnitude: media do deficit (j_min - jain) nas janelas violadas
      - persistencia: maior sequencia contigua de violacoes, como % da run

    D9 - L_max NAO e mais uma constante fixa da metodologia. E um
    parametro de analise de sensibilidade: l_max_pcts recebe uma lista de
    limites candidatos (padrao: uma faixa em torno do ponto de partida de
    10%), e a funcao retorna o alarme de persistencia calculado para CADA
    um desses limites, permitindo observar o impacto de diferentes
    tolerancias na classificacao das violacoes antes de qualquer escolha
    ser fixada no texto.
    """
    if l_max_pcts is None:
        l_max_pcts = [5.0, 10.0, 15.0, 20.0]  # faixa de sensibilidade, nao valor fixo

    if vencedores_validacao.empty:
        raise ValueError("Nao ha janelas nas runs de validacao")
    if "run_id" not in vencedores_validacao.columns:
        raise ValueError("A avaliacao de persistencia exige a coluna 'run_id'")

    df = vencedores_validacao.sort_values(
        ["run_id", "window_id", "time_s"]
    ).reset_index(drop=True)
    violado = df["jain_throughput"] < j_min

    frequencia_pct = 100.0 * violado.mean()

    if violado.any():
        magnitude_media = (j_min - df.loc[violado, "jain_throughput"]).mean()
    else:
        magnitude_media = 0.0

    persistencias_por_run = {}
    for run_id, grupo in df.groupby("run_id", sort=False):
        flags = grupo["jain_throughput"] < j_min
        max_seq = seq_atual = 0
        for v in flags:
            seq_atual = seq_atual + 1 if v else 0
            max_seq = max(max_seq, seq_atual)
        persistencias_por_run[run_id] = 100.0 * max_seq / len(grupo)

    persistencia_media_pct = float(np.mean(list(persistencias_por_run.values())))
    persistencia_max_pct = float(np.max(list(persistencias_por_run.values())))

    alarmes_por_limite = {
        l_max: persistencia_max_pct > l_max for l_max in l_max_pcts
    }

    return {
        "frequencia_pct": frequencia_pct,
        "magnitude_media": magnitude_media,
        # Mantem o nome legado como alias conservador do pior caso por run.
        "persistencia_pct": persistencia_max_pct,
        "persistencia_media_pct": persistencia_media_pct,
        "persistencia_max_pct": persistencia_max_pct,
        "persistencia_por_run_pct": persistencias_por_run,
        "alarmes_por_limite_l_max": alarmes_por_limite,
    }


# ---------------------------------------------------------------------------
# Orquestracao: roda o metodo completo para uma escala temporal
# ---------------------------------------------------------------------------

def _vencedores_por_janela(window_log_df: pd.DataFrame) -> pd.DataFrame:
    """
    Passo intermediario da orquestracao: aplica a Barganha de Nash (com
    os casos de borda D7) em cada (run_id, window_id), usando as metricas
    de jain_throughput e aggregate_thr_mbps JA PRONTAS no window_log
    padronizado (D10 -- nenhuma reagregacao ou recalculo acontece aqui).

    window_log_df precisa ser o resultado de carregar_window_log /
    concatenar_window_logs, contendo as colunas "run_id", "cenario",
    "window_id", "jain_throughput" e "aggregate_thr_mbps".
    """
    chaves = ["cenario", "run_id", "window_id"]
    vencedores = []
    for _, grupo in window_log_df.groupby(chaves, sort=False):
        candidatos = fronteira_pareto(grupo)
        candidatos = candidatos[candidatos["nao_dominado"]].drop(
            columns="nao_dominado"
        )
        vencedores.append(ponto_otimo_nash(candidatos))
    return pd.DataFrame(vencedores)


def rodar_metodo_para_escala(window_log_df: pd.DataFrame, window_ms: int,
                              runs_calibracao_por_cenario: dict,
                              runs_validacao_por_cenario: dict,
                              l_max_pcts: list = None) -> pd.DataFrame:
    """
    Orquestracao enxuta (so encadeia etapas ja implementadas, sem logica
    nova): vencedores de Nash por janela -> Jmin por cenario (D8, so nas
    runs de calibracao) -> violacoes por cenario (D9, so nas runs de
    validacao). Chamar uma vez por escala temporal (D4: 100/500/1000/2000ms).

    window_log_df precisa ser o resultado de carregar_window_log /
    concatenar_window_logs, ja contendo as colunas "run_id" e "cenario".
    window_ms e mantido no nome da assinatura apenas para rotular o
    resultado (coluna "window_ms") -- a reagregacao para diferentes
    escalas temporais (D4) deve ocorrer ANTES desta chamada, gerando um
    window_log_df diferente por escala.
    runs_calibracao_por_cenario / runs_validacao_por_cenario: dict
    cenario -> lista de run_id.

    Retorna um DataFrame com uma linha por cenario.
    """
    vencedores_df = _vencedores_por_janela(window_log_df)

    resultados = []
    for cenario, runs_calib in runs_calibracao_por_cenario.items():
        if cenario not in runs_validacao_por_cenario:
            raise ValueError(f"Cenario sem runs de validacao: {cenario}")
        runs_valid = runs_validacao_por_cenario[cenario]
        sobrepostas = set(runs_calib) & set(runs_valid)
        if sobrepostas:
            raise ValueError(
                f"Runs de calibracao e validacao sobrepostas em {cenario}: "
                f"{sorted(sobrepostas)}"
            )

        do_cenario = vencedores_df["cenario"] == cenario
        calib = vencedores_df[do_cenario & vencedores_df["run_id"].isin(runs_calib)]
        valid = vencedores_df[do_cenario & vencedores_df["run_id"].isin(runs_valid)]
        if calib.empty:
            raise ValueError(f"Nenhuma janela de calibracao para {cenario}")
        if valid.empty:
            raise ValueError(f"Nenhuma janela de validacao para {cenario}")

        j_min = float(calcular_jmin_calibracao(calib, "cenario").loc[cenario])
        violacoes = avaliar_violacoes(valid, j_min, l_max_pcts)

        resultados.append({"cenario": cenario, "window_ms": window_ms, "j_min": j_min, **violacoes})

    return pd.DataFrame(resultados)
