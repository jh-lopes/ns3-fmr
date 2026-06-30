/* -*-  Mode: C++; c-file-style: "gnu"; indent-tabs-mode: nil; -*- */

// ================================================================
// Simulacao5G V1.2
// Base para evolução da plataforma de simulação 5G-LENA.
// Esta versão mantém a infraestrutura da V1.1 e adiciona perfis de tráfego:
// - parâmetro typeTraffic
// - perfis EMBB, URLLC, MMTC e MISTO
// - registro do perfil nos arquivos e no relatório final
//
// A V1.1 adicionou somente infraestrutura de execução:
// - criação de pasta resultados-5g/data-hora/
// - configuracao.txt
// - resultados.csv
// - resumo.csv
// - flowmonitor.xml
// - barra de progresso
// - apresentação dos resultados também na tela
//
// Observação importante:
// Esta versão NÃO usa CcBwpHelper, pois essa classe não existe na API
// utilizada pelo 5G-LENA v4.1.1. A configuração de banda/BWP segue o
// padrão do exemplo oficial, usando CcBwpCreator.
// ================================================================


// 1. BIBLIOTECAS
#include "ns3/antenna-module.h"
#include "ns3/applications-module.h"
#include "ns3/buildings-module.h"
#include "ns3/config-store-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-apps-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/nr-module.h"
#include "ns3/point-to-point-module.h"

#include <cmath>
#include <cctype>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;

// Definição do componente de log
NS_LOG_COMPONENT_DEFINE("Simulacao5GV1_2");


// 2. VARIÁVEIS GLOBAIS DA INFRAESTRUTURA
std::string g_outputDir = "resultados-5g/";
std::string g_runDir;


// 3. FUNÇÕES AUXILIARES


// Estrutura que representa um perfil de tráfego da plataforma.
// Nesta versão, o perfil altera apenas os parâmetros da aplicação UDP,
// sem modificar rádio, BWP, numerologia ou escalonador.
struct PerfilDeTrafego
{
    std::string nome;
    std::string descricao;
    uint32_t tamanhoPacoteBytes;
    uint32_t lambdaPacotesPorSegundo;
};


// Normaliza o texto do tipo de tráfego para evitar erro por letras minúsculas.
std::string
NormalizarTypeTraffic(const std::string& typeTraffic)
{
    std::string valor = typeTraffic;

    for (char& caractere : valor)
    {
        caractere = static_cast<char>(std::toupper(static_cast<unsigned char>(caractere)));
    }

    return valor;
}


// Retorna os parâmetros de aplicação UDP para cada perfil de tráfego.
// EMBB  : pacotes maiores e alta taxa, priorizando vazão.
// URLLC : pacotes menores e alta frequência, priorizando atraso/jitter.
// MMTC  : pacotes pequenos e baixa frequência, representando tráfego leve de muitos dispositivos.
// MISTO : perfil intermediário para campanhas comparativas iniciais.
PerfilDeTrafego
ObterPerfilDeTrafego(const std::string& typeTraffic)
{
    std::string tipo = NormalizarTypeTraffic(typeTraffic);

    if (tipo == "EMBB")
    {
        return {"EMBB", "Enhanced Mobile Broadband - foco em vazão", 3000, 1000};
    }

    if (tipo == "URLLC")
    {
        return {"URLLC", "Ultra-Reliable Low-Latency Communications - foco em atraso e jitter", 300, 2000};
    }

    if (tipo == "MMTC")
    {
        return {"MMTC", "Massive Machine-Type Communications - tráfego leve e esparso", 100, 100};
    }

    if (tipo == "MISTO")
    {
        return {"MISTO", "Perfil híbrido simplificado para comparação inicial", 1200, 750};
    }

    NS_ABORT_MSG("typeTraffic inválido: " << typeTraffic
                                          << ". Use EMBB, URLLC, MMTC ou MISTO.");
}


