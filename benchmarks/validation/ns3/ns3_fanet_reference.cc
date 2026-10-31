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

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using namespace ns3;

namespace
{
constexpr uint16_t kApplicationPort = 9000;
constexpr uint32_t kPacketIdHeaderBytes = 12;

int64_t
TimeKey(double timeSeconds)
{
    return static_cast<int64_t>(std::llround(timeSeconds * 1'000'000.0));
}

std::vector<std::string>
SplitCsv(const std::string& line)
{
    std::vector<std::string> values;
    std::stringstream stream(line);
    std::string value;
    while (std::getline(stream, value, ','))
    {
        values.push_back(value);
    }
    if (!line.empty() && line.back() == ',')
    {
        values.emplace_back();
    }
    return values;
}

double
ParseFiniteDouble(const std::string& value, const std::string& field)
{
    std::size_t consumed = 0;
    const double parsed = std::stod(value, &consumed);
    if (consumed != value.size() || !std::isfinite(parsed))
    {
        throw std::runtime_error("Invalid finite numeric value for " + field + ": " + value);
    }
    return parsed;
}

uint32_t
ParseUint32(const std::string& value, const std::string& field)
{
    std::size_t consumed = 0;
    const unsigned long parsed = std::stoul(value, &consumed);
    if (consumed != value.size() || parsed > UINT32_MAX)
    {
        throw std::runtime_error("Invalid uint32 value for " + field + ": " + value);
    }
    return static_cast<uint32_t>(parsed);
}

std::map<std::string, std::size_t>
HeaderIndexes(const std::string& line)
{
    const auto columns = SplitCsv(line);
    std::map<std::string, std::size_t> indexes;
    for (std::size_t i = 0; i < columns.size(); ++i)
    {
        if (!indexes.emplace(columns[i], i).second)
        {
            throw std::runtime_error("Duplicate CSV header: " + columns[i]);
        }
    }
    return indexes;
}

std::string
Field(const std::vector<std::string>& values,
      const std::map<std::string, std::size_t>& indexes,
      const std::string& name)
{
    const auto it = indexes.find(name);
    if (it == indexes.end() || it->second >= values.size())
    {
        throw std::runtime_error("Missing CSV field: " + name);
    }
    return values[it->second];
}

struct MobilityFrame
{
    double timeSeconds{};
    std::vector<Vector> positions;
};

struct ScheduledPacket
{
    uint32_t packetId{};
    double generationSeconds{};
    double evaluatedAtSeconds{};
    uint32_t source{};
    uint32_t destination{};
    std::string sourceName;
    std::string destinationName;
};

struct PacketObservation
{
    ScheduledPacket scheduled;
    bool applicationGenerated{false};
    bool socketAccepted{false};
    int32_t socketErrnoCode{-1};
    std::string socketErrnoSymbol{"NOT_APPLICABLE"};
    uint32_t receiveCount{0};
    double firstReceiveSeconds{std::nan("")};
    double scheduledSendSeconds{std::nan("")};
    uint32_t physicalMinimumHops{0};
};

struct RunState
{
    std::vector<Ptr<ConstantPositionMobilityModel>> mobility;
    std::map<int64_t, MobilityFrame> frames;
    std::unordered_map<uint32_t, PacketObservation> packets;
    uint32_t generatedPackets{0};
    uint32_t socketAcceptedPackets{0};
    uint32_t duplicateReceives{0};
    uint32_t invalidReceives{0};
    std::string experiment;
    std::string routing;
    std::string profile;
    std::string coordinateFrame;
    std::string repetitionSeed;
    std::string trafficSeed;
    uint32_t seed{0};
    uint32_t run{0};
    double warmupSeconds{0.0};
    double rangeMeters{35.0};
    bool lastEvaluationSet{false};
    double lastEvaluationSeconds{0.0};

    uint32_t MinimumPhysicalHops(uint32_t source, uint32_t destination) const
    {
        std::vector<int32_t> distance(mobility.size(), -1);
        std::vector<uint32_t> frontier{source};
        distance.at(source) = 0;
        for (std::size_t cursor = 0; cursor < frontier.size(); ++cursor)
        {
            const uint32_t current = frontier[cursor];
            if (current == destination)
            {
                return static_cast<uint32_t>(distance[current]);
            }
            for (uint32_t neighbor = 0; neighbor < mobility.size(); ++neighbor)
            {
                if (distance[neighbor] >= 0)
                {
                    continue;
                }
                const Vector delta =
                    mobility[current]->GetPosition() - mobility[neighbor]->GetPosition();
                if (std::sqrt(delta.x * delta.x + delta.y * delta.y + delta.z * delta.z) <=
                    rangeMeters)
                {
                    distance[neighbor] = distance[current] + 1;
                    frontier.push_back(neighbor);
                }
            }
        }
        return 0;
    }

