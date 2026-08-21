# Bateria Test 3 — topologia estática aleatória

Esta bateria posiciona os UEs aleatoriamente em um disco a cada `rngRun` e os
mantém parados durante os 30 s simulados. Portanto, ela representa diferentes
**instantâneos de implantação**, e não o deslocamento físico de um mesmo UE.

## Desenho inicial: um único cenário

- UEs: 50;
- raio máximo: 500 m;
- raio mínimo: 10 m;
- largura de banda: 100 MHz;
- tráfego eMBB: 1500 bytes × 500 pacotes/s = 6 Mbps oferecidos por UE;
- carga total oferecida: 300 Mbps;
- schedulers: RR, PF, MR e QoS;
- mesma `seed` e mesmo `rngRun` para os quatro schedulers (análise pareada);
- nova topologia quando `rngRun` muda;
- 30 replicações mínimas, ampliadas em pontos de inspeção pré-especificados de
  10 em 10 até 100;
- a parada usa os seis contrastes pareados entre schedulers, e não quatro ICs
  marginais: exige meia largura relativa do contraste de throughput de até 5%
  e meia largura absoluta do contraste de Jain de até 0,01;
- o nível de confiança usa o quantil exato de Student e uma correção de
  Bonferroni conjunta para 12 contrastes (seis pares × duas métricas) e para
  todos os pontos de inspeção. Isso preserva o erro familiar de 5% apesar da
  parada sequencial.

O orquestrador calcula um hash das coordenadas e interrompe a bateria se os
schedulers de um mesmo `rngRun` receberem topologias diferentes. O
`ue_summary.csv` registra `seed`, `rng_run`, modo de posição, limite espacial e
coordenadas iniciais.

Ao terminar, `convergence_paired.csv` documenta cada contraste, tamanho
pareado, nível de confiança ajustado, meia largura, limite e decisão. Para não
interpretar Jain isoladamente, execute `analisar_bateria_test_3.py`: ele produz
percentis 5/10 e mediana de vazão por UE, UEs sem vazão, PDR/PLR e caudas de
atraso, recalcula Jain e gera testes pareados com tamanho de efeito e correção
de Holm.

Com 50 UEs, a carga de 300 Mbps fica ligeiramente acima da vazão agregada de
aproximadamente 260--275 Mbps observada nas baterias anteriores. Isso mantém
filas ativas e força concorrência pelos RBGs sem repetir a sobrecarga de 600
Mbps que já produziu PDR baixo e filas de vários segundos, nem usar
`lambdaOverride=5000`, que ofereceria 3 Gbps. O raio de 500 m também cria
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
  --lambda-pps 500 \
  --smoke
```

`--smoke` executa somente uma run de 1 s para cada um dos quatro schedulers.
Ele valida geração dos CSVs, `rng_run`, hash e pareamento da topologia, mas não
tem validade estatística e não avalia convergência.

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

## Análise complementar por UE

```bash
python3 scripts-VJ5/analisar_bateria_test_3.py \
  --input pesquisa/resultados/bateria_test_3/executions.csv \
  --output pesquisa/resultados/bateria_test_3/analysis
```

Artefatos:

- `qualidade_ue_por_run.csv`: métricas de distribuição por run/scheduler;
- `qualidade_ue_resumo_ic95.csv`: médias e IC95% por scheduler;
- `comparacoes_pareadas_ue.csv`: diferenças pareadas, IC95%, Cohen \(d_z\),
  proporção de vitórias e valor-p corrigido por Holm.

## Bateria completa

Após validar o smoke test:

```bash
nohup python3 scripts-VJ5/bateria_test_3.py \
  --output pesquisa/resultados/bateria_test_3 \
  --workers 2 \
  --ue-count 50 \
  --radius-m 500 \
  --bandwidth 100000000 \
  --lambda-pps 500 \
  > pesquisa/resultados/bateria_test_3.log 2>&1 &
```

Comece com dois workers por causa do consumo de memória observado nas baterias
anteriores. A execução pode ser retomada com o mesmo comando e diretório; linhas
`OK` do `executions.csv` são reutilizadas.
