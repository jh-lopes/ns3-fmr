#!/usr/bin/env python3
# ============================================================
# computar_rbg_por_ue.py
#
# Adiciona ao ue_summary.csv unidades RBG×símbolo alocadas por UE,
# cruzando com o log nativo do 5G-LENA slot_log_common.csv
# (--EnableCommonSlotCsv), que registra, POR SLOT, quantas unidades
# de recurso tempo-frequência (RBG × símbolo OFDM) cada UE recebeu
# (colunas: time_s,beam_id,rnti,dl_mcs,buf_req,allocated_rbg_symbol_units — ver nota
# "IMPORTANTE" abaixo pra semântica exata de allocated_rbg_symbol_units, corrigida em
# 13/ago/2026). Ver comentário no simulacao-vj5g.cc, linhas ~144-151.
#
# Por que precisa deste script (e não só olhar o CSV nativo direto):
#   - slot_log_common.csv é indexado por RNTI, não por ue_id.
#   - RNTI não é sequencial (ver correção de 12/ago/2026 no .cc/.h —
#     antes o código assumia rnti=ue_id+1, o que é FALSO).
#   - Desde 12/ago/2026, ue_summary.csv tem uma coluna "rnti" com o
#     valor real de cada UE, capturada de forma confiável durante a
#     simulação (SinrCallback + MakeBoundCallback). Este script usa
#     essa coluna pra fazer o cruzamento certo, sem adivinhar nada.
#
# IMPORTANTE — o que a coluna allocated_rbg_symbol_units REALMENTE significa (corrigido
# em 13/ago/2026, ver conversa no projeto "Simulação Dissertação"):
#
#   Uma explicação anterior deste comentário dizia que só existiriam
#   ~12 RBGs por slot pra dividir entre os UEs (RBG size=2 num canal de
#   24 RBs), e que por isso a maioria dos UEs receberia allocated_rbg_symbol_units=0 na
#   maioria dos slots. Essa explicação estava ERRADA — os dados reais
#   mostram allocated_rbg_symbol_units variando de 0 a >300, o que não bate com um teto
#   de 12.
#
#   A causa: allocated_rbg_symbol_units não conta RBGs na dimensão da frequência apenas.
#   No código-fonte do 5G-LENA (nr-mac-scheduler-ofdma.cc, função
#   WriteCommonSlotCsv, e nr-mac-scheduler-ue-info.h), a coluna é escrita
#   assim:
#       const uint32_t alloc = ueInfo->m_dlRBG.size();
#   E a estrutura é:
#       std::vector<uint16_t> m_dlRBG;  // RBG alocado neste slot
#       std::vector<uint8_t>  m_dlSym;  // símbolo OFDM correspondente
#                                        // de cada m_dlRBG neste slot
#   m_dlRBG e m_dlSym são vetores PARALELOS: cada posição i é um par
#   (RBG, símbolo OFDM). Ou seja, allocated_rbg_symbol_units conta unidades de recurso
#   TEMPO-FREQUÊNCIA (RBG × símbolo), não RBGs distintos na frequência.
#
#   Isso explica os números observados num teste real com 10 UEs, PF,
#   10MHz: a soma de allocated_rbg_symbol_units de todos os UEs, em CADA slot, é sempre
#   exatamente 338 — porque a grade de dados do slot inteiro (26 RBGs
#   × 13 símbolos de dados, já que 1 dos 14 símbolos fica reservado pra
#   controle/PDCCH) é sempre alocada por completo sob tráfego saturante
#   (fila cheia). O que muda de slot a slot é só COMO essas 338 unidades
#   são divididas entre os 10 UEs — e UEs com sinal pior (MCS mais
#   baixo) recebem mais unidades, porque precisam de mais recursos
#   tempo-frequência pra carregar a mesma quantidade de bytes.
#
#   Em resumo: allocated_rbg_symbol_units/rbg_symbol_units_total abaixo devem ser lidos como
#   "unidades RBG×símbolo alocadas", não como "quantidade de RBGs". A
#   comparação relativa entre UEs (quem recebeu mais/menos) continua
#   válida e é o que importa pra análise de justiça — só a unidade de
#   medida estava documentada errado.
#
# Uso (de dentro de ~/ns3-fmr/scripts-VJ5/, depois de uma rodada com
# --EnableUeSummaryCsv=true --EnableCommonSlotCsv=true):
#   python3 computar_rbg_por_ue.py \
#       --ue-summary pesquisa/resultados/.../ue_summary.csv \
#       --slot-log   pesquisa/resultados/.../slot_log_common.csv
#
# Por padrão, SOBRESCREVE o ue_summary.csv informado, adicionando as
# colunas novas (use --saida para gravar em outro arquivo em vez de
# sobrescrever).
#
# Requer: pandas
# ============================================================