    void ApplySnapshot(double timeSeconds)
    {
        if (lastEvaluationSet && timeSeconds + 1e-9 < lastEvaluationSeconds)
        {
            throw std::runtime_error("Packet schedule evaluates mobility out of time order");
        }
        const auto it = frames.find(TimeKey(timeSeconds));
        if (it == frames.end() || std::abs(it->second.timeSeconds - timeSeconds) > 1e-6)
        {
            throw std::runtime_error("No exact mobility frame for scheduled evaluation time " +
                                     std::to_string(timeSeconds));
        }
        if (it->second.positions.size() != mobility.size())
        {
            throw std::runtime_error("Mobility frame node count changed");
        }
        for (std::size_t i = 0; i < mobility.size(); ++i)
        {
            mobility[i]->SetPosition(it->second.positions[i]);
        }
        lastEvaluationSet = true;
        lastEvaluationSeconds = timeSeconds;
    }
};

const char*
SocketErrnoName(Socket::SocketErrno error)
{
    switch (error)
    {
    case Socket::ERROR_NOTERROR:
        return "ERROR_NOTERROR";
    case Socket::ERROR_ISCONN:
        return "ERROR_ISCONN";
    case Socket::ERROR_NOTCONN:
        return "ERROR_NOTCONN";
    case Socket::ERROR_MSGSIZE:
        return "ERROR_MSGSIZE";
    case Socket::ERROR_AGAIN:
        return "ERROR_AGAIN";
    case Socket::ERROR_SHUTDOWN:
        return "ERROR_SHUTDOWN";
    case Socket::ERROR_OPNOTSUPP:
        return "ERROR_OPNOTSUPP";
    case Socket::ERROR_AFNOSUPPORT:
        return "ERROR_AFNOSUPPORT";
    case Socket::ERROR_INVAL:
        return "ERROR_INVAL";
    case Socket::ERROR_BADF:
        return "ERROR_BADF";
    case Socket::ERROR_NOROUTETOHOST:
        return "ERROR_NOROUTETOHOST";
    case Socket::ERROR_NODEV:
        return "ERROR_NODEV";
    case Socket::ERROR_ADDRNOTAVAIL:
        return "ERROR_ADDRNOTAVAIL";
    case Socket::ERROR_ADDRINUSE:
        return "ERROR_ADDRINUSE";
    case Socket::SOCKET_ERRNO_LAST:
        return "SOCKET_ERRNO_LAST";
    }
    return "UNKNOWN_SOCKET_ERRNO";
}

class PacketIdentityHeader : public Header
{
  public:
    PacketIdentityHeader() = default;
    PacketIdentityHeader(uint32_t packetId, uint32_t source, uint32_t destination)
        : m_packetId(packetId),
          m_source(source),
          m_destination(destination)
    {
    }

    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::PacketIdentityHeader")
                                .SetParent<Header>()
                                .SetGroupName("Applications")
                                .AddConstructor<PacketIdentityHeader>();
        return tid;
    }
    TypeId GetInstanceTypeId() const override
    {
        return GetTypeId();
    }
    uint32_t GetSerializedSize() const override
    {
        return kPacketIdHeaderBytes;
    }
    void Serialize(Buffer::Iterator start) const override
    {
        start.WriteHtonU32(m_packetId);
        start.WriteHtonU32(m_source);
        start.WriteHtonU32(m_destination);
    }
    uint32_t Deserialize(Buffer::Iterator start) override
    {
        m_packetId = start.ReadNtohU32();
        m_source = start.ReadNtohU32();
        m_destination = start.ReadNtohU32();
        return kPacketIdHeaderBytes;
    }
    void Print(std::ostream& stream) const override
    {
        stream << "id=" << m_packetId << " src=" << m_source << " dst=" << m_destination;
    }
    uint32_t PacketId() const
    {
        return m_packetId;
    }
    uint32_t Source() const
    {
        return m_source;
    }
    uint32_t Destination() const
    {
        return m_destination;
    }

  private:
    uint32_t m_packetId{0};
    uint32_t m_source{0};
    uint32_t m_destination{0};
};

