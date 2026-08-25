# Registro de decisoes metodologicas -- Alfa Dinamico via Fronteira de Pareto
Dissertacao VJ5G -- Julio Henrique da Silva Lopes
Sessao de revisao registrada nesta data.

---

## 1. Normalizacao do ponto de desacordo (Barganha de Nash)

Decisao: o ponto de desacordo usado no criterio de Nash e definido, em cada
janela temporal, pelo minimo do indice de Jain e pelo minimo da vazao
agregada observados entre os escalonadores candidatos NESSA MESMA JANELA
(nao um minimo teorico global nem o maximo do dataset inteiro). Essa
convencao e a mesma ja usada no pipeline Run1-30, garantindo coerencia
entre o resultado preliminar e a versao final da metodologia.

## 2. Escopo da versao atual

Decisao: esta etapa da dissertacao entrega apenas a analise offline
(calculo de metricas por janela, fronteira de Pareto, criterio de Nash,
calibracao do Jmin e avaliacao de violacoes). A camada de controle em
tempo real dentro do escalonador fica registrada como proposta de
trabalho futuro, com as formulas ja especificadas, mas sem implementacao
real no ns-3 nesta versao.

## 3. Escalas temporais de janela

Decisao: o metodo e aplicado nas quatro escalas de janela -- 100ms, 500ms,
1000ms e 2000ms -- todas obtidas por reagregacao dos mesmos dados de slot
ja coletados (sem nova coleta no ns-3). Nao ha necessidade de rodar novas
simulacoes para obter as quatro escalas.

## 4. Regra de desempate da Barganha de Nash

Decisao: quando dois ou mais candidatos empatam no valor do produto de
Nash dentro da mesma janela, o desempate segue, nesta ordem:
  1) maior indice de Jain;
  2) maior vazao agregada;
  3) ponto mais recente (maior tempo/instante da janela).
Essa ordem prioriza justica como criterio central, mantendo o metodo
reprodutivel e auditavel.

## 5. Casos de borda da fronteira de Pareto e da Barganha de Nash

- Pontos exatamente iguais nos dois eixos (Jain e vazao): por definicao,
  nenhum domina o outro, ja que a dominancia exige desigualdade estrita em
  pelo menos um dos dois eixos.
- Comparacoes numericas de dominancia devem usar uma tolerancia minima de
  ponto flutuante, evitando que diferencas irrelevantes de arredondamento
  gerem falsa dominancia.
- Caso todos os candidatos empatem no ponto de desacordo em pelo menos um
  eixo, o produto de Nash zera para todos e a escolha do vencedor cai
  inteiramente na regra de desempate da secao 4.
- Caso exista apenas um ponto na fronteira de Pareto daquela janela, ele e
  selecionado diretamente como vencedor, sem necessidade de calcular o
  produto de Nash.

## 6. Calculo do indice de Jain por janela

Decisao: o indice de Jain de uma janela e calculado sobre a SOMA dos bytes
transmitidos por cada UE ao longo da janela inteira, e nao pela media dos
indices de Jain calculados slot a slot. Essa escolha e uma correcao
metodologica necessaria devido a nao linearidade do indice de Jain --
a media dos Jains por slot nao equivale ao Jain da soma agregada.

Pendencia explicita registrada: validar, a partir do arquivo real de
slot log, se um UE sem trafego em uma janela aparece com valor zero em
sua coluna de vazao ou se e simplesmente omitido do registro daquela
janela. Caso seja omitido, o pipeline de agregacao precisa preencher
esse UE com zero antes do calculo do Jain, ja que excluir silenciosamente
um UE sem trafego alteraria o denominador n do indice de Jain.

## 7. Calibracao do parametro Jmin (estratificada por cenario)

Redacao final acordada:

"A calibracao do parametro Jmin e realizada de forma estratificada por
cenario de simulacao, e nao de maneira global sobre todas as execucoes.
Para cada cenario, trinta runs independentes, variando apenas a semente
do gerador de numeros aleatorios, sao destinadas a etapa de calibracao,
enquanto as setenta restantes compoem o conjunto de validacao. Em cada
run de calibracao, aplica-se o criterio da Barganha de Nash para
selecionar, em cada janela temporal, o ponto de compromisso. Os valores
de Jain desses pontos sao entao usados para estimar o Jmin do cenario
pela mediana, escolhida por ser robusta a valores extremos. Esse desenho
pressupoe que as runs de um mesmo cenario diferem apenas pela
aleatoriedade da semente, mantendo fixos os demais parametros
experimentais."

## 8. Parametro de persistencia maxima (L_max)

