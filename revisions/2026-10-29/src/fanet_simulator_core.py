"""
Minimal FANET simulation core for the journal manuscript.

This script is intentionally lightweight and reproducible. It does not replace
AirSim/DJI Tello experiments; it provides a baseline communication-layer
simulation that can be coupled with AirSim trajectories or physical-drone logs.

Outputs:
  - fanet_results.csv with one row per scenario
  - optional fanet_latency_plot.png if matplotlib is available
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from itertools import combinations
import csv
import math
import random
from typing import Dict, Iterable, List, Optional, Set, Tuple

Point = Tuple[float, float, float]
Edge = Tuple[int, int]


@dataclass
class UAVNode:
    """State of one UAV in a 3-D simulation area."""
    node_id: int
    position: Point
    velocity: Point

    def move(self, dt: float, bounds: Point) -> None:
        """Update node position with simple reflective-boundary mobility."""
        px, py, pz = self.position
        vx, vy, vz = self.velocity
        bx, by, bz = bounds
        nx, ny, nz = px + vx * dt, py + vy * dt, pz + vz * dt

        if nx < 0 or nx > bx:
            vx *= -1
            nx = max(0.0, min(bx, nx))
        if ny < 0 or ny > by:
            vy *= -1
            ny = max(0.0, min(by, ny))
        if nz < 0 or nz > bz:
            vz *= -1
            nz = max(0.0, min(bz, nz))

        self.position = (nx, ny, nz)
        self.velocity = (vx, vy, vz)


@dataclass
class PacketObservation:
    """One simulated packet-transmission observation."""
    delivered: bool
    hop_count: int
    latency_ms: Optional[float]


class FANETSimulator:
    """Communication-layer FANET simulator with dynamic topology updates."""

    def __init__(
        self,
        num_uavs: int,
        area_bounds: Point = (100.0, 100.0, 40.0),
        communication_range: float = 35.0,
        duration_s: float = 120.0,
        dt_s: float = 1.0,
        packet_attempts_per_step: int = 5,
        seed: int = 42,
    ) -> None:
        self.num_uavs = num_uavs
        self.area_bounds = area_bounds
        self.communication_range = communication_range
        self.duration_s = duration_s
        self.dt_s = dt_s
        self.packet_attempts_per_step = packet_attempts_per_step
        self.rng = random.Random(seed)
        self.nodes = self._create_nodes()
        self.edge_lifetimes: Dict[Edge, float] = {}
        self.previous_edges: Set[Edge] = set()
        self.topology_changes = 0

    def _create_nodes(self) -> List[UAVNode]:
        nodes: List[UAVNode] = []
        bx, by, bz = self.area_bounds
        for i in range(self.num_uavs):
            position = (
                self.rng.uniform(0, bx),
                self.rng.uniform(0, by),
                self.rng.uniform(5, bz),
            )
            speed = self.rng.uniform(1.0, 8.0)
            theta = self.rng.uniform(0, 2 * math.pi)
            phi = self.rng.uniform(-0.25, 0.25)
            velocity = (
                speed * math.cos(theta),
                speed * math.sin(theta),
                speed * phi,
            )
            nodes.append(UAVNode(node_id=i, position=position, velocity=velocity))
        return nodes

    @staticmethod
    def _distance(a: Point, b: Point) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def compute_edges(self) -> Set[Edge]:
        edges: Set[Edge] = set()
        for a, b in combinations(self.nodes, 2):
            if self._distance(a.position, b.position) <= self.communication_range:
                edges.add((min(a.node_id, b.node_id), max(a.node_id, b.node_id)))
        return edges

    def _adjacency(self, edges: Iterable[Edge]) -> Dict[int, List[int]]:
        graph = {i: [] for i in range(self.num_uavs)}
        for a, b in edges:
            graph[a].append(b)
            graph[b].append(a)
        return graph

    def shortest_path_hops(self, src: int, dst: int, edges: Set[Edge]) -> Optional[int]:
        if src == dst:
            return 0
        graph = self._adjacency(edges)
        queue = deque([(src, 0)])
        seen = {src}
        while queue:
            node, depth = queue.popleft()
            for neighbor in graph[node]:
                if neighbor == dst:
                    return depth + 1
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return None

    def transmit_packet(self, edges: Set[Edge]) -> PacketObservation:
        src, dst = self.rng.sample(range(self.num_uavs), 2)
        hops = self.shortest_path_hops(src, dst, edges)
        if hops is None:
            return PacketObservation(delivered=False, hop_count=0, latency_ms=None)

        # A simple latency model: base delay + per-hop forwarding + jitter.
        latency = 8.0 + 4.5 * hops + self.rng.uniform(0.0, 3.0)
        return PacketObservation(delivered=True, hop_count=hops, latency_ms=latency)

    def step(self) -> Set[Edge]:
        for node in self.nodes:
            node.move(self.dt_s, self.area_bounds)
        edges = self.compute_edges()

        added_or_removed = edges.symmetric_difference(self.previous_edges)
        self.topology_changes += len(added_or_removed)
        for edge in edges:
            self.edge_lifetimes[edge] = self.edge_lifetimes.get(edge, 0.0) + self.dt_s
        self.previous_edges = edges
        return edges

    def run(self) -> Dict[str, float]:
        observations: List[PacketObservation] = []
        steps = int(self.duration_s / self.dt_s)
        for _ in range(steps):
            edges = self.step()
            for _ in range(self.packet_attempts_per_step):
                observations.append(self.transmit_packet(edges))

        attempted = len(observations)
        delivered = [obs for obs in observations if obs.delivered]
        latencies = [obs.latency_ms for obs in delivered if obs.latency_ms is not None]
        hops = [obs.hop_count for obs in delivered]

        pdr = len(delivered) / attempted if attempted else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else float("nan")
        avg_hops = sum(hops) / len(hops) if hops else float("nan")
        avg_link_lifetime = (
            sum(self.edge_lifetimes.values()) / len(self.edge_lifetimes)
            if self.edge_lifetimes
            else 0.0
        )
        topology_change_rate = self.topology_changes / self.duration_s
        throughput_pps = len(delivered) / self.duration_s

        return {
            "num_uavs": float(self.num_uavs),
            "pdr": pdr,
            "avg_latency_ms": avg_latency,
            "avg_hop_count": avg_hops,
            "avg_link_lifetime_s": avg_link_lifetime,
            "topology_change_rate_per_s": topology_change_rate,
            "throughput_packets_per_s": throughput_pps,
        }


def run_scenarios() -> List[Dict[str, float]]:
    scenarios = [3, 5, 10, 15, 20]
    rows: List[Dict[str, float]] = []
    for n in scenarios:
        sim = FANETSimulator(num_uavs=n, seed=100 + n)
        rows.append(sim.run())
    return rows


def write_csv(rows: List[Dict[str, float]], path: str = "fanet_results.csv") -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = run_scenarios()
    write_csv(rows)
    for row in rows:
        print(row)

    try:
        import matplotlib.pyplot as plt  # type: ignore

        x = [row["num_uavs"] for row in rows]
        y = [row["avg_latency_ms"] for row in rows]
        plt.figure()
        plt.plot(x, y, marker="o")
        plt.xlabel("Number of UAVs")
        plt.ylabel("Average latency (ms)")
        plt.title("FANET latency under dynamic topology")
        plt.tight_layout()
        plt.savefig("fanet_latency_plot.png", dpi=300)
    except Exception:
        # Plotting is optional; the CSV file is the primary reproducible output.
        pass


if __name__ == "__main__":
    main()
