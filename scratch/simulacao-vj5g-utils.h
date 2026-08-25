// ============================================================
// simulacao-vj5g-utils.h
//
// Funções e estruturas auxiliares usadas por
// simulacao-vj5g.cc — separadas em header para manter
// o arquivo principal mais enxuto e organizado por
// responsabilidade.
//
// Conteúdo deste arquivo:
//   - struct PerfilDeTrafego + ObterPerfilDeTrafego()
//     (perfis eMBB, URLLC, mMTC)
//   - g_sinrAcumulado + SinrCallback()
//     (coleta de SINR por UE via trace do PHY)
//   - g_bytesRecebidosPorUe + RxWindowCallback() + RegistrarJanela()
//     (log de throughput/Jain por janela — Bloco 6B, alimenta os
//     Pilares 1 e 2 do alfa dinâmico via Fronteira de Pareto)
//
// Autor: Júlio Henrique da Silva Lopes — UFAC (2026)
// ============================================================

#ifndef SIMULACAO_VJ5G_UTILS_H
#define SIMULACAO_VJ5G_UTILS_H

#include "ns3/core-module.h"
#include "ns3/nr-module.h"
#include "ns3/histogram.h"
#include "ns3/seq-ts-header.h"
#include <chrono>
#include <algorithm>
#include <cmath>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

using namespace ns3;

// ============================================================
// BLOCO 2: PERFIS DE TRÁFEGO
//
// Cada perfil representa um caso de uso 5G distinto,
// baseado nas especificações 3GPP TR 38.913 V17.0.0.
// ============================================================

// ------------------------------------------------------------
// Struct PerfilDeTrafego
//
// Agrupa todos os parâmetros que definem como o tráfego UDP
// é gerado para cada caso de uso 5G.
// ------------------------------------------------------------
struct PerfilDeTrafego
{
    std::string nome;        // Identificador do perfil
    std::string descricao;   // Descrição para o CSV de saída
    uint32_t pacoteBytes;    // Tamanho do pacote UDP em bytes
    uint32_t lambda;         // Taxa de envio em pacotes/segundo
    uint32_t flowsPorUe;     // Número de fluxos UDP por UE
    NrEpsBearer::Qci bearerQci;  // QCI do bearer EPS (define prioridade)
    uint32_t discardTimerMs; // PDCP discard timer em ms (0 = desativado)
};