NS_OBJECT_ENSURE_REGISTERED(PacketIdentityHeader);

class ScheduledUdpApplication : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::ScheduledUdpApplication")
                                .SetParent<Application>()
                                .SetGroupName("Applications")
                                .AddConstructor<ScheduledUdpApplication>();
        return tid;
    }

    void Configure(std::shared_ptr<RunState> state,
                   uint32_t nodeIndex,
                   uint32_t packetBytes,
                   std::vector<ScheduledPacket> outgoing,
                   std::vector<Ipv4Address> addresses,
                   double simulationEnd)
    {
        m_state = std::move(state);
        m_nodeIndex = nodeIndex;
        m_packetBytes = packetBytes;
        m_outgoing = std::move(outgoing);
        m_addresses = std::move(addresses);
        m_simulationEnd = simulationEnd;
    }

  private:
    void StartApplication() override
    {
        m_receiveSocket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        if (m_receiveSocket->Bind(InetSocketAddress(Ipv4Address::GetAny(), kApplicationPort)) != 0)
        {
            throw std::runtime_error("Could not bind packet receiver socket");
        }
        m_receiveSocket->SetRecvCallback(MakeCallback(&ScheduledUdpApplication::Receive, this));

        m_sendSocket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        if (m_sendSocket->Bind() != 0)
        {
            throw std::runtime_error("Could not bind scheduled UDP sender socket");
        }
        for (const auto& event : m_outgoing)
        {
            Simulator::Schedule(Seconds(m_state->warmupSeconds + event.generationSeconds),
                                &ScheduledUdpApplication::SendOne,
                                this,
                                event);
        }
    }

    void StopApplication() override
    {
        if (m_receiveSocket)
        {
            m_receiveSocket->SetRecvCallback(MakeNullCallback<void, Ptr<Socket>>());
            m_receiveSocket->Close();
            m_receiveSocket = nullptr;
        }
        if (m_sendSocket)
        {
            m_sendSocket->Close();
            m_sendSocket = nullptr;
        }
    }

    void SendOne(ScheduledPacket event)
    {
        m_state->ApplySnapshot(event.evaluatedAtSeconds);
        auto it = m_state->packets.find(event.packetId);
        if (it == m_state->packets.end())
        {
            ++m_state->invalidReceives;
            return;
        }

        it->second.applicationGenerated = true;
        it->second.scheduledSendSeconds = Simulator::Now().GetSeconds();
        it->second.physicalMinimumHops =
            m_state->MinimumPhysicalHops(event.source, event.destination);
        ++m_state->generatedPackets;

        Ptr<Packet> packet = Create<Packet>(m_packetBytes - kPacketIdHeaderBytes);
        packet->AddHeader(PacketIdentityHeader(event.packetId, event.source, event.destination));
        const int sent = m_sendSocket->SendTo(
            packet,
            0,
            InetSocketAddress(m_addresses.at(event.destination), kApplicationPort));
        if (sent >= 0)
        {
            it->second.socketAccepted = true;
            ++m_state->socketAcceptedPackets;
        }
        else
        {
            const Socket::SocketErrno error = m_sendSocket->GetErrno();
            it->second.socketErrnoCode = static_cast<int32_t>(error);
            it->second.socketErrnoSymbol = SocketErrnoName(error);
        }
    }

    void Receive(Ptr<Socket> socket)
    {
        Address from;
        while (Ptr<Packet> packet = socket->RecvFrom(from))
        {
            PacketIdentityHeader header;
            if (packet->GetSize() < kPacketIdHeaderBytes ||
                packet->RemoveHeader(header) != kPacketIdHeaderBytes)
            {
                ++m_state->invalidReceives;
                continue;
            }
            auto it = m_state->packets.find(header.PacketId());
            if (it == m_state->packets.end() ||
                it->second.scheduled.source != header.Source() ||
                it->second.scheduled.destination != header.Destination() ||
                header.Destination() != m_nodeIndex)
            {
                ++m_state->invalidReceives;
                continue;
            }
            ++it->second.receiveCount;
            if (it->second.receiveCount == 1)
            {
                it->second.firstReceiveSeconds = Simulator::Now().GetSeconds();
            }
            else
            {
                ++m_state->duplicateReceives;
            }
        }
    }

    std::shared_ptr<RunState> m_state;
    uint32_t m_nodeIndex{0};
    uint32_t m_packetBytes{256};
    std::vector<ScheduledPacket> m_outgoing;
    std::vector<Ipv4Address> m_addresses;
    double m_simulationEnd{0.0};
    Ptr<Socket> m_receiveSocket;
    Ptr<Socket> m_sendSocket;
};

