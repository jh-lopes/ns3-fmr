# Bateria de Teste 4 — instrumentação corrigida

A Bateria 4 repete o cenário eMBB pareado de 50 UEs corrigindo as limitações
identificadas na Bateria 3.

Ela também executa três cargas de aplicação independentes: `udp`, `http`
(modelo web browsing 3GPP sobre TCP) e `mixed`, no qual UEs pares usam UDP e
UEs ímpares usam HTTP. Cada carga possui seu próprio conjunto pareado de runs;
resultados de aplicações diferentes não são tratados como replicações.

## Correções incorporadas

- posições estáticas uniformes **por área** no anel de 10 m ao raio configurado;
- métricas canônicas coletadas na aplicação (`UdpServer` ou cliente HTTP 3GPP);
- detecção de duplicatas por `(UE, fluxo, sequência)`;
- atraso médio e p99 calculados com `SeqTsHeader` na aplicação;
- clientes param no fim da fase de tráfego e servidores permanecem durante o drain;
- `MaxPerHopDelay` maior que toda a execução, evitando censura do FlowMonitor;
- reconciliação obrigatória entre pacotes do UdpServer e do FlowMonitor;
- janelas completas, incluindo a última janela parcial e a fase `drain`;
- `metadata.json`, hash do binário, commit Git e comando integral por execução;
- nomes explícitos para métricas de aplicação e FlowMonitor.

## Semântica temporal

Por padrão:

- aplicações começam em `0,4 s`;
- clientes geram tráfego até `30 s`;
- servidores continuam ativos por `15 s` de drain;
- simulação termina em `45 s`;
- `FlowMaxPerHopDelay=60 s`.

As janelas possuem uma coluna `phase`:

- `traffic`: janela iniciada antes da parada dos clientes;
- `drain`: janela posterior, sem novas transmissões.

Pareto/Nash deve usar somente `phase=traffic`. O drain serve para medir entrega
eventual e reconciliar os instrumentos.

## Smoke test

```bash
python3 scripts-VJ5/bateria_test_4.py --smoke --no-progress
```

O smoke executa uma run de 1 s de tráfego + 1 s de drain para RR, PF, MR e
QoS nos modos UDP, HTTP e misto. Para testar apenas UDP, acrescente
`--application-modes udp`.

## Campanha

```bash
python3 scripts-VJ5/bateria_test_4.py \
  --output pesquisa/resultados/4_bateria_test_4 \
  --ue-count 50 \
  --radius-m 500 \
  --lambda-pps 500 \
  --application-modes udp,http,mixed \
  --sim-time 30 \
  --drain-time 15 \
  --flow-max-per-hop-delay 60 \
  --window-ms 100 \
  --min-runs 30 \
  --max-runs 100 \
  --batch-size 10 \
  --workers 2
```

O runner pode ser interrompido e retomado com o mesmo `--output`; execuções
`OK` existentes não são repetidas.

## Arquivos por execução

```text
run_NNN/scheduler/
├── command.txt
├── console.log
├── metadata.json
├── flow_summary.csv
├── ue_summary.csv
└── window_log.csv
```

## Critérios de falha automática

Uma execução é marcada como erro se ocorrer qualquer um dos casos:

- UE ausente/duplicado;
- posição fora do anel ou distância matematicamente inconsistente;
- pacote duplicado na aplicação;
- divergência entre pacotes recebidos pelo UdpServer e FlowMonitor;
- janela ausente, duplicada, com duração não positiva ou Jain inválido;
- `rng_run` divergente.

## Métricas principais

Para vazão e justiça durante a carga, use:

- `app_throughput_traffic_mbps`;
- `app_jain_traffic`;
- janelas `phase=traffic`.

Para entrega eventual após o drain, use:

- `app_goodput_total_mbps`;
- `app_jain_total`;
- `app_pdr_total_pct`.

As colunas `flowmon_*` são mantidas como instrumento de reconciliação e não
como fonte principal da análise.

No modo HTTP, o trace `Rx` do cliente 3GPP representa fragmentos entregues à
aplicação TCP, não datagramas com `SeqTsHeader`. Por isso, atraso/PDR de
aplicação e igualdade da quantidade de pacotes com o FlowMonitor são critérios
exclusivos do modo UDP. Vazão, Jain e janelas da fase `traffic` continuam sendo
medidos na aplicação em todos os modos; métricas de entrega após `drain` só
devem ser interpretadas para os fluxos UDP.
