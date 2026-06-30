# O Caminho de um Pacote na Simulação 5G
## Do envio ao recebimento — explicação completa

**Contexto:** dissertação "Uma Análise da Relação entre Vazão e Justiça  
na Divisão de Recursos em Escalonadores de Redes 5G"  
**Autor:** Júlio Henrique da Silva Lopes — UFAC (2026)

---

## Por que entender esse processo?

Na defesa, a banca pode perguntar:
- *"Como você mede a latência?"*
- *"O que é o PDCP Discard Timer?"*
- *"Por que o PLR é a métrica principal para URLLC?"*

Esse documento responde todas essas perguntas.

---

## O caminho completo de um pacote

### Passo 1 — O cliente envia o pacote

O servidor remoto (fonte de conteúdo) gera um pacote UDP
e o envia para o UE com uma taxa definida pelo `lambda`:

```
Servidor remoto
    ↓
Envia pacote de 200 bytes (URLLC)
Timestamp de saída: t = 0ms
```

O FlowMonitor registra o timestamp de saída nesse momento.

---

### Passo 2 — O pacote entra na fila do PDCP

Antes de chegar ao canal de rádio, o pacote passa pela
pilha de protocolos do 5G NR:

```
Servidor → IP → RLC → PDCP → canal de rádio → UE
```

A camada **PDCP (Packet Data Convergence Protocol)**
é responsável por:
- Comprimir cabeçalhos
- Cifrar os dados
- Gerenciar o reordenamento de pacotes
- **Controlar o tempo de vida do pacote (Discard Timer)**

O PDCP funciona como uma **sala de espera** antes do canal
de rádio. O pacote fica aqui até o scheduler decidir
transmiti-lo.

---

### Passo 3 — O scheduler decide quem transmite

A cada **slot de tempo** (0,5ms com numerologia μ=1),
o scheduler MAC olha para as filas de todos os UEs
e decide quem recebe RBGs (blocos de recurso):

```
Slot 1 (t=0,5ms):  scheduler → UE3 recebe RBGs (MCS alto)
                               UE1 aguarda na fila PDCP

Slot 2 (t=1,0ms):  scheduler → UE3 recebe RBGs novamente
                               UE1 continua aguardando

...

Slot N (t=Xms):    scheduler → UE1 finalmente recebe RBGs
                               pacote transmitido pelo rádio
```

Cada scheduler tem uma política diferente para essa decisão:

| Scheduler | Critério de decisão |
|---|---|
| RR | Vez na fila — todos recebem igualmente |
| MR | Maior MCS — prioriza quem tem melhor canal |
| PF | Taxa instantânea / histórico de atendimento |
| QoS | MCS + QCI + HOL delay (delay acumulado na fila) |
| FMR | Estado da rede → modelo RL aprendido offline |

---

### Passo 4 — Dois cenários possíveis

#### Cenário A — SEM Discard Timer

Sem discard timer, o pacote espera **indefinidamente**
na fila do PDCP:

```
t=0ms    → pacote entra na fila do PDCP
t=50ms   → aguardando (scheduler priorizou outros UEs)
t=150ms  → aguardando
t=300ms  → scheduler finalmente transmite o pacote
t=305ms  → pacote chega ao UE

FlowMonitor registra: delay = 305ms, PDR = 100%
```

**Problema:** para URLLC, um pacote com 305ms é inútil.
O requisito é menos de 10ms. O pacote chegou, mas
chegou tarde demais para ser usado pela aplicação.

A métrica de latência fica **distorcida** — parece que
tudo funcionou (PDR=100%), mas na prática a aplicação
URLLC já teria descartado o pacote.

---

#### Cenário B — COM Discard Timer (100ms)

Com `discardTimerMs = 100`, o PDCP inicia um relógio
para cada pacote no momento em que ele entra na fila:

```
t=0ms    → pacote entra na fila, relógio inicia
t=50ms   → aguardando, relógio em 50ms
t=100ms  → TEMPO ESGOTADO
            PDCP descarta o pacote
            pacote nunca chega ao UE

FlowMonitor registra: 1 pacote perdido → PLR aumenta
```

