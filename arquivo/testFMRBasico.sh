cd ~/ns3-fmr && source .venv/bin/activate && \
FMR_BASE_DIR=$HOME/ns3-fmr \
FMR_BIN=$HOME/ns3-fmr/build/scratch/ns3.46-fmr-compara-qos-default \
SIM_TIME=5s \
python3 run_fmr.py \
  --run-id teste_baseline \
  --only-bw 100 \
  --only-seed 1 \
  --only-mode rr \
  --plot-groups overview 2>&1 | tail -30