Decisao: o limite de persistencia maxima usado para sinalizar alarme na
avaliacao de violacoes do Jmin nao e fixado a priori como parte da
metodologia. Ele e tratado como parametro de analise de sensibilidade,
testado em uma faixa de valores (sugestao inicial: 10% como ponto de
partida) para observar o impacto de diferentes limites de tolerancia
sobre a classificacao das violacoes nas runs de validacao.

---

## Proximos passos

1. Validar a estrutura do slot log real (pendencia da secao 6) antes de
   rodar o pipeline com dados da bateria 3.
2. Ajustar o script `metodo_alfa_dinamico_vj5g.py` para:
   - preencher UEs sem trafego com zero antes do calculo do Jain (sujeito
     ao resultado da validacao acima);
   - adicionar tolerancia de ponto flutuante na comparacao de dominancia
     de Pareto;
   - explicitar no codigo os dois casos de borda da secao 5 (empate total
     e fronteira com ponto unico);
   - alterar `calcular_jmin_calibracao` para agrupar por cenario antes de
     calcular a mediana;
   - transformar o limite de persistencia em parametro de entrada testado
     em faixa de valores, em vez de constante fixa.
3. Apos os ajustes, localizar e apontar os arquivos de slot log da
   bateria 3 no Drive para rodar o pipeline completo.

## Validacao cruzada dos dados reais (ue_summary.csv) -- bateria_3

Objetivo: confirmar que o Jain e a vazao agregada ja calculados pelo
simulador ns-3 e gravados em ue_summary.csv (colunas jain_vazao e
throughput_agregado_mbps) sao consistentes com um recalculo independente
feito a partir do vetor de vazoes individuais por UE daquela execucao.

Metodo de checagem:
- Vazao agregada: soma simples das vazoes individuais de todos os UEs
  da execucao, comparada com throughput_agregado_mbps.
- Jain: recalculado sobre o VETOR de vazoes individuais (formula
  classica J = (soma x)^2 / (n * soma x^2)), nao sobre a soma unica,
  comparado com jain_vazao. Tolerancia adotada: 1e-4.

Amostra avaliada: caso completo (50 UEs, sem truncamento) da execucao
run_001, cenario 50 UEs / raio 500 metros / posicionamento aleatorio
estatico, escalonador Round Robin (RR), semente 1.

Resultado:
- Jain simulador = 0.995946 | Jain recalculado = 0.9959455851841058
  | diferenca = 4.15e-07 | aprovado
- Vazao agregada simulador = 2.93087 Mbps | vazao recalculada =
  2.9308695 Mbps | diferenca = 5.00e-07 Mbps | aprovado

Interpretacao: a diferenca esta na casa de sete casas decimais, ou
seja, e arredondamento de exportacao do proprio simulador, nao erro de
calculo. O caso testado teve todos os 50 UEs com trafego (nenhum UE
zerado), o que tambem valida indiretamente que a formula do Jain usada
pelo simulador trata corretamente o caso sem necessidade de exclusao
de UEs inativos nesse cenario especifico.

Decisao metodologica (24 de agosto de 2026): dado o resultado positivo
neste caso completo, e por recomendacao do orientando, a validacao
cruzada foi encerrada nesta amostra em vez de ser estendida as 100
execucoes da bateria_3. Justificativa: o objetivo da validacao --
confirmar a confiabilidade das colunas jain_vazao e
throughput_agregado_mbps como fonte oficial de metricas agregadas --
foi atingido; validar exaustivamente as 100 execucoes agregaria custo
sem agregar valor metodologico adicional, e desviaria o foco do
verdadeiro ganho metodologico da dissertacao, que esta na analise via
window_log.csv (fronteira de Pareto, Barganha de Nash e calibracao do
Jmin). Uma ressalva fica registrada: se, durante a analise do
window_log, algum cenario ou escalonador apresentar resultado
metodologicamente estranho ou fora do esperado, a checagem cruzada
pode ser retomada pontualmente para aquele caso especifico.

Conclusao: window_log.csv esta confirmado como fonte oficial e
confiavel de Jain e vazao por janela para a analise da fronteira de
Pareto, Barganha de Nash e calibracao do Jmin. Nao ha mais bloqueio
metodologico para iniciar essa etapa.


## Reescrita do bloco de entrada do metodo (window_log como fonte oficial)

Apos a validacao cruzada confirmar que jain_throughput e
aggregate_thr_mbps do window_log.csv sao confiaveis (ver secao
anterior), o script metodo_alfa_dinamico_vj5g.py foi reescrito:

1) A antiga Parte I (metricas_por_janela), que recalculava Jain a
   partir de bytes por UE por slot, foi substituida por
   carregar_window_log: uma funcao que so LE e PADRONIZA o window_log
   ja calculado pelo simulador -- confere colunas esperadas, padroniza
   nomes, e anexa metadados de cenario e run_id. Nenhuma metrica e
   recalculada nessa etapa (Decisao D10).

