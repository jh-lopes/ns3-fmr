# Fluxos no FMR e no simulador VJ5G

## Implementação de referência

O `scratch/fmr-compara-qos.cc` implementa múltiplos fluxos downlink com quatro
ideias úteis:

1. `numDlFlowsPerUe` é um parâmetro independente da quantidade de UEs;
2. a porta é determinística: `base + ue * fluxos_por_ue + fluxo`;
3. cada UE recebe um `NrEpcTft` com um filtro por porta e ativa o bearer uma
   única vez;
4. tráfego dinâmico mantém a quantidade de fluxos fixa e altera somente o
   intervalo de todos os clientes UDP em cada fase.

## O que foi incorporado ao VJ5G

O VJ5G mantém `flowsPerUe`, a validação do espaço de portas, `flow_index` nos
CSVs e a chave de sequência composta por `(flowIdx, seq)`. Além disso, agora
usa um TFT explícito por UE UDP, filtros com direção `DOWNLINK` e uma ativação
de bearer por UE, seguindo o desenho do FMR.

Os parâmetros existentes `dynamicTraffic`, `phaseDurations` e `phaseLambdas`
deixaram de ser apenas opções inertes. As listas são validadas, definem a
duração total do tráfego e cada lambda é aplicado exclusivamente à coleção de
`UdpClient`; clientes HTTP nunca recebem atributos UDP por engano.

## Diferenças deliberadas

- Em `mixed`, UEs pares usam UDP e UEs ímpares usam HTTP; o TFT explícito por
  porta só se aplica aos UEs UDP. HTTP mantém o TFT padrão porque suas conexões
  TCP usam portas efêmeras.
- O VJ5G preserva métricas canônicas na aplicação, detecção de duplicatas e
  média de atraso por UE ponderada por pacotes. Não reutiliza a média simples
  entre médias de fluxos do FMR.
- `lambdaOverride` é usado no modo estático. Quando `dynamicTraffic=true`, a
  primeira entrada de `phaseLambdas` é a taxa inicial e as fases seguintes a
  substituem.
- A quantidade de fluxos não muda durante uma execução. Isso preserva TFTs,
  portas e pareamento experimental; somente a taxa muda.

## Exemplo

```bash
./ns3 run "scratch/simulacao-vj5g \
  --applicationMode=udp \
  --ueNumPergNb=4 \
  --flowsPerUe=2 \
  --dynamicTraffic=true \
  --phaseDurations=2,2,2 \
  --phaseLambdas=100,250,100 \
  --drainTime=1s"
```

A duração de tráfego resultante é `udpAppStartTime + 6 s`; o drain é somado
depois. O log `[TRAFFIC]` registra início, duração, lambda e total de fluxos
UDP de cada fase.
