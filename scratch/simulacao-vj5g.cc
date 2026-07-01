// ============================================================
// simulacao-vj5g.cc
//
// Cenário de simulação 5G NR para dissertação de mestrado:
// "Uma Análise da Relação entre Vazão e Justiça na Divisão
//  de Recursos em Escalonadores de Redes 5G"
//
// Autor: Júlio Henrique da Silva Lopes — UFAC (2026)
//
// Este arquivo implementa um cenário 5G NR com:
//   - 5 escalonadores: RR, PF, MR, QoS, FMR (RL-based)
//   - 3 perfis de tráfego: eMBB, URLLC, mMTC
//   - Métricas: throughput, Jain (sobre vazão), delay p99,
//     PLR, PDR, SINR médio por UE, distância UE-gNB
//
// Diferenças em relação ao fmr-compara-qos.cc (Diego Canizio):
//   1. Perfis de tráfego diferenciados (eMBB/URLLC/mMTC)
//   2. Bearers QCI por perfil (essencial para QoS scheduler)
//   3. PDCP Discard Timer para URLLC
//   4. Jain calculado sobre vazão (não sobre RBGs)
//   5. Delay percentil 99 (p99)
//   6. SINR médio por UE via trace callback
//   7. Distância UE-gNB no CSV de saída
//   8. Mobilidade dinâmica configurável via parâmetro
//
// Organização do código:
//   - simulacao-vj5g-utils.h contém a struct
//     PerfilDeTrafego, ObterPerfilDeTrafego() e o
//     SinrCallback() — funções auxiliares usadas pelo main()
//   - Este arquivo contém apenas o main() com os blocos
//     de configuração da simulação, em ordem sequencial
// ============================================================

// ------------------------------------------------------------
// INCLUDES
// Cada include representa um módulo do ns-3 necessário.
// ------------------------------------------------------------
#include "ns3/antenna-module.h"       // IsotropicAntennaModel, DirectPathBeamforming
#include "ns3/applications-module.h"  // UdpClient, UdpServer
#include "ns3/buildings-module.h"     // Necessário para canal UMa com 5G-LENA
#include "ns3/core-module.h"          // Simulator, Time, CommandLine, RNG
#include "ns3/flow-monitor-module.h"  // FlowMonitor: throughput, delay, PLR
#include "ns3/internet-module.h"      // Pilha IP, roteamento estático
#include "ns3/mobility-module.h"      // Modelos de mobilidade (fixo e dinâmico)
#include "ns3/network-module.h"       // NodeContainer, NetDeviceContainer
#include "ns3/nr-module.h"            // 5G-LENA: NrHelper, schedulers, bearers
#include "ns3/point-to-point-module.h"// Link ponto-a-ponto (core network)

#include "simulacao-vj5g-utils.h" // PerfilDeTrafego, SinrCallback

#include <algorithm>  // std::sort, std::transform (para p99 e normalização)
#include <cmath>      // std::sqrt, std::pow
#include <fstream>    // Escrita de arquivos CSV
#include <iomanip>    // Formatação numérica (setprecision)
#include <iostream>   // Saída no console
#include <map>        // std::map
#include <numeric>    // std::accumulate
#include <string>
#include <vector>
#include <sstream>   // mobilidade manual

using namespace ns3;

// Identificador de log para este arquivo.
// Para ativar: export NS_LOG="SimulacaoVJ5G=level_info"
NS_LOG_COMPONENT_DEFINE("SimulacaoVJ5G");