import argparse
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Este script precisa do pandas. Instale com:")
    print("  pip install pandas --break-system-packages")
    sys.exit(1)

RESOURCE_COLUMN = "allocated_rbg_symbol_units"


def normalizar_coluna_recurso(slot_log):
    """Aceita logs antigos, mas usa internamente o nome cientificamente correto."""
    if RESOURCE_COLUMN in slot_log.columns:
        return slot_log
    if "alloc_rbg" in slot_log.columns:
        print("[rbg] AVISO: log legado com 'alloc_rbg'; interpretando a coluna "
              "como unidades RBG×símbolo.")
        return slot_log.rename(columns={"alloc_rbg": RESOURCE_COLUMN})
    raise ValueError(
        f"slot_log sem a coluna obrigatória '{RESOURCE_COLUMN}'")


def computar(ue_summary_path: Path, slot_log_path: Path, saida_path: Path) -> None:
    if not ue_summary_path.exists():
        print(f"[rbg] ERRO: {ue_summary_path} não encontrado.")
        raise SystemExit(1)
    if not slot_log_path.exists():
        print(f"[rbg] ERRO: {slot_log_path} não encontrado. "
              "Rode a simulação com --EnableCommonSlotCsv=true "
              f"--CommonSlotCsvPath={slot_log_path}")
        raise SystemExit(1)

    ue_summary = pd.read_csv(ue_summary_path)
    slot_log = normalizar_coluna_recurso(pd.read_csv(slot_log_path))

    if "rnti" not in ue_summary.columns:
        print("[rbg] ERRO: ue_summary.csv não tem a coluna 'rnti'. "
              "Esse arquivo foi gerado com uma versão do simulacao-vj5g.cc "
              "anterior a 12/ago/2026 — rode a simulação de novo com o "
              "binário atualizado.")
        raise SystemExit(1)

    # --- Agrega o log nativo por RNTI ---
    agregado = slot_log.groupby("rnti").agg(
        logged_events=("allocated_rbg_symbol_units", "size"),
        rbg_symbol_units_total=("allocated_rbg_symbol_units", "sum"),
        scheduled_events=("allocated_rbg_symbol_units", lambda s: (s > 0).sum()),
    ).reset_index()

    # Média de unidades RBG×símbolo só nos slots em que o UE de fato
    # recebeu algo (>0) — evita diluir a média com os zeros, que já são
    # capturados por scheduled_event_share_pct separadamente.
    agregado["rbg_symbol_units_mean_when_scheduled"] = (
        agregado["rbg_symbol_units_total"] / agregado["scheduled_events"].replace(0, pd.NA)
    ).round(3)

    # Fração das linhas do log (por RNTI) em que o UE recebeu RBG > 0.
    # NOTA: isso é "fração das vezes que o UE aparece no log", não
    # necessariamente "fração de TODOS os slots da simulação" — depende
    # de o log nativo escrever uma linha por UE em TODO slot (mesmo com
    # allocated_rbg_symbol_units=0) ou só quando o UE é considerado pelo scheduler. Se
    # "logged_events" for igual pra todos os UEs de uma rodada, é sinal
    # de que o log cobre todo slot uniformemente e esse percentual já
    # representa a simulação inteira; se variar entre UEs, represente
    # com essa ressalva.
    agregado["scheduled_event_share_pct"] = (
        agregado["scheduled_events"] / agregado["logged_events"] * 100
    ).round(2)

    # --- Junta com o ue_summary por RNTI ---
    # BUG corrigido em 13/ago/2026: se o ue_summary.csv informado já tiver
    # sido processado por este script antes (já tem estas colunas de uma
    # rodada anterior), o merge() duplicava as colunas (ex: "logged_events_x"
    # e "logged_events_y") em vez de sobrescrever — quebrando o script logo
    # em seguida com KeyError. Isso tornava o script NÃO IDEMPOTENTE: rodar
    # duas vezes em cima do mesmo arquivo sempre falhava. Corrigido
    # removendo, antes do merge, qualquer coluna de rodada anterior que já
    # exista no ue_summary — assim o resultado sempre reflete o slot_log
    # informado NESTA chamada, e rodar o script de novo (ex: depois de um
    # rebuild) simplesmente atualiza os valores em vez de quebrar.
    novas_colunas = ["logged_events", "rbg_symbol_units_total",
                      "scheduled_events", "rbg_symbol_units_mean_when_scheduled",
                      "scheduled_event_share_pct", "rb_symbol_units_total"]
    colunas_ja_existentes = [c for c in novas_colunas if c in ue_summary.columns]
    if colunas_ja_existentes:
        print(f"[rbg] AVISO: {ue_summary_path} já tinha as colunas "
              f"{colunas_ja_existentes} de uma rodada anterior deste script — "
              "serão recalculadas e sobrescritas com base no slot_log "
              "informado agora.")
        ue_summary = ue_summary.drop(columns=colunas_ja_existentes)

    resultado = ue_summary.merge(agregado, on="rnti", how="left")
    if "rb_per_rbg" in resultado.columns:
        resultado["rb_symbol_units_total"] = (
            resultado["rbg_symbol_units_total"] * resultado["rb_per_rbg"])
    else:
        resultado["rb_symbol_units_total"] = pd.NA

    for column in ("logged_events", "rbg_symbol_units_total",
                   "scheduled_events", "rb_symbol_units_total"):
        resultado[column] = resultado[column].round().astype("Int64")

    sem_correspondencia = resultado[resultado["logged_events"].isna()]
    if not sem_correspondencia.empty:
        print(f"[rbg] AVISO: {len(sem_correspondencia)} UE(s) do ue_summary.csv "
              "não têm nenhuma linha correspondente em slot_log_common.csv "
              "(RNTI sem entradas no log nativo) — colunas de RBG ficam vazias "
              "pra eles. UEs afetados: "
              + ", ".join(str(u) for u in sem_correspondencia["ue_id"].tolist()))

    resultado.to_csv(saida_path, index=False)

    print(f"\n[rbg] {len(agregado)} RNTIs distintos encontrados em {slot_log_path}")
    print(f"[rbg] Resultado salvo em: {saida_path}")
    print("\n[rbg] Resumo por UE:")
    colunas_resumo = ["ue_id", "rnti"] + novas_colunas
    colunas_resumo = [c for c in colunas_resumo if c in resultado.columns]
    print(resultado[colunas_resumo].to_string(index=False))


