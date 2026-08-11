#!/bin/bash

cd ~/ns3-fmr

SCHEDULER="rr"
PERFIS="embb urllc mmtc"
UES_LIST="3 9 30 60"
SIMTIME="5s"
SEED=1

BW=20000000
PWR=30

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
OUTDIR="pesquisa/resultados/validacao-perfis"
mkdir -p "$OUTDIR"

CSV="$OUTDIR/validacao_perfis_${TIMESTAMP}.csv"

echo "perfil,ues,scheduler,bandwidth_mhz,power_dbm,lambda_override,throughput_mbps,jain,pdr_medio,plr_medio,delay_medio_ms,status" > "$CSV"

for perfil in $PERFIS; do
  for ues in $UES_LIST; do

    echo "Rodando perfil=$perfil | UEs=$ues"

    FLOWCSV="$OUTDIR/flow_${perfil}_${ues}ues_${TIMESTAMP}.csv"

    OUTPUT=$(./ns3 run "scratch/simulacao-vj5g \
      --schedulerMode=$SCHEDULER \
      --trafficProfile=$perfil \
      --ueNumPergNb=$ues \
      --simTime=$SIMTIME \
      --seed=$SEED \
      --bandwidth=$BW \
      --totalTxPower=$PWR \
      --EnableFlowSummaryCsv=true \
      --FlowSummaryCsvPath=$FLOWCSV" 2>&1)

    RESULT=$(echo "$OUTPUT" | grep "\[RESULT\]")

    if [ -n "$RESULT" ]; then
      THR=$(echo "$RESULT" | grep -oP 'throughput_mbps=\K[0-9.]+')
      JAIN=$(echo "$RESULT" | grep -oP 'jain_vazao=\K[0-9.]+')

      PDR=$(awk -F, 'NR>1 {s+=$13;n++} END {if(n>0) print s/n; else print 0}' "$FLOWCSV")
      PLR=$(awk -F, 'NR>1 {s+=$12;n++} END {if(n>0) print s/n; else print 0}' "$FLOWCSV")
      DELAY=$(awk -F, 'NR>1 {s+=$9;n++} END {if(n>0) print s/n; else print 0}' "$FLOWCSV")

      echo "$perfil,$ues,$SCHEDULER,$((BW/1000000)),$PWR,0,$THR,$JAIN,$PDR,$PLR,$DELAY,OK" >> "$CSV"
    else
      echo "$perfil,$ues,$SCHEDULER,$((BW/1000000)),$PWR,0,,,,,,ERRO" >> "$CSV"
    fi

  done
done

echo "Arquivo gerado: $CSV"