// Gera string de data/hora para nomear pastas.
// Exemplo: 2026-06-25_20-15-30
std::string
GerarDataHora()
{
    std::time_t agora = std::time(nullptr);
    std::tm* tempoLocal = std::localtime(&agora);

    std::ostringstream nome;
    nome << std::put_time(tempoLocal, "%Y-%m-%d_%H-%M-%S");

    return nome.str();
}


// Cria a estrutura de pastas resultados-5g/DATA_HORA/.
void
CriarDiretorioDaExecucao()
{
    g_runDir = g_outputDir + GerarDataHora() + "/";

    std::error_code erro;
    std::filesystem::create_directories(g_runDir, erro);

    if (erro)
    {
        NS_ABORT_MSG("Erro ao criar diretório da execução: " << g_runDir
                                                            << " | detalhe: " << erro.message());
    }

    NS_LOG_UNCOND("Infraestrutura: pasta de resultados criada em: " << g_runDir);
}


// Salva os argumentos passados por linha de comando.
void
SalvarConfiguracao(int argc, char* argv[], const std::string& typeTraffic)
{
    std::ofstream arquivo(g_runDir + "configuracao.txt", std::ofstream::out | std::ofstream::trunc);

    if (!arquivo.is_open())
    {
        NS_ABORT_MSG("Não foi possível criar configuracao.txt em: " << g_runDir);
    }

    arquivo << "Versao=Simulacao5G V1.2\n";
    arquivo << "Descricao=Infraestrutura de resultados e perfis de tráfego sem alteração intencional da lógica do rádio\n";
    arquivo << "typeTraffic=" << typeTraffic << "\n";
    arquivo << "Comando=";

    for (int i = 0; i < argc; ++i)
    {
        arquivo << argv[i] << " ";
    }

    arquivo << "\n";
    arquivo.close();
}


// Cria arquivos CSV vazios logo no início da execução.
// Isso ajuda a confirmar que a infraestrutura está funcionando,
// mesmo que a simulação seja interrompida depois.
void
CriarArquivosBase()
{
    {
        std::ofstream arquivo(g_runDir + "resultados.csv", std::ofstream::out | std::ofstream::trunc);
        arquivo << "TypeTraffic,FlowID,Source,Dest,Throughput(Mbps),Delay(ms),Jitter(ms),LostPackets,PDR(%)\n";
    }

    {
        std::ofstream arquivo(g_runDir + "resumo.csv", std::ofstream::out | std::ofstream::trunc);
        arquivo << "Metrica,Valor\n";
        arquivo << "Status,Execucao iniciada\n";
    }

    {
        std::ofstream arquivo(g_runDir + "flowmonitor.xml", std::ofstream::out | std::ofstream::trunc);
        arquivo << "<!-- Arquivo temporario criado pela infraestrutura V1.1. "
                   "Ao final da simulacao, o FlowMonitor sobrescreve este arquivo. -->\n";
    }
}


// Barra de progresso visual no console.
void
ExibirBarraDeProgresso(Time simTime)
{
    double tempoAtual = Simulator::Now().GetSeconds();
    double tempoTotal = simTime.GetSeconds();

    double progresso = tempoTotal > 0.0 ? tempoAtual / tempoTotal : 1.0;

    if (progresso > 1.0)
    {
        progresso = 1.0;
    }

    const int largura = 40;
    int posicao = static_cast<int>(largura * progresso);

    std::cout << "\rProgresso da simulação: [";

    for (int i = 0; i < largura; ++i)
    {
        if (i < posicao)
        {
            std::cout << "=";
        }
        else if (i == posicao)
        {
            std::cout << ">";
        }
        else
        {
            std::cout << " ";
        }
    }

    std::cout << "] " << std::setw(3) << static_cast<int>(progresso * 100.0) << " %" << std::flush;

    if (Simulator::Now() + MilliSeconds(100) < simTime)
    {
        Simulator::Schedule(MilliSeconds(100), &ExibirBarraDeProgresso, simTime);
    }
}