NS_OBJECT_ENSURE_REGISTERED(ScheduledUdpApplication);

std::vector<MobilityFrame>
ReadMobility(const std::string& path,
             std::map<std::string, uint32_t>& nodeIds,
             const std::string& coordinateFrame)
{
    std::ifstream input(path);
    if (!input)
    {
        throw std::runtime_error("Cannot open mobility file: " + path);
    }
    std::string line;
    if (!std::getline(input, line))
    {
        throw std::runtime_error("Mobility CSV is empty");
    }
    const auto columns = HeaderIndexes(line);
    for (const auto& name : {"time_s", "node_id", "x_m", "y_m", "z_m"})
    {
        if (!columns.contains(name))
        {
            throw std::runtime_error(std::string("Mobility CSV lacks ") + name);
        }
    }

    std::map<int64_t, std::map<std::string, Vector>> grouped;
    std::map<int64_t, double> originalTimes;
    while (std::getline(input, line))
    {
        if (line.empty())
        {
            continue;
        }
        const auto values = SplitCsv(line);
        const double time = ParseFiniteDouble(Field(values, columns, "time_s"), "time_s");
        const std::string name = Field(values, columns, "node_id");
        if (name.empty())
        {
            throw std::runtime_error("Mobility CSV has an empty node_id");
        }
        const double x = ParseFiniteDouble(Field(values, columns, "x_m"), "x_m");
        const double y = ParseFiniteDouble(Field(values, columns, "y_m"), "y_m");
        double z = ParseFiniteDouble(Field(values, columns, "z_m"), "z_m");
        if (coordinateFrame == "ned")
        {
            z = -z;
        }
        else if (coordinateFrame != "cartesian")
        {
            throw std::runtime_error("coordinate-frame must be ned or cartesian");
        }
        const int64_t key = TimeKey(time);
        originalTimes[key] = time;
        if (!grouped[key].emplace(name, Vector(x, y, z)).second)
        {
            throw std::runtime_error("Duplicate node in mobility frame: " + name);
        }
    }
    if (grouped.empty())
    {
        throw std::runtime_error("Mobility CSV has no frames");
    }

    for (const auto& [name, position] : grouped.begin()->second)
    {
        (void)position;
        nodeIds.emplace(name, static_cast<uint32_t>(nodeIds.size()));
    }
    std::vector<MobilityFrame> frames;
    double previousTime = -1.0;
    for (const auto& [key, frameNodes] : grouped)
    {
        const double time = originalTimes.at(key);
        if (time <= previousTime)
        {
            throw std::runtime_error("Mobility frame times are not strictly increasing");
        }
        if (frameNodes.size() != nodeIds.size())
        {
            throw std::runtime_error("Mobility frames do not contain the same node count");
        }
        MobilityFrame frame;
        frame.timeSeconds = time;
        frame.positions.resize(nodeIds.size());
        for (const auto& [name, index] : nodeIds)
        {
            const auto position = frameNodes.find(name);
            if (position == frameNodes.end())
            {
                throw std::runtime_error("Mobility frame is missing node " + name);
            }
            frame.positions[index] = position->second;
        }
        frames.push_back(std::move(frame));
        previousTime = time;
    }
    return frames;
}

