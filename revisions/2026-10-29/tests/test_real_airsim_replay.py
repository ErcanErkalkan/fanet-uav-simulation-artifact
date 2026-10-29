import csv
import math
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPLAY_DIR = ROOT / "local_validation" / "2026-10-29" / "real_airsim_replay"
R1_SRC = ROOT / "revisions" / "2026-10-29" / "src"
sys.path.insert(0, str(R1_SRC))
sys.path.insert(0, str(REPLAY_DIR))

from fanet_unified_pipeline import UnifiedFANETPipeline, load_trace_frames
from run_real_airsim_replay import (
    derive_one_hz_trace,
    validate_binary_topology,
    validate_source_trace,
)


class RealAirSimReplayTests(unittest.TestCase):
    def write_trace(self, path: Path, frame_times: list[float]) -> None:
        fields = [
            "time_s",
            "monotonic_time_s",
            "sim_time_stamp_ns",
            "sequence",
            "vehicle_name",
            "node_id",
            "x_m",
            "y_m",
            "z_m",
            "vx_mps",
            "vy_mps",
            "vz_mps",
            "source",
        ]
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for sequence, time_s in enumerate(frame_times):
                for index, name in enumerate(("Drone1", "Drone2", "Drone3")):
                    writer.writerow(
                        {
                            "time_s": time_s,
                            "monotonic_time_s": time_s,
                            "sim_time_stamp_ns": 1_000_000_000 + sequence * 200_000_000,
                            "sequence": sequence,
                            "vehicle_name": name,
                            "node_id": name,
                            "x_m": 5.0 if index == 1 else 0.0,
                            "y_m": 5.0 if index == 2 else 0.0,
                            "z_m": -2.0,
                            "vx_mps": 0.0,
                            "vy_mps": 0.0,
                            "vz_mps": 0.0,
                            "source": "airsim",
                        }
                    )

    def args_for(self, trace: Path, rate: float, scenario: str) -> Namespace:
        return Namespace(
            scenario_name=scenario,
            source="trace",
            trace=trace,
            trace_time_column="monotonic_time_s",
            num_uavs=3,
            duration=2.0,
            dt=0.2,
            area_xy=100.0,
            altitude_min=-100.0,
            altitude_max=100.0,
            speed_min=0.0,
            speed_max=0.0,
            communication_range=35.0,
            packets_per_step=1,
            traffic_rate_pps=rate,
            traffic_seed=17,
            routing="aodv_like_reactive",
            link_model="binary",
        )

    def test_trace_loader_preserves_air_sim_source_ned_and_zero_velocity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.csv"
            self.write_trace(path, [0.0, 0.2])
            frames, mapping, source = load_trace_frames(
                path, time_column="monotonic_time_s"
            )
        self.assertEqual(source, "airsim")
        self.assertEqual(set(mapping), {"Drone1", "Drone2", "Drone3"})
        self.assertEqual(frames[0].nodes[0].position, [0.0, 0.0, -2.0])
        self.assertEqual(frames[1].nodes[0].velocity, [0.0, 0.0, 0.0])
        self.assertEqual(frames[1].time_s, 0.2)

    def test_nonincreasing_replay_time_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.csv"
            self.write_trace(path, [0.2, 0.1])
            with self.assertRaisesRegex(ValueError, "non-increasing"):
                load_trace_frames(path, time_column="monotonic_time_s")

    def test_deterministic_time_based_traffic_is_independent_of_trace_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "five_hz.csv"
            derived_path = Path(directory) / "one_hz.csv"
            self.write_trace(path, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
            self.write_trace(derived_path, [0.0, 1.0])
            five_hz = UnifiedFANETPipeline(
                self.args_for(path, 5.0, "five_hz"), seed=101
            )
            one_hz = UnifiedFANETPipeline(
                self.args_for(derived_path, 5.0, "one_hz"), seed=101
            )
            five_hz.run_once()
            one_hz.run_once()
        self.assertEqual(len(five_hz.packet_events), 6)
        self.assertEqual(len(one_hz.packet_events), 6)
        signatures = lambda events: [
            (event["generation_time_s"], event["source_node_id"], event["destination_node_id"])
            for event in events
        ]
        self.assertEqual(signatures(five_hz.packet_events), signatures(one_hz.packet_events))
        self.assertTrue(
            all(
                event["source_node_id"] != event["destination_node_id"]
                for event in five_hz.packet_events
            )
        )
        self.assertAlmostEqual(
            (len(five_hz.packet_events) - 1)
            / (five_hz.packet_events[-1]["generation_time_s"]),
            5.0,
        )

    def test_binary_three_uav_topology_is_fully_connected_within_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.csv"
            self.write_trace(path, [0.0, 0.2, 0.4])
            frames, _, _ = load_trace_frames(path, "monotonic_time_s")
        result = validate_binary_topology(frames)
        self.assertFalse(result["all_600_frames_fully_connected"])
        self.assertEqual(result["fully_connected_frames"], 3)
        self.assertLessEqual(
            result["pairwise_distance_ranges_m"]["Drone2-Drone3"]["maximum"],
            35.0,
        )

    def test_source_trace_is_real_air_sim_and_one_hz_derived_without_mutating_input(self):
        trace = (
            ROOT
            / "local_validation"
            / "2026-10-29"
            / "airsim"
            / "airsim_real_3uav_120s.csv"
        )
        if not trace.exists():
            self.skipTest("real AirSim evidence is not present")
        before = trace.read_bytes()
        rows, metadata, frames = validate_source_trace(trace)
        with tempfile.TemporaryDirectory() as directory:
            derived = Path(directory) / "derived.csv"
            selected = derive_one_hz_trace(rows, derived)
            derived_rows, derived_meta, derived_frames = validate_source_trace_for_derived(
                derived
            )
        self.assertEqual(metadata["source"], "airsim")
        self.assertEqual(metadata["frame_count"], 600)
        self.assertEqual(len(frames), 600)
        self.assertEqual(len(selected), 120)
        self.assertEqual(len(derived_rows), 360)
        self.assertEqual(derived_meta["frame_count"], 120)
        self.assertEqual(len(derived_frames), 120)
        self.assertEqual(trace.read_bytes(), before)


def validate_source_trace_for_derived(path: Path):
    from collections import defaultdict
    import json

    with path.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    frames = defaultdict(list)
    for row in rows:
        frames[int(row["sequence"])].append(row)
    loaded, mapping, source = load_trace_frames(path, "monotonic_time_s")
    return rows, {
        "source": source,
        "frame_count": len(frames),
        "vehicles": sorted(mapping),
    }, loaded


if __name__ == "__main__":
    unittest.main()