def gerar_detalhe_por_slot(ue_summary_path: Path, slot_log_path: Path,
                            saida_path: Path) -> None:
    """Gera UM único CSV com o comportamento do escalonamento slot a slot:
    uma linha por (UE, slot), com slot numerado sequencialmente (1, 2, 3...)
    em vez do time_s bruto, e ue_id (não RNTI) — junto com o que o
    scheduler decidiu naquele slot para aquele UE (dl_mcs, buf_req,
    allocated_rbg_symbol_units) e os metadados do cenário (scheduler, dispositivos, etc,
    repetidos em toda linha pra facilitar filtro/pivot depois).

    Também calcula, por slot, o Jain-alocação REAL daquele instante
    (colunas n_ues_no_slot e jain_rbg_symbol_units_slot) — diferente de jain_vazao
    (vindo do ue_summary.csv), que é um valor ÚNICO pra simulação inteira e
    por isso aparece repetido em toda linha do arquivo. jain_rbg_symbol_units_slot
    mede a justiça da divisão de allocated_rbg_symbol_units entre os UEs presentes NAQUELE
    slot específico, então varia slot a slot (ver comentário no código, na
    função _jain, para a fórmula). Slots UL (sem nenhuma linha no log
    nativo) não têm Jain calculado, porque não aparecem no arquivo.

    Substitui a necessidade de abrir o slot_log_common.csv bruto (indexado
    por RNTI, com time_s em vez de número de slot) — este arquivo já sai
    pronto pra ler, filtrar (ex: só slot 1 a 20, ou só um UE) ou plotar.
    """
    if not ue_summary_path.exists():
        print(f"[rbg] ERRO: {ue_summary_path} não encontrado.")
        raise SystemExit(1)
    if not slot_log_path.exists():
        print(f"[rbg] ERRO: {slot_log_path} não encontrado. "
              "Rode a simulação com --EnableCommonSlotCsv=true "
              f"--CommonSlotCsvPath={slot_log_path}")
        raise SystemExit(1)

    ue_summary = pd.read_csv(ue_summary_path)
    slot_log = normalizar_coluna_recurso(pd.read_csv(slot_log_path))

    if "rnti" not in ue_summary.columns:
        print("[rbg] ERRO: ue_summary.csv não tem a coluna 'rnti'. "
              "Esse arquivo foi gerado com uma versão do simulacao-vj5g.cc "
              "anterior a 12/ago/2026 — rode a simulação de novo com o "
              "binário atualizado.")
        raise SystemExit(1)

    # --- Slot sequencial (1, 2, 3...) a partir do time_s bruto ---
    # Todos os UEs compartilham a mesma linha do tempo de slots — o
    # tempo (time_s) de cada slot é o mesmo pra todo UE que aparece nele.
    # Ordena os valores únicos de time_s e usa a posição como número do
    # slot (1-indexado, mais natural de ler que 0-indexado).
    tempos_unicos = sorted(slot_log["time_s"].unique())
    slot_por_tempo = {t: i + 1 for i, t in enumerate(tempos_unicos)}
    slot_log = slot_log.copy()
    slot_log["slot"] = slot_log["time_s"].map(slot_por_tempo)

    # --- Jain REAL por slot (13/ago/2026) ---
    # jain_vazao (herdado do ue_summary.csv) é UM valor só, calculado sobre
    # a simulação inteira — por isso é idêntico em toda linha do arquivo.
    # Aqui calculamos um Jain de verdade PARA CADA SLOT, sobre os valores de
    # allocated_rbg_symbol_units que os UEs efetivamente receberam NAQUELE slot específico —
    # ou seja, mede a justiça da alocação instantânea, não da simulação
    # inteira. Fórmula padrão de Jain sobre o vetor x de alocações no slot:
    #   J = (sum(x))^2 / (n * sum(x^2))
    # onde n é a quantidade de UEs que aparecem no log NAQUELE slot (slots
    # UL, que não geram nenhuma linha no log nativo, não têm Jain — ver nota
    # metodológica no projeto sobre o bug do --tddPattern). J varia de
    # 1/n (todo o recurso concentrado em 1 UE) a 1.0 (dividido perfeitamente
    # igual entre todos os UEs presentes no slot).
    def _jain(x):
        x = x.to_numpy(dtype=float)
        n = len(x)
        soma = x.sum()
        soma_quadrados = (x ** 2).sum()
        if n == 0 or soma_quadrados == 0:
            return pd.NA
        return (soma ** 2) / (n * soma_quadrados)

    jain_por_slot = (
        slot_log.groupby("slot")["allocated_rbg_symbol_units"]
        .agg(jain_rbg_symbol_units_slot=_jain, n_ues_no_slot="size")
        .reset_index()
    )
    slot_log = slot_log.merge(jain_por_slot, on="slot", how="left")

    # --- Junta com ue_id (via rnti) e com TODAS as colunas do ue_summary ---
    # Inclui não só os metadados do cenário (scheduler, num_ues, seed...)
    # mas também as métricas agregadas por UE (throughput_mbps, sinr_mean_db,
    # distance_gnb_m, delay, plr/pdr, tx/rx/lost_packets, jain_vazao,
    # throughput_agregado_mbps) — repetidas em toda linha daquele UE, pra um
    # único arquivo trazer tanto o resumo da simulação inteira quanto o
    # detalhe slot a slot lado a lado.
    colunas_metadados = [c for c in ue_summary.columns if c not in ("ue_id", "rnti")]
    mapa_ue = ue_summary[["ue_id", "rnti"] + colunas_metadados].drop_duplicates()

    detalhe = slot_log.merge(mapa_ue, on="rnti", how="left")

    sem_ue_id = detalhe[detalhe["ue_id"].isna()]
    if not sem_ue_id.empty:
        rntis_orfaos = sorted(sem_ue_id["rnti"].unique().tolist())
        print(f"[rbg] AVISO: {len(sem_ue_id)} linha(s) do slot_log_common.csv "
              f"têm RNTI sem UE correspondente no ue_summary.csv (RNTIs: "
              f"{rntis_orfaos}) — provavelmente tráfego de controle/outro "
              "dispositivo não rastreado. Mantidas no arquivo com ue_id vazio.")

    colunas_finais = (["slot", "ue_id", "rnti"] + colunas_metadados +
                       ["time_s", "beam_id", "dl_mcs", "buf_req", "allocated_rbg_symbol_units",
                        "n_ues_no_slot", "jain_rbg_symbol_units_slot"])
    colunas_finais = [c for c in colunas_finais if c in detalhe.columns]
    detalhe = detalhe[colunas_finais].sort_values(["slot", "ue_id"])

    detalhe.to_csv(saida_path, index=False)

    n_slots = len(tempos_unicos)
    n_ues = mapa_ue["ue_id"].nunique()
    print(f"\n[rbg] Detalhe por slot salvo em: {saida_path}")
    print(f"[rbg] {n_slots} slots × {n_ues} UEs = {len(detalhe)} linhas")
    if "jain_rbg_symbol_units_slot" in detalhe.columns:
        jain_slot_unico = detalhe.drop_duplicates("slot")["jain_rbg_symbol_units_slot"]
        print(f"\n[rbg] Jain-por-slot (justiça da alocação instantânea, não da "
              f"simulação inteira): média={jain_slot_unico.mean():.4f}, "
              f"mín={jain_slot_unico.min():.4f}, máx={jain_slot_unico.max():.4f}")
    print("\n[rbg] Primeiras linhas (slot 1):")
    print(detalhe[detalhe["slot"] == 1].to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="Adiciona unidades RBG×símbolo por UE ao ue_summary.csv, "
                     "cruzando com o log nativo slot_log_common.csv. "
                     "Com --detalhe-por-slot, gera também (ou em vez disso) "
                     "um CSV slot a slot.")
    parser.add_argument("--ue-summary", required=True, type=Path,
                         help="Caminho do ue_summary.csv (precisa ter a "
                              "coluna 'rnti' — versão do simulador de "
                              "12/ago/2026 ou mais nova).")
    parser.add_argument("--slot-log", required=True, type=Path,
                         help="Caminho do slot_log_common.csv gerado com "
                              "--EnableCommonSlotCsv=true.")
    parser.add_argument("--saida", type=Path, default=None,
                         help="Caminho de saída do resumo agregado por UE. "
                              "Por padrão, sobrescreve o --ue-summary "
                              "informado. Ignorado se --somente-detalhe "
                              "for usado.")
    parser.add_argument("--detalhe-por-slot", type=Path, default=None,
                         help="Se informado, gera também um CSV com uma "
                              "linha por (UE, slot) — o comportamento do "
                              "escalonamento slot a slot (slot 1, 2, 3...). "
                              "Ex: --detalhe-por-slot detalhe_por_slot.csv")
    parser.add_argument("--somente-detalhe", action="store_true",
                         help="Gera só o CSV de --detalhe-por-slot, pulando "
                              "a atualização do ue_summary.csv agregado "
                              "(mais rápido se você só quer o detalhe).")
    args = parser.parse_args()

    if not args.somente_detalhe:
        saida = args.saida if args.saida is not None else args.ue_summary
        computar(args.ue_summary, args.slot_log, saida)

    if args.detalhe_por_slot is not None:
        gerar_detalhe_por_slot(args.ue_summary, args.slot_log, args.detalhe_por_slot)


if __name__ == "__main__":
    main()