std::vector<ScheduledPacket>
ReadTraffic(const std::string& path,
            const std::map<std::string, uint32_t>& nodeIds,
            const std::map<int64_t, MobilityFrame>& frames)
{
    std::ifstream input(path);
    if (!input)
    {
        throw std::runtime_error("Cannot open traffic schedule: " + path);
    }
    std::string line;
    if (!std::getline(input, line))
    {
        throw std::runtime_error("Traffic schedule is empty");
    }
    const auto columns = HeaderIndexes(line);
    for (const auto& name : {"packet_id", "generation_time_s", "evaluated_at_time_s",
                             "source_id", "destination_id"})
    {
        if (!columns.contains(name))
        {
            throw std::runtime_error(std::string("Traffic CSV lacks ") + name);
        }
    }

    std::vector<ScheduledPacket> events;
    std::set<uint32_t> ids;
    double previousGeneration = -1.0;
    double previousEvaluation = -1.0;
    while (std::getline(input, line))
    {
        if (line.empty())
        {
            continue;
        }
        const auto values = SplitCsv(line);
        ScheduledPacket event;
        event.packetId = ParseUint32(Field(values, columns, "packet_id"), "packet_id");
        event.generationSeconds =
            ParseFiniteDouble(Field(values, columns, "generation_time_s"), "generation_time_s");
        event.evaluatedAtSeconds =
            ParseFiniteDouble(Field(values, columns, "evaluated_at_time_s"), "evaluated_at_time_s");
        event.sourceName = Field(values, columns, "source_id");
        event.destinationName = Field(values, columns, "destination_id");
        if (!ids.insert(event.packetId).second)
        {
            throw std::runtime_error("Duplicate packet_id in traffic schedule");
        }
        const auto source = nodeIds.find(event.sourceName);
        const auto destination = nodeIds.find(event.destinationName);
        if (source == nodeIds.end() || destination == nodeIds.end())
        {
            throw std::runtime_error("Traffic source/destination is not in mobility input");
        }
        if (source->second == destination->second)
        {
            throw std::runtime_error("Traffic schedule contains a self-directed packet");
        }
        if (event.generationSeconds < 0.0 ||
            event.generationSeconds <= previousGeneration ||
            event.evaluatedAtSeconds < previousEvaluation)
        {
            throw std::runtime_error("Traffic schedule times are invalid or not monotonic");
        }
        if (!frames.contains(TimeKey(event.evaluatedAtSeconds)) ||
            std::abs(frames.at(TimeKey(event.evaluatedAtSeconds)).timeSeconds -
                     event.evaluatedAtSeconds) > 1e-6)
        {
            throw std::runtime_error("Traffic evaluation time has no exact mobility frame");
        }
        event.source = source->second;
        event.destination = destination->second;
        events.push_back(event);
        previousGeneration = event.generationSeconds;
        previousEvaluation = event.evaluatedAtSeconds;
    }
    if (events.empty())
    {
        throw std::runtime_error("Traffic schedule contains no packets");
    }
    return events;
}