// ------------------------------------------------------------
// ObterPerfilDeTrafego()
//
// Recebe o nome do perfil via parâmetro e retorna a
// configuração correspondente.
//
// Justificativas dos parâmetros por perfil:
//
// eMBB (Enhanced Mobile Broadband):
//   - 1500 bytes: MTU típica de vídeo HD
//   - lambda=1000: ~12 Mbps por fluxo, estressando a rede
//   - 2 fluxos/UE: simula vídeo + dados simultâneos
//   - NGBR_LOW_LAT_EMBB (QCI 70): Non-GBR, baixa latência
//   - Sem discard: eMBB tolera variação de delay
//   Referência: 3GPP TR 38.913 Tabela 7.1
//
// URLLC (Ultra-Reliable Low-Latency Communications):
//   - 200 bytes: pacote de controle típico (telemetria)
//   - lambda=500: carga média-alta para estressar scheduler
//   - 1 fluxo/UE: canal de controle por dispositivo
//   - GBR_CONV_VOICE (QCI 1): GBR, prioridade máxima,
//     delay budget 100ms, packet error rate 10^-2
//   - discardTimerMs=100: descarta pacotes > 100ms
//   Referência: 3GPP TS 22.261 Tabela 5.2-1
//
// mMTC (Massive Machine-Type Communications):
//   - 100 bytes: sensor/telemetria (temperatura, GPS)
//   - lambda=10: tráfego esporádico, ~8 kbps/dispositivo
//   - 1 fluxo/UE: um canal por sensor
//   - NGBR_VIDEO_TCP_DEFAULT (QCI 9): best effort
//   - Sem discard: mMTC não tem requisito crítico de latência
//   Referência: 3GPP TR 38.913 Tabela 7.2
// ------------------------------------------------------------
inline PerfilDeTrafego
ObterPerfilDeTrafego(const std::string& trafficProfile)
{
    // Normaliza para minúsculas — evita erro por capitalização
    // (ex: "EMBB" e "embb" funcionam igualmente)
    std::string perfil = trafficProfile;
    std::transform(perfil.begin(), perfil.end(),
                   perfil.begin(), ::tolower);

    if (perfil == "embb")
    {
        return {
            "embb",
            "Enhanced Mobile Broadband - foco em vazão (vídeo HD)",
            1500,                            // pacoteBytes
            1000,                            // lambda (pkt/s)
            1,                               // flowsPorUe
            NrEpsBearer::NGBR_LOW_LAT_EMBB, // QCI 70
            0                                // sem discard
        };
    }

    if (perfil == "urllc")
    {
        return {
            "urllc",
            "Ultra-Reliable Low-Latency - foco em latência e confiabilidade",
            200,                             // pacoteBytes
            500,                             // lambda (pkt/s)
            1,                               // flowsPorUe
            NrEpsBearer::GBR_CONV_VOICE,     // QCI 1 — prioridade máxima
            100                              // discardTimerMs = delay budget URLLC
        };
    }

    if (perfil == "mmtc")
    {
        return {
            "mmtc",
            "Massive Machine-Type Comms - IoT massivo, tráfego esporádico",
            100,                                // pacoteBytes
            10,                                 // lambda (pkt/s)
            1,                                  // flowsPorUe
            NrEpsBearer::NGBR_VIDEO_TCP_DEFAULT, // QCI 9 — best effort
            0                                   // sem discard
        };
    }

    // Perfil não reconhecido: aborta com mensagem clara
    NS_ABORT_MSG("trafficProfile inválido: '" << trafficProfile
        << "'. Opções válidas: embb | urllc | mmtc");

    // Nunca alcançado — suprime warning de retorno
    return {};
}

// ============================================================
// BLOCO 6A: COLETA DE SINR POR UE
//
// Contribuição original — não implementado no
// fmr-compara-qos.cc do Diego.
//
// Definidas neste header (escopo global) porque o callback
// é registrado durante a simulação (Bloco 6, em
// simulacao-vj5g.cc) e precisa de uma variável
// acessível tanto pelo callback quanto pelo main() ao final
// da simulação para calcular as médias por UE.
// ============================================================

// Armazena acumulado de SINR por ÍNDICE DO UE (ueIdx, a ordem de criação
// do nó — a mesma usada em todo o resto do código: distanciasUe[ueIdx],
// resumoPorUe[ueIdx] etc).
//
// CORREÇÃO (12/ago/2026): antes essa tabela era indexada por RNTI, com
// o código de leitura assumindo rnti = ueIdx + 1. Um diagnóstico real
// (rodada com 10 UEs) mostrou que os RNTIs de verdade, atribuídos pela
// RRC do 5G-LENA, NÃO são sequenciais a partir de 1 — nessa rodada saíram
// "1 2 3 4 5 6 11 12 13 14" (pulou de 6 para 11). Isso fazia os primeiros
// UEs acertarem por coincidência e os últimos lerem SINR errado (ou 0,
// quando o RNTI assumido nem existia no mapa). A correção conecta o
// trace com MakeBoundCallback, amarrando o ueIdx real no momento da
// conexão (ver Bloco 6.1 em simulacao-vj5g.cc) — não depende mais de
// nenhuma suposição sobre a numeração de RNTI.
// Mapa: ueIdx → {soma_sinr_db, contagem_amostras}
inline std::map<uint32_t, std::pair<double, uint32_t>> g_sinrAcumulado;

// NOVO (12/ago/2026): mapa ueIdx → RNTI real, populado no mesmo lugar
// (SinrCallback), que já recebe os dois valores de forma confiável. Serve
// pra exportar o RNTI de cada UE no ue_summary.csv, permitindo cruzar
// (em pós-processamento Python) com o log nativo do 5G-LENA
// slot_log_common.csv (--EnableCommonSlotCsv), que é indexado por RNTI e
// tem o RBG alocado por UE por slot — sem repetir o erro antigo de
// assumir rnti = ueIdx + 1.
inline std::map<uint32_t, uint16_t> g_ueIdxParaRnti;