**Vantagem:** o PLR agora reflete a **realidade da aplicação**
URLLC — se o scheduler não conseguiu transmitir dentro
do delay budget, o pacote é contado como perdido.

---

### Passo 5 — O FlowMonitor coleta as métricas

O FlowMonitor intercepta cada pacote em dois momentos:

```
Saída do servidor  → timestamp_tx
Chegada no UE      → timestamp_rx

delay = timestamp_rx - timestamp_tx
```

Ao final da simulação, para cada fluxo, calcula:

| Métrica | Cálculo | Relevância |
|---|---|---|
| Throughput | bytes_rx × 8 / tempo | eMBB |
| Delay médio | Σ delay / n_pacotes | URLLC |
| Delay p99 | percentil 99 dos delays | URLLC crítico |
| Jitter | variação entre delays consecutivos | URLLC |
| PLR | pacotes_perdidos / pacotes_enviados | URLLC |
| PDR | pacotes_recebidos / pacotes_enviados | Todos |

---

## Fluxo completo resumido

```
Servidor envia pacote (timestamp_tx)
          ↓
PDCP recebe → inicia relógio (se discardTimer ativo)
          ↓
Pacote aguarda na fila
          ↓
Scheduler aloca RBGs a cada slot (0,5ms)
          ↓
    ┌─────────────────────────────────────┐
    │ Transmitido antes do deadline?      │
    │                                     │
    │  SIM → rádio transmite             │
    │        UE recebe (timestamp_rx)     │
    │        FlowMonitor: delay, PDR      │
    │                                     │
    │  NÃO → PDCP descarta               │
    │  (discardTimer expirou)             │
    │        FlowMonitor: PLR +1          │
    └─────────────────────────────────────┘
```

---

## Por que UDP e não TCP?

**TCP** tem mecanismos que interferem na comparação:
- Controle de congestionamento → reduz taxa automaticamente
- Retransmissão → reenvia pacotes perdidos
- ACKs → confirmações de recebimento

Com TCP, se o scheduler MR causa starvation no UE1,
o TCP *reduz automaticamente a taxa* para compensar.
Você não consegue separar o efeito do scheduler
do efeito do protocolo de transporte.

**UDP é controlado** — você define exatamente `lambda`
pacotes por segundo com `pacoteBytes` bytes. O resultado
é 100% atribuível ao scheduler.

---

## O que o PDCP Discard Timer prova na dissertação

Com discard timer ativo no perfil URLLC, você pode
mostrar com dados:

```
MR:   PLR alto para UEs distantes
      → ignora UEs com canal ruim
      → inadequado para URLLC

QoS:  PLR baixo para todos os UEs
      → considera QCI e delay budget
      → adequado para URLLC

RR:   PLR médio — distribui igualmente mas sem prioridade
PF:   PLR médio — considera histórico mas não QCI
FMR:  PLR a ser avaliado — política aprendida por RL
```

**Isso responde diretamente à crítica do Prof. Igor:**
*"você roda uma aplicação URLLC e prova qual scheduler
é melhor — com dados, não sentimento."*

---

## Glossário rápido

| Termo | Significado |
|---|---|
| PDCP | Packet Data Convergence Protocol — camada de protocolo 5G |
| Discard Timer | Tempo máximo que um pacote pode ficar na fila |
| Delay Budget | Latência máxima tolerável pela aplicação |
| PLR | Packet Loss Ratio — fração de pacotes perdidos |
| PDR | Packet Delivery Ratio — fração de pacotes entregues |
| HOL Delay | Head-of-Line delay — tempo do pacote mais antigo na fila |
| QCI | QoS Class Identifier — define a prioridade do bearer |
| Bearer | Canal lógico com QoS garantido entre UE e rede |
| RBG | Resource Block Group — unidade de alocação de recursos |
| MCS | Modulation and Coding Scheme — eficiência espectral |
| λ (lambda) | Taxa de chegada de pacotes (pacotes/segundo) |
