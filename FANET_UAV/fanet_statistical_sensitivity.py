#!/usr/bin/env python3
"""
Statistical sensitivity benchmark for the FANET simulation layer.

This script complements the routing-abstraction benchmark by running at least
30 independent repetitions per scenario and reporting mean, standard deviation,
and 95% confidence intervals. It covers the parameters requested for the journal
revision: UAV count, communication range, UAV speed, packet rate, mobility
model, and simulation duration. The AirSim trajectory path is supported through
the companion fanet_trace_replay.py script because it requires external AirSim CSV logs; this
script focuses on repeatable synthetic mobility models.

The routing protocol used by default is AODV-like reactive routing because it is
less idealized than the shortest-path oracle and exposes route discovery and
route-break effects. Other routing modules can be selected from
fanet_routing_protocols.py.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Optional, Sequence, Set, Tuple

from fanet_routing_protocols import (
    AODVLikeReactive,
    GreedyGeographicRouting,
    OLSRLikeProactive,
    RoutingProtocol,
    ShortestPathOracle,
    make_protocol,
)

Position = Tuple[float, float, float]
Edge = Tuple[int, int]

SPEED_PROFILES = {
    "low": (0.4, 1.0, 0.10, 0.25),
    "medium": (1.0, 2.4, 0.20, 0.50),
    "high": (2.2, 4.0, 0.35, 0.90),
}

PROTOCOL_CHOICES = {
    "shortest_path_oracle": ShortestPathOracle.name,
    "aodv_like_reactive": AODVLikeReactive.name,
    "olsr_like_proactive": OLSRLikeProactive.name,
    "greedy_geographic": GreedyGeographicRouting.name,
}


@dataclass
class MobilityNode:
    node_id: int
    position: Position
    velocity: Position
    target: Optional[Position] = None
    gauss_heading: Position = field(default_factory=lambda: (0.0, 0.0, 0.0))


def distance(a: Position, b: Position) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def unit_vector(vec: Position) -> Position:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 1e-12:
        return (0.0, 0.0, 0.0)
    return tuple(x / norm for x in vec)  # type: ignore[return-value]


class StatisticalFANETSimulator:
    def __init__(
        self,
        num_uavs: int,
        communication_range: float,
        speed_profile: str,
        packets_per_step: int,
        mobility_model: str,
        protocol: RoutingProtocol,
        seed: int,
        duration_s: float = 120.0,
        dt_s: float = 1.0,
        area: Position = (120.0, 120.0, 50.0),
    ) -> None:
        if speed_profile not in SPEED_PROFILES:
            raise ValueError(f"Unknown speed profile: {speed_profile}")
        if mobility_model not in {"random_waypoint", "gauss_markov"}:
            raise ValueError(f"Unknown mobility model: {mobility_model}")
        self.num_uavs = num_uavs
        self.communication_range = communication_range
        self.speed_profile = speed_profile
        self.packets_per_step = packets_per_step
        self.mobility_model = mobility_model
        self.protocol = protocol
        self.seed = seed
        self.duration_s = duration_s
        self.dt_s = dt_s
        self.area = area
        self.rng = random.Random(seed)
        self.nodes = self._init_nodes()
        self.protocol.reset(num_uavs)

    def _random_position(self) -> Position:
        return (
            self.rng.uniform(0.0, self.area[0]),
            self.rng.uniform(0.0, self.area[1]),
            self.rng.uniform(8.0, self.area[2]),
        )

    def _random_velocity(self) -> Position:
        xy_min, xy_max, z_min, z_max = SPEED_PROFILES[self.speed_profile]
        speed_xy = self.rng.uniform(xy_min, xy_max)
        theta = self.rng.uniform(0.0, 2.0 * math.pi)
        vz = self.rng.uniform(-z_max, z_max)
        if abs(vz) < z_min:
            vz = z_min if vz >= 0 else -z_min
        return (speed_xy * math.cos(theta), speed_xy * math.sin(theta), vz)

    def _init_nodes(self) -> List[MobilityNode]:
        nodes: List[MobilityNode] = []
        for i in range(self.num_uavs):
            pos = self._random_position()
            vel = self._random_velocity()
            target = self._random_position() if self.mobility_model == "random_waypoint" else None
            nodes.append(MobilityNode(i, pos, vel, target, unit_vector(vel)))
        return nodes

    def _clip_position(self, pos: Position) -> Position:
        return (
            max(0.0, min(self.area[0], pos[0])),
            max(0.0, min(self.area[1], pos[1])),
            max(5.0, min(self.area[2], pos[2])),
        )

    def _move_random_waypoint(self, node: MobilityNode) -> None:
        if node.target is None or distance(node.position, node.target) < 2.0:
            node.target = self._random_position()
        direction = unit_vector((
            node.target[0] - node.position[0],
            node.target[1] - node.position[1],
            node.target[2] - node.position[2],
        ))
        xy_min, xy_max, _, _ = SPEED_PROFILES[self.speed_profile]
        speed = self.rng.uniform(xy_min, xy_max)
        vel = (direction[0] * speed, direction[1] * speed, direction[2] * speed)
        node.velocity = vel
        node.position = self._clip_position(tuple(node.position[i] + vel[i] * self.dt_s for i in range(3)))  # type: ignore[arg-type]

    def _move_gauss_markov(self, node: MobilityNode) -> None:
        alpha = 0.82
        noise = unit_vector((self.rng.gauss(0.0, 1.0), self.rng.gauss(0.0, 1.0), self.rng.gauss(0.0, 0.35)))
        heading = unit_vector(tuple(alpha * node.gauss_heading[i] + (1.0 - alpha) * noise[i] for i in range(3)))  # type: ignore[arg-type]
        xy_min, xy_max, _, _ = SPEED_PROFILES[self.speed_profile]
        speed = self.rng.uniform(xy_min, xy_max)
        vel = (heading[0] * speed, heading[1] * speed, heading[2] * speed * 0.5)
        new_pos = tuple(node.position[i] + vel[i] * self.dt_s for i in range(3))  # type: ignore[assignment]
        bounced = [False, False, False]
        x, y, z = new_pos
        if x < 0.0 or x > self.area[0]:
            bounced[0] = True
        if y < 0.0 or y > self.area[1]:
            bounced[1] = True
        if z < 5.0 or z > self.area[2]:
            bounced[2] = True
        if any(bounced):
            vel = tuple((-vel[i] if bounced[i] else vel[i]) for i in range(3))  # type: ignore[assignment]
            heading = unit_vector(vel)
            new_pos = tuple(node.position[i] + vel[i] * self.dt_s for i in range(3))  # type: ignore[assignment]
        node.gauss_heading = heading
        node.velocity = vel
        node.position = self._clip_position(new_pos)  # type: ignore[arg-type]

    def move_nodes(self) -> None:
        for node in self.nodes:
            if self.mobility_model == "random_waypoint":
                self._move_random_waypoint(node)
            else:
                self._move_gauss_markov(node)

    def positions(self) -> Dict[int, Position]:
        return {n.node_id: n.position for n in self.nodes}

    def compute_edges(self) -> Set[Edge]:
        edges: Set[Edge] = set()
        for a, b in combinations(self.nodes, 2):
            if distance(a.position, b.position) <= self.communication_range:
                edges.add((min(a.node_id, b.node_id), max(a.node_id, b.node_id)))
        return edges

    def _latency(self, decision) -> float:
        base = 8.0 + 4.5 * decision.hops
        discovery_penalty = 12.0 if decision.discovery else 0.0
        control_penalty = 0.05 * decision.control_packets
        speed_penalty = {"low": 0.0, "medium": 1.0, "high": 2.5}[self.speed_profile]
        jitter = self.rng.uniform(0.0, 3.0)
        return base + discovery_penalty + control_penalty + speed_penalty + jitter

    def run(self) -> Dict[str, float | int | str]:
        prev_edges: Set[Edge] = set()
        edge_lifetimes: Dict[Edge, float] = {}
        attempted = delivered = 0
        hops: List[int] = []
        latencies: List[float] = []
        topology_changes = 0
        control_packets = 0
        route_failures = 0
        stale_route_failures = 0
        steps = int(self.duration_s / self.dt_s)
        for step in range(steps):
            time_s = step * self.dt_s
            self.move_nodes()
            edges = self.compute_edges()
            topology_changes += len(edges.symmetric_difference(prev_edges))
            for edge in edges:
                edge_lifetimes[edge] = edge_lifetimes.get(edge, 0.0) + self.dt_s
            positions = self.positions()
            self.protocol.on_topology_change(time_s, edges, positions)
            for _ in range(self.packets_per_step):
                src, dst = self.rng.sample(range(self.num_uavs), 2)
                attempted += 1
                decision = self.protocol.route(src, dst, edges, positions, time_s)
                control_packets += decision.control_packets
                route_failures += 1 if decision.route_failure else 0
                stale_route_failures += 1 if decision.stale_route else 0
                if decision.delivered:
                    delivered += 1
                    hops.append(decision.hops)
                    latencies.append(self._latency(decision))
            prev_edges = edges
        return {
            "protocol": self.protocol.name,
            "num_uavs": self.num_uavs,
            "communication_range_m": self.communication_range,
            "speed_profile": self.speed_profile,
            "packets_per_step": self.packets_per_step,
            "mobility_model": self.mobility_model,
            "seed": self.seed,
            "attempted": attempted,
            "delivered": delivered,
            "pdr": delivered / attempted if attempted else 0.0,
            "avg_latency_ms": mean(latencies) if latencies else 0.0,
            "avg_hops": mean(hops) if hops else 0.0,
            "throughput_pps": delivered / self.duration_s if self.duration_s > 0.0 else 0.0,
            "topology_changes_per_s": topology_changes / self.duration_s,
            "avg_link_lifetime_s": mean(edge_lifetimes.values()) if edge_lifetimes else 0.0,
            "control_packets_per_s": control_packets / self.duration_s,
            "route_failures": route_failures,
            "stale_route_failures": stale_route_failures,
        }


def scenario_design(args: argparse.Namespace) -> List[Dict[str, object]]:
    """One-factor-at-a-time design plus density sweep.

    The full factorial matrix can be executed by modifying this function, but the
    one-factor design is the default because it keeps the paper benchmark compact
    while still measuring seed, density, range, speed, packet-rate, and mobility
    sensitivity.
    """
    default = {
        "num_uavs": 20,
        "communication_range": 35.0,
        "speed_profile": "medium",
        "packets_per_step": 5,
        "mobility_model": "random_waypoint",
        "duration_s": args.duration,
    }
    scenarios: List[Dict[str, object]] = []
    for n in [5, 10, 20, 30, 50]:
        rec = dict(default)
        rec.update({"factor": "UAV count", "level": str(n), "num_uavs": n})
        scenarios.append(rec)
    for r in [20.0, 35.0, 50.0, 75.0]:
        rec = dict(default)
        rec.update({"factor": "Communication range", "level": f"{r:.0f} m", "communication_range": r})
        scenarios.append(rec)
    for sp in ["low", "medium", "high"]:
        rec = dict(default)
        rec.update({"factor": "UAV speed", "level": sp, "speed_profile": sp})
        scenarios.append(rec)
    for p in [1, 5, 10]:
        rec = dict(default)
        rec.update({"factor": "Packet rate", "level": f"{p} pkt/step", "packets_per_step": p})
        scenarios.append(rec)
    for m in ["random_waypoint", "gauss_markov"]:
        rec = dict(default)
        rec.update({"factor": "Mobility model", "level": m.replace("_", "-"), "mobility_model": m})
        scenarios.append(rec)
    for d in [30.0, 60.0, 120.0]:
        rec = dict(default)
        rec.update({"factor": "Simulation duration", "level": f"{d:.0f} s", "duration_s": d})
        scenarios.append(rec)
    return scenarios


def summarise(raw_rows: List[Dict[str, float | int | str]]) -> List[Dict[str, float | int | str]]:
    metrics = [
        "pdr",
        "avg_latency_ms",
        "avg_hops",
        "throughput_pps",
        "topology_changes_per_s",
        "avg_link_lifetime_s",
        "control_packets_per_s",
        "route_failures",
    ]
    groups: Dict[Tuple[str, str], List[Dict[str, float | int | str]]] = defaultdict(list)
    for row in raw_rows:
        groups[(str(row["factor"]), str(row["level"]))].append(row)
    summary: List[Dict[str, float | int | str]] = []
    for (factor, level), rows in groups.items():
        base = rows[0]
        rec: Dict[str, float | int | str] = {
            "factor": factor,
            "level": level,
            "runs": len(rows),
            "protocol": base["protocol"],
            "num_uavs": base["num_uavs"],
            "communication_range_m": base["communication_range_m"],
            "speed_profile": base["speed_profile"],
            "packets_per_step": base["packets_per_step"],
            "mobility_model": base["mobility_model"],
            "duration_s": base["duration_s"],
        }
        for metric in metrics:
            vals = [float(r[metric]) for r in rows]
            m = mean(vals)
            s = stdev(vals) if len(vals) > 1 else 0.0
            ci95 = 1.96 * s / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
            rec[f"{metric}_mean"] = m
            rec[f"{metric}_std"] = s
            rec[f"{metric}_ci95"] = ci95
        summary.append(rec)
    order = {
        "UAV count": 0,
        "Communication range": 1,
        "UAV speed": 2,
        "Packet rate": 3,
        "Mobility model": 4,
    }
    return sorted(summary, key=lambda r: (order.get(str(r["factor"]), 99), str(r["level"])))


def write_csv(path: str | Path, rows: List[Dict[str, float | int | str]]) -> None:
    path = Path(path)
    if not rows:
        raise ValueError("No rows to write")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> None:
    scenarios = scenario_design(args)
    raw_rows: List[Dict[str, float | int | str]] = []
    for idx, scenario in enumerate(scenarios):
        for rep in range(args.repetitions):
            seed = args.seed + idx * 10000 + rep * 37
            sim = StatisticalFANETSimulator(
                num_uavs=int(scenario["num_uavs"]),
                communication_range=float(scenario["communication_range"]),
                speed_profile=str(scenario["speed_profile"]),
                packets_per_step=int(scenario["packets_per_step"]),
                mobility_model=str(scenario["mobility_model"]),
                protocol=make_protocol(args.protocol),
                seed=seed,
                duration_s=float(scenario["duration_s"]),
                dt_s=args.dt,
            )
            row = sim.run()
            row["factor"] = str(scenario["factor"])
            row["level"] = str(scenario["level"])
            row["duration_s"] = float(scenario["duration_s"])
            row["repetition"] = rep + 1
            raw_rows.append(row)
    summary = summarise(raw_rows)
    write_csv(args.raw_out, raw_rows)
    write_csv(args.summary_out, summary)
    print(f"Wrote {args.raw_out} ({len(raw_rows)} rows)")
    print(f"Wrote {args.summary_out} ({len(summary)} rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FANET statistical sensitivity benchmark")
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--protocol", default="aodv_like_reactive", choices=sorted(PROTOCOL_CHOICES))
    parser.add_argument("--seed", type=int, default=5100)
    parser.add_argument("--raw-out", default="fanet_statistical_raw.csv")
    parser.add_argument("--summary-out", default="fanet_statistical_summary.csv")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
