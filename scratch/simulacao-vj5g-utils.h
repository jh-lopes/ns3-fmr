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
//
// Autor: Júlio Henrique da Silva Lopes — UFAC (2026)
// ============================================================

#ifndef SIMULACAO_VJ5G_UTILS_H
#define SIMULACAO_VJ5G_UTILS_H

#include "ns3/core-module.h"
#include "ns3/nr-module.h"
#include "ns3/histogram.h"
#include <chrono>
#include <algorithm>
#include <cmath>
#include <map>
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
            2,                               // flowsPorUe
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

// Armazena acumulado de SINR por RNTI do UE.
// rnti (uint16_t) → identificador único do UE na célula
// Mapa: rnti → {soma_sinr_db, contagem_amostras}
inline std::map<uint16_t, std::pair<double, uint32_t>> g_sinrAcumulado;

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
// Conectada diretamente a cada UE PHY via
// TraceConnectWithoutContext (ver Bloco 6 em
// simulacao-vj5g.cc). Chamada a cada slot de simulação.
// Acumula o SINR em escala linear e converte para dB ao final.
//
// Parâmetros (definidos pela assinatura DlDataSinrTracedCallback):
//   cellId → ID da célula (não usado aqui)
//   rnti   → identificador do UE — chave do mapa
//   sinr   → valor do SINR em escala linear
//   bwpId  → ID da BWP (não usado aqui)
// ------------------------------------------------------------
inline void
SinrCallback(uint16_t cellId,
             uint16_t rnti,
             double   sinr,
             uint16_t bwpId)
{
    // Converte SINR linear para dB
    // Fórmula: SINR_dB = 10 * log10(SINR_linear)
    double sinrDb = 10.0 * std::log10(sinr);

    // Acumula soma e contagem para cálculo da média posterior
    g_sinrAcumulado[rnti].first  += sinrDb;
    g_sinrAcumulado[rnti].second += 1;
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

#endif // SIMULACAO_VJ5G_UTILS_H