// Ponto de início da simulação em tempo real (wall-clock).
// Preenchido em main() antes do Simulator::Run().
// Usado pela barra de progresso para mostrar tempo real decorrido.
inline std::chrono::steady_clock::time_point g_inicioReal;

// ------------------------------------------------------------
// ExibirBarraDeProgresso()
//
// Agendada recursivamente a cada 100ms de tempo simulado via
// Simulator::Schedule. Imprime na mesma linha (\r) sem criar
// novas linhas — atualiza a barra visualmente no terminal.
// Inclui tempo real decorrido (wall-clock) além do progresso
// percentual do tempo simulado.
// ------------------------------------------------------------
inline void
ExibirBarraDeProgresso(Time simTime)
{
    double tempoAtual = Simulator::Now().GetSeconds();
    double tempoTotal = simTime.GetSeconds();
    double progresso  = tempoTotal > 0.0
                        ? std::min(tempoAtual / tempoTotal, 1.0)
                        : 1.0;

    // Tempo real decorrido desde o início da simulação
    auto agora = std::chrono::steady_clock::now();
    double segundosReais = std::chrono::duration<double>(
        agora - g_inicioReal).count();

    const int largura = 38;
    int posicao = static_cast<int>(largura * progresso);

    std::cout << "\r[VJ5G] [";
    for (int i = 0; i < largura; ++i)
    {
        if      (i < posicao)  std::cout << "=";
        else if (i == posicao) std::cout << ">";
        else                   std::cout << " ";
    }
    std::cout << "] "
              << std::setw(3) << static_cast<int>(progresso * 100.0)
              << "% | sim="
              << std::fixed << std::setprecision(1)
              << tempoAtual << "s | real="
              << std::setprecision(0) << segundosReais << "s"
              << std::flush;

    // Agenda a próxima atualização se ainda há tempo simulado restante
    if (Simulator::Now() + MilliSeconds(100) < simTime)
    {
        Simulator::Schedule(MilliSeconds(100),
                            &ExibirBarraDeProgresso, simTime);
    }
}

// Garante que a barra termine visualmente em 100%
inline void
ImprimirBarraDeProgressoFinal()
{
    auto agora = std::chrono::steady_clock::now();
    double segundosReais = std::chrono::duration<double>(
        agora - g_inicioReal).count();

    const int largura = 38;
    std::cout << "\r[VJ5G] [";
    for (int i = 0; i < largura; ++i) std::cout << "=";
    std::cout << "] 100%"
              << " | real=" << std::fixed << std::setprecision(0)
              << segundosReais << "s" << std::endl;
}

// Linha separadora visual para o relatório de console
inline void
ImprimirSeparador(char c = '-', int largura = 52)
{
    for (int i = 0; i < largura; ++i) std::cout << c;
    std::cout << std::endl;
}

// ------------------------------------------------------------
// SinrCallback()
//
// Conectada a cada UE PHY via MakeBoundCallback(&SinrCallback, ueIdx)
// + TraceConnectWithoutContext (ver Bloco 6.1 em simulacao-vj5g.cc).
// Chamada a cada slot de simulação. Acumula o SINR em escala linear
// e converte para dB ao final.
//
// Parâmetros:
//   ueIdx  → índice real do UE (amarrado via MakeBoundCallback no
//            momento da conexão do trace — NÃO é o RNTI, e não
//            depende de nenhuma suposição sobre numeração de RNTI)
//   cellId → ID da célula (não usado aqui)
//   rnti   → identificador RNTI do UE na célula (não usado aqui —
//            mantido só porque faz parte da assinatura do trace source)
//   sinr   → valor do SINR em escala linear
//   bwpId  → ID da BWP (não usado aqui)
// ------------------------------------------------------------
inline void
SinrCallback(uint32_t ueIdx,
             uint16_t cellId,
             uint16_t rnti,
             double   sinr,
             uint16_t bwpId)
{
    // Converte SINR linear para dB
    // Fórmula: SINR_dB = 10 * log10(SINR_linear)
    double sinrDb = 10.0 * std::log10(sinr);

    // Acumula soma e contagem para cálculo da média posterior
    g_sinrAcumulado[ueIdx].first  += sinrDb;
    g_sinrAcumulado[ueIdx].second += 1;

    // Registra a correspondência ueIdx → RNTI real (idempotente — o RNTI
    // de um UE não muda durante a simulação, sobrescrever com o mesmo
    // valor a cada amostra não tem custo relevante).
    g_ueIdxParaRnti[ueIdx] = rnti;
}

