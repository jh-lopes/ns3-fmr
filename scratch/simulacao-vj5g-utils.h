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

#include <algorithm>
#include <cmath>
#include <map>
#include <string>
#include <utility>

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

#endif // SIMULACAO_VJ5G_UTILS_H
