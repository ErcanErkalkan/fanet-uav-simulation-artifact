#!/usr/bin/env python3
"""
Executable FANET routing-abstraction benchmark.

This script extends the simplified FANET connectivity simulator with four
routing strategies:

1. ShortestPathOracle: recomputes a shortest path on the current global graph.
2. AODVLikeReactive: caches routes, triggers route discovery on demand, and
   invalidates broken routes.
3. OLSRLikeProactive: updates a proactive routing table periodically and routes
   packets using the latest table, which may be stale between updates.
4. GreedyGeographicRouting: forwards to the neighbour that most reduces
   distance to the destination.

The implementation is deliberately lightweight. It is intended as a
reproducible protocol-abstraction benchmark, not as a packet-level replacement
for ns-3 or OMNeT++ implementations of the full standards.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from collections import deque
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

Position = Tuple[float, float, float]
Edge = Tuple[int, int]
PathNodes = List[int]


@dataclass
class UAVNode:
    node_id: int
    position: Position
    velocity: Position

    def move(self, dt: float, bounds: Position) -> None:
        px, py, pz = self.position
        vx, vy, vz = self.velocity
        bx, by, bz = bounds
        nx, ny, nz = px + vx * dt, py + vy * dt, pz + vz * dt
        if nx < 0.0 or nx > bx:
            vx *= -1.0
            nx = max(0.0, min(bx, nx))
        if ny < 0.0 or ny > by:
            vy *= -1.0
            ny = max(0.0, min(by, ny))
        if nz < 5.0 or nz > bz:
            vz *= -1.0
            nz = max(5.0, min(bz, nz))
        self.position = (nx, ny, nz)
        self.velocity = (vx, vy, vz)


@dataclass
class RouteDecision:
    delivered: bool
    path: Optional[PathNodes]
    control_packets: int = 0
    discovery: bool = False
    route_failure: bool = False
    stale_route: bool = False

    @property
    def hops(self) -> int:
        if not self.path or len(self.path) < 2:
            return 0
        return len(self.path) - 1


@dataclass
class PacketObservation:
    delivered: bool
    hop_count: int
    latency_ms: Optional[float]
    control_packets: int
    discovery: bool
    route_failure: bool
    stale_route: bool


class RoutingProtocol:
    name = "base"

    def reset(self, num_nodes: int) -> None:
        self.num_nodes = num_nodes

    def on_topology_change(
        self,
        time_s: float,
        edges: Set[Edge],
        positions: Dict[int, Position],
    ) -> None:
        return None

    def route(
        self,
        src: int,
        dst: int,
        edges: Set[Edge],
        positions: Dict[int, Position],
        time_s: float,
    ) -> RouteDecision:
        raise NotImplementedError

    @staticmethod
    def adjacency(num_nodes: int, edges: Set[Edge]) -> Dict[int, Set[int]]:
        adj: Dict[int, Set[int]] = {i: set() for i in range(num_nodes)}
        for a, b in edges:
            adj[a].add(b)
            adj[b].add(a)
        return adj

    @staticmethod
    def bfs_path(num_nodes: int, edges: Set[Edge], src: int, dst: int) -> Optional[PathNodes]:
        if src == dst:
            return [src]
        adj = RoutingProtocol.adjacency(num_nodes, edges)
        parent = {src: None}
        q: deque[int] = deque([src])
        while q:
            node = q.popleft()
            for nb in adj[node]:
                if nb not in parent:
                    parent[nb] = node
                    if nb == dst:
                        path = [dst]
                        while parent[path[-1]] is not None:
                            path.append(parent[path[-1]])  # type: ignore[arg-type]
                        path.reverse()
                        return path
                    q.append(nb)
        return None

    @staticmethod
    def path_valid(path: Sequence[int], edges: Set[Edge]) -> bool:
        if len(path) < 2:
            return False
        edge_set = set(edges)
        for a, b in zip(path[:-1], path[1:]):
            if (min(a, b), max(a, b)) not in edge_set:
                return False
        return True


class ShortestPathOracle(RoutingProtocol):
    name = "shortest_path_oracle"

    def route(self, src, dst, edges, positions, time_s):
        path = self.bfs_path(self.num_nodes, edges, src, dst)
        return RouteDecision(delivered=path is not None, path=path)


class AODVLikeReactive(RoutingProtocol):
    """Reactive route cache with route discovery and break detection.

    This is an abstraction inspired by AODV behaviour. It does not implement the
    full RFC message semantics. Its purpose is to avoid the unrealistic behaviour
    of recomputing global shortest paths for every packet. Routes are discovered
    on demand, cached, reused, and invalidated when a link in the cached route is
    no longer present.
    """

    name = "aodv_like_reactive"

    def __init__(self, route_ttl_s: float = 8.0) -> None:
        self.route_ttl_s = route_ttl_s
        self.cache: Dict[Tuple[int, int], Tuple[PathNodes, float]] = {}

    def reset(self, num_nodes: int) -> None:
        super().reset(num_nodes)
        self.cache = {}

    def route(self, src, dst, edges, positions, time_s):
        key = (src, dst)
        reverse_key = (dst, src)
        cached = self.cache.get(key)
        if cached is None and reverse_key in self.cache:
            rev_path, expiry = self.cache[reverse_key]
            cached = (list(reversed(rev_path)), expiry)

        if cached is not None:
            path, expiry = cached
            if time_s <= expiry and self.path_valid(path, edges):
                return RouteDecision(delivered=True, path=path, control_packets=0)
            self.cache.pop(key, None)
            self.cache.pop(reverse_key, None)
            failure = True
        else:
            failure = False

        path = self.bfs_path(self.num_nodes, edges, src, dst)
        # RREQ flooding abstraction plus RREP along the discovered path.
        control = self.num_nodes + (len(path) - 1 if path else 0)
        if path is None:
            return RouteDecision(False, None, control_packets=control, discovery=True, route_failure=failure)
        self.cache[key] = (path, time_s + self.route_ttl_s)
        self.cache[reverse_key] = (list(reversed(path)), time_s + self.route_ttl_s)
        return RouteDecision(True, path, control_packets=control, discovery=True, route_failure=failure)


class OLSRLikeProactive(RoutingProtocol):
    """Periodic proactive table recomputation with stale-route effects."""

    name = "olsr_like_proactive"

    def __init__(self, update_interval_s: float = 2.0) -> None:
        self.update_interval_s = update_interval_s
        self.next_update_s = 0.0
        self.table: Dict[Tuple[int, int], Optional[PathNodes]] = {}
        self.snapshot_edges: Set[Edge] = set()
        self.last_update_control_packets = 0

    def reset(self, num_nodes: int) -> None:
        super().reset(num_nodes)
        self.next_update_s = 0.0
        self.table = {}
        self.snapshot_edges = set()
        self.last_update_control_packets = 0

    def on_topology_change(self, time_s, edges, positions):
        if time_s + 1e-9 < self.next_update_s:
            self.last_update_control_packets = 0
            return
        self.snapshot_edges = set(edges)
        self.table = {}
        for src in range(self.num_nodes):
            for dst in range(self.num_nodes):
                if src == dst:
                    continue
                self.table[(src, dst)] = self.bfs_path(self.num_nodes, self.snapshot_edges, src, dst)
        # HELLO + topology-control abstraction; proportional to nodes and active links.
        self.last_update_control_packets = self.num_nodes + 2 * len(edges)
        self.next_update_s = time_s + self.update_interval_s

    def route(self, src, dst, edges, positions, time_s):
        path = self.table.get((src, dst))
        control = self.last_update_control_packets
        self.last_update_control_packets = 0
        if path is None:
            return RouteDecision(False, None, control_packets=control)
        if not self.path_valid(path, edges):
            return RouteDecision(False, None, control_packets=control, stale_route=True, route_failure=True)
        return RouteDecision(True, path, control_packets=control)


class GreedyGeographicRouting(RoutingProtocol):
    """Neighbour-to-neighbour greedy forwarding using current positions."""

    name = "greedy_geographic"

    @staticmethod
    def dist(a: Position, b: Position) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def route(self, src, dst, edges, positions, time_s):
        adj = self.adjacency(self.num_nodes, edges)
        current = src
        visited = {src}
        path = [src]
        while current != dst:
            current_dist = self.dist(positions[current], positions[dst])
            candidates = [n for n in adj[current] if n not in visited]
            if not candidates:
                return RouteDecision(False, None)
            best = min(candidates, key=lambda n: self.dist(positions[n], positions[dst]))
            if self.dist(positions[best], positions[dst]) >= current_dist:
                # Local minimum: no neighbour gives positive progress.
                return RouteDecision(False, None, route_failure=True)
            path.append(best)
            visited.add(best)
            current = best
        return RouteDecision(True, path)


def make_protocol(name: str) -> RoutingProtocol:
    choices = {
        ShortestPathOracle.name: ShortestPathOracle,
        AODVLikeReactive.name: AODVLikeReactive,
        OLSRLikeProactive.name: OLSRLikeProactive,
        GreedyGeographicRouting.name: GreedyGeographicRouting,
    }
    if name not in choices:
        raise ValueError(f"Unknown routing protocol {name}. Choices: {sorted(choices)}")
    return choices[name]()


class RoutingBenchmarkSimulator:
    def __init__(
        self,
        num_uavs: int,
        protocol: RoutingProtocol,
        seed: int,
        duration_s: float = 120.0,
        dt_s: float = 1.0,
        area: Position = (120.0, 120.0, 50.0),
        communication_range: float = 35.0,
        packets_per_step: int = 5,
    ) -> None:
        self.num_uavs = num_uavs
        self.protocol = protocol
        self.seed = seed
        self.duration_s = duration_s
        self.dt_s = dt_s
        self.area = area
        self.communication_range = communication_range
        self.packets_per_step = packets_per_step
        self.rng = random.Random(seed)
        self.nodes = self._init_nodes()
        self.protocol.reset(num_uavs)

    def _init_nodes(self) -> List[UAVNode]:
        nodes: List[UAVNode] = []
        for i in range(self.num_uavs):
            pos = (
                self.rng.uniform(0.0, self.area[0]),
                self.rng.uniform(0.0, self.area[1]),
                self.rng.uniform(8.0, self.area[2]),
            )
            vel = (
                self.rng.uniform(-2.0, 2.0),
                self.rng.uniform(-2.0, 2.0),
                self.rng.uniform(-0.5, 0.5),
            )
            nodes.append(UAVNode(i, pos, vel))
        return nodes

    @staticmethod
    def _distance(a: Position, b: Position) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def positions(self) -> Dict[int, Position]:
        return {n.node_id: n.position for n in self.nodes}

    def compute_edges(self) -> Set[Edge]:
        edges: Set[Edge] = set()
        for a, b in combinations(self.nodes, 2):
            if self._distance(a.position, b.position) <= self.communication_range:
                edges.add((min(a.node_id, b.node_id), max(a.node_id, b.node_id)))
        return edges

    def _latency(self, decision: RouteDecision) -> float:
        base = 8.0 + 4.5 * decision.hops
        discovery_penalty = 12.0 if decision.discovery else 0.0
        control_penalty = 0.05 * decision.control_packets
        jitter = self.rng.uniform(0.0, 3.0)
        return base + discovery_penalty + control_penalty + jitter

    def run(self) -> Dict[str, float | int | str]:
        prev_edges: Set[Edge] = set()
        edge_lifetimes: Dict[Edge, float] = {}
        attempted = delivered = 0
        hops: List[int] = []
        latencies: List[float] = []
        topology_changes = 0
        control_packets = 0
        discoveries = 0
        route_failures = 0
        stale_failures = 0

        steps = int(self.duration_s / self.dt_s)
        for step in range(steps):
            time_s = step * self.dt_s
            for node in self.nodes:
                node.move(self.dt_s, self.area)
            edges = self.compute_edges()
            topology_changes += len(edges.symmetric_difference(prev_edges))
            for e in edges:
                edge_lifetimes[e] = edge_lifetimes.get(e, 0.0) + self.dt_s
            pos = self.positions()
            self.protocol.on_topology_change(time_s, edges, pos)
            for _ in range(self.packets_per_step):
                src, dst = self.rng.sample(range(self.num_uavs), 2)
                attempted += 1
                decision = self.protocol.route(src, dst, edges, pos, time_s)
                control_packets += decision.control_packets
                discoveries += 1 if decision.discovery else 0
                route_failures += 1 if decision.route_failure else 0
                stale_failures += 1 if decision.stale_route else 0
                if decision.delivered:
                    delivered += 1
                    hops.append(decision.hops)
                    latencies.append(self._latency(decision))
            prev_edges = edges

        return {
            "protocol": self.protocol.name,
            "num_uavs": self.num_uavs,
            "seed": self.seed,
            "attempted": attempted,
            "delivered": delivered,
            "pdr": delivered / attempted if attempted else 0.0,
            "avg_latency_ms": mean(latencies) if latencies else 0.0,
            "avg_hops": mean(hops) if hops else 0.0,
            "throughput_pps": delivered / self.duration_s if self.duration_s > 0 else 0.0,
            "topology_changes_per_s": topology_changes / self.duration_s,
            "avg_link_lifetime_s": mean(edge_lifetimes.values()) if edge_lifetimes else 0.0,
            "control_packets_per_s": control_packets / self.duration_s,
            "route_discoveries": discoveries,
            "route_failures": route_failures,
            "stale_route_failures": stale_failures,
        }


def aggregate(rows: List[Dict[str, float | int | str]]) -> List[Dict[str, float | int | str]]:
    keys = [
        "pdr",
        "avg_latency_ms",
        "avg_hops",
        "throughput_pps",
        "topology_changes_per_s",
        "avg_link_lifetime_s",
        "control_packets_per_s",
        "route_failures",
        "stale_route_failures",
    ]
    groups: Dict[Tuple[str, int], List[Dict[str, float | int | str]]] = {}
    for row in rows:
        groups.setdefault((str(row["protocol"]), int(row["num_uavs"])), []).append(row)
    out: List[Dict[str, float | int | str]] = []
    for (protocol, n), vals in sorted(groups.items()):
        rec: Dict[str, float | int | str] = {"protocol": protocol, "num_uavs": n, "runs": len(vals)}
        for k in keys:
            vector = [float(v[k]) for v in vals]
            rec[f"{k}_mean"] = mean(vector)
            rec[f"{k}_std"] = pstdev(vector) if len(vector) > 1 else 0.0
        out.append(rec)
    return out


def write_csv(path: Path, rows: List[Dict[str, float | int | str]]) -> None:
    if not rows:
        raise ValueError("No rows to write")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_benchmark(args: argparse.Namespace) -> None:
    protocols = [
        ShortestPathOracle.name,
        AODVLikeReactive.name,
        OLSRLikeProactive.name,
        GreedyGeographicRouting.name,
    ]
    raw_rows: List[Dict[str, float | int | str]] = []
    for n in args.uavs:
        for protocol_name in protocols:
            for rep in range(args.repetitions):
                sim = RoutingBenchmarkSimulator(
                    num_uavs=n,
                    protocol=make_protocol(protocol_name),
                    seed=args.seed + 1000 * rep + 17 * n,
                    duration_s=args.duration,
                    dt_s=args.dt,
                    communication_range=args.communication_range,
                    packets_per_step=args.packets_per_step,
                )
                raw_rows.append(sim.run())
    write_csv(Path(args.raw_out), raw_rows)
    summary_rows = aggregate(raw_rows)
    write_csv(Path(args.summary_out), summary_rows)
    print(f"Wrote {args.raw_out} and {args.summary_out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FANET routing protocol abstraction benchmark")
    parser.add_argument("--uavs", nargs="+", type=int, default=[5, 10, 20, 30])
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--communication-range", type=float, default=35.0)
    parser.add_argument("--packets-per-step", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--raw-out", default="fanet_routing_raw.csv")
    parser.add_argument("--summary-out", default="fanet_routing_summary.csv")
    return parser.parse_args()


if __name__ == "__main__":
    run_benchmark(parse_args())