// Declaração antecipada — a implementação está no Bloco 7A,
// mais abaixo neste arquivo. RegistrarJanela() (Bloco 6B) reusa
// esta função para não duplicar a fórmula de Jain entre a
// métrica agregada de fim de simulação e a métrica por janela.
inline double CalcularJainVazao(const std::vector<double>& throughputs);

// ============================================================
// BLOCO 6B: LOG POR JANELA DE TEMPO (throughput + Jain)
//
// Adicionado para viabilizar a "parte prática" combinada na
// sessão: os Pilares 1 e 2 do alfa dinâmico via Fronteira de
// Pareto (ver registro-sessao-alfa-dinamico-vj5g.md no projeto).
//
//   - Pilar 2 (ranqueamento por perfil eMBB): precisa contar
//     quantas vezes cada scheduler atinge um ponto não-dominado
//     na fronteira T×J. Isso exige uma série de pontos (T,J) por
//     JANELA, não só o par agregado de fim de simulação que o
//     Bloco 7 já produz.
//   - Pilar 1 (alfa dinâmico): precisa da mesma série T×J por
//     janela para prototipar, em Python, o recálculo da fronteira
//     e o critério de Nash — ANTES de portar a lógica para dentro
//     de um scheduler C++ novo no contrib/nr.
//
// Diferença deliberada em relação ao SlotCsv já existente: aquele
// é um atributo interno da classe NrMacSchedulerOfdmaFmr (só
// existe para schedulerMode=fmr_rl). Este log é observacional —
// mede o que CHEGOU no UdpServer de cada UE via trace "Rx" — e
// por isso funciona para QUALQUER schedulerMode (rr/pf/mr/qos/
// fmr_rl) sem depender de nada interno ao scheduler.
// ============================================================

// Bytes recebidos acumulados por UE (soma de todos os flows do
// UE) desde o início da simulação. Redimensionado em main()
// logo após a criação dos UEs (Bloco 3.2).
struct AppRxStats
{
    uint64_t totalUniquePackets = 0;
    uint64_t totalBytes = 0;
    uint64_t trafficUniquePackets = 0;
    uint64_t trafficBytes = 0;
    uint64_t duplicatePackets = 0;
    uint64_t malformedPackets = 0;
    double delaySumMs = 0.0;
    std::vector<double> delaysMs;
};

inline std::vector<uint64_t> g_bytesRecebidosPorUe;
inline std::vector<uint64_t> g_pacotesRecebidosPorUe;
inline std::vector<AppRxStats> g_appRxStats;
inline std::vector<std::set<uint64_t>> g_sequenciasRecebidasPorUe;
inline Time g_trafficStopTime = Seconds(0);

// Snapshot do acumulado no fechamento da última janela — usado
// para isolar o delta de bytes recebidos DENTRO da janela atual.
inline std::vector<uint64_t> g_bytesRecebidosUltimaJanela;
inline std::vector<uint64_t> g_pacotesRecebidosUltimaJanela;

// CSV de saída do log por janela. Global porque é escrito tanto
// pelo callback periódico (RegistrarJanela) quanto fechado ao
// final em main() — mesmo padrão de g_sinrAcumulado.
inline std::ofstream g_windowCsv;

// Contador de janelas já processadas nesta simulação.
// Reiniciado implicitamente a cada execução do binário (processo
// novo por rodada — não há necessidade de reset manual).
inline uint32_t g_janelaId = 0;
inline Time g_inicioUltimaJanela = Seconds(0);