// ============================================================
// FUNÇÃO PRINCIPAL
// ============================================================
int
main(int argc, char* argv[])
{
    // --------------------------------------------------------
    // BLOCO 1: PARÂMETROS DE ENTRADA
    //
    // Todos os parâmetros são configuráveis via linha de
    // comando. O run_simulacao.py os passa automaticamente
    // para cada simulação do experimento.
    // --------------------------------------------------------

    // --- Cenário ---
    // schedulerMode: define qual escalonador MAC será usado
    std::string schedulerMode  = "rr";   // rr | pf | mr | qos | fmr_rl
    std::string trafficProfile = "embb"; // embb | urllc | mmtc
    uint16_t    ueNumPergNb    = 9;      // UEs por gNB (9 ou 30 para mMTC)
    uint16_t    gNbNum         = 1;      // gNBs (sempre 1 — single-cell)

    // --- Rádio ---
    // 4 GHz: banda sub-6GHz típica do 5G urbano
    double  centralFrequency = 4e9;
    // 100 MHz: com μ=1 resulta em ~132 RBs disponíveis
    double  bandwidth        = 100e6;
    // 43 dBm: potência típica de macro-célula (3GPP TR 38.901)
    double  totalTxPowerDbm  = 43.0;
    // μ=1 → SCS=30kHz → slot de 0,5ms
    // Único para todos os perfis: comparação controlada
    uint8_t numerology       = 1;

    // --- Simulação ---
    Time     simTime         = Seconds(30.0);
    Time     udpAppStartTime = MilliSeconds(400);
    uint32_t seed            = 1;  // Seeds 1, 2, 3 para repetições
    uint32_t run             = 1;

    // --- Mobilidade ---
    // enableMobility=false → posições fixas (Bateria 1 e 2)
    // enableMobility=true  → dinâmica (trabalho futuro)
    bool        enableMobility   = false;
    std::string mobilityModel    = "random_walk"; // random_walk | random_waypoint
    double      mobilitySpeedMin = 0.5;   // m/s — pedestre lento
    double      mobilitySpeedMax = 1.5;   // m/s — pedestre rápido
    double      mobilityBounds   = 200.0; // m — raio da área / distância máxima
    std::string ueDistances      = ""; // distancia manual 
    // --- ns3-ai (para FMR com agente RL) ---
    // Para outros schedulers, enableNs3Ai deve ser false
    bool        enableNs3Ai    = false;
    uint32_t    aiShmSize      = 4096;
    std::string aiSegmentName  = "ns3ai_fmr";
    std::string aiCpp2PyName   = "fmr_cpp2py";
    std::string aiPy2CppName   = "fmr_py2cpp";
    std::string aiLockableName = "fmr_lock";
    bool        aiCppIsCreator = true;
    std::string aiProtocol     = "SendThenRecv";
    bool        aiVerbose      = false;
    double      fmrAlphaFixed  = 0.7;
    double      fmrTau         = 0.70;

    // --- QoS scheduler ---
    // FairnessIndex: 0.0 = máxima eficiência, 1.0 = máxima justiça
    // Valor 0.5: equilíbrio — comparável ao PF
    // LastAvgTPutWeight: peso da média histórica de throughput
    // (nome interno do atributo no ns3::NrMacSchedulerOfdmaQos —
    // ver contrib/nr/model/nr-mac-scheduler-ofdma-qos.cc)
    // Referência: 3GPP TS 36.213 — scheduling policies
    double qosFairnessIndex = 0.5;
    double qosTimeWindow    = 99.0; // janela temporal em ms

    // --- Saída ---
    std::string outputDir   = "./";
    std::string simTag      = "default";

    // Slot CSV: RBGs e MCS por UE a cada slot
    bool        enableSlotCsv  = false;
    std::string slotCsvPath    = "slot_log.csv";
    bool        slotCsvAppend  = false;
    bool        slotCsvFlush   = false;

    // Flow Summary CSV: throughput, delay, PLR por fluxo
    bool        enableFlowSummaryCsv = false;
    std::string flowSummaryCsvPath   = "flow_summary.csv";

    // UE Snapshot CSV: throughput instantâneo por UE
    bool        enableUeSnapshotCsv  = false;
    std::string ueSnapshotCsvPath    = "ue_snapshot.csv";
    Time        ueSnapshotPeriod     = MilliSeconds(100);

    // Tráfego dinâmico por fases (herdado do fmr-compara-qos.cc,
    // mantido para compatibilidade com run_simulacao.py)
    bool        dynamicTraffic = false;
    std::string phaseDurations = "6,6,6,6,6";
    std::string phaseLambdas   = "5,10,15,8,20";
    std::string tddPattern     = "DL|DL|DL|DL|UL|DL|DL|DL|DL|UL|";

// lambdaOverride: sobrescreve o lambda do perfil de tráfego.
    // Valor 0 = usa o lambda definido pelo perfil (padrão).
    // Útil para testes de sobrecarga sem criar um novo perfil.
    uint32_t lambdaOverride = 0;

    // --------------------------------------------------------
    // Registro dos parâmetros na linha de comando
    // --------------------------------------------------------
    CommandLine cmd;

    // Cenário
    cmd.AddValue("schedulerMode",
                 "Escalonador MAC: rr | pf | mr | qos | fmr_rl",
                 schedulerMode);
    cmd.AddValue("trafficProfile",
                 "Perfil de tráfego: embb | urllc | mmtc",
                 trafficProfile);
    cmd.AddValue("ueNumPergNb",
                 "Número de UEs por gNB (9 para Bateria 1, 30 para mMTC)",
                 ueNumPergNb);
cmd.AddValue("lambdaOverride",
                 "Sobrescreve lambda do perfil (0=usa perfil, >0=sobrescreve)",
                 lambdaOverride);
    cmd.AddValue("gNbNum",
                 "Número de gNBs (padrão: 1)",
                 gNbNum);

    // Rádio
    cmd.AddValue("centralFrequency",
                 "Frequência central em Hz (padrão: 4e9)",
                 centralFrequency);
    cmd.AddValue("bandwidth",
                 "Largura de banda em Hz (padrão: 100e6)",
                 bandwidth);
    cmd.AddValue("totalTxPower",
                 "Potência TX do gNB em dBm (padrão: 43)",
                 totalTxPowerDbm);
    cmd.AddValue("numerology",
                 "Numerologia 5G NR: 0=15kHz, 1=30kHz, 2=60kHz",
                 numerology);

    // Simulação
    cmd.AddValue("simTime",  "Tempo total de simulação", simTime);
    cmd.AddValue("seed",     "Semente do RNG",           seed);
    cmd.AddValue("rngRun",   "Run do RNG",               run);

    // Mobilidade
    cmd.AddValue("enableMobility",
                 "Ativa mobilidade dinâmica (false=fixo, true=dinâmico)",
                 enableMobility);
    cmd.AddValue("mobilityModel",
                 "Modelo: random_walk | random_waypoint",
                 mobilityModel);
    cmd.AddValue("mobilitySpeedMin",
                 "Velocidade mínima em m/s",
                 mobilitySpeedMin);
    cmd.AddValue("mobilitySpeedMax",
                 "Velocidade máxima em m/s",
                 mobilitySpeedMax);
    cmd.AddValue("mobilityBounds",
                 "Raio da área em metros (fixo: distância máxima)",
                 mobilityBounds);
     cmd.AddValue("ueDistances",
             "Distâncias fixas dos UEs em metros. Ex.: 10,250,260",
             ueDistances);            

    // ns3-ai / FMR
    cmd.AddValue("EnableNs3Ai",    "Ativa agente Python para FMR", enableNs3Ai);
    cmd.AddValue("AiShmSize",      "Tamanho da memória compartilhada", aiShmSize);
    cmd.AddValue("AiSegmentName",  "Nome do segmento shm",  aiSegmentName);
    cmd.AddValue("AiCpp2PyName",   "Nome msg C++→Python",   aiCpp2PyName);
    cmd.AddValue("AiPy2CppName",   "Nome msg Python→C++",   aiPy2CppName);
    cmd.AddValue("AiLockableName", "Nome do lock shm",      aiLockableName);
    cmd.AddValue("AiCppIsCreator", "C++ cria shm",          aiCppIsCreator);
    cmd.AddValue("AiProtocol",     "Protocolo shm",         aiProtocol);
    cmd.AddValue("AiVerbose",      "Log verboso do agente", aiVerbose);
    cmd.AddValue("FmrAlphaFixed",  "Alpha fixo do FMR",     fmrAlphaFixed);
    cmd.AddValue("FmrTau",         "Tau do FMR",            fmrTau);

    // QoS scheduler
    cmd.AddValue("QosFairnessIndex",
                 "FairnessIndex do QoS scheduler (0=eficiência, 1=justiça)",
                 qosFairnessIndex);
    cmd.AddValue("QosTimeWindow",
                 "LastAvgTPutWeight do QoS scheduler — peso da média "
                 "histórica (padrão: 99)",
                 qosTimeWindow);

    // Saída
    cmd.AddValue("outputDir",            "Diretório de saída",       outputDir);
    cmd.AddValue("simTag",               "Tag dos arquivos",         simTag);
    cmd.AddValue("EnableSlotCsv",        "Ativa CSV por slot",       enableSlotCsv);
    cmd.AddValue("SlotCsvPath",          "Caminho do slot CSV",      slotCsvPath);
    cmd.AddValue("SlotCsvAppend",        "Append no slot CSV",       slotCsvAppend);
    cmd.AddValue("SlotCsvFlush",         "Flush no slot CSV",        slotCsvFlush);
    cmd.AddValue("EnableFlowSummaryCsv", "Ativa CSV de fluxos",     enableFlowSummaryCsv);
    cmd.AddValue("FlowSummaryCsvPath",   "Caminho do flow CSV",     flowSummaryCsvPath);
    cmd.AddValue("EnableUeSnapshotCsv",  "Ativa snapshot de UE",    enableUeSnapshotCsv);
    cmd.AddValue("UeSnapshotCsvPath",    "Caminho do snapshot",     ueSnapshotCsvPath);
    cmd.AddValue("UeSnapshotPeriod",     "Período do snapshot",     ueSnapshotPeriod);
    cmd.AddValue("dynamicTraffic",       "Ativa fases dinâmicas",   dynamicTraffic);
    cmd.AddValue("phaseDurations",       "Duração das fases (s)",   phaseDurations);
    cmd.AddValue("phaseLambdas",         "Lambda por fase (pkt/s)", phaseLambdas);
    cmd.AddValue("tddPattern",           "Padrão TDD",              tddPattern);

    cmd.Parse(argc, argv);

    // Configura o gerador de números aleatórios.
    // Seeds diferentes garantem independência estatística
    // entre as 3 repetições de cada simulação.
    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(run);

    NS_LOG_INFO("schedulerMode="   << schedulerMode
             << " trafficProfile=" << trafficProfile
             << " ueNumPergNb="    << ueNumPergNb
             << " bandwidth="      << bandwidth / 1e6 << "MHz"
             << " simTime="        << simTime.GetSeconds() << "s"
             << " seed="           << seed
             << " enableMobility=" << enableMobility);

    // --------------------------------------------------------
    // BLOCO 3: TOPOLOGIA FÍSICA
    //
    // Define posições dos nós, canal de rádio e BWP.
    //
    // Escolhas de projeto documentadas:
    //   Canal UMa: urbano macro, realista para 5G (3GPP TR 38.901)
    //   Posições fixas (padrão): reprodutibilidade entre seeds
    //   DirectPathBeamforming: foco no scheduler — beamforming
    //     ideal remove variável de confusão
    //   μ=1 para todos os perfis: comparação controlada
    // --------------------------------------------------------

    // --- 3.1 Obter perfil de tráfego ---
    // Chamada à função definida em simulacao-vj5g-utils.h
    PerfilDeTrafego perfil = ObterPerfilDeTrafego(trafficProfile);

    // Aplica override de lambda se especificado via linha de comando.
    // Permite testar cenários de sobrecarga sem criar novos perfis.
    if (lambdaOverride > 0)
    {
        NS_LOG_UNCOND("[VJ5G] Lambda sobrescrito: "
                   << perfil.lambda << " → " << lambdaOverride << " pkt/s");
        perfil.lambda = lambdaOverride;
    }
    
    NS_LOG_INFO("Perfil: "    << perfil.nome
             << " pacote="    << perfil.pacoteBytes << "B"
             << " lambda="    << perfil.lambda << "pkt/s"
             << " flows/UE="  << perfil.flowsPorUe
             << " discard="   << perfil.discardTimerMs << "ms");

    // --- 3.2 Criar nós ---
    NodeContainer gnbNodes;
    gnbNodes.Create(gNbNum);      // 1 gNB

    NodeContainer ueNodes;
    ueNodes.Create(ueNumPergNb);  // 9 ou 30 UEs

    // --- 3.3 Configurar mobilidade ---
    //
    // Modo fixo (enableMobility=false) — padrão desta dissertação:
    //   UEs em linha com distâncias crescentes. Cria assimetria
    //   de canal intencional — UE0 próximo (MCS alto) até
    //   UE_N distante (MCS baixo). Essencial para diferenciar
    //   o comportamento dos schedulers.
    //
    // Modo dinâmico (enableMobility=true) — trabalho futuro:
    //   Random Walk 2D ou Random Waypoint dentro de área definida.
    //   Permite avaliar schedulers sob variação dinâmica de canal.

    // gNB sempre fixo — estação base não se move
    MobilityHelper mobilityGnb;
    mobilityGnb.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobilityGnb.Install(gnbNodes);
    gnbNodes.Get(0)->GetObject<MobilityModel>()
        ->SetPosition(Vector(0.0, 0.0, 25.0));
    // Altura 25m: macro-célula urbana (3GPP TR 38.901 UMa)

    MobilityHelper mobilityUe;

    if (!enableMobility)
{
    // ============================================================
    // MODO DE MOBILIDADE FIXA
    //
    // Os UEs permanecem parados durante toda a simulação.
    // Esse modo é utilizado para garantir reprodutibilidade dos
    // experimentos e permitir comparar diferentes escalonadores
    // exatamente nas mesmas condições de propagação.
    // ============================================================

    mobilityUe.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobilityUe.Install(ueNodes);

    // ------------------------------------------------------------
    // Vetor que armazenará as distâncias informadas manualmente
    // pelo usuário através do parâmetro:
    //
    // --ueDistances=10,250,260
    //
    // Caso o vetor permaneça vazio, será utilizado o posicionamento
    // automático já existente no simulador.
    // ------------------------------------------------------------
    std::vector<double> distanciasManuais;

    // ------------------------------------------------------------
    // Verifica se o usuário informou distâncias manualmente.
    //
    // Exemplo:
    // --ueDistances=10,250,260
    //
    // A string é convertida para:
    //
    // distanciasManuais[0] = 10
    // distanciasManuais[1] = 250
    // distanciasManuais[2] = 260
    // ------------------------------------------------------------
    if (!ueDistances.empty())
    {
        std::stringstream ss(ueDistances);
        std::string token;

        while (std::getline(ss, token, ','))
        {
            distanciasManuais.push_back(std::stod(token));
        }

        // --------------------------------------------------------
        // Garante que exista exatamente uma distância para cada UE.
        //
        // Exemplo:
        //
        // 3 UEs
        // --ueDistances=10,250,260      -> OK
        //
        // 3 UEs
        // --ueDistances=10,250          -> ERRO
        // --------------------------------------------------------
        NS_ABORT_MSG_IF(
            distanciasManuais.size() != ueNodes.GetN(),
            "ueDistances deve conter exatamente uma distância por UE.");
    }

    // ------------------------------------------------------------
    // Posicionamento dos UEs
    // ------------------------------------------------------------
    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        // Número utilizado para distribuir igualmente os UEs
        // quando o posicionamento automático estiver ativo.
        uint32_t divisor = static_cast<uint32_t>(
            std::max(1u, static_cast<uint32_t>(ueNumPergNb) - 1u));

        double dist;

        // --------------------------------------------------------
        // MODO MANUAL
        //
        // Utiliza exatamente a distância informada pelo usuário.
        //
        // Exemplo:
        //
        // UE0 -> 10 m
        // UE1 -> 250 m
        // UE2 -> 260 m
        // --------------------------------------------------------
        if (!distanciasManuais.empty())
        {
            dist = distanciasManuais[i];
        }
        else
        {
            // ----------------------------------------------------
            // MODO AUTOMÁTICO (comportamento original)
            //
            // Distribui os UEs igualmente entre 10 m e
            // mobilityBounds.
            //
            // Exemplo:
            //
            // mobilityBounds = 200 m
            // 3 UEs
            //
            // UE0 -> 10 m
            // UE1 -> 105 m
            // UE2 -> 200 m
            //
            // Esse comportamento permanece exatamente igual ao
            // existente antes desta modificação.
            // ----------------------------------------------------
            dist = 10.0 + (mobilityBounds - 10.0) / divisor * i;
        }

        // Posiciona o UE no eixo X.
        // O gNB permanece na origem (0,0).
        // Todos os UEs permanecem no eixo Y = 0.
        // Altura = 1.5 m (terminal do usuário).
        ueNodes.Get(i)->GetObject<MobilityModel>()
            ->SetPosition(Vector(dist, 0.0, 1.5));

        // Log para conferência da posição atribuída.
        NS_LOG_INFO("UE" << i
                    << " distância configurada = "
                    << dist << " m");
    }

    // ------------------------------------------------------------
    // Informa no log qual modo foi utilizado.
    // Isso facilita reproduzir experimentos posteriormente.
    // ------------------------------------------------------------
    if (!ueDistances.empty())
    {
        NS_LOG_INFO("Mobilidade: FIXA MANUAL"
                    << " | distâncias = "
                    << ueDistances);
    }
    else
    {
        NS_LOG_INFO("Mobilidade: FIXA AUTOMÁTICA"
                    << " | UEs = " << ueNumPergNb
                    << " | intervalo = [10 m, "
                    << mobilityBounds << " m]");
    }
}

    // --- 3.4 Configurar EPC e helpers NR ---
    // NrPointToPointEpcHelper: simula o core 5G com link P2P
    Ptr<NrPointToPointEpcHelper> nrEpcHelper =
        CreateObject<NrPointToPointEpcHelper>();

    // IdealBeamformingHelper: beamforming perfeito por posição
    // Remove variável de confusão do beamforming das comparações
    Ptr<IdealBeamformingHelper> idealBeamformingHelper =
        CreateObject<IdealBeamformingHelper>();

    // NrHelper: coordena PHY, MAC, RLC, PDCP e dispositivos
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    nrHelper->SetBeamformingHelper(idealBeamformingHelper);
    nrHelper->SetEpcHelper(nrEpcHelper);

    // --- 3.5 Configurar banda de frequência e BWP ---
    // Uma única banda com um CC e uma BWP.
    // FDM de numerologias por perfil fica como trabalho futuro.
    BandwidthPartInfoPtrVector allBwps;
    CcBwpCreator ccBwpCreator;
    const uint8_t numCcPerBand = 1;

    CcBwpCreator::SimpleOperationBandConf bandConf(
        centralFrequency,  // 4 GHz
        bandwidth,         // 100 MHz
        numCcPerBand);     // 1 CC

    OperationBandInfo band =
        ccBwpCreator.CreateOperationBandContiguousCc(bandConf);

    // Canal 3GPP TR 38.901 — UMa (Urban Macro)
    // Inclui: path loss, shadowing, fast fading
    Ptr<NrChannelHelper> channelHelper =
        CreateObject<NrChannelHelper>();
    channelHelper->ConfigureFactories("UMa", "Default", "ThreeGpp");
    channelHelper->AssignChannelsToBands({band});
    allBwps = CcBwpCreator::GetAllBwps({band});

    // DirectPath: feixe aponta direto para o dispositivo
    idealBeamformingHelper->SetAttribute(
        "BeamformingMethod",
        TypeIdValue(DirectPathBeamforming::GetTypeId()));

    // Antena gNB: array 4x4 (típico para macro sub-6GHz)
    nrHelper->SetGnbAntennaAttribute("NumRows",    UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("AntennaElement",
        PointerValue(CreateObject<IsotropicAntennaModel>()));

    // Antena UE: array 2x2 (típico para dispositivo móvel)
    nrHelper->SetUeAntennaAttribute("NumRows",    UintegerValue(2));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(2));
    nrHelper->SetUeAntennaAttribute("AntennaElement",
        PointerValue(CreateObject<IsotropicAntennaModel>()));

    // Buffer RLC grande: evita descarte por buffer cheio
    // URLLC usa PDCP discard — mais realista que buffer overflow
    Config::SetDefault("ns3::NrRlcUm::MaxTxBufferSize",
                       UintegerValue(999999999));

    // --- 3.6 Instalar dispositivos NR ---
    NetDeviceContainer gnbDevs =
        nrHelper->InstallGnbDevice(gnbNodes, allBwps);
    NetDeviceContainer ueDevs =
        nrHelper->InstallUeDevice(ueNodes, allBwps);

    // Configurar potência de transmissão do gNB
    NrHelper::GetGnbPhy(gnbDevs.Get(0), 0)->SetTxPower(totalTxPowerDbm);

    // --- 3.7 Configurar host remoto (servidor de conteúdo) ---
    // Tráfego downlink parte do remoteHost para os UEs.
    // 100Gbps simula backhaul de alta capacidade (não gargalo).
    auto [remoteHost, remoteHostIpv4Address] =
        nrEpcHelper->SetupRemoteHost("100Gb/s", 2500, Seconds(0.010));

    // --- 3.8 Instalar pilha IP nos UEs ---
    InternetStackHelper internet;
    internet.Install(ueNodes);

    Ipv4InterfaceContainer ueIpIface =
        nrEpcHelper->AssignUeIpv4Address(NetDeviceContainer(ueDevs));

    // Conectar cada UE ao gNB
    for (uint32_t i = 0; i < ueDevs.GetN(); ++i)
    {
        nrHelper->AttachToGnb(ueDevs.Get(i), gnbDevs.Get(0));
    }

    // Roteamento padrão nos UEs (todo tráfego → gateway EPC)
    Ipv4StaticRoutingHelper ipv4RoutingHelper;
    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        Ptr<Ipv4StaticRouting> ueStaticRouting =
            ipv4RoutingHelper.GetStaticRouting(
                ueNodes.Get(i)->GetObject<Ipv4>());
        ueStaticRouting->SetDefaultRoute(
            nrEpcHelper->GetUeDefaultGatewayAddress(), 1);
    }

    // --------------------------------------------------------
    // FIM DO BLOCO 3
    // --------------------------------------------------------

    // --------------------------------------------------------
    // BLOCO 4: CONFIGURAÇÃO DO SCHEDULER
    //
    // Seleciona o scheduler MAC baseado em --schedulerMode.
    // A função TypeId::LookupByName() busca o scheduler pelo
    // nome registrado no ns-3. Se o nome for inválido,
    // o ns-3 aborta com mensagem de erro clara.
    //
    // Schedulers disponíveis no 5G-LENA NR v4.1:
    //   RR  → ns3::NrMacSchedulerOfdmaRR
    //         Distribuição cíclica igualitária de RBGs.
    //         Alta justiça, baixa eficiência espectral.
    //
    //   PF  → ns3::NrMacSchedulerOfdmaPF
    //         Balanço taxa instantânea / histórico de serviço.
    //         Equilíbrio clássico eficiência-justiça.
    //
    //   MR  → ns3::NrMacSchedulerOfdmaMR
    //         Prioriza UEs com melhor canal (maior MCS).
    //         Máxima eficiência, causa starvation.
    //
    //   QoS → ns3::NrMacSchedulerOfdmaQos
    //         Considera QCI, HOL delay e delay budget.
    //         Projetado para tráfego heterogêneo (URLLC/eMBB).
    //         Parâmetros configuráveis: FairnessIndex,
    //         LastAvgTPutWeight.
    //
    //   FMR → ns3::NrMacSchedulerOfdmaFmr
    //         Baseado em Reinforcement Learning (PPO).
    //         Aprende política de alocação offline.
    //         Requer agente Python via ns3-ai (shared memory).
    // --------------------------------------------------------

    // Imprime o tipo de scheduler sendo usado
    NS_LOG_UNCOND("SchedulerType: " << [&]() -> std::string {
        if (schedulerMode == "rr")     return "ns3::NrMacSchedulerOfdmaRR";
        if (schedulerMode == "pf")     return "ns3::NrMacSchedulerOfdmaPF";
        if (schedulerMode == "mr")     return "ns3::NrMacSchedulerOfdmaMR";
        if (schedulerMode == "qos")    return "ns3::NrMacSchedulerOfdmaQos";
        if (schedulerMode == "fmr_rl") return "ns3::NrMacSchedulerOfdmaFmr";
        return "UNKNOWN";
    }());

    if (schedulerMode == "rr")
    {
        // Round Robin: sem parâmetros adicionais
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaRR"));
    }
    else if (schedulerMode == "pf")
    {
        // Proportional Fair: sem parâmetros adicionais
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaPF"));
    }
    else if (schedulerMode == "mr")
    {
        // Max Rate: sem parâmetros adicionais
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaMR"));
    }
    else if (schedulerMode == "qos")
    {
        // QoS-aware scheduler
        // FairnessIndex: controla o equilíbrio entre eficiência
        //   e justiça. Valor padrão 0.5 = equilíbrio.
        //   Aumentar → mais justo (similar ao RR)
        //   Diminuir → mais eficiente (similar ao MR)
        // LastAvgTPutWeight: peso da média histórica de
        //   throughput. Maior valor → decisões mais estáveis;
        //   menor valor → reage mais rápido às mudanças.
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaQos"));
        nrHelper->SetSchedulerAttribute(
            "FairnessIndex", DoubleValue(qosFairnessIndex));
        nrHelper->SetSchedulerAttribute(
            "LastAvgTPutWeight", DoubleValue(qosTimeWindow));
    }
    else if (schedulerMode == "fmr_rl")
    {
        // Fair Max Rate — RL-based
        // Requer agente Python rodando em paralelo via ns3-ai.
        // Para outros schedulers, enableNs3Ai deve ser false.
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaFmr"));

        nrHelper->SetSchedulerAttribute(
            "AlphaFixed", DoubleValue(fmrAlphaFixed));
        nrHelper->SetSchedulerAttribute(
            "Tau", DoubleValue(fmrTau));

        // Configuração da comunicação via shared memory (ns3-ai)
        nrHelper->SetSchedulerAttribute(
            "EnableNs3Ai", BooleanValue(enableNs3Ai));
        nrHelper->SetSchedulerAttribute(
            "AiShmSize", UintegerValue(aiShmSize));
        nrHelper->SetSchedulerAttribute(
            "AiSegmentName", StringValue(aiSegmentName));
        nrHelper->SetSchedulerAttribute(
            "AiCpp2PyName", StringValue(aiCpp2PyName));
        nrHelper->SetSchedulerAttribute(
            "AiPy2CppName", StringValue(aiPy2CppName));
        nrHelper->SetSchedulerAttribute(
            "AiLockableName", StringValue(aiLockableName));
        nrHelper->SetSchedulerAttribute(
            "AiCppIsCreator", BooleanValue(aiCppIsCreator));
        nrHelper->SetSchedulerAttribute(
            "AiProtocol", StringValue(aiProtocol));
        nrHelper->SetSchedulerAttribute(
            "AiVerbose", BooleanValue(aiVerbose));

        // CSV por slot — necessário para análise do FMR
        nrHelper->SetSchedulerAttribute(
            "EnableSlotCsv", BooleanValue(enableSlotCsv));
        nrHelper->SetSchedulerAttribute(
            "SlotCsvPath", StringValue(slotCsvPath));
        nrHelper->SetSchedulerAttribute(
            "SlotCsvAppend", BooleanValue(slotCsvAppend));
        nrHelper->SetSchedulerAttribute(
            "SlotCsvFlush", BooleanValue(slotCsvFlush));
    }
    else
    {
        NS_ABORT_MSG("schedulerMode inválido: '" << schedulerMode
            << "'. Use: rr | pf | mr | qos | fmr_rl");
    }

    // --------------------------------------------------------
    // FIM DO BLOCO 4
    // --------------------------------------------------------

    // --------------------------------------------------------
    // BLOCO 5: APLICAÇÕES UDP COM BEARERS QCI
    //
    // Este bloco é a principal diferença desta dissertação
    // em relação ao trabalho do Diego (fmr-compara-qos.cc).
    //
    // Cada perfil de tráfego recebe:
    //   1. Bearer com QCI específico — define prioridade no
    //      QoS scheduler e nos mecanismos de QoS do 5G NR
    //   2. PDCP Discard Timer — ativo apenas para URLLC,
    //      descarta pacotes que excedem o delay budget (100ms)
    //   3. Número de fluxos por UE — conforme o perfil
    //   4. Tamanho de pacote e lambda — conforme o perfil
    //
    // Referências:
    //   QCI values: 3GPP TS 23.203 Tabela 6.1.7
    //   PDCP Discard: 3GPP TS 36.323 Seção 5.3
    // --------------------------------------------------------

    // --- 5.1 Configurar PDCP Discard Timer ---
    // Ativo apenas para URLLC (discardTimerMs > 0).
    // Pacotes que excedem o delay budget são descartados
    // e contabilizados como perda (PLR) no FlowMonitor.
    // Isso torna a métrica de PLR realista para URLLC.
    if (perfil.discardTimerMs > 0)
    {
        // EnablePdcpDiscarding: ativa o mecanismo de descarte
        Config::SetDefault("ns3::NrRlcUm::EnablePdcpDiscarding",
                           BooleanValue(true));
        // DiscardTimerMs: tempo máximo na fila em milissegundos
        Config::SetDefault("ns3::NrRlcUm::DiscardTimerMs",
                           UintegerValue(perfil.discardTimerMs));

        NS_LOG_INFO("PDCP Discard Timer ativo: "
                 << perfil.discardTimerMs << "ms");
    }

    // --- 5.2 Instalar aplicações UDP ---
    // Instala 'flowsPorUe' pares cliente-servidor por UE.
    // O servidor roda no UE (recebe dados).
    // O cliente roda no servidor remoto (envia dados).
    // Isso simula downlink — que é o caso principal do 5G.

    ApplicationContainer serverApps; // servidores nos UEs
    ApplicationContainer clientApps; // clientes no remoteHost

    // Porta base para os fluxos UDP.
    // Cada fluxo usa uma porta diferente:
    // UE0/fluxo0=1234, UE0/fluxo1=1235, UE1/fluxo0=1236, ...
    uint16_t portBase = 1234;

    // Vetor para armazenar ponteiros dos servidores UDP.
    // Usado no Bloco 7 para calcular throughput por UE.
    std::vector<Ptr<UdpServer>> udpServers;

    for (uint32_t ueIdx = 0; ueIdx < ueNodes.GetN(); ++ueIdx)
    {
        for (uint32_t flowIdx = 0; flowIdx < perfil.flowsPorUe; ++flowIdx)
        {
            uint16_t port = portBase
                + static_cast<uint16_t>(ueIdx * perfil.flowsPorUe + flowIdx);

            // --- Servidor UDP no UE ---
            // Escuta na porta definida e recebe os pacotes
            UdpServerHelper serverHelper(port);
            ApplicationContainer serverApp =
                serverHelper.Install(ueNodes.Get(ueIdx));
            serverApps.Add(serverApp);

            // Guarda ponteiro para leitura posterior no Bloco 7
            udpServers.push_back(
                DynamicCast<UdpServer>(serverApp.Get(0)));

            // --- Cliente UDP no servidor remoto ---
            // Envia 'lambda' pacotes/s de 'pacoteBytes' bytes
            UdpClientHelper clientHelper(
                ueIpIface.GetAddress(ueIdx), port);

            // Intervalo entre pacotes = 1/lambda segundos
            // lambda=1000 → 1ms entre pacotes
            // lambda=500  → 2ms entre pacotes
            // lambda=10   → 100ms entre pacotes
            clientHelper.SetAttribute(
                "Interval",
                TimeValue(Seconds(1.0 / static_cast<double>(perfil.lambda))));

            // Tamanho do pacote UDP em bytes
            clientHelper.SetAttribute(
                "PacketSize", UintegerValue(perfil.pacoteBytes));

            // Sem limite de pacotes — envia durante toda a simulação
            clientHelper.SetAttribute(
                "MaxPackets", UintegerValue(0xFFFFFFFF));

            clientApps.Add(clientHelper.Install(remoteHost));

            // --- Bearer QCI ---
            // Define a prioridade do fluxo no QoS scheduler.
            // Sem isso, o QoS scheduler trata todos igualmente.
            // eMBB  → NGBR_LOW_LAT_EMBB (QCI 70)
            // URLLC → GBR_CONV_VOICE    (QCI 1)
            // mMTC  → NGBR_VIDEO_TCP    (QCI 9)
            NrEpsBearer bearer(perfil.bearerQci);

            // Ativa o bearer no UE para este fluxo
            // O gNB usará o QCI deste bearer para priorização
            nrHelper->ActivateDedicatedEpsBearer(
                ueDevs.Get(ueIdx),
                bearer,
                NrEpcTft::Default());
        }
    }

    // --- 5.3 Configurar tempos de início e fim ---
    // As aplicações começam após 400ms para garantir que
    // o procedimento de attach (conexão UE-gNB) foi concluído.
    // Sem esse delay, os primeiros pacotes seriam perdidos.
    serverApps.Start(udpAppStartTime);  // 400ms
    clientApps.Start(udpAppStartTime);  // 400ms
    serverApps.Stop(simTime);
    clientApps.Stop(simTime);

    NS_LOG_INFO("Aplicações UDP instaladas:"
             << " UEs=" << ueNodes.GetN()
             << " flows/UE=" << perfil.flowsPorUe
             << " total_flows=" << ueNodes.GetN() * perfil.flowsPorUe
             << " pacote=" << perfil.pacoteBytes << "B"
             << " lambda=" << perfil.lambda << "pkt/s"
             << " bearer_qci=" << static_cast<int>(perfil.bearerQci));

    // --------------------------------------------------------
    // FIM DO BLOCO 5
    // --------------------------------------------------------

    // --------------------------------------------------------
    // BLOCO 6: COLETA DE SINR E DISTÂNCIA UE-gNB
    //
    // Contribuição original — não implementado no
    // fmr-compara-qos.cc do Diego.
    //
    // SINR: conecta SinrCallback() (definido em
    //   simulacao-vj5g-utils.h) diretamente em cada
    //   UE PHY via TraceConnectWithoutContext. Essa abordagem
    //   é mais confiável que Config::Connect com wildcard (*),
    //   que não localiza corretamente os objetos NrUePhy
    //   quando há nós adicionais do EPC no NodeList.
    //   Valores acumulados por RNTI em g_sinrAcumulado durante
    //   a simulação. Média calculada no Bloco 8 (resumo final).
    //
    // Distância: extraída do MobilityModel após posicionamento.
    //   Calculada uma vez — posições são fixas (Bateria 1 e 2).
    // --------------------------------------------------------

    // --- 6.1 Conectar trace de SINR ---
    // GetUePhy(device, bwpIndex) retorna o objeto PHY do UE
    // para a BWP de índice 0 (única BWP configurada — ver
    // Bloco 3.5). TraceConnectWithoutContext conecta o
    // callback sem passar o caminho do objeto como string,
    // compatível com a assinatura de SinrCallback().
    for (uint32_t i = 0; i < ueDevs.GetN(); ++i)
    {
        Ptr<NrUePhy> uePhy = nrHelper->GetUePhy(ueDevs.Get(i), 0);
        uePhy->TraceConnectWithoutContext(
            "DlDataSinr",
            MakeCallback(&SinrCallback));
    }

    NS_LOG_INFO("Trace DlDataSinr conectado diretamente em "
             << ueDevs.GetN() << " UEs via GetUePhy");

    // --- 6.2 Coletar distâncias UE-gNB ---
    // Extraída do MobilityModel — posição definida no Bloco 3.
    // Armazenada em vetor indexado por UE (0 a N-1).
    std::vector<double> distanciasUe(ueNodes.GetN(), 0.0);

    // Posição do gNB — referência para cálculo de distância
    Vector posGnb = gnbNodes.Get(0)
        ->GetObject<MobilityModel>()
        ->GetPosition();

    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        Vector posUe = ueNodes.Get(i)
            ->GetObject<MobilityModel>()
            ->GetPosition();

        // CalculateDistance: função do ns-3 que calcula
        // distância euclidiana 3D entre dois vetores de posição
        distanciasUe[i] = CalculateDistance(posGnb, posUe);

        NS_LOG_INFO("UE" << i
                 << " posição=(" << posUe.x << "," << posUe.y << ")"
                 << " distância=" << distanciasUe[i] << "m");
    }

    // --------------------------------------------------------
    // FIM DO BLOCO 6
    // Próximo: Bloco 7 — FlowMonitor + CSVs de saída
    //          Bloco 8 — Resumo consolidado
    // --------------------------------------------------------

    // --------------------------------------------------------
    // BLOCO 7: FLOWMONITOR + CSV DE SAÍDA
    //
    // Instala o FlowMonitor, executa a simulação completa,
    // e extrai as métricas por fluxo: throughput, delay médio,
    // delay p99, jitter, PLR, PDR. Calcula o Índice de Jain
    // sobre vazão agregando throughput por UE — contribuição
    // original desta dissertação (ver CalcularJainVazao em
    // simulacao-vj5g-utils.h).
    //
    // Mapeamento fluxo → UE: cada fluxo UDP usa uma porta
    // única (portBase + ueIdx*flowsPorUe + flowIdx, definida
    // no Bloco 5). O FlowMonitor identifica fluxos por
    // 5-tupla (IP origem, IP destino, porta origem, porta
    // destino, protocolo) — usamos a porta de destino para
    // recuperar o índice do UE.
    //
    // Mapeamento RNTI → UE: o ns-3 atribui RNTI sequencialmente
    // conforme os UEs são conectados via AttachToGnb (Bloco 3,
    // executado em ordem de 0 a N-1). Premissa: RNTI = ueIdx+1.
    // Esta é uma suposição documentada, válida para o cenário
    // single-cell desta dissertação (sem handover).
    // --------------------------------------------------------

    // --- 7.1 Instalar FlowMonitor ---
    // Deve ser instalado antes do Simulator::Run() para
    // capturar todos os pacotes desde o início da simulação.
    FlowMonitorHelper flowmonHelper;
    Ptr<FlowMonitor> monitor = flowmonHelper.InstallAll();

    // Bins de 1ms para delay e jitter — permite cálculo preciso
