import csv
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(
    0, str(ROOT / "benchmarks" / "validation" / "ns3")
)

from run_ns3_paired_experiments import (  # noqa: E402
    flowmonitor_lost_diagnostic,
    load_topology,
    student_t_half_width,
    validate_ns3_run,
)


class PairedNs3ExperimentTests(unittest.TestCase):
    def write_inputs(self, directory: Path, positions, endpoints):
        mobility = directory / "mobility.csv"
        traffic = directory / "traffic.csv"
        with mobility.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["time_s", "sequence", "node_id", "x_m", "y_m", "z_m"],
            )
            writer.writeheader()
            for sequence, frame in enumerate(positions):
                for node_id, position in frame.items():
                    writer.writerow(
                        {
                            "time_s": sequence,
                            "sequence": sequence,
                            "node_id": node_id,
                            "x_m": position[0],
                            "y_m": position[1],
                            "z_m": position[2],
                        }
                    )
        with traffic.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "packet_id", "source_id", "destination_id", "trace_sequence",
                ],
            )
            writer.writeheader()
            for packet_id, source, destination, sequence in endpoints:
                writer.writerow(
                    {
                        "packet_id": packet_id,
                        "source_id": source,
                        "destination_id": destination,
                        "trace_sequence": sequence,
                    }
                )
        return mobility, traffic

    def test_student_t_interval_reports_half_width_and_na_for_one_sample(self):
        values = [float(index) for index in range(30)]
        expected = 2.045229642 * (math.sqrt(77.5) / math.sqrt(30))
        self.assertAlmostEqual(student_t_half_width(values), expected)
        self.assertEqual(student_t_half_width([1.0]), "NA")

    def test_air_sim_named_three_node_trace_is_directly_connected(self):
        positions = [
            {
                "Drone1": (0.0, 0.0, -2.0),
                "Drone2": (5.0, 0.0, -2.0),
                "Drone3": (0.0, 5.0, -2.0),
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            mobility, traffic = self.write_inputs(
                Path(temp_dir), positions, [(0, "Drone1", "Drone3", 0)]
            )
            topology, _, _ = load_topology(mobility, traffic)
        self.assertEqual(topology["experiment"], "C")
        self.assertEqual(topology["fully_connected_frames"], 1)
        self.assertEqual(topology["packets_requiring_multihop"], 0)
        self.assertEqual(topology["packets_without_binary_path"], 0)

    def test_linear_topology_distinguishes_multihop_from_unreachable(self):
        positions = [
            {
                "0": (0.0, 0.0, 0.0),
                "1": (30.0, 0.0, 0.0),
                "2": (60.0, 0.0, 0.0),
                "3": (120.0, 0.0, 0.0),
            }
        ]
        events = [(0, "0", "2", 0), (1, "0", "3", 0)]
        with tempfile.TemporaryDirectory() as temp_dir:
            mobility, traffic = self.write_inputs(Path(temp_dir), positions, events)
            topology, _, _ = load_topology(mobility, traffic)
        self.assertEqual(topology["experiment"], "D")
        self.assertEqual(topology["packets_requiring_multihop"], 1)
        self.assertEqual(topology["packets_without_binary_path"], 1)

    def test_flowmonitor_and_application_receive_counts_remain_distinct(self):
        summary = {
            "scheduled_packets": "10",
            "application_generated_packets": "10",
            "socket_accepted_packets": "10",
            "socket_rejected_packets": "0",
            "application_unique_delivered_packets": "10",
            "application_duplicate_receives": "0",
            "invalid_packet_receives": "0",
            "flowmonitor_tx_packets": "10",
            "flowmonitor_rx_packets": "9",
        }
        events = [{"packet_id": str(index)} for index in range(10)]
        validate_ns3_run(summary, events, 10, "synthetic FlowMonitor discrepancy")

    def test_flowmonitor_assumed_loss_is_not_treated_as_rx_complement(self):
        rows = [
            {
                "simulator": "ns-3.49",
                "experiment": "D",
                "routing": "aodv",
                "flowmonitor_tx_packets": "150",
                "flowmonitor_rx_packets": "79",
                "flowmonitor_lost_packets": "85",
            },
            {
                "simulator": "Python_R1_abstraction",
                "experiment": "D",
                "routing": "aodv",
                "flowmonitor_tx_packets": "NA",
                "flowmonitor_rx_packets": "NA",
                "flowmonitor_lost_packets": "NA",
            },
        ]
        diagnostic = flowmonitor_lost_diagnostic(rows)
        self.assertEqual(
            diagnostic["runs_where_lost_exceeds_nonnegative_tx_minus_rx"], 1
        )
        self.assertEqual(diagnostic["by_experiment_routing"], {"D/aodv": 1})

    def test_rejects_packet_audit_id_duplicates(self):
        summary = {
            "scheduled_packets": "2",
            "application_generated_packets": "2",
            "socket_accepted_packets": "2",
            "socket_rejected_packets": "0",
            "application_unique_delivered_packets": "1",
            "application_duplicate_receives": "0",
            "invalid_packet_receives": "0",
            "flowmonitor_tx_packets": "2",
            "flowmonitor_rx_packets": "1",
        }
        events = [{"packet_id": "1"}, {"packet_id": "1"}]
        with self.assertRaisesRegex(RuntimeError, "missing or duplicated"):
            validate_ns3_run(summary, events, 2, "duplicate-ID test")


if __name__ == "__main__":
    unittest.main()