// Imprime a barra final em 100% para evitar que a simulação termine visualmente em 90%.
void
ImprimirBarraDeProgressoFinal()
{
    const int largura = 40;

    std::cout << "\rProgresso da simulação: [";

    for (int i = 0; i < largura; ++i)
    {
        std::cout << "=";
    }

    std::cout << "] 100 %" << std::endl;
}


// Imprime uma linha separadora para organizar a saída no terminal.
void
ImprimirSeparador(char caractere = '-', int largura = 92)
{
    for (int i = 0; i < largura; ++i)
    {
        std::cout << caractere;
    }
    std::cout << std::endl;
}

// Converte endereços IPv4 para string antes da impressão.
// Isso evita desalinhamento visual quando std::setw é aplicado diretamente sobre Ipv4Address.
std::string
EnderecoParaString(const Ipv4Address& endereco)
{
    std::ostringstream texto;
    texto << endereco;
    return texto.str();
}

// Calcula o Índice de Justiça de Jain com base nas vazões dos fluxos.
double
CalcularJain(const std::vector<double>& valores)
{
    double soma = 0.0;
    double somaQuadrados = 0.0;
    uint32_t quantidade = 0;

    for (double valor : valores)
    {
        if (valor > 0.0)
        {
            soma += valor;
            somaQuadrados += valor * valor;
            quantidade++;
        }
    }

    if (quantidade == 0 || somaQuadrados == 0.0)
    {
        return 0.0;
    }

    return (soma * soma) / (static_cast<double>(quantidade) * somaQuadrados);
}

// Imprime o cabeçalho geral do relatório final no terminal.
void
ImprimirCabecalhoRelatorio(const std::string& schedulerType,
                           const std::string& modoEscalonador,
                           const PerfilDeTrafego& perfil,
                           uint16_t gNbNum,
                           uint16_t ueNumPergNb,
                           uint32_t fluxosEncontrados)
{
    std::cout << std::endl;
    ImprimirSeparador('=', 52);
    std::cout << "              RESULTADOS DA SIMULAÇÃO" << std::endl;
    ImprimirSeparador('=', 52);
    std::cout << std::endl;

    std::cout << "Escalonador : " << schedulerType << std::endl;
    std::cout << "Modo         : " << modoEscalonador << std::endl;
    std::cout << "Tráfego      : " << perfil.nome << std::endl;
    std::cout << "Descrição    : " << perfil.descricao << std::endl;
    std::cout << "Pacote UDP   : " << perfil.tamanhoPacoteBytes << " bytes" << std::endl;
    std::cout << "Lambda UDP   : " << perfil.lambdaPacotesPorSegundo << " pacotes/s" << std::endl;
    std::cout << "gNBs         : " << gNbNum << std::endl;
    std::cout << "UEs          : " << static_cast<uint32_t>(gNbNum) * ueNumPergNb << std::endl;
    std::cout << std::endl;
    std::cout << "Fluxos encontrados : " << fluxosEncontrados << std::endl;
}

// Imprime as métricas de um fluxo individual no formato de relatório.
void
ImprimirBlocoFluxo(uint32_t flowId,
                   const std::string& origem,
                   uint16_t portaOrigem,
                   const std::string& destino,
                   uint16_t portaDestino,
                   uint64_t txPackets,
                   uint64_t rxPackets,
                   uint64_t perdas,
                   double throughput,
                   double delay,
                   double jitter,
                   double pdr)
{
    std::cout << std::endl;
    ImprimirSeparador('-', 52);
    std::cout << "Fluxo " << flowId << std::endl;
    ImprimirSeparador('-', 52);

    std::cout << "Origem     : " << origem << ":" << portaOrigem << std::endl;
    std::cout << "Destino    : " << destino << ":" << portaDestino << std::endl;
    std::cout << std::endl;

    std::cout << "Tx Packets : " << txPackets << std::endl;
    std::cout << "Rx Packets : " << rxPackets << std::endl;
    std::cout << "Perdas     : " << perdas << std::endl;
    std::cout << std::endl;

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "Throughput : " << throughput << " Mbps" << std::endl;
    std::cout << "Delay      : " << delay << " ms" << std::endl;
    std::cout << "Jitter     : " << jitter << " ms" << std::endl;
    std::cout << "PDR        : " << pdr << " %" << std::endl;
}