// do delay p99 no Bloco 7.5 (CalcularPercentilDelay).
// Padrão do FlowMonitor é 100ms/bin, insuficiente para URLLC.
monitor->SetAttribute("DelayBinWidth",  DoubleValue(0.001));
monitor->SetAttribute("JitterBinWidth", DoubleValue(0.001));

    // --- 7.2 Executar a simulação completa ---
   // Registra início do tempo real para a barra de progresso
g_inicioReal = std::chrono::steady_clock::now();
NS_LOG_UNCOND("[VJ5G] Simulação iniciada."
           << " scheduler=" << schedulerMode
           << " perfil=" << trafficProfile
           << " ues=" << ueNumPergNb
           << " simTime=" << simTime.GetSeconds() << "s");

// Agenda a barra de progresso — atualiza a cada 100ms simulados
Simulator::Schedule(Seconds(0.0), &ExibirBarraDeProgresso, simTime);
   
    Simulator::Stop(simTime);
    Simulator::Run();

ImprimirBarraDeProgressoFinal();
NS_LOG_UNCOND("[VJ5G] Simulação finalizada. Processando resultados...");
    
    // --- 7.3 Processar resultados do FlowMonitor ---
    monitor->CheckForLostPackets();

    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowmonHelper.GetClassifier());
    FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();

    // Tempo ativo de tráfego — usado para calcular throughput
    // em Mbps a partir dos bytes recebidos
    double activeSeconds = (simTime - udpAppStartTime).GetSeconds();

    // Vetor de throughput por UE — usado no cálculo do Jain
    // sobre vazão (Bloco 7.5). Inicializado com zero para
    // todos os UEs, mesmo que não recebam nenhum pacote.
    std::vector<double> throughputPorUe(ueNodes.GetN(), 0.0);

    // --- 7.4 Abrir CSV de saída e escrever cabeçalho ---
    std::ofstream flowCsv;
    if (enableFlowSummaryCsv)
    {
        flowCsv.open(flowSummaryCsvPath);
        flowCsv << "scheduler,traffic_profile,num_ues,seed,"
                << "bandwidth_mhz,flow_id,ue_id,"
                << "throughput_mbps,delay_mean_ms,delay_p99_ms,"
                << "jitter_mean_ms,plr_pct,pdr_pct,"
                << "tx_packets,rx_packets,lost_packets,"
                << "sinr_mean_db,distance_gnb_m\n";
    }

    // --- 7.5 Percorrer cada fluxo e extrair métricas ---
    for (const auto& flowPair : stats)
    {
        FlowId flowId = flowPair.first;
        const FlowMonitor::FlowStats& flowStats = flowPair.second;

        Ipv4FlowClassifier::FiveTuple tuple =
            classifier->FindFlow(flowId);

        // Recupera o índice do UE a partir da porta de destino.
        // Porta = portBase + ueIdx*flowsPorUe + flowIdx
        // → ueIdx = (porta - portBase) / flowsPorUe
        uint16_t destPort = tuple.destinationPort;
        uint32_t ueIdx = (destPort - portBase) / perfil.flowsPorUe;

        // Ignora fluxos fora do intervalo UDP da simulação
// (fluxos de controle do EPC: ARP, DHCP, sinalização)
if (destPort < portBase ||
    destPort >= portBase +
        static_cast<uint16_t>(ueNumPergNb * perfil.flowsPorUe))
{
    continue;
}

        // Throughput em Mbps: bytes recebidos × 8 / tempo ativo / 1e6
        double throughputMbps = 0.0;
        if (activeSeconds > 0.0)
        {
            throughputMbps = (flowStats.rxBytes * 8.0)
                            / activeSeconds / 1e6;
        }

        // Acumula throughput por UE (um UE pode ter múltiplos
        // fluxos — ex: eMBB com flowsPorUe=2)
        if (ueIdx < throughputPorUe.size())
        {
            throughputPorUe[ueIdx] += throughputMbps;
        }

        // Delay médio em ms
        double delayMeanMs = 0.0;
        if (flowStats.rxPackets > 0)
        {
            delayMeanMs = (flowStats.delaySum.GetSeconds()
                          / flowStats.rxPackets) * 1000.0;
        }

        // Delay p99 via histograma (CalcularPercentilDelay
        // definida em simulacao-vj5g-utils.h)
        double delayP99Ms =
            CalcularPercentilDelay(flowStats.delayHistogram, 0.99);

        // Jitter médio em ms
        double jitterMeanMs = 0.0;
        if (flowStats.rxPackets > 1)
        {
            jitterMeanMs = (flowStats.jitterSum.GetSeconds()
                           / (flowStats.rxPackets - 1)) * 1000.0;
        }

        // PLR (Packet Loss Ratio) e PDR (Packet Delivery Ratio)
        double plrPct = 0.0;
        double pdrPct = 0.0;
        if (flowStats.txPackets > 0)
        {
            plrPct = (static_cast<double>(flowStats.lostPackets)
                     / flowStats.txPackets) * 100.0;
            pdrPct = (static_cast<double>(flowStats.rxPackets)
                     / flowStats.txPackets) * 100.0;
        }

        // SINR médio do UE — recuperado de g_sinrAcumulado
        // (preenchido pelo SinrCallback durante a simulação).
        // RNTI = ueIdx + 1 (premissa documentada no cabeçalho).
        double sinrMeanDb = 0.0;
        uint16_t rnti = static_cast<uint16_t>(ueIdx + 1);
        auto sinrIt = g_sinrAcumulado.find(rnti);
        if (sinrIt != g_sinrAcumulado.end()
            && sinrIt->second.second > 0)
        {
            sinrMeanDb = sinrIt->second.first / sinrIt->second.second;
        }

        // Distância UE-gNB — calculada no Bloco 6.2
        double distanceM = 0.0;
        if (ueIdx < distanciasUe.size())
        {
            distanceM = distanciasUe[ueIdx];
        }

        NS_LOG_INFO("Flow " << flowId
                 << " UE" << ueIdx
                 << " thr=" << throughputMbps << "Mbps"
                 << " delay=" << delayMeanMs << "ms"
                 << " p99=" << delayP99Ms << "ms"
                 << " plr=" << plrPct << "%");

        if (enableFlowSummaryCsv)
        {
            flowCsv << schedulerMode << ","
                    << trafficProfile << ","
                    << ueNumPergNb << ","
                    << seed << ","
                    << (bandwidth / 1e6) << ","
                    << flowId << ","
                    << ueIdx << ","
                    << throughputMbps << ","
                    << delayMeanMs << ","
                    << delayP99Ms << ","
                    << jitterMeanMs << ","
                    << plrPct << ","
                    << pdrPct << ","
                    << flowStats.txPackets << ","
                    << flowStats.rxPackets << ","
                    << flowStats.lostPackets << ","
                    << sinrMeanDb << ","
                    << distanceM << "\n";
        }
    }

    if (enableFlowSummaryCsv)
    {
        flowCsv.close();
        NS_LOG_INFO("CSV de fluxos salvo em: " << flowSummaryCsvPath);
    }

    // --- 7.6 Calcular Índice de Jain sobre vazão ---
    // Contribuição original — agrega throughput por UE
    // (não por fluxo individual) e aplica a fórmula de Jain.
    // Nota: Jain=1.0 é esperado quando a demanda da aplicação
