# Bateria Test 3 — topologia estática aleatória

Esta bateria posiciona os UEs aleatoriamente em um disco a cada `rngRun` e os
mantém parados durante os 30 s simulados. Portanto, ela representa diferentes
**instantâneos de implantação**, e não o deslocamento físico de um mesmo UE.

## Desenho inicial: um único cenário

- UEs: 50;
- raio máximo: 500 m;
- raio mínimo: 10 m;
- largura de banda: 100 MHz;
- tráfego eMBB: 1500 bytes × 1000 pacotes/s = 12 Mbps oferecidos por UE;
- carga total oferecida: 600 Mbps;
- schedulers: RR, PF, MR e QoS;
- mesma `seed` e mesmo `rngRun` para os quatro schedulers (análise pareada);
- nova topologia quando `rngRun` muda;
- 30 replicações mínimas, ampliadas em lotes de 10 até 100 enquanto o IC95%
  relativo de throughput for maior que 5% ou a meia largura absoluta do IC95%
  de Jain for maior que 0,01.

O orquestrador calcula um hash das coordenadas e interrompe a bateria se os
schedulers de um mesmo `rngRun` receberem topologias diferentes. O
`ue_summary.csv` registra `seed`, `rng_run`, modo de posição, limite espacial e
coordenadas iniciais.

Com 50 UEs, a carga de 600 Mbps é superior à vazão agregada de aproximadamente
260--275 Mbps observada nas baterias anteriores. Isso mantém filas ativas e
força concorrência pelos RBGs sem usar o `lambdaOverride=5000`, que ofereceria
3 Gbps e produziria uma sobrecarga excessiva. O raio de 500 m também cria
heterogeneidade de canal suficiente para separar RR, PF, MR e QoS.

Os valores podem ser alterados explicitamente com `--ue-count`, `--radius-m`,
`--bandwidth` e `--lambda-pps`, mas a execução padrão contém apenas o cenário
`static_random_50ues_500m`.

## Validação curta obrigatória

```bash
cd ~/ns3-fmr
./ns3 build -j 12

python3 scripts-VJ5/bateria_test_3.py \
  --output pesquisa/resultados/smoke_test_3 \
  --workers 2 \
  --ue-count 50 \
  --radius-m 500 \
  --bandwidth 100000000 \
  --lambda-pps 1000 \
  --sim-time 2 \
  --min-runs 2 \
  --max-runs 2 \
  --batch-size 2
```

Confira que os hashes são iguais entre schedulers da mesma run e diferentes
entre runs:

```bash
python3 - <<'PY'
import pandas as pd

path = "pesquisa/resultados/smoke_test_3/executions.csv"
data = pd.read_csv(path)
print(data.groupby(["scenario", "rng_run"])["position_hash"].nunique())
print(data.groupby(["scenario", "rng_run"])["position_hash"].first())
PY
```

O primeiro resultado deve ser sempre `1`. No segundo, runs distintas devem ter
hashes distintos.

## Bateria completa

Após validar o smoke test:

```bash
nohup python3 scripts-VJ5/bateria_test_3.py \
  --output pesquisa/resultados/bateria_test_3 \
  --workers 2 \
  --ue-count 50 \
  --radius-m 500 \
  --bandwidth 100000000 \
  --lambda-pps 1000 \
  > pesquisa/resultados/bateria_test_3.log 2>&1 &
```

Comece com dois workers por causa do consumo de memória observado nas baterias
anteriores. A execução pode ser retomada com o mesmo comando e diretório; linhas
`OK` do `executions.csv` são reutilizadas.
