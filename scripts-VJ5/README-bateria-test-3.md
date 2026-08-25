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
- 30 replicações mínimas, ampliadas em lotes de 10 até 100 enquanto o IC95%
  relativo de throughput for maior que 5% ou a meia largura absoluta do IC95%
  de Jain for maior que 0,01.

O orquestrador calcula um hash das coordenadas e interrompe a bateria se os
schedulers de um mesmo `rngRun` receberem topologias diferentes. O
`ue_summary.csv` registra `seed`, `rng_run`, modo de posição, limite espacial e
coordenadas iniciais.

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
Ele valida geração dos CSVs, sintaxe decimal ASCII, limites físicos, `rng_run`,
hash e pareamento da topologia, mas não tem validade estatística e não avalia
convergência. Uma execução com vírgula decimal, valor convertido em data, Jain
fora de `[0,1]` ou coordenada escalada por mil recebe status `ERROR`.

## Importação em Google Sheets

Os arquivos `window_log.csv`, `ue_summary.csv` e `flow_summary.csv` são as
fontes canônicas e usam vírgula como delimitador e ponto como separador
decimal. Antes de importar, configure a planilha como **Estados Unidos** em
`Arquivo > Configurações > Localidade`. Não importe esses CSVs diretamente em
uma planilha `pt_BR`: valores como `0.272873` podem virar `272873` e `1.5` pode
ser interpretado como data. Alterar apenas a aparência depois não recupera o
valor original; nesse caso, reimporte a partir do CSV canônico.

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

### Vários fluxos por UE

Use `--flows-per-ue N` para instalar `N` fluxos UDP independentes em cada UE.
`--lambda-pps` é a taxa **por fluxo**, portanto a carga oferecida é
`UEs × fluxos/UE × lambda × tamanho_do_pacote × 8`. O número de fluxos
faz parte do nome do cenário e do `executions.csv`, evitando misturar campanhas
com cargas distintas.

```bash
python3 scripts-VJ5/bateria_test_3.py --flows-per-ue 2 --lambda-pps 500
```

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