// (lambda × pacoteBytes) é inferior à capacidade do canal
// para todos os UEs. Nesse caso o gargalo é a aplicação,
// não o scheduler. Para observar Jain < 1, é necessário
// que a carga ofertada exceda a capacidade de alguns UEs
// (ex: scheduler MR com UEs distantes, ou lambda elevado).
    double jainVazao = CalcularJainVazao(throughputPorUe);

    double throughputAgregadoMbps = 0.0;
    for (double thr : throughputPorUe)
    {
        throughputAgregadoMbps += thr;
    }

    NS_LOG_UNCOND("[RESULT] scheduler=" << schedulerMode
               << " perfil=" << trafficProfile
               << " throughput_agregado_mbps=" << throughputAgregadoMbps
               << " jain_vazao=" << jainVazao
               << " ues=" << ueNumPergNb);

// Relatório visual no console — resume os resultados principais
std::cout << std::endl;
ImprimirSeparador('=', 52);
std::cout << "         RESULTADOS VJ5G - SIMULAÇÃO 5G NR" << std::endl;
ImprimirSeparador('=', 52);
std::cout << std::fixed << std::setprecision(2);
std::cout << "Scheduler           : " << schedulerMode << std::endl;
std::cout << "Perfil de tráfego   : " << trafficProfile << std::endl;
std::cout << "Descrição           : " << perfil.descricao << std::endl;
std::cout << "UEs                 : " << ueNumPergNb << std::endl;
std::cout << "Seed                : " << seed << std::endl;
std::cout << "Bandwidth           : " << bandwidth/1e6 << " MHz" << std::endl;
std::cout << "Tempo simulado      : " << simTime.GetSeconds() << " s" << std::endl;
ImprimirSeparador('-', 52);
std::cout << "Throughput agregado : " << throughputAgregadoMbps << " Mbps" << std::endl;
std::cout << "Índice de Jain      : " << std::setprecision(4)
          << jainVazao << std::endl;
std::cout << "SINR coletado       : " << g_sinrAcumulado.size()
          << " UEs" << std::endl;
ImprimirSeparador('=', 52);

// Linha de resultado estruturada para parsing pelo orquestrador Python
NS_LOG_UNCOND("[RESULT]"
           << " scheduler=" << schedulerMode
           << " perfil=" << trafficProfile
           << " throughput_mbps=" << throughputAgregadoMbps
           << " jain_vazao=" << jainVazao
           << " ues=" << ueNumPergNb
           << " seed=" << seed);

    Simulator::Destroy();

    // --------------------------------------------------------
    // FIM DO BLOCO 7
    // Próximo: Bloco 8 — Resumo consolidado
    // --------------------------------------------------------

    return 0;
} // fim do main