// Imprime a lista de arquivos gerados pela infraestrutura da versão V1.1.
void
ImprimirArquivosGerados(const std::string& diretorio)
{
    std::cout << std::endl;
    std::cout << "Arquivos gerados" << std::endl;
    std::cout << std::endl;
    std::cout << "✔ configuracao.txt" << std::endl;
    std::cout << "✔ resultados.csv" << std::endl;
    std::cout << "✔ resumo.csv" << std::endl;
    std::cout << "✔ flowmonitor.xml" << std::endl;
    std::cout << std::endl;
    std::cout << "Diretório" << std::endl;
    std::cout << std::endl;
    std::cout << diretorio << std::endl;
}

// 4. FUNÇÃO MAIN
int
main(int argc, char* argv[])
{
    // --------------------------------------------------------------------
    // 1. CONFIGURAÇÃO DE PARÂMETROS
    // --------------------------------------------------------------------
    uint16_t gNbNum = 1;
    uint16_t ueNumPergNb = 2;
    bool logging = false;

    Time simTime = MilliSeconds(1000);
    Time udpAppStartTime = MilliSeconds(400);

    uint16_t numerology = 0;
    double centralFrequency = 4e9;
    double bandwidth = 10e6;
    double totalTxPower = 43;

    bool enableOfdma = false;
    std::string schedulerType = "PF";
    std::string typeTraffic = "EMBB";

    CommandLine cmd(__FILE__);

    cmd.AddValue("gNbNum", "Número de gNBs", gNbNum);
    cmd.AddValue("ueNumPergNb", "Número de UEs por gNB", ueNumPergNb);
    cmd.AddValue("logging", "Habilita logs", logging);
    cmd.AddValue("simTime", "Tempo de simulação", simTime);
    cmd.AddValue("numerology", "Numerologia usada no gNB", numerology);
    cmd.AddValue("centralFrequency", "Frequência central do sistema", centralFrequency);
    cmd.AddValue("bandwidth", "Largura de banda do sistema", bandwidth);
    cmd.AddValue("totalTxPower", "Potência total de transmissão", totalTxPower);
    cmd.AddValue("enableOfdma", "Se verdadeiro, usa escalonador OFDMA; caso contrário, TDMA", enableOfdma);
    cmd.AddValue("schedulerType", "Tipo de escalonador: PF, RR ou MR", schedulerType);
    cmd.AddValue("typeTraffic", "Perfil de tráfego: EMBB, URLLC, MMTC ou MISTO", typeTraffic);

    cmd.Parse(argc, argv);

    PerfilDeTrafego perfilTrafego = ObterPerfilDeTrafego(typeTraffic);
    typeTraffic = perfilTrafego.nome;

    // --------------------------------------------------------------------
    // 2. INFRAESTRUTURA V1.1
    // --------------------------------------------------------------------
    CriarDiretorioDaExecucao();
    SalvarConfiguracao(argc, argv, typeTraffic);
    CriarArquivosBase();

    NS_LOG_UNCOND("Infraestrutura: arquivos base criados.");
    NS_LOG_UNCOND("Infraestrutura: iniciando configuração da simulação.");

    // --------------------------------------------------------------------
    // 3. CONFIGURAÇÃO DO CENÁRIO
    // --------------------------------------------------------------------
    if (logging)
    {
        auto logLevel =
            static_cast<LogLevel>(LOG_PREFIX_FUNC | LOG_PREFIX_TIME | LOG_PREFIX_NODE | LOG_LEVEL_INFO);

        LogComponentEnable("NrMacSchedulerNs3", logLevel);
        LogComponentEnable("NrMacSchedulerTdma", logLevel);
    }

    int64_t randomStream = 1;

    GridScenarioHelper gridScenario;
    gridScenario.SetRows(1);
    gridScenario.SetColumns(gNbNum);
    gridScenario.SetHorizontalBsDistance(5.0);
    gridScenario.SetVerticalBsDistance(5.0);
    gridScenario.SetBsHeight(1.5);
    gridScenario.SetUtHeight(1.5);
    gridScenario.SetSectorization(GridScenarioHelper::SINGLE);
    gridScenario.SetBsNumber(gNbNum);
    gridScenario.SetUtNumber(ueNumPergNb * gNbNum);
    gridScenario.SetScenarioHeight(3);
    gridScenario.SetScenarioLength(3);
    randomStream += gridScenario.AssignStreams(randomStream);
    gridScenario.CreateScenario();

    // --------------------------------------------------------------------
    // 4. CONFIGURAÇÃO NR
    // --------------------------------------------------------------------
    Ptr<NrPointToPointEpcHelper> nrEpcHelper = CreateObject<NrPointToPointEpcHelper>();
    Ptr<IdealBeamformingHelper> idealBeamformingHelper = CreateObject<IdealBeamformingHelper>();
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();

    nrHelper->SetBeamformingHelper(idealBeamformingHelper);
    nrHelper->SetEpcHelper(nrEpcHelper);

    nrEpcHelper->SetAttribute("S1uLinkDelay", TimeValue(MilliSeconds(0)));

    std::string subTipo = enableOfdma ? "Ofdma" : "Tdma";
    std::string escalonadorCompleto = "ns3::NrMacScheduler" + subTipo + schedulerType;

    NS_LOG_UNCOND("Escalonador configurado: " << escalonadorCompleto);
    nrHelper->SetSchedulerTypeId(TypeId::LookupByName(escalonadorCompleto));

    idealBeamformingHelper->SetAttribute("BeamformingMethod",
                                         TypeIdValue(DirectPathBeamforming::GetTypeId()));

    nrHelper->SetUeAntennaAttribute("NumRows", UintegerValue(1));
    nrHelper->SetUeAntennaAttribute("NumColumns", UintegerValue(1));
    nrHelper->SetUeAntennaAttribute("AntennaElement",
                                    PointerValue(CreateObject<IsotropicAntennaModel>()));

    nrHelper->SetGnbAntennaAttribute("NumRows", UintegerValue(1));
    nrHelper->SetGnbAntennaAttribute("NumColumns", UintegerValue(1));
    nrHelper->SetGnbAntennaAttribute("AntennaElement",
                                     PointerValue(CreateObject<IsotropicAntennaModel>()));

    // --------------------------------------------------------------------
    // 5. CONFIGURAÇÃO DE BANDA/BWP
    //
    // Correção principal:
    // A classe CcBwpHelper não existe. O padrão compatível com o exemplo
    // oficial do 5G-LENA é usar CcBwpCreator.
    // --------------------------------------------------------------------
    BandwidthPartInfoPtrVector allBwps;
    CcBwpCreator ccBwpCreator;
    OperationBandInfo band;
    const uint8_t numOfCcs = 1;

    CcBwpCreator::SimpleOperationBandConf bandConf(centralFrequency, bandwidth, numOfCcs);
    bandConf.m_numBwp = 1;

    band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf);

    Ptr<NrChannelHelper> channelHelper = CreateObject<NrChannelHelper>();
    channelHelper->ConfigureFactories("UMi", "LOS", "ThreeGpp");
    channelHelper->SetPathlossAttribute("ShadowingEnabled", BooleanValue(false));
    channelHelper->AssignChannelsToBands({band}, NrChannelHelper::INIT_PROPAGATION);

    allBwps = CcBwpCreator::GetAllBwps({band});

    double potenciaLinear = std::pow(10.0, totalTxPower / 10.0);

    // --------------------------------------------------------------------
    // 6. INSTALAÇÃO DOS DISPOSITIVOS
    // --------------------------------------------------------------------
    NetDeviceContainer gnbNetDev =
        nrHelper->InstallGnbDevice(gridScenario.GetBaseStations(), allBwps);

    NetDeviceContainer ueNetDev =
        nrHelper->InstallUeDevice(gridScenario.GetUserTerminals(), allBwps);

    randomStream += nrHelper->AssignStreams(gnbNetDev, randomStream);
    randomStream += nrHelper->AssignStreams(ueNetDev, randomStream);

    NrHelper::GetGnbPhy(gnbNetDev.Get(0), 0)->SetAttribute("Numerology",
                                                           UintegerValue(numerology));

    NrHelper::GetGnbPhy(gnbNetDev.Get(0), 0)->SetAttribute("TxPower",
                                                           DoubleValue(10 * std::log10(potenciaLinear)));

    // --------------------------------------------------------------------
    // 7. INTERNET, ENDEREÇAMENTO E ASSOCIAÇÃO
    // --------------------------------------------------------------------
    auto [remoteHost, remoteHostIpv4Address] =
        nrEpcHelper->SetupRemoteHost("100Gb/s", 2500, Seconds(0.0));

    InternetStackHelper internet;
    internet.Install(gridScenario.GetUserTerminals());

    Ipv4InterfaceContainer ueIpIface =
        nrEpcHelper->AssignUeIpv4Address(NetDeviceContainer(ueNetDev));

    nrHelper->AttachToClosestGnb(ueNetDev, gnbNetDev);

    // --------------------------------------------------------------------
    // 8. APLICAÇÕES UDP SIMPLES
    // --------------------------------------------------------------------
    uint16_t portaDl = 1234;
    uint32_t tamanhoPacoteUdp = perfilTrafego.tamanhoPacoteBytes;
    uint32_t lambda = perfilTrafego.lambdaPacotesPorSegundo;

    ApplicationContainer serverApps;
    UdpServerHelper servidorUdp(portaDl);
    serverApps.Add(servidorUdp.Install(gridScenario.GetUserTerminals()));

    UdpClientHelper clienteUdp;
    clienteUdp.SetAttribute("MaxPackets", UintegerValue(0xFFFFFFFF));
    clienteUdp.SetAttribute("PacketSize", UintegerValue(tamanhoPacoteUdp));
    clienteUdp.SetAttribute("Interval", TimeValue(Seconds(1.0 / lambda)));

    ApplicationContainer clientApps;

    for (uint32_t i = 0; i < gridScenario.GetUserTerminals().GetN(); ++i)
    {
        Address enderecoUe = ueIpIface.GetAddress(i);

        clienteUdp.SetAttribute(
            "Remote",
            AddressValue(addressUtils::ConvertToSocketAddress(enderecoUe, portaDl)));

        clientApps.Add(clienteUdp.Install(remoteHost));

        Ptr<NrEpcTft> tft = Create<NrEpcTft>();
        NrEpcTft::PacketFilter filtro;
        filtro.localPortStart = portaDl;
        filtro.localPortEnd = portaDl;
        tft->Add(filtro);

        NrEpsBearer bearer(NrEpsBearer::NGBR_LOW_LAT_EMBB);
        nrHelper->ActivateDedicatedEpsBearer(ueNetDev.Get(i), bearer, tft);
    }

    serverApps.Start(udpAppStartTime);
    clientApps.Start(udpAppStartTime);
    serverApps.Stop(simTime);
    clientApps.Stop(simTime);

    // --------------------------------------------------------------------
    // 9. FLOWMONITOR E EXECUÇÃO
    // --------------------------------------------------------------------
    FlowMonitorHelper flowmonHelper;

    NodeContainer endpointNodes;
    endpointNodes.Add(remoteHost);
    endpointNodes.Add(gridScenario.GetUserTerminals());

    Ptr<FlowMonitor> monitor = flowmonHelper.Install(endpointNodes);

    monitor->SetAttribute("DelayBinWidth", DoubleValue(0.001));
    monitor->SetAttribute("JitterBinWidth", DoubleValue(0.001));
    monitor->SetAttribute("PacketSizeBinWidth", DoubleValue(20));

    NS_LOG_UNCOND("Simulação iniciada.");
    Simulator::Schedule(Seconds(0.0), &ExibirBarraDeProgresso, simTime);

    Simulator::Stop(simTime);
    Simulator::Run();

    // Garante que a barra de progresso seja finalizada em 100% na tela.
    ImprimirBarraDeProgressoFinal();

    NS_LOG_UNCOND("Simulação finalizada. Exportando resultados.");

    // --------------------------------------------------------------------
    // 10. EXPORTAÇÃO DE RESULTADOS V1.1
    // --------------------------------------------------------------------
    monitor->CheckForLostPackets();

    FlowMonitor::FlowStatsContainer stats = monitor->GetFlowStats();
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowmonHelper.GetClassifier());

    double duracaoFluxo = (simTime - udpAppStartTime).GetSeconds();

    std::ofstream resultados(g_runDir + "resultados.csv", std::ofstream::out | std::ofstream::trunc);
    resultados << "TypeTraffic,FlowID,Source,Dest,Throughput(Mbps),Delay(ms),Jitter(ms),LostPackets,PDR(%)\n";

    double vazaoTotal = 0.0;
    double atrasoTotal = 0.0;
    double jitterTotal = 0.0;
    double pdrTotal = 0.0;
    uint64_t txTotal = 0;
    uint64_t rxTotal = 0;
    uint64_t perdasTotal = 0;
    uint32_t fluxosAtivos = 0;
    std::vector<double> vazoesParaJain;

    // A partir daqui, os mesmos valores exportados no CSV também são exibidos na tela,
    // agora em formato de relatório textual por fluxo.
    ImprimirCabecalhoRelatorio(schedulerType,
                               subTipo,
                               perfilTrafego,
                               gNbNum,
                               ueNumPergNb,
                               static_cast<uint32_t>(stats.size()));

    for (auto const& flow : stats)
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(flow.first);

        double vazao = 0.0;
        double atraso = 0.0;
        double jitter = 0.0;
        double pdr = 0.0;

        if (flow.second.rxPackets > 0)
        {
            vazao = flow.second.rxBytes * 8.0 / duracaoFluxo / 1e6;
            atraso = flow.second.delaySum.GetMilliSeconds() /
                     static_cast<double>(flow.second.rxPackets);
            jitter = flow.second.jitterSum.GetMilliSeconds() /
                     static_cast<double>(flow.second.rxPackets);
        }

        if (flow.second.txPackets > 0)
        {
            pdr = 100.0 * static_cast<double>(flow.second.rxPackets) /
                  static_cast<double>(flow.second.txPackets);
        }

        std::string origem = EnderecoParaString(t.sourceAddress);
        std::string destino = EnderecoParaString(t.destinationAddress);

        resultados << typeTraffic << ","
                   << flow.first << ","
                   << origem << ","
                   << destino << ","
                   << vazao << ","
                   << atraso << ","
                   << jitter << ","
                   << flow.second.lostPackets << ","
                   << pdr << "\n";

        ImprimirBlocoFluxo(flow.first,
                           origem,
                           t.sourcePort,
                           destino,
                           t.destinationPort,
                           flow.second.txPackets,
                           flow.second.rxPackets,
                           flow.second.lostPackets,
                           vazao,
                           atraso,
                           jitter,
                           pdr);

        if (flow.second.rxPackets > 0)
        {
            vazaoTotal += vazao;
            atrasoTotal += atraso;
            jitterTotal += jitter;
            pdrTotal += pdr;
            txTotal += flow.second.txPackets;
            rxTotal += flow.second.rxPackets;
            perdasTotal += flow.second.lostPackets;
            vazoesParaJain.push_back(vazao);
            fluxosAtivos++;
        }
    }

    resultados.close();

    double divisor = fluxosAtivos > 0 ? static_cast<double>(fluxosAtivos) : 1.0;
    double vazaoMedia = vazaoTotal / divisor;
    double atrasoMedio = atrasoTotal / divisor;
    double jitterMedio = jitterTotal / divisor;
    double pdrMedio = pdrTotal / divisor;
    double jain = CalcularJain(vazoesParaJain);

    std::ofstream resumo(g_runDir + "resumo.csv", std::ofstream::out | std::ofstream::trunc);
    resumo << "Metrica,Valor\n";
    resumo << "TypeTraffic," << typeTraffic << "\n";
    resumo << "DescricaoTrafego," << perfilTrafego.descricao << "\n";
    resumo << "TamanhoPacoteUDP(bytes)," << perfilTrafego.tamanhoPacoteBytes << "\n";
    resumo << "LambdaUDP(pacotes/s)," << perfilTrafego.lambdaPacotesPorSegundo << "\n";
    resumo << "VazaoAgregada(Mbps)," << vazaoTotal << "\n";
    resumo << "VazaoMedia(Mbps)," << vazaoMedia << "\n";
    resumo << "AtrasoMedio(ms)," << atrasoMedio << "\n";
    resumo << "JitterMedio(ms)," << jitterMedio << "\n";
    resumo << "PDRMedio(%)," << pdrMedio << "\n";
    resumo << "JainThroughput," << jain << "\n";
    resumo << "TxPacketsTotal," << txTotal << "\n";
    resumo << "RxPacketsTotal," << rxTotal << "\n";
    resumo << "PerdasTotal," << perdasTotal << "\n";
    resumo << "FluxosAtivos," << fluxosAtivos << "\n";
    resumo << "Escalonador," << schedulerType << "\n";
    resumo << "ModoEscalonador," << subTipo << "\n";
    resumo << "TempoSimulacao(s)," << simTime.GetSeconds() << "\n";
    resumo.close();

    std::cout << std::endl;
    ImprimirSeparador('-', 52);
    std::cout << "RESUMO GERAL" << std::endl;
    ImprimirSeparador('-', 52);
    std::cout << std::endl;

    std::cout << "TypeTraffic         : " << typeTraffic << std::endl;
    std::cout << "Perfil              : " << perfilTrafego.descricao << std::endl;
    std::cout << std::endl;
    std::cout << std::fixed << std::setprecision(2);
    std::cout << "Throughput agregado : " << vazaoTotal << " Mbps" << std::endl;
    std::cout << "Throughput médio    : " << vazaoMedia << " Mbps" << std::endl;
    std::cout << "Delay médio         : " << atrasoMedio << " ms" << std::endl;
    std::cout << "Jitter médio        : " << jitterMedio << " ms" << std::endl;
    std::cout << "PDR médio           : " << pdrMedio << " %" << std::endl;
    std::cout << "Perdas              : " << perdasTotal << std::endl;
    std::cout << std::fixed << std::setprecision(4);
    std::cout << "Índice de Jain      : " << jain << std::endl;
    std::cout << std::endl;
    std::cout << std::fixed << std::setprecision(3);
    std::cout << "Tempo simulado      : " << simTime.GetSeconds() << " s" << std::endl;

    monitor->SerializeToXmlFile(g_runDir + "flowmonitor.xml", true, true);

    ImprimirArquivosGerados(g_runDir);

    std::cout << std::endl;
    ImprimirSeparador('=', 52);

    NS_LOG_UNCOND("Resultados salvos em: " << g_runDir);

    Simulator::Destroy();

    return 0;
}