// ------------------------------------------------------------
// RxWindowCallback()
//
// Conectada ao trace "Rx" de cada UdpServer instalado (um por
// UE por flow — ver Bloco 5.2 em simulacao-vj5g.cc). O índice
// do UE (ueIdx) é fixado no momento da conexão via
// MakeBoundCallback.
//
// Assinatura corrigida: o trace "Rx" do ns3::UdpServer nesta
// versão do ns-3 (5G-LENA NR v4.1 / ns-3.46) dispara com um
// único argumento — Ptr<const Packet> — sem o endereço de
// origem. A versão anterior desta função declarava um segundo
// parâmetro (const Address&) que não existe na TracedCallback
// real, causando erro de tipo incompatível em tempo de execução
// ("Incompatible types... CallbackImpl<void,Ptr<Packet const>>").
// ------------------------------------------------------------
inline void
RxWindowCallback(uint32_t ueIdx, uint32_t flowIdx, Ptr<const Packet> packet)
{
    if (ueIdx >= g_bytesRecebidosPorUe.size())
    {
        return;
    }

    Ptr<Packet> copy = packet->Copy();
    SeqTsHeader seqTs;
    if (copy->RemoveHeader(seqTs) == 0)
    {
        ++g_appRxStats[ueIdx].malformedPackets;
        return;
    }

    const uint64_t sequenceKey =
        (static_cast<uint64_t>(flowIdx) << 32) | seqTs.GetSeq();
    if (!g_sequenciasRecebidasPorUe[ueIdx].insert(sequenceKey).second)
    {
        ++g_appRxStats[ueIdx].duplicatePackets;
        return;
    }

    const uint64_t packetBytes = packet->GetSize();
    const double delayMs =
        std::max(0.0, (Simulator::Now() - seqTs.GetTs()).GetSeconds() * 1000.0);

    ++g_pacotesRecebidosPorUe[ueIdx];
    g_bytesRecebidosPorUe[ueIdx] += packetBytes;
    ++g_appRxStats[ueIdx].totalUniquePackets;
    g_appRxStats[ueIdx].totalBytes += packetBytes;
    g_appRxStats[ueIdx].delaySumMs += delayMs;
    g_appRxStats[ueIdx].delaysMs.push_back(delayMs);

    if (Simulator::Now() <= g_trafficStopTime)
    {
        ++g_appRxStats[ueIdx].trafficUniquePackets;
        g_appRxStats[ueIdx].trafficBytes += packetBytes;
    }
}

// O modelo HTTP 3GPP usa TCP e não carrega SeqTsHeader. Nesse caso, o trace
// Rx do cliente representa bytes já entregues à aplicação (retransmissões TCP
// não aparecem novamente), mas não permite reconstruir atraso/PDR por objeto.
inline void
RxHttpCallback(uint32_t ueIdx, Ptr<const Packet> packet)
{
    if (ueIdx >= g_bytesRecebidosPorUe.size())
    {
        return;
    }
    const uint64_t bytes = packet->GetSize();
    ++g_pacotesRecebidosPorUe[ueIdx];
    g_bytesRecebidosPorUe[ueIdx] += bytes;
    ++g_appRxStats[ueIdx].totalUniquePackets;
    g_appRxStats[ueIdx].totalBytes += bytes;
    if (Simulator::Now() <= g_trafficStopTime)
    {
        ++g_appRxStats[ueIdx].trafficUniquePackets;
        g_appRxStats[ueIdx].trafficBytes += bytes;
    }
}

