#!/bin/bash
# ============================================================
# teste_completo_vj5g.sh
#
# Testa todos os schedulers × perfis × UEs × cenários para
# identificar combinações estáveis no 5G-LENA.
#
# Cenários testados:
#   C1: 100MHz, 43dBm (referência)
#   C2: 20MHz,  30dBm (competição moderada)
#   C3: 10MHz,  23dBm (competição intensa)
#
# Uso: bash teste_completo_vj5g.sh
# ============================================================

cd ~/ns3-fmr

SCHEDULERS="rr pf mr qos"
PERFIS="embb urllc mmtc"
UES_LIST="3 5 6 7 8 9"
SIMTIME="5s"
SEED=1

# Cenários: nome, bandwidth, potência
declare -a CENARIO_NOMES=("C1" "C2" "C3")
declare -a CENARIO_BW=("100000000" "20000000" "10000000")
declare -a CENARIO_PWR=("43" "30" "23")

# Arquivo de log com timestamp
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_DIR="pesquisa/resultados/testes"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/teste_cenarios_${TIMESTAMP}.txt"
CSV_FILE="$LOG_DIR/teste_cenarios_${TIMESTAMP}.csv"

# Função que escreve na tela E no arquivo de log simultaneamente
log() {
    echo "$1" | tee -a "$LOG_FILE"
}

# Cabeçalho do CSV
echo "cenario,bandwidth_mhz,power_dbm,scheduler,perfil,num_ues,throughput_mbps,jain_vazao,status,erro" \
    > "$CSV_FILE"

log "============================================================"
log "  TESTE COMPLETO VJ5G — cenários C1, C2 e C3"
log "  Data: $(date '+%Y-%m-%d %H:%M:%S')"
log "  simTime=$SIMTIME | seed=$SEED"
log "  Log: $LOG_FILE"
log "  CSV: $CSV_FILE"
log "============================================================"

OK_COUNT=0
ERRO_COUNT=0

for idx in 0 1 2; do
    CENARIO=${CENARIO_NOMES[$idx]}
    BW=${CENARIO_BW[$idx]}
    PWR=${CENARIO_PWR[$idx]}
    BW_MHZ=$(echo "scale=0; $BW / 1000000" | bc)

    log ""
    log "============================================================"
    log "  $CENARIO — Bandwidth=${BW_MHZ}MHz | Potência=${PWR}dBm"
    log "============================================================"
    printf "%-5s %-10s %-10s %-5s %-14s %-10s %-8s\n" \
        "CEN" "SCHEDULER" "PERFIL" "UEs" "THROUGHPUT" "JAIN" "STATUS" \
        | tee -a "$LOG_FILE"
    log "------------------------------------------------------------"

    for sched in $SCHEDULERS; do
        for perfil in $PERFIS; do
            for ues in $UES_LIST; do

                OUTPUT=$(./ns3 run "scratch/simulacao-vj5g \
                    --schedulerMode=$sched \
                    --trafficProfile=$perfil \
                    --ueNumPergNb=$ues \
                    --simTime=$SIMTIME \
                    --seed=$SEED \
                    --bandwidth=$BW \
                    --totalTxPower=$PWR" 2>&1)

                RESULT=$(echo "$OUTPUT" | grep "\[RESULT\]")
                FATAL=$(echo "$OUTPUT"  | grep -E "NS_FATAL|ASSERT failed")

                if [ -n "$RESULT" ]; then
                    THROUGHPUT=$(echo "$RESULT" | grep -oP 'throughput_mbps=\K[0-9.]+')
                    JAIN=$(echo "$RESULT"       | grep -oP 'jain_vazao=\K[0-9.]+')

                    printf "%-5s %-10s %-10s %-5s %-14s %-10s %-8s\n" \
                        "$CENARIO" "$sched" "$perfil" "$ues" \
                        "${THROUGHPUT} Mbps" "$JAIN" "OK" \
                        | tee -a "$LOG_FILE"

                    echo "$CENARIO,$BW_MHZ,$PWR,$sched,$perfil,$ues,$THROUGHPUT,$JAIN,OK," \
                        >> "$CSV_FILE"
                    OK_COUNT=$((OK_COUNT + 1))
                else
                    MSG=$(echo "$FATAL" | grep -oP 'msg="\K[^"]+' | head -1)

                    printf "%-5s %-10s %-10s %-5s %-14s %-10s %-8s\n" \
                        "$CENARIO" "$sched" "$perfil" "$ues" \
                        "-" "-" "ERRO" \
                        | tee -a "$LOG_FILE"

                    [ -n "$MSG" ] && log "  → $MSG"

                    MSG_CLEAN=$(echo "$MSG" | tr ',' ';')
                    echo "$CENARIO,$BW_MHZ,$PWR,$sched,$perfil,$ues,,,ERRO,$MSG_CLEAN" \
                        >> "$CSV_FILE"
                    ERRO_COUNT=$((ERRO_COUNT + 1))
                fi
            done
            log ""
        done
    done
done

log "============================================================"
log "RESUMO FINAL: $OK_COUNT OK | $ERRO_COUNT ERROS"
log "Arquivos gerados:"
log "  Log: $LOG_FILE"
log "  CSV: $CSV_FILE"
log "============================================================"