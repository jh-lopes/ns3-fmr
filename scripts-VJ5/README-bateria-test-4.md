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
- CQI, MCS e rank médios a partir de `CqiFeedbackTrace`;
- RSRP e RSRQ médios da célula servidora via `ReportUeMeasurements`, sempre
  acompanhados das respectivas contagens de amostras.
- cenário, condição e modelo de canal configuráveis, estado do shadowing e
  quantidade efetiva de RBs por RBG registrados em cada execução.

## Semântica temporal

`--drainTime=0s` é válido e significa encerrar a simulação sem uma fase
adicional de drenagem. Valores negativos são rejeitados. Informar apenas
`--FlowSummaryCsvPath` não ativa a coleta; para gerar esse arquivo numa
execução manual, use também `--EnableFlowSummaryCsv=true`.

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

## Perfis de validação multifluxo

Dois perfis reproduzíveis exercitam a atualização de múltiplos fluxos sem
forçar congestionamento completo:

```bash
# Rápido: 4 UEs, raio de 75 m, 2 fluxos/UE, 1 run e 2 s de tráfego.
python3 scripts-VJ5/bateria_test_4.py --validation-profile quick

# Completo: 8 UEs, raio de 150 m, 3 fluxos/UE, UDP+misto,
# 5 runs pareadas por scheduler e 10 s de tráfego por execução.
python3 scripts-VJ5/bateria_test_4.py --validation-profile complete
```

O perfil rápido valida `ue_summary.csv`, `flow_summary.csv`, `window_log.csv`,
as contagens de fluxos no FlowMonitor, pareamento da topologia, CQI/MCS,
RSRP/RSRQ e reconciliação entre aplicação e FlowMonitor. O perfil completo
repete essas verificações em cinco `rngRun` para RR, PF, MR e QoS.

## Campanha

### Vários fluxos por UE

`--flows-per-ue N` cria `N` fluxos UDP independentes por UE UDP. Em modo
`mixed`, a opção se aplica somente aos UEs pares, destinados a UDP; os UEs
ímpares continuam usando a aplicação HTTP 3GPP. Em modo `http`, o valor é
registrado para proveniência, mas não multiplica as sessões HTTP.

`--lambda-pps` representa pacotes por segundo **por fluxo**. A bateria calcula
a carga UDP como `UEs_UDP × fluxos/UE × lambda × 1500 × 8` e registra
`flows_per_ue` no nome do cenário, metadados, ledger e CSVs do simulador.

```bash
python3 scripts-VJ5/bateria_test_4.py --application-modes udp,mixed \
  --flows-per-ue 3 --lambda-pps 500
```

```bash
python3 scripts-VJ5/bateria_test_4.py \
  --output pesquisa/resultados/4_bateria_test_4 \
  --ue-count 50 \
  --radius-m 500 \
  --lambda-pps 500 \
  --application-modes udp,http,mixed \
  --channel-scenario UMa \
  --channel-condition Default \
  --channel-model ThreeGpp \
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

O shadowing fica ativo por padrão. Use `--disable-shadowing` somente em uma
campanha separada; misturar execuções com e sem shadowing no mesmo cenário
invalida o pareamento estatístico.

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

Valores de rádio ausentes são exportados como `nan`, nunca como zero. RSRQ é
uma exceção deliberada: quando todas as amostras do trace forem zero, o campo
`rsrq_mean_db` fica vazio e `rsrq_available=false`. As
colunas `cqi_samples` e `measurement_samples` permitem distinguir ausência de
trace de uma medição física igual a zero; o ledger informa quantos UEs tiveram
cada família de medida.

No modo HTTP, o trace `Rx` do cliente 3GPP representa fragmentos entregues à
aplicação TCP, não datagramas com `SeqTsHeader`. Por isso, atraso/PDR de
aplicação e igualdade da quantidade de pacotes com o FlowMonitor são critérios
exclusivos do modo UDP. Vazão, Jain e janelas da fase `traffic` continuam sendo
medidos na aplicação em todos os modos; métricas de entrega após `drain` só
devem ser interpretadas para os fluxos UDP.

## Unidade do log de escalonamento

No `slot_log_common.csv`, `allocated_rbg_symbol_units` é o tamanho de
`m_dlRBG`. Como `m_dlRBG` e `m_dlSym` são vetores paralelos, cada entrada
representa um par `(RBG, símbolo OFDM)`, não um RBG de frequência único. Os
agregados usam, portanto, `rbg_symbol_units_total` e
`rb_symbol_units_total`; eles não devem ser descritos como “RBs recebidos”.