void
WriteOutputs(const std::string& summaryPath,
             const std::string& eventsPath,
             const std::shared_ptr<RunState>& state,
             const std::vector<ScheduledPacket>& schedule,
             Ptr<FlowMonitor> monitor,
             FlowMonitorHelper& flowHelper,
             const std::vector<Ipv4Address>& addresses,
             double drainSeconds,
             uint32_t packetBytes,
             uint32_t totalFrames,
             double measurementSeconds,
             double rangeMeters)
{
    monitor->CheckForLostPackets();
    const auto classifier = DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    uint64_t flowTx = 0;
    uint64_t flowRx = 0;
    uint64_t flowLost = 0;
    uint64_t flowReportedDrops = 0;
    uint64_t forwarded = 0;
    double flowDelaySeconds = 0.0;
    const auto statsByFlow = monitor->GetFlowStats();
    for (const auto& [flowId, stats] : statsByFlow)
    {
        const auto tuple = classifier->FindFlow(flowId);
        if (tuple.destinationPort != kApplicationPort)
        {
            continue;
        }
        flowTx += stats.txPackets;
        flowRx += stats.rxPackets;
        flowLost += stats.lostPackets;
        for (const uint32_t dropped : stats.packetsDropped)
        {
            flowReportedDrops += dropped;
        }
        forwarded += stats.timesForwarded;
        flowDelaySeconds += stats.delaySum.GetSeconds();
    }
    if (flowLost < flowReportedDrops)
    {
        throw std::runtime_error(
            "FlowMonitor reported-drop count exceeds lostPackets");
    }
    const uint64_t flowPendingTimeout = flowLost - flowReportedDrops;

    uint32_t uniqueReceived = 0;
    double applicationDelaySum = 0.0;
    for (const auto& [packetId, observation] : state->packets)
    {
        (void)packetId;
        if (observation.receiveCount > 0)
        {
            ++uniqueReceived;
            applicationDelaySum +=
                observation.firstReceiveSeconds - observation.scheduledSendSeconds;
        }
    }
    if (uniqueReceived > state->generatedPackets)
    {
        throw std::runtime_error("Application delivery count exceeds generated packet count");
    }
    const double pdr = state->generatedPackets
                           ? static_cast<double>(uniqueReceived) / state->generatedPackets
                           : 0.0;
    const double appDelayMs = uniqueReceived
                                  ? 1000.0 * applicationDelaySum / uniqueReceived
                                  : std::nan("");
    const double flowDelayMs =
        flowRx ? 1000.0 * flowDelaySeconds / static_cast<double>(flowRx) : std::nan("");
    const double forwardingEstimate =
        flowRx ? 1.0 + static_cast<double>(forwarded) / flowRx : std::nan("");
    const uint32_t undelivered =
        state->generatedPackets >= uniqueReceived ? state->generatedPackets - uniqueReceived : 0;

    std::ofstream summary(summaryPath);
    if (!summary)
    {
        throw std::runtime_error("Cannot write run summary");
    }
    summary << "experiment,routing,profile,coordinate_frame,repetition_seed,traffic_seed,"
               "ns3_seed,ns3_run,n_nodes,mobility_frames,"
               "measurement_s,warmup_s,drain_s,packet_bytes,scheduled_packets,"
               "application_generated_packets,socket_accepted_packets,socket_rejected_packets,"
               "flowmonitor_tx_packets,"
               "flowmonitor_rx_packets,flowmonitor_lost_packets,"
               "flowmonitor_reported_drop_packets,flowmonitor_pending_timeout_packets,"
               "application_unique_delivered_packets,"
               "application_duplicate_receives,invalid_packet_receives,"
               "undelivered_after_drain_packets,pdr,"
               "mean_application_delay_ms,mean_flowmonitor_delay_ms,times_forwarded,"
               "forwarding_based_hops_estimate,control_messages,control_bytes\n";
    summary << state->experiment << ',' << state->routing << ',' << state->profile << ','
            << state->coordinateFrame << ',' << state->repetitionSeed << ','
            << state->trafficSeed << ',' << state->seed << ',' << state->run << ','
            << addresses.size() << ',' << totalFrames << ',' << std::setprecision(12)
            << measurementSeconds << ',' << state->warmupSeconds << ',' << drainSeconds << ','
            << packetBytes << ',' << schedule.size() << ',' << state->generatedPackets << ','
            << state->socketAcceptedPackets << ','
            << (state->generatedPackets - state->socketAcceptedPackets) << ','
            << flowTx << ',' << flowRx << ',' << flowLost << ',' << flowReportedDrops << ','
            << flowPendingTimeout << ',' << uniqueReceived << ','
            << state->duplicateReceives << ',' << state->invalidReceives << ',' << undelivered
            << ',' << pdr << ',';
    if (std::isfinite(appDelayMs))
    {
        summary << appDelayMs;
    }
    else
    {
        summary << "NA";
    }
    summary << ',';
    if (std::isfinite(flowDelayMs))
    {
        summary << flowDelayMs;
    }
    else
    {
        summary << "NA";
    }
    summary << ',' << forwarded << ',';
    if (std::isfinite(forwardingEstimate))
    {
        summary << forwardingEstimate;
    }
    else
    {
        summary << "NA";
    }
    summary << ",NA,NA\n";

    std::ofstream audit(eventsPath);
    if (!audit)
    {
        throw std::runtime_error("Cannot write packet event audit");
    }
    audit << "experiment,routing,profile,repetition_seed,traffic_seed,ns3_seed,ns3_run,"
             "packet_id,source_id,destination_id,"
             "generation_time_s,evaluated_at_time_s,packet_bytes,application_generated,"
             "socket_accepted,application_receive_count,delivered_same_id,"
             "scheduled_send_ns_time,receive_ns_time,application_latency_ms,"
             "loss_reason,simulation_send_time_s,simulation_receive_time_s,"
             "socket_errno_code,socket_errno_symbol,physical_minimum_hops_at_send,"
             "route_table_status,interference_transmission_evidence,warmup_s,drain_s,"
             "range_m,measurement_phase\n";
    for (const auto& event : schedule)
    {
        const auto& observation = state->packets.at(event.packetId);
        const bool delivered = observation.receiveCount > 0;
        audit << state->experiment << ',' << state->routing << ',' << state->profile << ','
              << state->repetitionSeed << ',' << state->trafficSeed << ',' << state->seed << ','
              << state->run << ',' << event.packetId << ','
              << event.sourceName << ',' << event.destinationName << ','
              << std::setprecision(12) << event.generationSeconds << ','
              << event.evaluatedAtSeconds << ',' << packetBytes << ','
              << (observation.applicationGenerated ? 1 : 0) << ','
              << (observation.socketAccepted ? 1 : 0) << ',' << observation.receiveCount << ','
              << (delivered ? 1 : 0) << ',';
        if (std::isfinite(observation.scheduledSendSeconds))
        {
            audit << observation.scheduledSendSeconds - state->warmupSeconds;
        }
        else
        {
            audit << "NA";
        }
        audit << ',';
        if (delivered)
        {
            audit << observation.firstReceiveSeconds - state->warmupSeconds;
        }
        else
        {
            audit << "NA";
        }
        audit << ',';
        if (delivered)
        {
            audit << 1000.0 * (observation.firstReceiveSeconds -
                               observation.scheduledSendSeconds);
        }
        else
        {
            audit << "NA";
        }
        audit << ','
              << (delivered ? "NA"
                            : !observation.socketAccepted
                                  ? "socket_send_rejected;cause_unattributed"
                                  : "undelivered_within_drain;cause_unattributed")
              << ',' << std::setprecision(12);
        if (std::isfinite(observation.scheduledSendSeconds))
        {
            audit << observation.scheduledSendSeconds;
        }
        else
        {
            audit << "NA";
        }
        audit << ',';
        if (delivered)
        {
            audit << observation.firstReceiveSeconds;
        }
        else
        {
            audit << "NA";
        }
        audit << ',' << observation.socketErrnoCode << ','
              << observation.socketErrnoSymbol << ',';
        if (observation.physicalMinimumHops > 0)
        {
            audit << observation.physicalMinimumHops;
        }
        else if (observation.applicationGenerated)
        {
            audit << "NO_PHYSICAL_PATH";
        }
        else
        {
            audit << "NA";
        }
        const double measurementStart = state->warmupSeconds;
        const double measurementEnd = measurementStart + measurementSeconds;
        const double eventTime = observation.scheduledSendSeconds;
        const std::string phase = !std::isfinite(eventTime) ? "not_generated"
                                  : eventTime < measurementStart ? "warmup"
                                  : eventTime < measurementEnd ? "measurement"
                                                               : "drain";
        audit << ",not_instrumented,not_instrumented," << state->warmupSeconds << ','
              << drainSeconds << ',' << rangeMeters << ',' << phase << '\n';
    }
}
} // namespace