2) Reagregacao por escala temporal (100/500/1000/2000ms) foi isolada
   em uma funcao propria, reagregar_window_log, que fica fora da
   orquestracao principal. Ela agrupa janelas de 100ms consecutivas e
   agrega aggregate_thr_mbps e jain_throughput pela MEDIA (nao soma,
   pois sao taxas/indices por janela, nao contagens cumulativas).
   Decisao tomada explicitamente para manter o metodo (Pareto + Nash +
   Jmin) agnostico a escala: a orquestracao (rodar_metodo_para_escala)
   sempre recebe um window_log ja pronto na escala desejada e nao
   precisa saber que outras escalas existem. Isso permite testar novas
   escalas no futuro sem tocar no nucleo do algoritmo.

3) As Partes II (fronteira de Pareto), III (Nash com desempate D5 e
   casos de borda D7) e IV (Jmin por cenario D8, violacoes com
   sensibilidade de L_max D9) permanecem sem alteracao de logica --
   apenas passaram a consumir o window_log padronizado em vez de
   metricas recalculadas de slot.

Pipeline testado de ponta a ponta com dados sinteticos nas quatro
escalas (100/500/1000/2000ms), confirmando que a reagregacao e a
orquestracao funcionam de forma independente e correta.

## Retificacao da validacao do window_log legado da Bateria 3

Uma auditoria posterior mostrou que a validacao cruzada registrada acima
confirmou apenas a coerencia entre ue_summary.csv e flow_summary.csv, ambos
derivados do FlowMonitor. Ela nao comparou diretamente os contadores do
window_log.csv e, portanto, nao validou a metrica temporal da Bateria 3.

O codigo usado naquela bateria conectava RxWindowCallback ao trace Rx do
UdpServer e somava todo evento recebido sem identificar a sequencia do
pacote. A comparacao integral das 400 combinacoes run-scheduler revelou
inflacao do numero de pacotes estimado pelo window_log em relacao ao
FlowMonitor: media de 2,78 vezes em RR, 2,83 em PF, 2,83 em QoS e 1,50 em
MR, com 362 de 400 combinacoes acima de 10% de divergencia. O inicio da
primeira janela em 0,5 s nao causa essa diferenca: as aplicacoes iniciam em
0,4 s e a primeira janela de 100 ms fecha corretamente em 0,5 s.

Decisao D11: o window_log legado da Bateria 3 nao pode alimentar resultados
Pareto-Nash. Ele pode ser aberto apenas para testes estruturais e
diagnosticos, mediante autorizacao explicita no codigo. A Bateria 3 continua
util para analisar ue_summary/flow_summary, posicoes, carga e comportamento
dos schedulers, mas suas metricas temporais T x Jain precisam ser regeneradas
com o callback atual.

O callback atual remove duplicatas por (flowIdx, numero de sequencia) e
registra a origem semantica metric_source=app_rx_unique_payload. Em um teste
controlado, a integral ponderada do window_log foi 23,889230769 Mbps, contra
23,8892 Mbps no resumo da aplicacao, e os dois lados contabilizaram exatamente
5.176 pacotes, sem duplicatas. O metodo Python aceita end_time_s como time_s,
valida metric_source e bloqueia logs legados por padrao.

## Diagnostico das perdas elevadas na Bateria 3

A Bateria 3 ofereceu 50 UEs x 500 pacotes/s x 1.500 bytes = 300 Mbps durante
29,6 s, sem periodo de drain. O CSV antigo definiu lost_packets como tx-rx no
instante final; assim, pacotes ainda enfileirados ou em transito foram
classificados como perdidos. Sob carga muito acima do goodput entregue, essa
metrica mede principalmente backlog nao drenado, e nao perda radio isolada.

Os resultados confirmam saturacao: goodput agregado medio de 56,44 Mbps em
MR, 4,44 Mbps em PF, 4,04 Mbps em QoS e 3,79 Mbps em RR. As respectivas
fracoes nao entregues sao coerentes com a carga de 300 Mbps. MR maximiza
vazao privilegiando canais favoraveis, mas deixa em media apenas 24,19 de 50
UEs ativos; PF, QoS e RR atendem todos os UEs, com maior justica, ao custo de
filas extensas e atraso medio proximo de cinco segundos.

Decisao D12: novas campanhas devem separar app_pdr_at_traffic_stop de
app_pdr_total, registrar app_undelivered_at_stop_packets e usar drainTime
explicito. A carga oferecida deve ser reportada junto dos resultados. A
comparacao Pareto-Nash usa exclusivamente throughput de payload unico
recebido pela aplicacao, nao throughput do FlowMonitor nem o log legado.
