#!/usr/bin/env bash
# Executa RR/PF/MR em paralelo e aplica a análise Pareto--Nash por cenário.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

ROOT="${VJ5G_OUTPUT_ROOT:-pesquisa/resultados/bateria_vj5g}"
SIM_TIME="${VJ5G_SIM_TIME:-30s}"
WINDOW_MS="${VJ5G_WINDOW_MS:-100}"
BANDWIDTH="${VJ5G_BANDWIDTH:-100000000}"
TX_POWER="${VJ5G_TX_POWER:-43}"
LAMBDA_OVERRIDE="${VJ5G_LAMBDA_OVERRIDE:-5000}"
<<<<<<< ours
MAX_WORKERS="${VJ5G_MAX_WORKERS:-4}"
=======
MAX_WORKERS="${VJ5G_MAX_WORKERS:-8}"
>>>>>>> theirs
MIN_AVAILABLE_GB="${VJ5G_MIN_AVAILABLE_GB:-8}"
SIM_BINARY="${VJ5G_SIM_BINARY:-}"

read -r -a SEEDS <<< "${VJ5G_SEEDS:-1 2 3}"
read -r -a UES_LIST <<< "${VJ5G_UE_COUNTS:-10 50 100}"
read -r -a SCHEDULERS <<< "${VJ5G_SCHEDULERS:-rr pf mr}"
SIGNAL_NAMES=(bom moderado degradado)
SIGNAL_BOUNDS=(100 250 500)

