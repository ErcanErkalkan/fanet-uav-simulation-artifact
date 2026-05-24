#!/usr/bin/env python3
"""Unified FANET pipeline for synthetic and trace-driven experiments.

This runner connects the artifact pieces that are otherwise available as
separate benchmark scripts:

* mobility source: synthetic random motion or AirSim-compatible CSV trace
* link model: binary range or probabilistic wireless channel
* routing: shortest-path oracle, AODV-like, OLSR-like, or greedy geographic
* metrics: one common raw/summary CSV schema

The model remains a lightweight simulation abstraction. It is intended to make
the manuscript's "single pipeline" claim executable without replacing packet-
level simulators such as ns-3 or OMNeT++.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from statistics import mean, pstdev, stdev
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from fanet_routing_protocols import Edge, Position, RouteDecision, make_protocol
from fanet_wireless_channel_model import UAVNode, WirelessChannel, WirelessConfig


@dataclass
class TraceFrame:
    time_s: float
    nodes: List[UAVNode]


def distance(a: UAVNode, b: UAVNode) -> float:
    return math.sqrt(sum((a.position[k] - b.position[k]) ** 2 for k in range(3)))


def ci95(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * stdev(values) / math.sqrt(len(values))


def numeric_mean(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def numeric_pstdev(values: Sequence[float]) -> float:
    return pstdev(values) if len(values) > 1 else 0.0


def load_trace_frames(path: Path) -> Tuple[List[TraceFrame], Dict[str, int], str]:
    by_sequence: Dict[int, List[Dict[str, str]]] = defaultdict(list)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"time_s", "sequence", "node_id", "x_m", "y_m", "z_m"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Trace file is missing required columns: {sorted(missing)}")
        for row in reader:
            by_sequence[int(row["sequence"])].append(row)

    if not by_sequence:
        raise ValueError("Trace file contains no trajectory samples.")

    node_names = sorted({row["node_id"] for rows in by_sequence.values() for row in rows})
    node_map = {name: idx for idx, name in enumerate(node_names)}
    frames: List[TraceFrame] = []
    previous_positions: Dict[str, Tuple[float, float, float, float]] = {}
    source_values = set()

    for sequence in sorted(by_sequence):
        rows = sorted(by_sequence[sequence], key=lambda row: node_map[row["node_id"]])
        time_s = mean(float(row["time_s"]) for row in rows)
        nodes: List[UAVNode] = []
        for row in rows:
            name = row["node_id"]
            idx = node_map[name]
            x, y, z = float(row["x_m"]), float(row["y_m"]), float(row["z_m"])
            vx = float(row.get("vx_mps") or 0.0)
            vy = float(row.get("vy_mps") or 0.0)
            vz = float(row.get("vz_mps") or 0.0)
            if vx == 0.0 and vy == 0.0 and name in previous_positions:
                prev_t, prev_x, prev_y, prev_z = previous_positions[name]
                dt = max(1e-9, time_s - prev_t)
                vx, vy, vz = (x - prev_x) / dt, (y - prev_y) / dt, (z - prev_z) / dt
            heading = math.atan2(vy, vx) if vx != 0.0 or vy != 0.0 else 0.0
            nodes.append(UAVNode(idx, [x, y, z], [vx, vy, vz], heading))
            previous_positions[name] = (time_s, x, y, z)
            if row.get("source"):
                source_values.add(str(row["source"]))
        frames.append(TraceFrame(time_s=time_s, nodes=nodes))

    source_label = sorted(source_values)[0] if source_values else "trace"
    return frames, node_map, source_label


class SyntheticMobility:
    def __init__(
        self,
        num_uavs: int,
        seed: int,
        area_xy: float,
        altitude_bounds: Tuple[float, float],
        speed_range: Tuple[float, float],
    ) -> None:
        self.rng = random.Random(seed)
        self.area_xy = area_xy
        self.altitude_bounds = altitude_bounds
        self.speed_range = speed_range
        self.nodes = self._make_nodes(num_uavs)

    def _make_nodes(self, num_uavs: int) -> List[UAVNode]:
        nodes: List[UAVNode] = []
        for i in range(num_uavs):
            speed = self.rng.uniform(*self.speed_range)
            heading = self.rng.uniform(0.0, 2.0 * math.pi)
            nodes.append(
                UAVNode(
                    i,
                    [
                        self.rng.uniform(0.0, self.area_xy),
                        self.rng.uniform(0.0, self.area_xy),
                        self.rng.uniform(*self.altitude_bounds),
                    ],
                    [
                        speed * math.cos(heading),
                        speed * math.sin(heading),
                        self.rng.uniform(-0.5, 0.5),
                    ],
                    heading,
                )
            )
        return nodes

    def frames(self, duration_s: float, dt_s: float) -> Iterable[TraceFrame]:
        steps = int(duration_s / dt_s)
        for step in range(steps):
            time_s = step * dt_s
            for node in self.nodes:
                node.move(dt_s, self.area_xy, self.altitude_bounds)
            copied = [
                UAVNode(n.node_id, list(n.position), list(n.velocity), n.heading_rad)
                for n in self.nodes
            ]
            yield TraceFrame(time_s=time_s, nodes=copied)


class UnifiedFANETPipeline:
    def __init__(self, args: argparse.Namespace, seed: int) -> None:
        self.args = args
        self.seed = seed
        self.rng = random.Random(seed)
        self.protocol = make_protocol(args.routing)
        self.channel = WirelessChannel(WirelessConfig(), self.rng)
        self.trace_node_map: Dict[str, int] = {}
        self.trace_source = "synthetic"
        self.trace_frames: Optional[List[TraceFrame]] = None

        if args.source == "trace":
            if args.trace is None:
                raise ValueError("--trace is required when --source trace is selected.")
            self.trace_frames, self.trace_node_map, self.trace_source = load_trace_frames(args.trace)
            self.num_uavs = len(self.trace_node_map)
            self.duration_s = max(self.trace_frames[-1].time_s - self.trace_frames[0].time_s, 1e-9)
            self.sample_count = len(self.trace_frames)
        else:
            self.num_uavs = args.num_uavs
            self.duration_s = args.duration
            self.sample_count = int(args.duration / args.dt)

        self.protocol.reset(self.num_uavs)

    def frame_iter(self) -> Iterable[TraceFrame]:
        if self.trace_frames is not None:
            yield from self.trace_frames
            return
        mobility = SyntheticMobility(
            self.args.num_uavs,
            self.seed,
            self.args.area_xy,
            (self.args.altitude_min, self.args.altitude_max),
            (self.args.speed_min, self.args.speed_max),
        )
        yield from mobility.frames(self.args.duration, self.args.dt)

    def positions(self, nodes: Sequence[UAVNode]) -> Dict[int, Position]:
        return {n.node_id: (n.position[0], n.position[1], n.position[2]) for n in nodes}

    def edge_quality(self, nodes: Sequence[UAVNode]) -> Dict[Edge, Dict[str, float]]:
        qualities: Dict[Edge, Dict[str, float]] = {}
        for a, b in combinations(nodes, 2):
            key = (min(a.node_id, b.node_id), max(a.node_id, b.node_id))
            if self.args.link_model == "binary":
                d = distance(a, b)
                if d <= self.args.communication_range:
                    qualities[key] = {
                        "reliability": 1.0,
                        "sinr_db": 99.0,
                        "hop_delay_ms": 4.5,
                        "energy_j": 0.0,
                    }
                continue

            q_ab = self.channel.hop_quality(a, b, list(nodes))
            q_ba = self.channel.hop_quality(b, a, list(nodes))
            reliability = min(q_ab["reliability"], q_ba["reliability"])
            if reliability >= self.channel.cfg.reliability_threshold:
                qualities[key] = {
                    "reliability": reliability,
                    "sinr_db": min(q_ab["sinr_db"], q_ba["sinr_db"]),
                    "hop_delay_ms": q_ab["tx_delay_ms"] + q_ab["prop_delay_ms"] + q_ab["queue_delay_ms"],
                    "energy_j": q_ab["energy_j"],
                }
        return qualities

    def routing_latency_ms(self, decision: RouteDecision) -> float:
        discovery_penalty = 12.0 if decision.discovery else 0.0
        control_penalty = 0.05 * decision.control_packets
        return discovery_penalty + control_penalty + self.rng.uniform(0.0, 3.0)

    def evaluate_delivery(
        self,
        decision: RouteDecision,
        qualities: Dict[Edge, Dict[str, float]],
    ) -> Tuple[bool, float, float, List[float], List[float], bool]:
        if not decision.delivered or not decision.path:
            return False, 0.0, 0.0, [], [], False

        latency_ms = 8.0 + self.routing_latency_ms(decision)
        energy_j = 0.0
        reliabilities: List[float] = []
        sinrs: List[float] = []

        for a, b in zip(decision.path[:-1], decision.path[1:]):
            key = (min(a, b), max(a, b))
            q = qualities.get(key)
            if q is None:
                return False, 0.0, energy_j, reliabilities, sinrs, True
            reliabilities.append(q["reliability"])
            sinrs.append(q["sinr_db"])
            latency_ms += q["hop_delay_ms"]
            energy_j += q["energy_j"]
            if self.rng.random() > q["reliability"]:
                return False, 0.0, energy_j, reliabilities, sinrs, False
        return True, latency_ms, energy_j, reliabilities, sinrs, False

    def run_once(self) -> Dict[str, float | int | str]:
        attempted = delivered = 0
        discoveries = 0
        route_failures = 0
        stale_failures = 0
        channel_failures = 0
        control_packets = 0
        topology_changes = 0
        previous_edges: set[Edge] = set()
        edge_lifetimes: Dict[Edge, float] = {}
        last_time: Optional[float] = None

        latencies: List[float] = []
        hops: List[int] = []
        packet_reliabilities: List[float] = []
        packet_sinrs: List[float] = []
        packet_energy_j: List[float] = []

        for frame in self.frame_iter():
            step_dt = self.args.dt if last_time is None else max(0.0, frame.time_s - last_time)
            qualities = self.edge_quality(frame.nodes)
            edges = set(qualities)
            topology_changes += len(edges.symmetric_difference(previous_edges))
            for edge in edges:
                edge_lifetimes[edge] = edge_lifetimes.get(edge, 0.0) + step_dt
            pos = self.positions(frame.nodes)
            self.protocol.on_topology_change(frame.time_s, edges, pos)

            if self.num_uavs >= 2:
                for _ in range(self.args.packets_per_step):
                    src, dst = self.rng.sample(range(self.num_uavs), 2)
                    attempted += 1
                    decision = self.protocol.route(src, dst, edges, pos, frame.time_s)
                    control_packets += decision.control_packets
                    discoveries += 1 if decision.discovery else 0
                    route_failures += 1 if decision.route_failure else 0
                    stale_failures += 1 if decision.stale_route else 0
                    ok, latency_ms, energy_j, reliabilities, sinrs, missing_edge = self.evaluate_delivery(decision, qualities)
                    if missing_edge:
                        route_failures += 1
                    if decision.delivered and not ok and not missing_edge:
                        channel_failures += 1
                    if ok:
                        delivered += 1
                        latencies.append(latency_ms)
                        hops.append(decision.hops)
                        packet_energy_j.append(energy_j)
                        if reliabilities:
                            packet_reliabilities.append(mean(reliabilities))
                        if sinrs:
                            packet_sinrs.append(mean(sinrs))

            previous_edges = edges
            last_time = frame.time_s

        throughput_duration = max(self.duration_s, 1e-9)
        return {
            "scenario": self.args.scenario_name,
            "source": self.args.source,
            "trace_source": self.trace_source,
            "trace_file": "" if self.args.trace is None else Path(self.args.trace).name,
            "link_model": self.args.link_model,
            "routing_protocol": self.args.routing,
            "num_uavs": self.num_uavs,
            "seed": self.seed,
            "samples": self.sample_count,
            "duration_s": self.duration_s,
            "packet_attempts": attempted,
            "delivered_packets": delivered,
            "pdr": delivered / attempted if attempted else 0.0,
            "avg_latency_ms": numeric_mean(latencies),
            "std_latency_ms": numeric_pstdev(latencies),
            "avg_hops": numeric_mean(hops),
            "throughput_pps": delivered / throughput_duration,
            "topology_changes_per_s": topology_changes / throughput_duration,
            "avg_link_lifetime_s": numeric_mean(list(edge_lifetimes.values())),
            "control_packets_per_s": control_packets / throughput_duration,
            "route_discoveries": discoveries,
            "route_failures": route_failures,
            "stale_route_failures": stale_failures,
            "channel_failures": channel_failures,
            "mean_link_reliability": numeric_mean(packet_reliabilities),
            "mean_sinr_db": numeric_mean(packet_sinrs) if packet_sinrs else (99.0 if self.args.link_model == "binary" and delivered else 0.0),
            "energy_mj_per_packet": numeric_mean(packet_energy_j) * 1000.0,
        }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    if not rows:
        return []
    metric_keys = [
        "pdr",
        "avg_latency_ms",
        "avg_hops",
        "throughput_pps",
        "topology_changes_per_s",
        "avg_link_lifetime_s",
        "control_packets_per_s",
        "route_failures",
        "stale_route_failures",
        "channel_failures",
        "mean_link_reliability",
        "mean_sinr_db",
        "energy_mj_per_packet",
    ]
    group_keys = ["scenario", "source", "trace_source", "trace_file", "link_model", "routing_protocol", "num_uavs"]
    groups: Dict[Tuple[object, ...], List[Dict[str, object]]] = {}
    for row in rows:
        key = tuple(row[k] for k in group_keys)
        groups.setdefault(key, []).append(row)

    summary_rows: List[Dict[str, object]] = []
    for key, subset in groups.items():
        result: Dict[str, object] = {name: value for name, value in zip(group_keys, key)}
        result["runs"] = len(subset)
        for metric in metric_keys:
            values = [float(row[metric]) for row in subset]
            result[f"{metric}_mean"] = f"{mean(values):.6f}"
            result[f"{metric}_std"] = f"{stdev(values):.6f}" if len(values) > 1 else "0.000000"
            result[f"{metric}_ci95"] = f"{ci95(values):.6f}"
        summary_rows.append(result)
    return summary_rows


def cloned_args(args: argparse.Namespace, **updates: object) -> argparse.Namespace:
    values = vars(args).copy()
    values.update(updates)
    return argparse.Namespace(**values)


def article_matrix_args(args: argparse.Namespace) -> List[argparse.Namespace]:
    trace_path = args.trace or Path(__file__).with_name("sample_airsim_trajectory_3uav.csv")
    base = {
        "duration": 30.0,
        "dt": 1.0,
        "communication_range": 35.0,
        "packets_per_step": 5,
        "routing": "aodv_like_reactive",
    }
    return [
        cloned_args(
            args,
            **base,
            scenario_name="synthetic_binary_aodv",
            source="synthetic",
            trace=None,
            num_uavs=20,
            link_model="binary",
        ),
        cloned_args(
            args,
            **base,
            scenario_name="synthetic_wireless_aodv",
            source="synthetic",
            trace=None,
            num_uavs=20,
            link_model="wireless",
        ),
        cloned_args(
            args,
            **base,
            scenario_name="airsim_trace_binary_aodv",
            source="trace",
            trace=trace_path,
            link_model="binary",
        ),
        cloned_args(
            args,
            **base,
            scenario_name="airsim_trace_wireless_aodv",
            source="trace",
            trace=trace_path,
            link_model="wireless",
        ),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified synthetic/trace FANET pipeline")
    parser.add_argument("--matrix", choices=["none", "article"], default="none")
    parser.add_argument("--scenario-name", default="custom")
    parser.add_argument("--source", choices=["synthetic", "trace"], default="synthetic")
    parser.add_argument("--trace", type=Path, default=None, help="AirSim-compatible trajectory CSV for --source trace")
    parser.add_argument("--num-uavs", type=int, default=20)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--area-xy", type=float, default=100.0)
    parser.add_argument("--altitude-min", type=float, default=15.0)
    parser.add_argument("--altitude-max", type=float, default=45.0)
    parser.add_argument("--speed-min", type=float, default=1.5)
    parser.add_argument("--speed-max", type=float, default=6.0)
    parser.add_argument("--communication-range", type=float, default=35.0)
    parser.add_argument("--packets-per-step", type=int, default=5)
    parser.add_argument("--link-model", choices=["binary", "wireless"], default="binary")
    parser.add_argument(
        "--routing",
        choices=["shortest_path_oracle", "aodv_like_reactive", "olsr_like_proactive", "greedy_geographic"],
        default="aodv_like_reactive",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--raw-out", type=Path, default=Path("fanet_unified_raw.csv"))
    parser.add_argument("--summary-out", type=Path, default=Path("fanet_unified_summary.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows: List[Dict[str, object]] = []
    scenarios = article_matrix_args(args) if args.matrix == "article" else [args]
    for scenario_args in scenarios:
        for offset in range(args.repetitions):
            pipeline = UnifiedFANETPipeline(scenario_args, args.seed + offset)
            rows.append(pipeline.run_once())
    write_csv(args.raw_out, rows)
    write_csv(args.summary_out, summarize(rows))
    print(f"Wrote {args.raw_out}")
    print(f"Wrote {args.summary_out}")


if __name__ == "__main__":
    main()