int
main(int argc, char* argv[])
{
    std::string experiment;
    std::string routing;
    std::string profile = "range_limited_wifi";
    std::string coordinateFrame = "cartesian";
    std::string mobilityPath;
    std::string trafficPath;
    std::string summaryPath;
    std::string eventsPath;
    std::string repetitionSeed;
    std::string trafficSeed;
    uint32_t seed = 20261029;
    uint32_t run = 1;
    uint32_t packetBytes = 256;
    double rangeMeters = 35.0;
    double warmupSeconds = 5.0;
    double drainSeconds = 10.0;
    double measurementWindowSeconds = 0.0;
    CommandLine command(__FILE__);
    command.AddValue("experiment", "C or D", experiment);
    command.AddValue("routing", "aodv or olsr", routing);
    command.AddValue("profile", "range_limited_wifi or log_distance_wifi", profile);
    command.AddValue("coordinate-frame", "cartesian or ned", coordinateFrame);
    command.AddValue("mobility", "normalized mobility CSV path", mobilityPath);
    command.AddValue("traffic", "normalized traffic schedule CSV path", trafficPath);
    command.AddValue("summary", "per-run summary CSV output path", summaryPath);
    command.AddValue("events", "per-run packet audit CSV output path", eventsPath);
    command.AddValue("repetition-seed", "paired experiment repetition seed", repetitionSeed);
    command.AddValue("traffic-seed", "traffic schedule seed", trafficSeed);
    command.AddValue("seed", "RNG seed", seed);
    command.AddValue("run", "RNG run number", run);
    command.AddValue("packet-bytes", "UDP application payload bytes", packetBytes);
    command.AddValue("range-m", "hard range gate for range_limited_wifi", rangeMeters);
    command.AddValue("warmup-s", "routing warm-up before the measurement schedule", warmupSeconds);
    command.AddValue("drain-s", "time after last evaluated event to drain packets", drainSeconds);
    command.AddValue("measurement-window-s", "declared measurement window duration", measurementWindowSeconds);
    command.Parse(argc, argv);

    try
    {
        if ((experiment != "C" && experiment != "D") ||
            (routing != "aodv" && routing != "olsr") ||
            (profile != "range_limited_wifi" && profile != "log_distance_wifi") ||
            packetBytes < kPacketIdHeaderBytes || warmupSeconds < 0.0 || drainSeconds <= 0.0 ||
            measurementWindowSeconds <= 0.0 || repetitionSeed.empty() || trafficSeed.empty())
        {
            throw std::runtime_error("Invalid experiment, routing, profile, packet size, or timing");
        }

        std::map<std::string, uint32_t> nodeIds;
        auto mobilityFrames = ReadMobility(mobilityPath, nodeIds, coordinateFrame);
        if (nodeIds.size() < 2)
        {
            throw std::runtime_error("At least two nodes are required");
        }
        auto state = std::make_shared<RunState>();
        state->experiment = experiment;
        state->routing = routing;
        state->profile = profile;
        state->coordinateFrame = coordinateFrame;
        state->repetitionSeed = repetitionSeed;
        state->trafficSeed = trafficSeed;
        state->seed = seed;
        state->run = run;
        state->warmupSeconds = warmupSeconds;
        state->rangeMeters = rangeMeters;
        for (auto& frame : mobilityFrames)
        {
            state->frames.emplace(TimeKey(frame.timeSeconds), std::move(frame));
        }
        auto schedule = ReadTraffic(trafficPath, nodeIds, state->frames);
        for (const auto& event : schedule)
        {
            state->packets.emplace(event.packetId, PacketObservation{event});
        }
        const double lastEventTime = std::max(schedule.back().generationSeconds,
                                              schedule.back().evaluatedAtSeconds);
        const double measurementSeconds = measurementWindowSeconds;
        const double simulationEnd = warmupSeconds + lastEventTime + drainSeconds;

        RngSeedManager::SetSeed(seed);
        RngSeedManager::SetRun(run);

        NodeContainer nodes;
        nodes.Create(static_cast<uint32_t>(nodeIds.size()));
        for (uint32_t i = 0; i < nodes.GetN(); ++i)
        {
            auto mobility = CreateObject<ConstantPositionMobilityModel>();
            mobility->SetPosition(state->frames.begin()->second.positions[i]);
            nodes.Get(i)->AggregateObject(mobility);
            state->mobility.push_back(mobility);
        }

        YansWifiChannelHelper channel;
        channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
        if (profile == "range_limited_wifi")
        {
            channel.AddPropagationLoss("ns3::RangePropagationLossModel",
                                       "MaxRange",
                                       DoubleValue(rangeMeters));
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
        const auto devices = wifi.Install(phy, mac, nodes);

        InternetStackHelper internet;
        if (routing == "aodv")
        {
            AodvHelper aodv;
            internet.SetRoutingHelper(aodv);
        }
        else
        {
            OlsrHelper olsr;
            internet.SetRoutingHelper(olsr);
        }
        internet.Install(nodes);

        Ipv4AddressHelper addressHelper;
        addressHelper.SetBase("10.20.0.0", "255.255.0.0");
        const auto interfaces = addressHelper.Assign(devices);
        std::vector<Ipv4Address> addresses;
        for (uint32_t i = 0; i < interfaces.GetN(); ++i)
        {
            addresses.push_back(interfaces.GetAddress(i));
        }

        std::vector<std::vector<ScheduledPacket>> eventsBySource(nodes.GetN());
        for (const auto& event : schedule)
        {
            eventsBySource.at(event.source).push_back(event);
        }
        for (uint32_t i = 0; i < nodes.GetN(); ++i)
        {
            Ptr<ScheduledUdpApplication> application =
                CreateObject<ScheduledUdpApplication>();
            application->Configure(state,
                                   i,
                                   packetBytes,
                                   std::move(eventsBySource[i]),
                                   addresses,
                                   simulationEnd);
            nodes.Get(i)->AddApplication(application);
            application->SetStartTime(Seconds(0.0));
            application->SetStopTime(Seconds(simulationEnd));
        }

        FlowMonitorHelper flowHelper;
        Ptr<FlowMonitor> monitor = flowHelper.InstallAll();
        Simulator::Stop(Seconds(simulationEnd));
        Simulator::Run();
        WriteOutputs(summaryPath,
                     eventsPath,
                     state,
                     schedule,
                     monitor,
                     flowHelper,
                     addresses,
                     drainSeconds,
                     packetBytes,
                     static_cast<uint32_t>(state->frames.size()),
                     measurementSeconds,
                     rangeMeters);
        Simulator::Destroy();
        std::cout << "completed," << experiment << ',' << routing << ',' << seed << ','
                  << run << ',' << schedule.size() << ',' << state->generatedPackets << ','
                  << state->socketAcceptedPackets << '\n';
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "EXPERIMENT_ERROR: " << error.what() << '\n';
        Simulator::Destroy();
        return 2;
    }
}
