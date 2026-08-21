# Plano — `bateria_test_4_Perfis_Qos`

## Pergunta de pesquisa

Em que condições o scheduler QoS preserva os requisitos de cada perfil melhor
que RR, PF e MR, e qual é o custo dessa preservação em vazão agregada e justiça?

## Hipóteses

1. QoS reduz atraso de cauda e violações do perfil sensível a latência.
2. MR maximiza vazão agregada, mas piora percentis inferiores e justiça.
3. PF oferece um compromisso em tráfego homogêneo; a vantagem de QoS aumenta
   quando perfis heterogêneos disputam os mesmos RBGs.

## Pré-requisito: auditoria e extensão do simulador

O CLI atual aceita um único `--trafficProfile` para toda a execução. Antes da
fase heterogênea, implementar uma atribuição explícita por UE/fluxo, por
exemplo `--profileMix=embb:20,urllc:20,mmtc:10`. O simulador deverá registrar em
`flow_summary.csv` e `ue_summary.csv` o perfil real, 5QI, prioridade, PDB e taxa
oferecida de cada fluxo. Um teste deverá provar que os quatro schedulers usam a
mesma mistura, topologia e streams em cada `rngRun`.

## Desenho em duas fases

### Fase A — calibração homogênea

- Cenário físico fixo: 50 UEs, raio radial uniforme de 10--500 m, 100 MHz,
  30 s e topologia estática.
- Perfis separados: 100% eMBB, 100% URLLC e 100% mMTC.
- Schedulers: RR, PF, MR e QoS.
- Objetivo: verificar a implementação dos perfis e identificar uma carga por
  perfil que cause concorrência sem colapso generalizado.
- Fazer 10 runs de calibração por célula; essas runs não entram na inferência
  confirmatória.

### Fase B — campanha confirmatória heterogênea

Usar três misturas pré-especificadas, mantendo 50 UEs:

| Mistura | eMBB | URLLC | mMTC | Finalidade |
|---|---:|---:|---:|---|
| Balanceada | 20 | 20 | 10 | comparação geral |
| eMBB dominante | 30 | 10 | 10 | custo de proteger baixa latência |
| URLLC dominante | 10 | 30 | 10 | estresse de requisitos de atraso |

Executar 30 runs pareadas fixas por mistura. Só aumentar para 50 runs se uma
análise de precisão, definida antes da campanha confirmatória, indicar ICs
insuficientes. Não reutilizar as runs de calibração.

## Variáveis controladas

- mesma `seed`, `rngRun`, topologia, mistura e streams entre schedulers;
- mesma carga oferecida por perfil e mesmo período de aquecimento;
- mesmo modelo de propagação, numerologia, TDD, potência e largura de banda;
- um único processo orquestrador por diretório de saída;
- hash de posições e hash da atribuição perfil--UE em cada run.

## Desfechos primários (definidos antes da execução)

1. URLLC: atraso p99 e proporção de fluxos que violam o PDB;
2. eMBB: vazão agregada e percentil 5 da vazão por UE;
3. mMTC: PDR e proporção de UEs sem entrega;
4. rede: eficiência espectral e Jain, sempre acompanhado de mediana, p5/p10,
   UEs com vazão zero, PDR, PLR e atraso de cauda.

## Inferência

- unidade amostral: `rngRun`, nunca janela de 100 ms;
- contrastes pareados entre os seis pares de schedulers;
- IC de Student exato para a média das diferenças;
- Cohen \(d_z\), proporção de vitórias e valor-p do teste t pareado;
- correção de Holm por família de desfechos;
- declarar separadamente análise exploratória de métricas não primárias.

## Critérios de validade

- quatro schedulers concluídos para toda run incluída;
- hashes de posição e mistura iguais dentro da run e distintos entre runs;
- nenhum CSV vazio, duplicado ou com `rng_run` divergente;
- Jain recalculado a partir dos UEs dentro de tolerância numérica;
- carga efetivamente oferecida e recebida auditada por perfil;
- smoke test de 1 s e piloto de 3 runs antes da campanha confirmatória.

## Volume previsto

Fase confirmatória mínima: $3$ misturas $\times 30$ runs $\times 4$
schedulers = **360 simulações**. A Fase A de calibração acrescenta
$3\times10\times4=120$ simulações, totalizando 480 antes de eventuais runs de
precisão. Recomenda-se executar cada mistura em diretório independente.

## Entregáveis

- `bateria_test_4_Perfis_Qos.py` e testes unitários;
- manifesto imutável da configuração e versões do ns-3/5G-LENA;
- `executions.csv`, hashes e relatório de qualidade;
- tabelas por perfil e contrastes pareados;
- gráficos de ECDF, atraso p99, p5 de vazão, PDR e Pareto multiobjetivo;
- seção metodológica em LaTeX e registro explícito de exclusões/falhas.