// ------------------------------------------------------------
// RegistrarJanela()
//
// Agendada recursivamente a cada windowSize de tempo simulado
// (mesmo padrão recursivo de ExibirBarraDeProgresso). Calcula,
// para a janela que acabou de fechar:
//
//   - throughput instantâneo por UE = delta de bytes / duração
//     da janela (Mbps)
//   - throughput agregado = soma dos throughputs por UE
//   - Jain sobre esse vetor de throughputs por UE
//
// Esse par (throughput agregado, Jain) É exatamente o ponto que
// alimenta a Fronteira de Pareto por slot usada no SEMISH — só
// que agora gerado para qualquer scheduler, não só o FMR.
// ------------------------------------------------------------
inline void
RegistrarJanela(Time windowSize,
                 Time trafficStopTime,
                 Time totalStopTime,
                 std::string schedulerMode,
                 std::string trafficProfile,
                 uint16_t ueNumPergNb,
                 uint32_t seed,
                 uint32_t rngRun,
                 double bandwidthMhz)
{
    const Time now = Simulator::Now();
    const double windowSeconds = (now - g_inicioUltimaJanela).GetSeconds();
    if (windowSeconds <= 0.0)
    {
        return;
    }
    std::vector<double> throughputPorUeJanela(g_bytesRecebidosPorUe.size(), 0.0);
    uint64_t pacotesJanela = 0;

    for (size_t i = 0; i < g_bytesRecebidosPorUe.size(); ++i)
    {
        uint64_t delta =
            g_bytesRecebidosPorUe[i] - g_bytesRecebidosUltimaJanela[i];
        throughputPorUeJanela[i] =
            (static_cast<double>(delta) * 8.0) / windowSeconds / 1e6; // Mbps
        g_bytesRecebidosUltimaJanela[i] = g_bytesRecebidosPorUe[i];
        pacotesJanela += g_pacotesRecebidosPorUe[i] -
                         g_pacotesRecebidosUltimaJanela[i];
        g_pacotesRecebidosUltimaJanela[i] = g_pacotesRecebidosPorUe[i];
    }

    double throughputAgregado = 0.0;
    for (double thr : throughputPorUeJanela)
    {
        throughputAgregado += thr;
    }

    // Reutiliza a mesma função de Jain do Bloco 7A — evita duplicar
    // a fórmula entre a métrica agregada e a métrica por janela.
    double jainJanela = CalcularJainVazao(throughputPorUeJanela);

    if (g_windowCsv.is_open())
    {
        g_windowCsv << schedulerMode << ","
                    << trafficProfile << ","
                    << ueNumPergNb << ","
                    << seed << ","
                    << rngRun << ","
                    << bandwidthMhz << ","
                    << g_janelaId << ","
                    << g_inicioUltimaJanela.GetSeconds() << ","
                    << now.GetSeconds() << ","
                    << windowSeconds << ","
                    << (now <= trafficStopTime ? "traffic" : "drain") << ","
                    << throughputAgregado << ","
                    << jainJanela << ","
                    << pacotesJanela << "\n";
    }

    ++g_janelaId;
    g_inicioUltimaJanela = now;

    // Reagenda a próxima janela enquanto houver tempo simulado
    // restante — mesmo critério de corte usado na barra de
    // progresso, para não agendar uma janela que nunca fecha.
    if (now < totalStopTime)
    {
        Time nextDelay = std::min(windowSize, totalStopTime - now);
        if (now < trafficStopTime)
        {
            nextDelay = std::min(nextDelay, trafficStopTime - now);
        }
        Simulator::Schedule(nextDelay,
                            &RegistrarJanela,
                            windowSize, trafficStopTime, totalStopTime,
                            schedulerMode, trafficProfile,
                            ueNumPergNb, seed, rngRun, bandwidthMhz);
    }
}

