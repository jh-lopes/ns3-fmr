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
//   9. Posicionamento manual de UEs via --ueDistances
//   10. Log por janela de throughput+Jain (--EnableWindowCsv),
//       válido para qualquer schedulerMode — base para os
//       Pilares 1 (alfa dinâmico) e 2 (ranqueamento eMBB) da
//       Fronteira de Pareto (ver registro-sessao-alfa-dinamico-
//       vj5g.md no projeto)
//   11. Log de RBG por UE por slot (--EnableCommonSlotCsv) —
//       liga um atributo NATIVO da classe base
//       NrMacSchedulerOfdma (não é código novo desta
//       dissertação), válido para rr/pf/mr/qos. Permite
//       comparar Jain sobre RBGs (estilo Diego) com Jain sobre
//       vazão (Bloco 7) lado a lado
//
// Organização do código:
//   - simulacao-vj5g-utils.h contém structs e funções auxiliares
//   - Este arquivo contém o main() com os blocos de configuração
//
// ATENÇÃO — ORDEM OBRIGATÓRIA NO 5G-LENA:
//   SetSchedulerTypeId DEVE ser chamado ANTES de InstallGnbDevice.
//   O Bloco 4 está posicionado antes do Bloco 3.6 por esse motivo.
// ============================================================

// ------------------------------------------------------------
// INCLUDES
// ------------------------------------------------------------
#include "ns3/antenna-module.h"
#include "ns3/applications-module.h"
#include "ns3/buildings-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/nr-module.h"
#include "ns3/point-to-point-module.h"

#include "simulacao-vj5g-utils.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <numeric>
#include <numbers>
#include <string>
#include <vector>
#include <sstream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("SimulacaoVJ5G");