if ! [[ "$MAX_WORKERS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERRO: VJ5G_MAX_WORKERS deve ser inteiro positivo" >&2
  exit 2
fi
if ! [[ "$MIN_AVAILABLE_GB" =~ ^[0-9]+$ ]]; then
  echo "ERRO: VJ5G_MIN_AVAILABLE_GB deve ser inteiro não negativo" >&2
  exit 2
fi

if [[ -z "$SIM_BINARY" ]]; then
  for candidate in \
    build/scratch/ns3.*-simulacao-vj5g-optimized \
    build/scratch/ns3.*-simulacao-vj5g-default; do
    if [[ -x "$candidate" ]]; then
      SIM_BINARY="$candidate"
      break
    fi
  done
fi
if [[ -z "$SIM_BINARY" || ! -x "$SIM_BINARY" ]]; then
  echo "ERRO: binário simulacao-vj5g não encontrado. Execute ./ns3 build -j 12" >&2
  exit 2
fi
SIM_BINARY=$(realpath "$SIM_BINARY")

mkdir -p "$ROOT/00_metadata"
git rev-parse HEAD > "$ROOT/00_metadata/git_commit.txt"
git status --short --branch > "$ROOT/00_metadata/git_status.txt"
date --iso-8601=seconds > "$ROOT/00_metadata/inicio.txt"
printf '%s\n' "$SIM_BINARY" > "$ROOT/00_metadata/sim_binary.txt"

TOTAL=$((${#SEEDS[@]} * ${#UES_LIST[@]} * ${#SIGNAL_NAMES[@]} * ${#SCHEDULERS[@]}))
MIN_AVAILABLE_KB=$((MIN_AVAILABLE_GB * 1024 * 1024))

wait_for_capacity() {
  while (($(jobs -pr | wc -l) >= MAX_WORKERS)); do
    wait -n || true
  done
  while ((MIN_AVAILABLE_KB > 0)); do
    local available_kb
    available_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    ((available_kb >= MIN_AVAILABLE_KB)) && break
    echo "[MEM] ${available_kb} KiB disponíveis; aguardando limite de ${MIN_AVAILABLE_GB} GiB"
    sleep 10
  done
}

run_one() {
  local seed="$1" ues="$2" signal="$3" bounds="$4" scheduler="$5"
  local run_dir="$ROOT/seed_$(printf '%03d' "$seed")/ue_$(printf '%03d' "$ues")/signal_$signal"
  local mode_dir="$run_dir/$scheduler"
  local window="$mode_dir/window_log.csv"
  local flow="$mode_dir/flow_summary.csv"
  local ue_summary="$mode_dir/ue_summary.csv"
  local log="$mode_dir/ns3.log"
  local success="$mode_dir/SUCCESS"
  local failed="$mode_dir/FAILED"
  mkdir -p "$mode_dir"

  if [[ -s "$success" && -s "$window" && -s "$flow" && -s "$ue_summary" ]]; then
    echo "[SKIP] seed=$seed ues=$ues sinal=$signal scheduler=$scheduler"
    return 0
  fi
  rm -f "$success" "$failed" "$window" "$flow" "$ue_summary"

  local command=(
    "$SIM_BINARY"
    "--schedulerMode=$scheduler" "--trafficProfile=embb" "--ueNumPergNb=$ues"
    "--simTime=$SIM_TIME" "--seed=$seed" "--rngRun=1"
    "--bandwidth=$BANDWIDTH" "--totalTxPower=$TX_POWER"
    "--lambdaOverride=$LAMBDA_OVERRIDE" "--enableMobility=false"
    "--mobilityBounds=$bounds" "--EnableWindowCsv=true"
    "--WindowCsvPath=$window" "--WindowSizeMs=$WINDOW_MS"
    "--EnableFlowSummaryCsv=true" "--FlowSummaryCsvPath=$flow"
    "--EnableUeSummaryCsv=true" "--UeSummaryCsvPath=$ue_summary"
  )
  printf '%q ' "${command[@]}" > "$mode_dir/comando.txt"
  printf '\n' >> "$mode_dir/comando.txt"
  echo "[RUN] seed=$seed ues=$ues sinal=$signal scheduler=$scheduler"

  # O executável é chamado diretamente: evita descoberta/build concorrente
  # pelo front-end ./ns3 quando vários workers iniciam ao mesmo tempo.
  "${command[@]}" > "$log" 2>&1
  local rc=$?
  if ((rc == 0)) && [[ -s "$window" && -s "$flow" && -s "$ue_summary" ]]; then
    date --iso-8601=seconds > "$success"
    echo "[OK] seed=$seed ues=$ues sinal=$signal scheduler=$scheduler"
    return 0
  fi
  printf 'return_code=%s\n' "$rc" > "$failed"
  echo "[FALHA] seed=$seed ues=$ues sinal=$signal scheduler=$scheduler rc=$rc" >&2
  return 1
}

echo "Binário: $SIM_BINARY"
echo "Bateria: $TOTAL simulações; workers=$MAX_WORKERS; reserva=${MIN_AVAILABLE_GB}GiB"
for seed in "${SEEDS[@]}"; do
  for ues in "${UES_LIST[@]}"; do
    for index in "${!SIGNAL_NAMES[@]}"; do
      for scheduler in "${SCHEDULERS[@]}"; do
        wait_for_capacity
        run_one "$seed" "$ues" "${SIGNAL_NAMES[$index]}" \
          "${SIGNAL_BOUNDS[$index]}" "$scheduler" &
      done
    done
  done
done
wait || true

ANALYSIS_FAILURES=0
for seed in "${SEEDS[@]}"; do
  for ues in "${UES_LIST[@]}"; do
    for signal in "${SIGNAL_NAMES[@]}"; do
      run_dir="$ROOT/seed_$(printf '%03d' "$seed")/ue_$(printf '%03d' "$ues")/signal_$signal"
      if ! python3 - "$run_dir" "${SCHEDULERS[@]}" <<'PY'
import sys
from pathlib import Path
import pandas as pd

run_dir = Path(sys.argv[1])
schedulers = sys.argv[2:]
frames = []
for scheduler in schedulers:
    mode_dir = run_dir / scheduler
    path = mode_dir / "window_log.csv"
    if not (mode_dir / "SUCCESS").exists() or not path.is_file():
        raise SystemExit(f"execução incompleta: {scheduler} em {run_dir}")
    frames.append(pd.read_csv(path))
pd.concat(frames, ignore_index=True).to_csv(run_dir / "window_log_combinado.csv", index=False)
PY
      then
        ANALYSIS_FAILURES=$((ANALYSIS_FAILURES + 1))
        continue
      fi
      rm -rf "$run_dir/analise"
      python3 pesquisa/experimentos/analise_vj5g.py \
        --input "$run_dir/window_log_combinado.csv" \
        --output "$run_dir/analise" || ANALYSIS_FAILURES=$((ANALYSIS_FAILURES + 1))
  done; done; done

SUCCESS_COUNT=$(find "$ROOT" -name SUCCESS -type f | wc -l)
FAILED_COUNT=$(find "$ROOT" -name FAILED -type f | wc -l)
date --iso-8601=seconds > "$ROOT/00_metadata/fim.txt"
cat > "$ROOT/00_metadata/resumo.txt" <<EOF
total_planejado=$TOTAL
execucoes_ok=$SUCCESS_COUNT
falhas_simulacao=$FAILED_COUNT
falhas_analise=$ANALYSIS_FAILURES
workers=$MAX_WORKERS
EOF
cat "$ROOT/00_metadata/resumo.txt"
((SUCCESS_COUNT == TOTAL && FAILED_COUNT == 0 && ANALYSIS_FAILURES == 0))