inline double
CalcularPercentilAmostras(std::vector<double> values, double percentil)
{
    if (values.empty())
    {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const double position = percentil * static_cast<double>(values.size() - 1);
    const size_t lower = static_cast<size_t>(std::floor(position));
    const size_t upper = static_cast<size_t>(std::ceil(position));
    const double fraction = position - static_cast<double>(lower);
    return values[lower] + (values[upper] - values[lower]) * fraction;
}

// ============================================================
// BLOCO 7A: FUNÇÕES AUXILIARES DE MÉTRICAS
//
// Calculam percentil de delay e Índice de Jain sobre vazão.
// Definidas aqui para serem reutilizáveis e testáveis
// separadamente do código de simulação no main().
// ============================================================

// ------------------------------------------------------------
// CalcularPercentilDelay()
//
// Calcula o percentil de delay a partir do histograma
// acumulado pelo FlowMonitor (ns3::Histogram).
//
// O histograma divide o delay observado em "bins" (faixas)
// de largura fixa, cada um com uma contagem de pacotes que
// caíram naquela faixa. Para achar o percentil P:
//   1. Soma o total de pacotes em todos os bins
//   2. Percorre os bins em ordem, acumulando a contagem
//   3. Para quando a soma acumulada atinge P% do total
//   4. Retorna o limite superior do bin onde isso ocorreu
//
// Essa é uma aproximação — a precisão depende da largura
// do bin (BinWidth do FlowMonitor, padrão 100ms). Para os
// fins desta dissertação, identificar se o delay ultrapassa
// o budget de 100ms do URLLC é suficiente.
//
// Parâmetros:
//   hist      → histograma de delay do FlowMonitor::FlowStats
//   percentil → valor entre 0.0 e 1.0 (ex: 0.99 para p99)
// ------------------------------------------------------------
inline double
CalcularPercentilDelay(const Histogram& hist, double percentil)
{
    uint32_t nBins = hist.GetNBins();
    if (nBins == 0)
    {
        return 0.0;
    }

    // Soma total de pacotes em todos os bins
    double total = 0.0;
    for (uint32_t i = 0; i < nBins; ++i)
    {
        total += hist.GetBinCount(i);
    }

    if (total == 0.0)
    {
        return 0.0;
    }

    // Percorre acumulando até atingir o percentil desejado
    double acumulado = 0.0;
    for (uint32_t i = 0; i < nBins; ++i)
    {
        acumulado += hist.GetBinCount(i);
        if (acumulado / total >= percentil)
        {
            // GetBinEnd retorna o limite superior do bin
            // (em segundos, no FlowMonitor) — convertido para ms
            return hist.GetBinEnd(i) * 1000.0;
        }
    }

    // Caso o percentil não seja atingido (não deveria ocorrer
    // com total > 0), retorna o fim do último bin
    return hist.GetBinEnd(nBins - 1) * 1000.0;
}

// ------------------------------------------------------------
// CalcularJainVazao()
//
// Calcula o Índice de Jain a partir das vazões individuais
// por UE — contribuição original desta dissertação.
//
// Fórmula: J = (Σ thr_i)² / (n × Σ thr_i²)
//
// Diferente do trabalho do Diego (fmr-compara-qos.cc), que
// calcula o Jain sobre RBGs alocados, aqui o índice mede
// equidade na EXPERIÊNCIA do usuário — quanto throughput
// cada UE efetivamente recebeu, não apenas quantos recursos
// foram alocados a ele.
//
// J = 1   → distribuição perfeitamente equitativa
// J = 1/n → máxima desigualdade (um UE concentra tudo)
// ------------------------------------------------------------
inline double
CalcularJainVazao(const std::vector<double>& throughputs)
{
    if (throughputs.empty())
    {
        return 0.0;
    }

    double soma = 0.0;
    double somaQuadrados = 0.0;

    for (double thr : throughputs)
    {
        soma += thr;
        somaQuadrados += thr * thr;
    }

    if (somaQuadrados == 0.0)
    {
        return 0.0; // evita divisão por zero se todos os UEs tiverem thr=0
    }

    double n = static_cast<double>(throughputs.size());
    return (soma * soma) / (n * somaQuadrados);
}

// ============================================================
// RESUMO POR UE — estrutura auxiliar para o Bloco 7
//
// Acumula métricas por UE durante o loop de fluxos (Bloco 7.5).
// Preenchida incrementalmente — um UE pode ter múltiplos fluxos
// (ex: eMBB com flowsPorUe=2). Usada para console e CSV.
// ============================================================
struct ResumoUe
{
    double   throughputMbps = 0.0; // soma dos fluxos do UE
    double   delaySomaMs    = 0.0; // soma para calcular média
    double   delayP99Ms     = 0.0; // máximo p99 entre os fluxos
    uint64_t txPackets      = 0;
    uint64_t rxPackets      = 0;
    uint64_t undeliveredAtStopPackets    = 0;
};

#endif // SIMULACAO_VJ5G_UTILS_H