// ============================================================
// FUNÇÃO PRINCIPAL
// ============================================================
int
main(int argc, char* argv[])
{
    // --------------------------------------------------------
    // BLOCO 1: PARÂMETROS DE ENTRADA
    // --------------------------------------------------------

    // --- Cenário ---
    std::string schedulerMode  = "rr";
    std::string trafficProfile = "embb";
    uint16_t    ueNumPergNb    = 9;
    uint16_t    gNbNum         = 1;

    // --- Rádio ---
    double  centralFrequency = 4e9;
    double  bandwidth        = 100e6;
    double  totalTxPowerDbm  = 43.0;
    uint8_t numerology       = 1;

    // --- Simulação ---
    Time     simTime         = Seconds(30.0);
    Time     udpAppStartTime = MilliSeconds(400);
    Time     drainTime       = Seconds(0.0);
    Time     flowMaxPerHopDelay = Seconds(60.0);
    uint32_t seed            = 1;
    uint32_t run             = 1;

    // --- Mobilidade ---
    bool        enableMobility   = false;
    std::string positionMode     = "fixed_line";
    std::string mobilityModel    = "random_walk";
    double      mobilitySpeedMin = 0.5;
    double      mobilitySpeedMax = 1.5;
    double      mobilityBounds   = 200.0;
    // Distâncias manuais por UE. Ex: --ueDistances=10,250,260
    // Se vazio, usa posicionamento automático.
    std::string ueDistances      = "";

    // --- ns3-ai (para FMR com agente RL) ---
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
    // FairnessIndex: 0.0=eficiência máxima, 1.0=justiça máxima
    // LastAvgTPutWeight: nome real do atributo no ns-3
    double qosFairnessIndex = 0.5;
    double qosTimeWindow    = 99.0;

    // --- Saída ---
    std::string outputDir   = "./";
    std::string simTag      = "default";

    bool        enableSlotCsv  = false;
    std::string slotCsvPath    = "slot_log.csv";
    bool        slotCsvAppend  = false;
    bool        slotCsvFlush   = false;

    // CSV de RBG por UE por slot — recurso NATIVO da classe base
    // NrMacSchedulerOfdma (contrib/nr/model/nr-mac-scheduler-ofdma.cc,
    // atributos EnableCommonSlotCsv/CommonSlotCsvPath/...). Funciona
    // para rr/pf/mr/qos, que usam o AssignDLRBG() padrão da classe
    // base. NÃO funciona para fmr_rl, que sobrescreve AssignDLRBG()
    // com sua própria lógica e usa EnableSlotCsv/SlotCsvPath (acima)
    // em vez deste. Colunas do CSV gerado:
    // time_s,beam_id,rnti,dl_mcs,buf_req,alloc_rbg
    bool        enableCommonSlotCsv  = false;
    std::string commonSlotCsvPath    = "slot_log_common.csv";
    bool        commonSlotCsvAppend  = false;

    bool        enableFlowSummaryCsv = false;
    std::string flowSummaryCsvPath   = "flow_summary.csv";

    bool        enableUeSnapshotCsv  = false;
    std::string ueSnapshotCsvPath    = "ue_snapshot.csv";
    Time        ueSnapshotPeriod     = MilliSeconds(100);

    bool        dynamicTraffic = false;
    std::string phaseDurations = "6,6,6,6,6";
    std::string phaseLambdas   = "5,10,15,8,20";
    std::string tddPattern     = "DL|DL|DL|DL|UL|DL|DL|DL|DL|UL|";

    // lambdaOverride: sobrescreve o lambda do perfil.
    // Valor 0 = usa o lambda definido pelo perfil (padrão).
    // Útil para testes de sobrecarga sem criar um novo perfil.
    uint32_t lambdaOverride = 0;

    // Detalhes por UE no console ao final da simulação
    bool        enableConsoleDetails = false;

    // CSV de resumo por UE — agrega fluxos por UE e inclui Jain
    bool        enableUeSummaryCsv   = false;
    std::string ueSummaryCsvPath     = "ue_summary.csv";

    // CSV de log por janela (throughput + Jain instantâneos) —
    // Bloco 6B. Alimenta os Pilares 1 e 2 do alfa dinâmico via
    // Fronteira de Pareto (ver registro-sessao-alfa-dinamico-vj5g.md
    // no projeto). Funciona para qualquer schedulerMode.
    bool        enableWindowCsv      = false;
    std::string windowCsvPath        = "window_log.csv";
    // Tamanho da janela de recálculo em ms. 100ms é o ponto de
    // partida (mesmo período do ExibirBarraDeProgresso) — o
    // tamanho ideal ainda é um dos pontos em aberto do Pilar 1
    // e deve ser calibrado depois de olhar os primeiros dados.
    uint32_t    windowSizeMs         = 100;

    // --------------------------------------------------------
    // Registro dos parâmetros na linha de comando
    // --------------------------------------------------------
    CommandLine cmd;

    cmd.AddValue("schedulerMode",
                 "Escalonador MAC: rr | pf | mr | qos | fmr_rl",
                 schedulerMode);
    cmd.AddValue("trafficProfile",
                 "Perfil de tráfego: embb | urllc | mmtc",
                 trafficProfile);
    cmd.AddValue("ueNumPergNb",
                 "Número de UEs por gNB (9 para Bateria 1, 30 para mMTC)",
                 ueNumPergNb);
    cmd.AddValue("gNbNum", "Número de gNBs (padrão: 1)", gNbNum);
    cmd.AddValue("centralFrequency",
                 "Frequência central em Hz (padrão: 4e9)", centralFrequency);
    cmd.AddValue("bandwidth",
                 "Largura de banda em Hz (padrão: 100e6)", bandwidth);
    cmd.AddValue("totalTxPower",
                 "Potência TX do gNB em dBm (padrão: 43)", totalTxPowerDbm);
    cmd.AddValue("numerology",
                 "Numerologia 5G NR: 0=15kHz, 1=30kHz, 2=60kHz", numerology);
    cmd.AddValue("simTime",  "Tempo total de simulação", simTime);
    cmd.AddValue("drainTime",
                 "Tempo adicional sem novas transmissões para drenar filas",
                 drainTime);
    cmd.AddValue("FlowMaxPerHopDelay",
                 "Timeout do FlowMonitor; deve superar simTime+drainTime",
                 flowMaxPerHopDelay);
    cmd.AddValue("seed",     "Semente do RNG",           seed);
    cmd.AddValue("rngRun",   "Run do RNG",               run);
    cmd.AddValue("enableMobility",
                 "Ativa mobilidade dinâmica (false=fixo, true=dinâmico)",
                 enableMobility);
    cmd.AddValue("positionMode",
                 "Posicionamento sem mobilidade: fixed_line | random_disc_static",
                 positionMode);
    cmd.AddValue("mobilityModel",
                 "Modelo: random_walk | random_waypoint", mobilityModel);
    cmd.AddValue("mobilitySpeedMin", "Velocidade mínima em m/s", mobilitySpeedMin);
    cmd.AddValue("mobilitySpeedMax", "Velocidade máxima em m/s", mobilitySpeedMax);
    cmd.AddValue("mobilityBounds",
                 "Raio da área em metros (fixo: distância máxima)", mobilityBounds);
    cmd.AddValue("ueDistances",
                 "Distâncias fixas dos UEs em metros. Ex.: 10,250,260",
                 ueDistances);
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
    cmd.AddValue("QosFairnessIndex",
                 "FairnessIndex do QoS scheduler (0=eficiência, 1=justiça)",
                 qosFairnessIndex);
    cmd.AddValue("QosTimeWindow",
                 "LastAvgTPutWeight do QoS scheduler (padrão: 99)",
                 qosTimeWindow);
    cmd.AddValue("outputDir",            "Diretório de saída",      outputDir);
    cmd.AddValue("simTag",               "Tag dos arquivos",        simTag);
    cmd.AddValue("EnableSlotCsv",        "Ativa CSV por slot",      enableSlotCsv);
    cmd.AddValue("SlotCsvPath",          "Caminho do slot CSV",     slotCsvPath);
    cmd.AddValue("SlotCsvAppend",        "Append no slot CSV",      slotCsvAppend);
    cmd.AddValue("SlotCsvFlush",         "Flush no slot CSV",       slotCsvFlush);
    cmd.AddValue("EnableCommonSlotCsv",
                 "Ativa CSV de RBG por UE por slot (rr/pf/mr/qos)",
                 enableCommonSlotCsv);
    cmd.AddValue("CommonSlotCsvPath",
                 "Caminho do CSV de RBG por UE",
                 commonSlotCsvPath);
    cmd.AddValue("CommonSlotCsvAppend",
                 "Append no CSV de RBG por UE",
                 commonSlotCsvAppend);
    cmd.AddValue("EnableFlowSummaryCsv", "Ativa CSV de fluxos",    enableFlowSummaryCsv);
    cmd.AddValue("FlowSummaryCsvPath",   "Caminho do flow CSV",    flowSummaryCsvPath);
    cmd.AddValue("EnableUeSnapshotCsv",  "Ativa snapshot de UE",   enableUeSnapshotCsv);
    cmd.AddValue("UeSnapshotCsvPath",    "Caminho do snapshot",    ueSnapshotCsvPath);
    cmd.AddValue("UeSnapshotPeriod",     "Período do snapshot",    ueSnapshotPeriod);
    cmd.AddValue("dynamicTraffic",       "Ativa fases dinâmicas",  dynamicTraffic);
    cmd.AddValue("phaseDurations",       "Duração das fases (s)",  phaseDurations);
    cmd.AddValue("phaseLambdas",         "Lambda por fase (pkt/s)",phaseLambdas);
    cmd.AddValue("tddPattern",           "Padrão TDD",             tddPattern);
    cmd.AddValue("lambdaOverride",
                 "Sobrescreve lambda do perfil (0=usa perfil, >0=sobrescreve)",
                 lambdaOverride);
    cmd.AddValue("EnableConsoleDetails",
                 "Exibe resumo por UE no console ao final",
                 enableConsoleDetails);
    cmd.AddValue("EnableUeSummaryCsv",
                 "Ativa CSV de resumo por UE com Jain",
                 enableUeSummaryCsv);
    cmd.AddValue("UeSummaryCsvPath",
                 "Caminho do CSV de resumo por UE",
                 ueSummaryCsvPath);
    cmd.AddValue("EnableWindowCsv",
                 "Ativa CSV de throughput+Jain por janela (Pilares 1 e 2)",
                 enableWindowCsv);
    cmd.AddValue("WindowCsvPath",
                 "Caminho do CSV de log por janela",
                 windowCsvPath);
    cmd.AddValue("WindowSizeMs",
                 "Duração da janela de recálculo em ms (padrão: 100)",
                 windowSizeMs);

    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(simTime <= udpAppStartTime,
                    "simTime deve ser maior que o início das aplicações");
    NS_ABORT_MSG_IF(drainTime.IsNegative(), "drainTime não pode ser negativo");
    const Time totalStopTime = simTime + drainTime;
    NS_ABORT_MSG_IF(flowMaxPerHopDelay <= totalStopTime,
                    "FlowMaxPerHopDelay deve ser maior que simTime+drainTime");

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
    // --------------------------------------------------------

    // --- 3.1 Obter perfil de tráfego ---
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
    gnbNodes.Create(gNbNum);

    NodeContainer ueNodes;
    ueNodes.Create(ueNumPergNb);

    // Redimensiona os acumuladores do log por janela (Bloco 6B)
    // agora que o número de UEs é conhecido. Precisa ocorrer
    // antes do Bloco 5, onde RxWindowCallback já pode começar
    // a escrever nesses vetores assim que os UdpServers recebem
    // os primeiros pacotes.
    g_bytesRecebidosPorUe.assign(ueNumPergNb, 0);
    g_bytesRecebidosUltimaJanela.assign(ueNumPergNb, 0);
    g_pacotesRecebidosPorUe.assign(ueNumPergNb, 0);
    g_pacotesRecebidosUltimaJanela.assign(ueNumPergNb, 0);
    g_appRxStats.assign(ueNumPergNb, AppRxStats{});
    g_sequenciasRecebidasPorUe.assign(ueNumPergNb, {});
    g_trafficStopTime = simTime;
    g_inicioUltimaJanela = udpAppStartTime;

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
        // Garante reprodutibilidade dos experimentos e permite comparar
        // schedulers exatamente nas mesmas condições de propagação.
        // ============================================================

        mobilityUe.SetMobilityModel("ns3::ConstantPositionMobilityModel");

        if (positionMode == "random_disc_static")
        {
            NS_ABORT_MSG_IF(!ueDistances.empty(),
                            "ueDistances só pode ser usado com positionMode=fixed_line");
            NS_ABORT_MSG_IF(mobilityBounds <= 10.0,
                            "mobilityBounds deve ser maior que 10 m");

            // Uniformidade espacial por ÁREA: rho=sqrt(U(Rmin²,Rmax²)).
            // Usar rho~U(Rmin,Rmax) concentraria UEs artificialmente no
            // centro. Streams fixos + rngRun preservam o pareamento entre
            // schedulers e geram uma topologia distinta em cada run.
            Ptr<UniformRandomVariable> area = CreateObject<UniformRandomVariable>();
            Ptr<UniformRandomVariable> angle = CreateObject<UniformRandomVariable>();
            area->SetStream(1);
            angle->SetStream(2);
            Ptr<ListPositionAllocator> allocator = CreateObject<ListPositionAllocator>();
            const double minRadiusSquared = 10.0 * 10.0;
            const double maxRadiusSquared = mobilityBounds * mobilityBounds;
            for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
            {
                const double radius = std::sqrt(
                    minRadiusSquared + area->GetValue() *
                    (maxRadiusSquared - minRadiusSquared));
                const double theta = 2.0 * std::numbers::pi * angle->GetValue();
                allocator->Add(Vector(radius * std::cos(theta),
                                      radius * std::sin(theta), 1.5));
            }
            mobilityUe.SetPositionAllocator(allocator);
            mobilityUe.Install(ueNodes);
        }
        else if (positionMode == "fixed_line")
        {
            mobilityUe.Install(ueNodes);
        }
        else
        {
            NS_ABORT_MSG("positionMode inválido: '" << positionMode
                << "'. Use: fixed_line | random_disc_static");
        }

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

        if (!ueDistances.empty())
        {
            std::stringstream ss(ueDistances);
            std::string token;

            while (std::getline(ss, token, ','))
            {
                distanciasManuais.push_back(std::stod(token));
            }

            // Garante que exista exatamente uma distância por UE.
            // --ueDistances=10,250,260 com 3 UEs → OK
            // --ueDistances=10,250     com 3 UEs → ERRO
            NS_ABORT_MSG_IF(
                distanciasManuais.size() != ueNodes.GetN(),
                "ueDistances deve conter exatamente uma distância por UE.");
        }

        if (positionMode == "fixed_line")
        {
            for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
            {
                uint32_t divisor = static_cast<uint32_t>(
                    std::max(1u, static_cast<uint32_t>(ueNumPergNb) - 1u));

                double dist;

                if (!distanciasManuais.empty())
                {
                    // MODO MANUAL: distância definida pelo usuário
                    dist = distanciasManuais[i];
                }
                else
                {
                    // MODO AUTOMÁTICO: distribui igualmente de 10m a mobilityBounds
                    // Para 3 UEs com bounds=200: UE0=10m, UE1=105m, UE2=200m
                    dist = 10.0 + (mobilityBounds - 10.0) / divisor * i;
                }

                ueNodes.Get(i)->GetObject<MobilityModel>()
                    ->SetPosition(Vector(dist, 0.0, 1.5));
                // Altura 1.5m: dispositivo móvel ao nível do usuário

                NS_LOG_INFO("UE" << i << " distância configurada = " << dist << " m");
            }
        }

        if (!ueDistances.empty())
        {
            NS_LOG_INFO("Mobilidade: FIXA MANUAL | distâncias = " << ueDistances);
        }
        else if (positionMode == "fixed_line")
        {
            NS_LOG_INFO("Mobilidade: FIXA AUTOMÁTICA"
                     << " | UEs = " << ueNumPergNb
                     << " | intervalo = [10 m, " << mobilityBounds << " m]");
        }
        else
        {
            NS_LOG_INFO("Mobilidade: FIXA ALEATÓRIA | disco = [10 m, "
                        << mobilityBounds << " m] | rngRun=" << run);
        }
    }
    else
    {
        // Modo dinâmico — trabalho futuro
        if (mobilityModel == "random_walk")
        {
            mobilityUe.SetMobilityModel(
                "ns3::RandomWalk2dMobilityModel",
                "Bounds",
                RectangleValue(Rectangle(
                    -mobilityBounds, mobilityBounds,
                    -mobilityBounds, mobilityBounds)),
                "Speed",
                StringValue("ns3::UniformRandomVariable[Min="
                    + std::to_string(mobilitySpeedMin)
                    + "|Max="
                    + std::to_string(mobilitySpeedMax) + "]"),
                "Distance",
                DoubleValue(mobilityBounds / 4.0));
        }
        else if (mobilityModel == "random_waypoint")
        {
            mobilityUe.SetMobilityModel(
                "ns3::RandomWaypointMobilityModel",
                "Speed",
                StringValue("ns3::UniformRandomVariable[Min="
                    + std::to_string(mobilitySpeedMin)
                    + "|Max="
                    + std::to_string(mobilitySpeedMax) + "]"),
                "Pause",
                StringValue("ns3::ConstantRandomVariable[Constant=0]"),
                "PositionAllocator",
                StringValue("ns3::RandomRectanglePositionAllocator"));
        }
        else
        {
            NS_ABORT_MSG("mobilityModel inválido: '" << mobilityModel
                << "'. Use: random_walk | random_waypoint");
        }

        mobilityUe.SetPositionAllocator(
            "ns3::RandomDiscPositionAllocator",
            "X",   StringValue("0.0"),
            "Y",   StringValue("0.0"),
            "Rho", StringValue("ns3::UniformRandomVariable[Min=10|Max="
                + std::to_string(static_cast<int>(mobilityBounds)) + "]"));
        mobilityUe.Install(ueNodes);

        NS_LOG_INFO("Mobilidade: DINAMICA modelo=" << mobilityModel
                 << " speed=[" << mobilitySpeedMin
                 << "," << mobilitySpeedMax << "]m/s");
    }

    // --- 3.4 Configurar EPC e helpers NR ---
    Ptr<NrPointToPointEpcHelper> nrEpcHelper =
        CreateObject<NrPointToPointEpcHelper>();

    Ptr<IdealBeamformingHelper> idealBeamformingHelper =
        CreateObject<IdealBeamformingHelper>();

    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    nrHelper->SetBeamformingHelper(idealBeamformingHelper);
    nrHelper->SetEpcHelper(nrEpcHelper);

    // --- 3.5 Configurar banda de frequência e BWP ---
    BandwidthPartInfoPtrVector allBwps;
    CcBwpCreator ccBwpCreator;
    const uint8_t numCcPerBand = 1;

    CcBwpCreator::SimpleOperationBandConf bandConf(
        centralFrequency, bandwidth, numCcPerBand);

    OperationBandInfo band =
        ccBwpCreator.CreateOperationBandContiguousCc(bandConf);

    Ptr<NrChannelHelper> channelHelper = CreateObject<NrChannelHelper>();
    channelHelper->ConfigureFactories("UMa", "Default", "ThreeGpp");
    channelHelper->AssignChannelsToBands({band});
    allBwps = CcBwpCreator::GetAllBwps({band});

    idealBeamformingHelper->SetAttribute(
        "BeamformingMethod",
        TypeIdValue(DirectPathBeamforming::GetTypeId()));

    // CORREÇÃO (12/ago/2026): --numerology existia como parâmetro de linha
    // de comando (variável `numerology`, padrão 1 = 30kHz) mas nunca era
    // aplicado a nada — SimpleOperationBandConf() acima só recebe
    // centralFrequency/bandwidth/numCcPerBand, sem numerologia. Ou seja, a
    // simulação sempre rodou com o valor padrão da própria NrGnbPhy, não
    // com o que o usuário pedia no --numerology. Aplicando aqui via
    // atributo da PHY da gNB — precisa vir ANTES de InstallGnbDevice(),
    // igual às demais configurações de antena logo abaixo.
    // NÃO TESTADO EM COMPILAÇÃO (sem acesso ao ns-3-nr aqui) — se o nome
    // do atributo "Numerology" não existir na sua versão do NrGnbPhy, a
    // compilação vai falhar com um erro claro apontando essa linha; me
    // mande a mensagem de erro que eu ajusto.
    nrHelper->SetGnbPhyAttribute("Numerology", UintegerValue(numerology));

    // CORREÇÃO (13/ago/2026): --tddPattern tinha o MESMO problema do
    // --numerology — existia como parâmetro de linha de comando (variável
    // `tddPattern`, padrão "DL|DL|DL|DL|UL|DL|DL|DL|DL|UL|" = 80% DL/20%
    // UL) mas nunca era aplicado a nada. Evidência de que essa correção é a
    // certa: o formato da string (pipe-delimitado, "DL|UL|...") é
    // exatamente o formato que o atributo "Pattern" da NrGnbPhy espera nos
    // exemplos padrão do 5G-LENA — não foi um valor inventado, foi montado
    // já nesse formato específico e nunca conectado.
    //
    // Isso é o suspeito mais provável do "gap" de ~32% dos slots faltando
    // no slot_log_common.csv (ver análise de 12/ago/2026): slots UL não
    // têm alocação de downlink pra logar, então a linha nem é escrita —
    // e o padrão default da biblioteca (desconhecido até agora) pode ter
    // uma fração de UL bem maior que os 20% que essa variável sempre
    // sugeriu. Depois desta correção, o gap deve mudar (idealmente cair
    // pra ~20%, batendo com o padrão default acima) — comparar a próxima
    // rodada de slot_log_common.csv com a anterior confirma.
    //
    // NÃO TESTADO EM COMPILAÇÃO (sem acesso ao ns-3-nr aqui) — mesma
    // ressalva do Numerology acima: se "Pattern" não for o nome certo do
    // atributo nesta versão, a compilação falha com erro claro nesta
    // linha; me manda a mensagem que eu ajusto.
    nrHelper->SetGnbPhyAttribute("Pattern", StringValue(tddPattern));

    nrHelper->SetGnbAntennaAttribute("NumRows",    UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(4));
    nrHelper->SetGnbAntennaAttribute("AntennaElement",
        PointerValue(CreateObject<IsotropicAntennaModel>()));

    nrHelper->SetUeAntennaAttribute("NumRows",    UintegerValue(2));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(2));
    nrHelper->SetUeAntennaAttribute("AntennaElement",
        PointerValue(CreateObject<IsotropicAntennaModel>()));

    Config::SetDefault("ns3::NrRlcUm::MaxTxBufferSize",
                       UintegerValue(999999999));

    // --------------------------------------------------------
    // BLOCO 4: CONFIGURAÇÃO DO SCHEDULER
    //
    // POSICIONADO ANTES DO InstallGnbDevice — obrigatório no
    // 5G-LENA. SetSchedulerTypeId deve ser chamado antes de
    // InstallGnbDevice para que o scheduler seja aplicado.
    // Se chamado depois, o ns-3 usa o scheduler padrão (RR)
    // para todos os modos, tornando os resultados idênticos.
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
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaRR"));
    }
    else if (schedulerMode == "pf")
    {
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaPF"));
    }
    else if (schedulerMode == "mr")
    {
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaMR"));
    }
    else if (schedulerMode == "qos")
    {
        // FairnessIndex: equilíbrio eficiência/justiça (0=MR, 1=RR)
        // LastAvgTPutWeight: peso da média histórica de throughput.
        //   Maior valor → decisões mais estáveis
        //   Menor valor → reage mais rápido às mudanças
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaQos"));
        nrHelper->SetSchedulerAttribute(
            "FairnessIndex", DoubleValue(qosFairnessIndex));
        nrHelper->SetSchedulerAttribute(
            "LastAvgTPutWeight", DoubleValue(qosTimeWindow));
    }
    else if (schedulerMode == "fmr_rl")
    {
        // FMR requer agente Python rodando em paralelo via ns3-ai
        nrHelper->SetSchedulerTypeId(
            TypeId::LookupByName("ns3::NrMacSchedulerOfdmaFmr"));
        nrHelper->SetSchedulerAttribute(
            "AlphaFixed", DoubleValue(fmrAlphaFixed));
        nrHelper->SetSchedulerAttribute(
            "Tau", DoubleValue(fmrTau));
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

    // --- 4.1 CSV de RBG por UE por slot (fora do if/else acima) ---
    //
    // EnableCommonSlotCsv é um atributo da classe BASE
    // NrMacSchedulerOfdma (contrib/nr/model/nr-mac-scheduler-
    // ofdma.cc), herdado por rr/pf/mr/qos/fmr_rl igualmente —
    // por isso é aplicado uma única vez aqui, fora da cadeia
    // if/else, em vez de duplicado em cada branch.
    //
    // Só produz saída de fato para rr/pf/mr/qos: esses usam o
    // AssignDLRBG() padrão da classe base, que chama
    // WriteCommonSlotCsv() internamente (nr-mac-scheduler-
    // ofdma.cc, linha 595). O fmr_rl sobrescreve AssignDLRBG()
    // com sua própria implementação (nr-mac-scheduler-ofdma-
    // fmr.cc, linha 804) e usa EnableSlotCsv/SlotCsvPath (Bloco
    // 4, branch fmr_rl acima) em vez deste — setar este atributo
    // para fmr_rl não quebra nada, só não gera arquivo.
    nrHelper->SetSchedulerAttribute(
        "EnableCommonSlotCsv", BooleanValue(enableCommonSlotCsv));
    nrHelper->SetSchedulerAttribute(
        "CommonSlotCsvPath", StringValue(commonSlotCsvPath));
    nrHelper->SetSchedulerAttribute(
        "CommonSlotCsvAppend", BooleanValue(commonSlotCsvAppend));

    // --------------------------------------------------------
    // FIM DO BLOCO 4
    // --------------------------------------------------------

    // --- 3.6 Instalar dispositivos NR ---
    // APÓS SetSchedulerTypeId — ordem obrigatória no 5G-LENA
    NetDeviceContainer gnbDevs =
        nrHelper->InstallGnbDevice(gnbNodes, allBwps);
    NetDeviceContainer ueDevs =
        nrHelper->InstallUeDevice(ueNodes, allBwps);

    NrHelper::GetGnbPhy(gnbDevs.Get(0), 0)->SetTxPower(totalTxPowerDbm);

    // --- 3.7 Configurar host remoto ---
    auto [remoteHost, remoteHostIpv4Address] =
        nrEpcHelper->SetupRemoteHost("100Gb/s", 2500, Seconds(0.010));

    // --- 3.8 Instalar pilha IP nos UEs ---
    InternetStackHelper internet;
    internet.Install(ueNodes);

    Ipv4InterfaceContainer ueIpIface =
        nrEpcHelper->AssignUeIpv4Address(NetDeviceContainer(ueDevs));

    for (uint32_t i = 0; i < ueDevs.GetN(); ++i)
    {
        nrHelper->AttachToGnb(ueDevs.Get(i), gnbDevs.Get(0));
    }

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
    // BLOCO 5: APLICAÇÕES UDP COM BEARERS QCI
    //
    // Principal diferença desta dissertação em relação ao
    // fmr-compara-qos.cc do Diego:
    //   1. Bearer com QCI específico por perfil
    //   2. PDCP Discard Timer para URLLC
    //   3. Número de fluxos e parâmetros UDP por perfil
    //
    // Referências:
    //   QCI values: 3GPP TS 23.203 Tabela 6.1.7
    //   PDCP Discard: 3GPP TS 36.323 Seção 5.3
    // --------------------------------------------------------

    // --- 5.1 Configurar PDCP Discard Timer ---
    // Ativo apenas para URLLC (discardTimerMs > 0).
    // Pacotes que excedem o delay budget são descartados
    // e contabilizados como perda (PLR) no FlowMonitor.
    if (perfil.discardTimerMs > 0)
    {
        Config::SetDefault("ns3::NrRlcUm::EnablePdcpDiscarding",
                           BooleanValue(true));
        Config::SetDefault("ns3::NrRlcUm::DiscardTimerMs",
                           UintegerValue(perfil.discardTimerMs));
        NS_LOG_INFO("PDCP Discard Timer ativo: " << perfil.discardTimerMs << "ms");
    }

    // --- 5.2 Instalar aplicações UDP ---
    ApplicationContainer serverApps;
    ApplicationContainer clientApps;

    // Porta base para os fluxos UDP.
    // UE0/fluxo0=1234, UE0/fluxo1=1235, UE1/fluxo0=1236, ...
    uint16_t portBase = 1234;
    std::vector<Ptr<UdpServer>> udpServers;

    for (uint32_t ueIdx = 0; ueIdx < ueNodes.GetN(); ++ueIdx)
    {
        for (uint32_t flowIdx = 0; flowIdx < perfil.flowsPorUe; ++flowIdx)
        {
            uint16_t port = portBase
                + static_cast<uint16_t>(ueIdx * perfil.flowsPorUe + flowIdx);

            UdpServerHelper serverHelper(port);
            ApplicationContainer serverApp =
                serverHelper.Install(ueNodes.Get(ueIdx));
            serverApps.Add(serverApp);
            Ptr<UdpServer> servidorUe =
                DynamicCast<UdpServer>(serverApp.Get(0));
            udpServers.push_back(servidorUe);

            // Bloco 6B: conecta o trace "Rx" deste servidor ao
            // acumulador de bytes por UE. MakeBoundCallback fixa
            // ueIdx como primeiro argumento — funciona para
            // qualquer schedulerMode, pois observa o que chegou
            // na camada de aplicação, não o scheduler em si.
            // Quando flowsPorUe > 1, os bytes de todos os flows
            // do mesmo UE se somam no mesmo índice do vetor.
            servidorUe->TraceConnectWithoutContext(
                "Rx", MakeBoundCallback(&RxWindowCallback, ueIdx, flowIdx));

            UdpClientHelper clientHelper(ueIpIface.GetAddress(ueIdx), port);
            clientHelper.SetAttribute(
                "Interval",
                TimeValue(Seconds(1.0 / static_cast<double>(perfil.lambda))));
            clientHelper.SetAttribute(
                "PacketSize", UintegerValue(perfil.pacoteBytes));
            clientHelper.SetAttribute(
                "MaxPackets", UintegerValue(0xFFFFFFFF));
            clientApps.Add(clientHelper.Install(remoteHost));

            NrEpsBearer bearer(perfil.bearerQci);
            nrHelper->ActivateDedicatedEpsBearer(
                ueDevs.Get(ueIdx), bearer, NrEpcTft::Default());
        }
    }

    // --- 5.3 Configurar tempos ---
    // Apps começam após 400ms — garante attach UE-gNB completo.
    serverApps.Start(udpAppStartTime);
    clientApps.Start(udpAppStartTime);
    serverApps.Stop(totalStopTime);
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
    // SINR: conecta SinrCallback() diretamente em cada UE PHY
    //   via TraceConnectWithoutContext. Mais confiável que
    //   Config::Connect com wildcard — evita capturar nós do
    //   EPC no NodeList.
    //
    // Distância: extraída do MobilityModel após posicionamento.
    // --------------------------------------------------------

    // --- 6.1 Conectar trace de SINR ---
    // CORREÇÃO (12/ago/2026): antes conectava com MakeCallback(&SinrCallback)
    // puro, e a leitura posterior tentava adivinhar de qual UE cada SINR
    // era (assumindo rnti = ueIdx + 1 — ver correção em g_sinrAcumulado no
    // .h). Agora amarra o índice REAL do UE (i, o mesmo índice usado em
    // ueDevs/ueNodes) no momento da conexão, via MakeBoundCallback — o
    // trace passa a saber de qual UE ele é sem depender do RNTI.
    for (uint32_t i = 0; i < ueDevs.GetN(); ++i)
    {
        Ptr<NrUePhy> uePhy = nrHelper->GetUePhy(ueDevs.Get(i), 0);
        uePhy->TraceConnectWithoutContext(
            "DlDataSinr", MakeBoundCallback(&SinrCallback, i));
    }

    NS_LOG_INFO("Trace DlDataSinr conectado diretamente em "
             << ueDevs.GetN() << " UEs via GetUePhy (ueIdx amarrado por UE)");

    // --- 6.2 Coletar distâncias UE-gNB ---
    std::vector<double> distanciasUe(ueNodes.GetN(), 0.0);
    std::vector<Vector> posicoesIniciaisUe(ueNodes.GetN());
    Vector posGnb = gnbNodes.Get(0)
        ->GetObject<MobilityModel>()->GetPosition();

    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        Vector posUe = ueNodes.Get(i)
            ->GetObject<MobilityModel>()->GetPosition();
        posicoesIniciaisUe[i] = posUe;
        distanciasUe[i] = CalculateDistance(posGnb, posUe);
        NS_LOG_INFO("UE" << i
                 << " posição=(" << posUe.x << "," << posUe.y << ")"
                 << " distância=" << distanciasUe[i] << "m");
    }

    // O diagnóstico [DIAG-DIST] que existia aqui (11/ago/2026) investigava
    // um distance_gnb_m absurdo (~100+ km) visto no ue_summary.csv de uma
    // rodada anterior, para UEs de índice mais alto. O log confirmou que o
    // valor calculado aqui sempre esteve correto (ex: UE5 = 117.9208905m),
    // e o CSV de uma rodada nova (12/ago/2026, já com os outros dois
    // consertos aplicados e o binário recompilado) saiu correto também
    // (117.921, com decimal). Não foi encontrada nenhuma transformação no
    // caminho entre esse cálculo e a escrita no CSV — o mais provável é
    // que o CSV problemático original tenha vindo de um binário
    // desatualizado (build não refletindo o .cc mais recente na época).
    // Se esse valor voltar a aparecer errado numa rodada futura, é sinal
    // de recompilar do zero (./ns3 build, ou ./ns3 clean && ./ns3 build)
    // antes de investigar o código de novo. Diagnóstico removido.

    // --------------------------------------------------------
    // FIM DO BLOCO 6
    // --------------------------------------------------------

    // --------------------------------------------------------
    // BLOCO 7: FLOWMONITOR + CSV DE SAÍDA
    //
    // Extrai métricas por fluxo: throughput, delay médio,
    // delay p99, jitter, PLR, PDR. Calcula Índice de Jain
    // sobre vazão — contribuição original desta dissertação.
    //
    // Mapeamento fluxo → UE: porta de destino revela ueIdx.
    //   Porta = portBase + ueIdx*flowsPorUe + flowIdx
    //   → ueIdx = (porta - portBase) / flowsPorUe
    //
    // Mapeamento RNTI → UE: RNTI = ueIdx+1 (premissa documentada,
    //   válida para single-cell sem handover).
    // --------------------------------------------------------

    // --- 7.1 Instalar FlowMonitor ---
    FlowMonitorHelper flowmonHelper;
    Ptr<FlowMonitor> monitor = flowmonHelper.InstallAll();

    // Bins de 1ms para delay e jitter — permite cálculo preciso
    // do delay p99. Padrão do FlowMonitor é 100ms/bin,
    // insuficiente para URLLC (delay budget = 100ms).
    monitor->SetAttribute("DelayBinWidth",  DoubleValue(0.001));
    monitor->SetAttribute("JitterBinWidth", DoubleValue(0.001));
    monitor->SetAttribute("MaxPerHopDelay", TimeValue(flowMaxPerHopDelay));

    // --- 7.1b Abrir CSV de log por janela (Bloco 6B) ---
    // Aberto antes do Run() porque RegistrarJanela é agendada
    // recursivamente durante a simulação e escreve nele a cada
    // janela que fecha.
    if (enableWindowCsv)
    {
        g_windowCsv.open(windowCsvPath);
        g_windowCsv << "scheduler,traffic_profile,num_ues,seed,rng_run,"
                    << "bandwidth_mhz,window_id,start_time_s,end_time_s,"
                    << "duration_s,phase,aggregate_thr_mbps,jain_throughput,"
                    << "app_rx_packets\n";

        // Primeira janela fecha em udpAppStartTime + windowSizeMs —
        // não em windowSizeMs a partir de zero, porque as apps só
        // começam a enviar/receber tráfego em udpAppStartTime
        // (linha ~700). Agendar antes disso só geraria janelas
        // vazias (thr=0, Jain=0) sem significado.
        Simulator::Schedule(udpAppStartTime + MilliSeconds(windowSizeMs),
                            &RegistrarJanela,
                            MilliSeconds(windowSizeMs), simTime, totalStopTime,
                            schedulerMode, trafficProfile,
                            ueNumPergNb, seed, run, bandwidth / 1e6);

        NS_LOG_INFO("Log por janela ativo: windowSizeMs=" << windowSizeMs
                 << " path=" << windowCsvPath);
    }

    // --- 7.2 Executar simulação ---
    g_inicioReal = std::chrono::steady_clock::now();
    NS_LOG_UNCOND("[VJ5G] Simulação iniciada."
               << " scheduler=" << schedulerMode
               << " perfil=" << trafficProfile
               << " ues=" << ueNumPergNb
               << " trafficStop=" << simTime.GetSeconds() << "s"
               << " drain=" << drainTime.GetSeconds() << "s");

    Simulator::Schedule(Seconds(0.0), &ExibirBarraDeProgresso, totalStopTime);
    // O epsilon permite que o callback da janela que fecha exatamente em
    // totalStopTime execute antes do encerramento do simulador.
    Simulator::Stop(totalStopTime + NanoSeconds(1));
    Simulator::Run();

    ImprimirBarraDeProgressoFinal();
    NS_LOG_UNCOND("[VJ5G] Simulação finalizada. Processando resultados...");

    // --- 7.3 Processar resultados ---
    monitor->CheckForLostPackets();

    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowmonHelper.GetClassifier());
    FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();

    double activeSeconds = (simTime - udpAppStartTime).GetSeconds();

    // Throughput por UE — base para Jain sobre vazão
    std::vector<double> throughputPorUe(ueNodes.GetN(), 0.0);

    // Acumuladores por UE para ue_summary.csv
    std::vector<ResumoUe> resumoPorUe(ueNodes.GetN());

    // --- 7.4 Abrir flow_summary CSV ---
    std::ofstream flowCsv;
    if (enableFlowSummaryCsv)
    {
        flowCsv.open(flowSummaryCsvPath);
        flowCsv << "scheduler,traffic_profile,num_ues,seed,rng_run,"
                << "bandwidth_mhz,flow_id,ue_id,"
                << "flowmon_throughput_mbps,flowmon_delay_mean_ms,"
                << "flowmon_delay_p99_ms,flowmon_jitter_mean_ms,"
                << "flowmon_undelivered_pct,flowmon_pdr_pct,"
                << "flowmon_tx_packets,flowmon_rx_packets,"
                << "flowmon_undelivered_at_stop_packets,"
                << "sinr_mean_db,distance_gnb_m\n";
    }

    // --- 7.5 Percorrer fluxos e extrair métricas ---
    for (const auto& flowPair : stats)
    {
        FlowId flowId = flowPair.first;
        const FlowMonitor::FlowStats& flowStats = flowPair.second;

        Ipv4FlowClassifier::FiveTuple tuple =
            classifier->FindFlow(flowId);

        uint16_t destPort = tuple.destinationPort;
        uint32_t ueIdx = (destPort - portBase) / perfil.flowsPorUe;

        // Ignora fluxos de controle do EPC (ARP, DHCP, sinalização)
        if (destPort < portBase ||
            destPort >= portBase +
                static_cast<uint16_t>(ueNumPergNb * perfil.flowsPorUe))
        {
            continue;
        }

        double throughputMbps = 0.0;
        if (activeSeconds > 0.0)
        {
            throughputMbps = (flowStats.rxBytes * 8.0) / activeSeconds / 1e6;
        }

        if (ueIdx < throughputPorUe.size())
        {
            throughputPorUe[ueIdx] += throughputMbps;
        }

        double delayMeanMs = 0.0;
        if (flowStats.rxPackets > 0)
        {
            delayMeanMs = (flowStats.delaySum.GetSeconds()
                          / flowStats.rxPackets) * 1000.0;
        }

        double delayP99Ms =
            CalcularPercentilDelay(flowStats.delayHistogram, 0.99);

        double jitterMeanMs = 0.0;
        if (flowStats.rxPackets > 1)
        {
            jitterMeanMs = (flowStats.jitterSum.GetSeconds()
                           / (flowStats.rxPackets - 1)) * 1000.0;
        }

        // O contador lostPackets nativo do FlowMonitor depende do timeout.
        // A diferença tx-rx é exportada explicitamente
        // como "não entregue até o fim"; ela não é chamada de perda física,
        // pois pode incluir backlog remanescente após o drain.
        uint64_t undeliveredAtStop = (flowStats.txPackets > flowStats.rxPackets)
            ? (flowStats.txPackets - flowStats.rxPackets) : 0;

        double plrPct = 0.0;
        double pdrPct = 0.0;
        if (flowStats.txPackets > 0)
        {
            plrPct = (static_cast<double>(undeliveredAtStop)
                     / flowStats.txPackets) * 100.0;
            pdrPct = (static_cast<double>(flowStats.rxPackets)
                     / flowStats.txPackets) * 100.0;
        }

        // CORREÇÃO (12/ago/2026): g_sinrAcumulado agora é indexado por
        // ueIdx real (amarrado no Bloco 6.1 via MakeBoundCallback), não
        // mais por um RNTI adivinhado — ver correção completa no .h.
        double sinrMeanDb = 0.0;
        auto sinrIt = g_sinrAcumulado.find(ueIdx);
        if (sinrIt != g_sinrAcumulado.end() && sinrIt->second.second > 0)
        {
            sinrMeanDb = sinrIt->second.first / sinrIt->second.second;
        }

        double distanceM = 0.0;
        if (ueIdx < distanciasUe.size())
        {
            distanceM = distanciasUe[ueIdx];
        }

        // Acumula métricas por UE para o ue_summary.csv
        if (ueIdx < resumoPorUe.size())
        {
            resumoPorUe[ueIdx].throughputMbps += throughputMbps;
            resumoPorUe[ueIdx].delaySomaMs    += delayMeanMs;
            resumoPorUe[ueIdx].delayP99Ms      =
                std::max(resumoPorUe[ueIdx].delayP99Ms, delayP99Ms);
            resumoPorUe[ueIdx].txPackets       += flowStats.txPackets;
            resumoPorUe[ueIdx].rxPackets       += flowStats.rxPackets;
            resumoPorUe[ueIdx].undeliveredAtStopPackets     += undeliveredAtStop;
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
                    << run << ","
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
                    << undeliveredAtStop << ","
                    << sinrMeanDb << ","
                    << distanceM << "\n";
        }
    }

    if (enableFlowSummaryCsv)
    {
        flowCsv.close();
        NS_LOG_INFO("flow_summary salvo em: " << flowSummaryCsvPath);
    }

    // --- 7.6 Métricas canônicas na aplicação ---
    // O FlowMonitor permanece como instrumento de comparação, mas a fonte
    // principal passa a ser o UdpServer: ele não esquece pacotes atrasados e
    // mede payload, exatamente como o log por janela.
    std::vector<double> appTrafficThroughputPorUe(ueNodes.GetN(), 0.0);
    std::vector<double> appTotalGoodputPorUe(ueNodes.GetN(), 0.0);
    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        if (activeSeconds > 0.0)
        {
            appTrafficThroughputPorUe[i] =
                (g_appRxStats[i].trafficBytes * 8.0) / activeSeconds / 1e6;
            // Eventual goodput: tudo que chegou até o fim do drain,
            // normalizado pela duração em que a carga foi oferecida.
            appTotalGoodputPorUe[i] =
                (g_appRxStats[i].totalBytes * 8.0) / activeSeconds / 1e6;
        }
    }

    const double appTrafficJain = CalcularJainVazao(appTrafficThroughputPorUe);
    const double appTotalJain = CalcularJainVazao(appTotalGoodputPorUe);
    const double flowmonJain = CalcularJainVazao(throughputPorUe);
    const double appTrafficThroughputAgregado =
        std::accumulate(appTrafficThroughputPorUe.begin(),
                        appTrafficThroughputPorUe.end(), 0.0);
    const double appTotalGoodputAgregado =
        std::accumulate(appTotalGoodputPorUe.begin(),
                        appTotalGoodputPorUe.end(), 0.0);
    const double flowmonThroughputAgregado =
        std::accumulate(throughputPorUe.begin(), throughputPorUe.end(), 0.0);

    // --- 7.7 Exportar ue_summary.csv e detalhe no console ---
    std::ofstream ueCsv;
    if (enableUeSummaryCsv)
    {
        ueCsv.open(ueSummaryCsvPath);
        // Coluna "rnti" adicionada em 12/ago/2026: permite cruzar este CSV
        // com o log nativo do 5G-LENA slot_log_common.csv (RBG por UE por
        // slot, indexado por RNTI — ver --EnableCommonSlotCsv), sem repetir
        // o erro de assumir rnti = ueIdx + 1. Ver computar_rbg_por_ue.py.
        ueCsv << "scheduler,traffic_profile,num_ues,seed,rng_run,bandwidth_mhz,"
              << "position_mode,mobility_enabled,mobility_bounds_m,"
              << "ue_id,rnti,x_initial_m,y_initial_m,z_initial_m,"
              << "app_throughput_traffic_mbps,app_goodput_total_mbps,"
              << "app_rx_packets_at_traffic_stop,app_rx_packets_total,"
              << "app_rx_bytes_at_traffic_stop,app_rx_bytes_total,"
              << "app_duplicate_packets,app_malformed_packets,"
              << "app_delay_mean_ms,app_delay_p99_ms,"
              << "app_pdr_at_traffic_stop_pct,app_pdr_total_pct,"
              << "app_undelivered_at_stop_packets,"
              << "flowmon_throughput_mbps,flowmon_delay_mean_ms,"
              << "flowmon_delay_p99_ms,flowmon_pdr_pct,"
              << "flowmon_undelivered_at_stop_packets,flowmon_tx_packets,"
              << "flowmon_rx_packets,sinr_mean_db,sinr_samples,distance_gnb_m,"
              << "app_jain_traffic,app_jain_total,flowmon_jain,"
              << "app_throughput_traffic_aggregate_mbps,"
              << "app_goodput_total_aggregate_mbps,"
              << "flowmon_throughput_aggregate_mbps,"
              << "packet_size_bytes,lambda_pps,app_start_s,traffic_stop_s,"
              << "drain_time_s,total_stop_s,flow_max_per_hop_delay_s,"
              << "window_size_ms,central_frequency_hz,total_tx_power_dbm,"
              << "numerology,tdd_pattern\n";
    }

    if (enableConsoleDetails)
    {
        std::cout << std::endl;
        ImprimirSeparador('-', 52);
        std::cout << "DETALHE POR UE" << std::endl;
        ImprimirSeparador('-', 52);
    }

    for (uint32_t i = 0; i < ueNodes.GetN(); ++i)
    {
        const ResumoUe& r = resumoPorUe[i];
        const AppRxStats& app = g_appRxStats[i];

        uint32_t nFluxos = perfil.flowsPorUe;
        double delayMedioMs = nFluxos > 0 ? r.delaySomaMs / nFluxos : 0.0;

        double flowmonPdrPct = r.txPackets > 0
            ? static_cast<double>(r.rxPackets) / r.txPackets * 100.0 : 0.0;
        double appPdrTrafficPct = r.txPackets > 0
            ? static_cast<double>(app.trafficUniquePackets) / r.txPackets * 100.0 : 0.0;
        double appPdrTotalPct = r.txPackets > 0
            ? static_cast<double>(app.totalUniquePackets) / r.txPackets * 100.0 : 0.0;
        uint64_t appUndeliveredAtStop = r.txPackets > app.totalUniquePackets
            ? r.txPackets - app.totalUniquePackets : 0;
        double appDelayMeanMs = app.totalUniquePackets > 0
            ? app.delaySumMs / static_cast<double>(app.totalUniquePackets) : 0.0;
        double appDelayP99Ms = CalcularPercentilAmostras(app.delaysMs, 0.99);

        // CORREÇÃO (12/ago/2026): idem — busca por ueIdx real (i), não
        // mais por RNTI adivinhado.
        double sinrDb = 0.0;
        auto sinrIt = g_sinrAcumulado.find(i);
        if (sinrIt != g_sinrAcumulado.end() && sinrIt->second.second > 0)
        {
            sinrDb = sinrIt->second.first / sinrIt->second.second;
        }

        double distM = i < distanciasUe.size() ? distanciasUe[i] : 0.0;

        if (enableConsoleDetails)
        {
            std::cout << std::fixed;
            std::cout << "UE" << std::left << std::setw(2) << i
                      << " " << std::setw(8) << std::setprecision(2)
                      << appTrafficThroughputPorUe[i] << " Mbps(app)"
                      << " | SINR " << std::setw(7) << std::setprecision(2)
                      << sinrDb << " dB"
                      << " | Dist " << std::setw(6) << std::setprecision(1)
                      << distM << " m"
                      << " | Delay " << std::setw(7) << std::setprecision(2)
                      << appDelayMeanMs << " ms"
                      << " | PDR " << std::setprecision(2)
                      << appPdrTotalPct << "%" << std::endl;
        }

        if (enableUeSummaryCsv)
        {
            // RNTI real do UE (0 se por algum motivo nenhuma amostra de
            // SINR chegou a ser coletada para ele — não deveria acontecer
            // em uma simulação normal, mas evita usar um valor não
            // inicializado do mapa).
            auto rntiIt = g_ueIdxParaRnti.find(i);
            uint16_t rntiReal = (rntiIt != g_ueIdxParaRnti.end()) ? rntiIt->second : 0;
            const Vector& initialPosition = posicoesIniciaisUe[i];

            ueCsv << schedulerMode << ","
                  << trafficProfile << ","
                  << ueNumPergNb << ","
                  << seed << ","
                  << run << ","
                  << (bandwidth / 1e6) << ","
                  << (enableMobility ? mobilityModel : positionMode) << ","
                  << (enableMobility ? "true" : "false") << ","
                  << mobilityBounds << ","
                  << i << ","
                  << rntiReal << ","
                  << initialPosition.x << ","
                  << initialPosition.y << ","
                  << initialPosition.z << ","
                  << appTrafficThroughputPorUe[i] << ","
                  << appTotalGoodputPorUe[i] << ","
                  << app.trafficUniquePackets << ","
                  << app.totalUniquePackets << ","
                  << app.trafficBytes << ","
                  << app.totalBytes << ","
                  << app.duplicatePackets << ","
                  << app.malformedPackets << ","
                  << appDelayMeanMs << ","
                  << appDelayP99Ms << ","
                  << appPdrTrafficPct << ","
                  << appPdrTotalPct << ","
                  << appUndeliveredAtStop << ","
                  << r.throughputMbps << ","
                  << delayMedioMs << ","
                  << r.delayP99Ms << ","
                  << flowmonPdrPct << ","
                  << r.undeliveredAtStopPackets << ","
                  << r.txPackets << ","
                  << r.rxPackets << ","
                  << sinrDb << ","
                  << (sinrIt != g_sinrAcumulado.end() ? sinrIt->second.second : 0) << ","
                  << distM << ","
                  << appTrafficJain << ","
                  << appTotalJain << ","
                  << flowmonJain << ","
                  << appTrafficThroughputAgregado << ","
                  << appTotalGoodputAgregado << ","
                  << flowmonThroughputAgregado << ","
                  << perfil.pacoteBytes << ","
                  << perfil.lambda << ","
                  << udpAppStartTime.GetSeconds() << ","
                  << simTime.GetSeconds() << ","
                  << drainTime.GetSeconds() << ","
                  << totalStopTime.GetSeconds() << ","
                  << flowMaxPerHopDelay.GetSeconds() << ","
                  << windowSizeMs << ","
                  << centralFrequency << ","
                  << totalTxPowerDbm << ","
                  << static_cast<uint32_t>(numerology) << ","
                  << tddPattern << "\n";
        }
    }

    if (enableUeSummaryCsv)
    {
        ueCsv.close();
        NS_LOG_UNCOND("[VJ5G] ue_summary salvo em: " << ueSummaryCsvPath);
    }

    // Fecha o CSV de log por janela. RegistrarJanela inclui também
    // a última janela parcial e identifica traffic/drain explicitamente.
    if (enableWindowCsv && g_windowCsv.is_open())
    {
        g_windowCsv.close();
        NS_LOG_UNCOND("[VJ5G] window_log salvo em: " << windowCsvPath
                   << " (" << g_janelaId << " janelas)");
    }

    // Relatório visual no console
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
    std::cout << "RNG run             : " << run << std::endl;
    std::cout << "Bandwidth           : " << bandwidth/1e6 << " MHz" << std::endl;
    std::cout << "Numerologia         : " << static_cast<int>(numerology)
               << " (agora aplicada de fato — ver correção de 12/ago/2026)" << std::endl;
    std::cout << "Padrão TDD          : " << tddPattern
               << " (agora aplicado de fato — ver correção de 13/ago/2026)" << std::endl;
    std::cout << "Fim do tráfego      : " << simTime.GetSeconds() << " s" << std::endl;
    std::cout << "Tempo de drain      : " << drainTime.GetSeconds() << " s" << std::endl;
    std::cout << "Fim da simulação    : " << totalStopTime.GetSeconds() << " s" << std::endl;
    ImprimirSeparador('-', 52);
    std::cout << "Throughput app      : " << appTrafficThroughputAgregado << " Mbps" << std::endl;
    std::cout << "Goodput app + drain : " << appTotalGoodputAgregado << " Mbps" << std::endl;
    std::cout << "Throughput FlowMon  : " << flowmonThroughputAgregado << " Mbps" << std::endl;
    std::cout << "Jain app (tráfego)  : " << std::setprecision(4)
              << appTrafficJain << std::endl;
    std::cout << "Jain app (+ drain)  : " << appTotalJain << std::endl;
    std::cout << "Jain FlowMonitor    : " << flowmonJain << std::endl;
    std::cout << "SINR coletado       : " << g_sinrAcumulado.size()
              << " UEs" << std::endl;
    ImprimirSeparador('=', 52);

    // O diagnóstico [DIAG-SINR] que existia aqui (11/ago/2026) confirmou a
    // causa do sinr_mean_db=0 em UEs de índice mais alto: o código assumia
    // rnti = ueIdx + 1, mas os RNTIs reais atribuídos pela RRC não são
    // sequenciais a partir de 1 (numa rodada de 10 UEs, saíram
    // "1 2 3 4 5 6 11 12 13 14" — pulou de 6 para 11). Corrigido conectando
    // o trace de SINR com MakeBoundCallback amarrando o ueIdx real (Bloco
    // 6.1), então g_sinrAcumulado passou a ser indexado por ueIdx, não por
    // RNTI — ver simulacao-vj5g-utils.h. Diagnóstico removido depois de
    // confirmada a causa.

    // Linha estruturada para parsing pelo orquestrador Python
    NS_LOG_UNCOND("[RESULT]"
               << " scheduler=" << schedulerMode
               << " perfil=" << trafficProfile
               << " throughput_mbps=" << appTrafficThroughputAgregado
               << " jain_vazao=" << appTrafficJain
               << " app_total_goodput_mbps=" << appTotalGoodputAgregado
               << " app_total_jain=" << appTotalJain
               << " flowmon_throughput_mbps=" << flowmonThroughputAgregado
               << " flowmon_jain=" << flowmonJain
               << " ues=" << ueNumPergNb
               << " seed=" << seed
               << " rng_run=" << run);

    Simulator::Destroy();

    // --------------------------------------------------------
    // FIM DO BLOCO 7
    // Próximo: Bloco 8 — Resumo consolidado
    // --------------------------------------------------------

    return 0;
} // fim do main
