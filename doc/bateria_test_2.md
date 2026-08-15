# Bateria Test 2 — replicações progressivas e pareadas

## Desenho experimental

A bateria mantém `seed=1` e varia `rngRun` de 1 até, no máximo, 100. Para um
mesmo cenário e `rngRun`, RR, PF e MR usam o mesmo início de streams aleatórios.
Isso forma blocos pareados e permite calcular diferenças por replicação.

### Fase A — cenário principal estático

- UEs: 5, 10 e 50;
- limite espacial: 100, 250 e 500 m;
- schedulers: RR, PF e MR;
- tráfego: eMBB;
- mobilidade desativada;
- duração: 30 s, com janelas de 100 ms.

### Fase B — sensibilidade à mobilidade

- UEs: 10 e 50;
- limite espacial: 250 m;
- schedulers: RR, PF e MR;
- Random Walk 2D a 3 km/h (0,833333 m/s);
- duração e janelas iguais às da Fase A.

## Regra de parada

Cada cenário começa com 30 runs completos. Depois, o orquestrador acrescenta
lotes de 10 runs até que **todos os três schedulers** satisfaçam simultaneamente:

- IC95% do throughput médio por execução com semilargura relativa de até 5%;
- IC95% do Jain médio por execução com semilargura absoluta de até 0,01.

O limite é 100 runs. A unidade inferencial é o resumo de cada execução; as
janelas correlacionadas são usadas para produzir o ponto descritivo Jain ×
throughput daquela execução, não como replicações independentes.

## Preparação no servidor

Use o Python 3 disponível no ambiente virtual do servidor:

```bash
python3 ./ns3 configure --enable-examples --enable-tests
python3 ./ns3 build simulacao-vj5g
```

Antes de ocupar os workers, confira a matriz sem executar simulações:

```bash
python3 scripts-VJ5/bateria_test_2.py --dry-run
```

Execute toda a bateria com quatro workers:

```bash
python3 scripts-VJ5/bateria_test_2.py --phase all --workers 4
```

Também é possível executar as fases separadamente e retomar posteriormente. O
arquivo `executions.csv` funciona como ledger: combinações concluídas com
sucesso não são repetidas.

```bash
python3 scripts-VJ5/bateria_test_2.py --phase static --workers 4
python3 scripts-VJ5/bateria_test_2.py --phase mobility --workers 4
```

O log nativo de RBG×símbolo é habilitado por padrão. Para um ensaio rápido que
economize disco, use `--no-enable-rbg`. Os arquivos completos de cada execução
ficam sob `pesquisa/resultados/bateria_test_2/<cenario>/run_NNN/<scheduler>/`.

## Consolidação

Depois da bateria, gere os ICs, as diferenças pareadas e as marcações de Pareto
e Nash:

```bash
python3 scripts-VJ5/analisar_bateria_test_2.py
```

Os produtos consolidados são:

- `summary_ic95.csv`: média e semilargura do IC95% por cenário/scheduler;
- `paired_differences.csv`: PF−RR, MR−RR e MR−PF dentro de cada `rngRun`;
- `pareto_nash_by_run.csv`: dominância de Pareto e produto de Nash normalizado;
- `convergence.csv`: diagnóstico que determinou a parada progressiva.

## Instrumentação temporal

Além do `window_log.csv`, cada execução produz `ue_temporal.csv` com `rng_run`,
tempo, janela, scheduler, UE, posição, distância até a gNB e SINR médio do
período. Isso permite relacionar alterações de Jain e throughput à trajetória e
ao canal. O resumo final por UE e o FlowMonitor permanecem disponíveis, e o log
de slots pode ser cruzado com `computar_rbg_por_ue.py`.
