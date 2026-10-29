#include "ns3/aodv-module.h"
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-flow-classifier.h"
#include "ns3/mobility-module.h"
#include "ns3/olsr-module.h"
#include "ns3/propagation-module.h"
#include "ns3/wifi-module.h"

#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

using namespace ns3;

namespace
{
uint32_t g_applicationTxPackets = 0;
uint32_t g_applicationRxPackets = 0;

void
CountApplicationTx(Ptr<const Packet>)
{
    ++g_applicationTxPackets;
}

void
CountApplicationRx(Ptr<const Packet>, const Address&)
{
    ++g_applicationRxPackets;
}
} // namespace

int
main(int argc, char* argv[])
{
    std::string scenario = "single-hop";
    std::string routing = "global";
    std::string profile = "range_limited_wifi";
    uint32_t seed = 20261029;
    CommandLine command(__FILE__);
    command.AddValue("scenario", "single-hop, out-of-range, or linear-chain", scenario);
    command.AddValue("routing", "global, aodv, or olsr", routing);
    command.AddValue("profile", "range_limited_wifi or log_distance_wifi", profile);
    command.AddValue("seed", "ns-3 RNG seed", seed);
    command.Parse(argc, argv);

    uint32_t nodeCount = 0;
    double rangeM = 50.0;
    std::vector<double> xCoordinates;
    if (scenario == "single-hop")
    {
        nodeCount = 2;
        xCoordinates = {0.0, 20.0};
    }
    else if (scenario == "out-of-range")
    {
        nodeCount = 2;
        xCoordinates = {0.0, 100.0};
    }
    else if (scenario == "linear-chain")
    {
        nodeCount = 3;
        xCoordinates = {0.0, 40.0, 80.0};
    }
    else
    {
        std::cerr << "Unsupported scenario: " << scenario << '\n';
        return 2;
    }

    if ((profile != "range_limited_wifi" && profile != "log_distance_wifi") ||
        (routing != "global" && routing != "aodv" && routing != "olsr") ||
        (scenario == "linear-chain" && routing == "global") ||
        (scenario != "linear-chain" && routing != "global"))
    {
        std::cerr << "Unsupported routing/scenario combination\n";
        return 2;
    }

    constexpr uint16_t port = 9000;
    constexpr uint32_t offeredPackets = 5;
    constexpr uint32_t packetSizeBytes = 256;
    constexpr double intervalSeconds = 1.0;
    constexpr double trafficStartSeconds = 10.0;
    constexpr double simulationDurationSeconds = 20.0;
    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(1);

    NodeContainer nodes;
    nodes.Create(nodeCount);

    Ptr<ListPositionAllocator> positions = CreateObject<ListPositionAllocator>();
    for (double x : xCoordinates)
    {
        positions->Add(Vector(x, 0.0, 0.0));
    }
    MobilityHelper mobility;
    mobility.SetPositionAllocator(positions);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodes);

    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    if (profile == "range_limited_wifi")
    {
        channel.AddPropagationLoss("ns3::RangePropagationLossModel",
                                   "MaxRange",
                                   DoubleValue(rangeM));
    }
    else
    {
        channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
                                   "Exponent",
                                   DoubleValue(3.0),
                                   "ReferenceDistance",
                                   DoubleValue(1.0),
                                   "ReferenceLoss",
                                   DoubleValue(40.05));
    }
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    phy.Set("ChannelSettings", StringValue("{1, 20, BAND_2_4GHZ, 0}"));
    phy.Set("TxPowerStart", DoubleValue(16.0));
    phy.Set("TxPowerEnd", DoubleValue(16.0));
    phy.Set("RxSensitivity", DoubleValue(-101.0));

    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode",
                                 StringValue("ErpOfdmRate6Mbps"),
                                 "ControlMode",
                                 StringValue("ErpOfdmRate6Mbps"));
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac", "FrameRetryLimit", UintegerValue(7));
    NetDeviceContainer devices = wifi.Install(phy, mac, nodes);

    InternetStackHelper internet;
    AodvHelper aodv;
    OlsrHelper olsr;
    Ipv4GlobalRoutingHelper global;
    if (routing == "aodv")
    {
        internet.SetRoutingHelper(aodv);
    }
    else if (routing == "olsr")
    {
        internet.SetRoutingHelper(olsr);
    }
    else
    {
        internet.SetRoutingHelper(global);
    }
    internet.Install(nodes);

    Ipv4AddressHelper addresses;
    addresses.SetBase("10.1.1.0", "255.255.255.0");
    Ipv4InterfaceContainer interfaces = addresses.Assign(devices);
    if (routing == "global")
    {
        Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    }

    PacketSinkHelper sinkHelper(
        "ns3::UdpSocketFactory",
        InetSocketAddress(Ipv4Address::GetAny(), port));
    ApplicationContainer sink = sinkHelper.Install(nodes.Get(nodeCount - 1));
    sink.Start(Seconds(0.0));
    sink.Stop(Seconds(simulationDurationSeconds));

    UdpClientHelper client(interfaces.GetAddress(nodeCount - 1), port);
    client.SetAttribute("MaxPackets", UintegerValue(offeredPackets));
    client.SetAttribute("Interval", TimeValue(Seconds(intervalSeconds)));
    client.SetAttribute("PacketSize", UintegerValue(packetSizeBytes));
    ApplicationContainer source = client.Install(nodes.Get(0));
    source.Start(Seconds(trafficStartSeconds));
    source.Stop(Seconds(simulationDurationSeconds - 0.1));

    g_applicationTxPackets = 0;
    g_applicationRxPackets = 0;
    Config::ConnectWithoutContext(
        "/NodeList/*/ApplicationList/*/$ns3::UdpClient/Tx",
        MakeCallback(&CountApplicationTx));
    Config::ConnectWithoutContext(
        "/NodeList/*/ApplicationList/*/$ns3::PacketSink/Rx",
        MakeCallback(&CountApplicationRx));

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();
    Simulator::Stop(Seconds(simulationDurationSeconds));
    Simulator::Run();
    monitor->CheckForLostPackets(Seconds(0));

    const auto classifier = DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    uint32_t txPackets = 0;
    uint32_t rxPackets = 0;
    uint32_t lostPackets = 0;
    uint32_t timesForwarded = 0;
    uint32_t flowTxPackets = 0;
    uint32_t flowRxPackets = 0;
    double meanDelayMs = std::nan("");
    double legacyIntegerMeanDelayMs = std::nan("");
    bool flowFound = false;
    for (const auto& entry : monitor->GetFlowStats())
    {
        const auto tuple = classifier->FindFlow(entry.first);
        if (tuple.sourceAddress == interfaces.GetAddress(0) &&
            tuple.destinationAddress == interfaces.GetAddress(nodeCount - 1) &&
            tuple.destinationPort == port)
        {
            const auto& stats = entry.second;
            flowTxPackets += stats.txPackets;
            flowRxPackets += stats.rxPackets;
            lostPackets += stats.lostPackets;
            timesForwarded += stats.timesForwarded;
            if (stats.rxPackets > 0)
            {
                meanDelayMs =
                    1000.0 * stats.delaySum.GetSeconds() / static_cast<double>(stats.rxPackets);
                legacyIntegerMeanDelayMs = static_cast<double>(
                    stats.delaySum.GetMilliSeconds() / stats.rxPackets);
            }
            flowFound = true;
        }
    }
    Simulator::Destroy();

    txPackets = g_applicationTxPackets;
    rxPackets = g_applicationRxPackets;
    const double pdr = txPackets > 0 ? static_cast<double>(rxPackets) / txPackets : 0.0;
    const double hopEstimate =
        rxPackets > 0 ? 1.0 + static_cast<double>(timesForwarded) / rxPackets : std::nan("");
    const double sourceDestinationDistanceM = xCoordinates.back() - xCoordinates.front();
    bool passed = flowFound && txPackets == offeredPackets;
    if (scenario == "single-hop")
    {
        passed = passed && rxPackets == txPackets;
    }
    else if (scenario == "out-of-range")
    {
        passed = passed && rxPackets == 0;
    }
    else
    {
        passed = passed && rxPackets > 0 && hopEstimate >= 1.9;
    }

    std::cout << std::fixed << std::setprecision(6)
              << "RESULT," << profile << ',' << scenario << ',' << routing << ',' << nodeCount << ','
              << sourceDestinationDistanceM << ',' << rangeM << ','
              << simulationDurationSeconds << ',' << packetSizeBytes << ','
              << offeredPackets << ',' << txPackets << ',' << flowTxPackets << ','
              << flowRxPackets << ',' << rxPackets << ',' << pdr << ',';
    if (std::isfinite(meanDelayMs))
    {
        std::cout << meanDelayMs;
    }
    else
    {
        std::cout << "NA";
    }
    std::cout << ',';
    if (std::isfinite(legacyIntegerMeanDelayMs))
    {
        std::cout << legacyIntegerMeanDelayMs;
    }
    else
    {
        std::cout << "NA";
    }
    std::cout << ',' << timesForwarded << ',';
    if (std::isfinite(hopEstimate))
    {
        std::cout << hopEstimate;
    }
    else
    {
        std::cout << "NA";
    }
    std::cout << ',' << lostPackets << ",NA," << seed << ','
              << (passed ? "passed" : "failed") << '\n';
    return passed ? 0 : 1;
}
