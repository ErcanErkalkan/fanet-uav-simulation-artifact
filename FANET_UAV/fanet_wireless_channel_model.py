#!/usr/bin/env python3
"""Probabilistic wireless-channel extension for FANET simulations.

This script complements the routing and statistical benchmarks by replacing the
binary distance-threshold link model with a lightweight radio model including
path loss, shadowing, noise, interference, packet-collision penalty, bandwidth-
limited transmission delay, queueing delay, and per-packet transmission energy.
It is intentionally compact and reproducible; it is not a substitute for a full
PHY/MAC simulator such as ns-3.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import csv
import math
from pathlib import Path
import random
from statistics import mean, stdev
from typing import Dict, Iterable, List, Optional, Tuple

C_LIGHT = 299_792_458.0


def dbm_to_mw(x_dbm: float) -> float:
    return 10.0 ** (x_dbm / 10.0)


def mw_to_dbm(x_mw: float) -> float:
    return 10.0 * math.log10(max(x_mw, 1e-30))


@dataclass
class UAVNode:
    node_id: int
    position: List[float]
    velocity: List[float]
    heading_rad: float

    def move(self, dt: float, area_xy: float, altitude_bounds: Tuple[float, float]) -> None:
        for k in range(3):
            self.position[k] += self.velocity[k] * dt
        # reflective horizontal boundaries
        for k in (0, 1):
            if self.position[k] < 0.0 or self.position[k] > area_xy:
                self.velocity[k] *= -1.0
                self.position[k] = min(max(self.position[k], 0.0), area_xy)
        # altitude bounds
        z_min, z_max = altitude_bounds
        if self.position[2] < z_min or self.position[2] > z_max:
            self.velocity[2] *= -1.0
            self.position[2] = min(max(self.position[2], z_min), z_max)
        self.heading_rad = math.atan2(self.velocity[1], self.velocity[0])


@dataclass
class WirelessConfig:
    frequency_hz: float = 2.4e9
    bandwidth_hz: float = 5e6
    tx_power_dbm: float = 18.0
    tx_power_w: float = 0.063  # approximately 18 dBm
    noise_figure_db: float = 7.0
    path_loss_exponent_los: float = 2.15
    path_loss_exponent_nlos: float = 2.85
    shadowing_sigma_db: float = 2.5
    rx_sensitivity_dbm: float = -88.0
    sinr_threshold_db: float = 8.0
    logistic_slope: float = 1.35
    reliability_threshold: float = 0.45
    packet_size_bytes: int = 1024
    queue_base_ms: float = 1.5
    mac_collision_penalty: float = 0.15
    interfering_tx_probability: float = 0.10
    obstacle_loss_db: float = 7.0
    obstacle_probability: float = 0.10
    orientation_loss_max_db: float = 5.0
    rx_power_w: float = 0.040


class WirelessChannel:
    def __init__(self, cfg: WirelessConfig, rng: random.Random):
        self.cfg = cfg
        self.rng = rng
        self.lambda_m = C_LIGHT / cfg.frequency_hz
        self.noise_dbm = -174.0 + 10.0 * math.log10(cfg.bandwidth_hz) + cfg.noise_figure_db
        self.noise_mw = dbm_to_mw(self.noise_dbm)

    def distance(self, a: UAVNode, b: UAVNode) -> float:
        return math.sqrt(sum((a.position[k] - b.position[k]) ** 2 for k in range(3)))

    def fspl_1m_db(self) -> float:
        return 20.0 * math.log10(4.0 * math.pi / self.lambda_m)

    def elevation_angle_deg(self, a: UAVNode, b: UAVNode) -> float:
        horizontal = math.sqrt((a.position[0] - b.position[0]) ** 2 + (a.position[1] - b.position[1]) ** 2)
        dz = abs(a.position[2] - b.position[2])
        return math.degrees(math.atan2(dz, max(horizontal, 1e-6)))

    def orientation_loss_db(self, tx: UAVNode, rx: UAVNode) -> float:
        bearing = math.atan2(rx.position[1] - tx.position[1], rx.position[0] - tx.position[0])
        diff = abs((bearing - tx.heading_rad + math.pi) % (2.0 * math.pi) - math.pi)
        return self.cfg.orientation_loss_max_db * diff / math.pi

    def path_loss_db(self, tx: UAVNode, rx: UAVNode) -> float:
        d = max(self.distance(tx, rx), 1.0)
        elev = self.elevation_angle_deg(tx, rx)
        # Higher elevation angles are more likely to be LoS in aerial links.
        p_los = min(0.95, max(0.25, 0.25 + elev / 90.0))
        n = self.cfg.path_loss_exponent_los if self.rng.random() < p_los else self.cfg.path_loss_exponent_nlos
        obstacle_loss = self.cfg.obstacle_loss_db if self.rng.random() < self.cfg.obstacle_probability else 0.0
        shadowing = self.rng.gauss(0.0, self.cfg.shadowing_sigma_db)
        altitude_gain = min(3.0, elev / 30.0)  # mild aerial LoS benefit, capped
        return (
            self.fspl_1m_db()
            + 10.0 * n * math.log10(d)
            + shadowing
            + obstacle_loss
            + self.orientation_loss_db(tx, rx)
            - altitude_gain
        )

    def received_power_dbm(self, tx: UAVNode, rx: UAVNode) -> float:
        return self.cfg.tx_power_dbm - self.path_loss_db(tx, rx)

    def interference_mw(self, tx: UAVNode, rx: UAVNode, nodes: List[UAVNode]) -> Tuple[float, int]:
        total_mw = 0.0
        active = 0
        candidates = [other for other in nodes if other.node_id not in (tx.node_id, rx.node_id)]
        if len(candidates) > 6:
            candidates = self.rng.sample(candidates, 6)
        for other in candidates:
            if self.rng.random() <= self.cfg.interfering_tx_probability:
                p_dbm = self.received_power_dbm(other, rx)
                # Scale the sampled interferers to approximate the full node set.
                scale = max(1.0, (len(nodes) - 2) / max(1, len(candidates)))
                if p_dbm > self.cfg.rx_sensitivity_dbm - 12.0:
                    total_mw += dbm_to_mw(p_dbm) * scale
                    active += 1
        return total_mw, active

    def hop_quality(self, tx: UAVNode, rx: UAVNode, nodes: List[UAVNode]) -> Dict[str, float]:
        pr_dbm = self.received_power_dbm(tx, rx)
        pr_mw = dbm_to_mw(pr_dbm)
        interference_mw, active_interferers = self.interference_mw(tx, rx, nodes)
        sinr_db = pr_dbm - mw_to_dbm(self.noise_mw + interference_mw)
        # Logistic packet success probability, clipped by receiver sensitivity.
        reliability = 1.0 / (1.0 + math.exp(-(sinr_db - self.cfg.sinr_threshold_db) / self.cfg.logistic_slope))
        if pr_dbm < self.cfg.rx_sensitivity_dbm:
            reliability *= 0.20
        collision_factor = max(0.05, 1.0 - self.cfg.mac_collision_penalty * active_interferers)
        reliability = max(0.0, min(1.0, reliability * collision_factor))
        d = self.distance(tx, rx)
        tx_ms = (8.0 * self.cfg.packet_size_bytes / self.cfg.bandwidth_hz) * 1000.0
        prop_ms = (d / C_LIGHT) * 1000.0
        load = min(0.93, self.cfg.interfering_tx_probability * (1 + active_interferers))
        queue_ms = self.cfg.queue_base_ms * (1.0 + load / max(1e-6, 1.0 - load))
        energy_j = (self.cfg.tx_power_w + self.cfg.rx_power_w) * (tx_ms / 1000.0)
        return {
            "distance_m": d,
            "rx_power_dbm": pr_dbm,
            "sinr_db": sinr_db,
            "reliability": reliability,
            "interferers": float(active_interferers),
            "tx_delay_ms": tx_ms,
            "prop_delay_ms": prop_ms,
            "queue_delay_ms": queue_ms,
            "energy_j": energy_j,
        }


class WirelessFANETSimulator:
    def __init__(
        self,
        num_uavs: int,
        seed: int,
        duration_s: float = 30.0,
        dt_s: float = 1.0,
        area_xy: float = 100.0,
        altitude_bounds: Tuple[float, float] = (15.0, 45.0),
        speed_range: Tuple[float, float] = (1.5, 6.0),
        packet_attempts_per_step: int = 6,
        binary_range_m: float = 35.0,
        wireless_cfg: Optional[WirelessConfig] = None,
    ):
        self.num_uavs = num_uavs
        self.seed = seed
        self.rng = random.Random(seed)
        self.duration_s = duration_s
        self.dt_s = dt_s
        self.area_xy = area_xy
        self.altitude_bounds = altitude_bounds
        self.speed_range = speed_range
        self.packet_attempts_per_step = packet_attempts_per_step
        self.binary_range_m = binary_range_m
        self.channel = WirelessChannel(wireless_cfg or WirelessConfig(), self.rng)
        self.nodes = self._make_nodes()

    def _make_nodes(self) -> List[UAVNode]:
        nodes: List[UAVNode] = []
        for i in range(self.num_uavs):
            pos = [
                self.rng.uniform(0, self.area_xy),
                self.rng.uniform(0, self.area_xy),
                self.rng.uniform(*self.altitude_bounds),
            ]
            speed = self.rng.uniform(*self.speed_range)
            theta = self.rng.uniform(0, 2 * math.pi)
            vz = self.rng.uniform(-0.5, 0.5)
            vel = [speed * math.cos(theta), speed * math.sin(theta), vz]
            nodes.append(UAVNode(i, pos, vel, theta))
        return nodes

    def step(self) -> None:
        for node in self.nodes:
            node.move(self.dt_s, self.area_xy, self.altitude_bounds)

    def binary_edges(self) -> Dict[Tuple[int, int], Dict[str, float]]:
        edges: Dict[Tuple[int, int], Dict[str, float]] = {}
        for i in range(self.num_uavs):
            for j in range(i + 1, self.num_uavs):
                d = self.channel.distance(self.nodes[i], self.nodes[j])
                if d <= self.binary_range_m:
                    edges[(i, j)] = {"reliability": 1.0, "sinr_db": 99.0, "energy_j": 0.0}
        return edges

    def wireless_edges(self) -> Dict[Tuple[int, int], Dict[str, float]]:
        edges: Dict[Tuple[int, int], Dict[str, float]] = {}
        for i in range(self.num_uavs):
            for j in range(i + 1, self.num_uavs):
                q_ij = self.channel.hop_quality(self.nodes[i], self.nodes[j], self.nodes)
                q_ji = self.channel.hop_quality(self.nodes[j], self.nodes[i], self.nodes)
                reliability = min(q_ij["reliability"], q_ji["reliability"])
                if reliability >= self.channel.cfg.reliability_threshold:
                    edges[(i, j)] = {
                        "reliability": reliability,
                        "sinr_db": min(q_ij["sinr_db"], q_ji["sinr_db"]),
                        "rx_power_dbm": min(q_ij["rx_power_dbm"], q_ji["rx_power_dbm"]),
                        "interferers": max(q_ij["interferers"], q_ji["interferers"]),
                        "hop_delay_ms": q_ij["tx_delay_ms"] + q_ij["prop_delay_ms"] + q_ij["queue_delay_ms"],
                        "energy_j": q_ij["energy_j"],
                    }
        return edges

    @staticmethod
    def adjacency(edges: Dict[Tuple[int, int], Dict[str, float]], n: int) -> Dict[int, List[int]]:
        adj = {i: [] for i in range(n)}
        for i, j in edges:
            adj[i].append(j)
            adj[j].append(i)
        return adj

    @staticmethod
    def shortest_path(src: int, dst: int, edges: Dict[Tuple[int, int], Dict[str, float]], n: int) -> Optional[List[int]]:
        adj = WirelessFANETSimulator.adjacency(edges, n)
        queue: List[Tuple[int, List[int]]] = [(src, [src])]
        seen = {src}
        while queue:
            node, path = queue.pop(0)
            if node == dst:
                return path
            for nb in adj[node]:
                if nb not in seen:
                    seen.add(nb)
                    queue.append((nb, path + [nb]))
        return None

    def transmit(self, model: str, edges: Dict[Tuple[int, int], Dict[str, float]]) -> Tuple[bool, int, float, float, float]:
        src, dst = self.rng.sample(range(self.num_uavs), 2)
        path = self.shortest_path(src, dst, edges, self.num_uavs)
        if not path:
            return False, 0, 0.0, 0.0, 0.0
        hops = len(path) - 1
        if model == "binary":
            latency_ms = 8.0 + 4.5 * hops + self.rng.uniform(0.0, 3.0)
            return True, hops, latency_ms, 0.0, 99.0
        latency_ms = 0.0
        energy_j = 0.0
        sinrs = []
        for a, b in zip(path, path[1:]):
            key = (min(a, b), max(a, b))
            q = edges[key]
            sinrs.append(q["sinr_db"])
            energy_j += q["energy_j"]
            latency_ms += q["hop_delay_ms"]
            # Packet-level stochastic success, not just graph reachability.
            if self.rng.random() > q["reliability"]:
                return False, hops, 0.0, energy_j, mean(sinrs)
        routing_ms = 3.0 + 1.0 * hops
        mac_backoff_ms = self.rng.expovariate(1 / 1.5)
        return True, hops, latency_ms + routing_ms + mac_backoff_ms, energy_j, mean(sinrs)

    def run_once(self, model: str) -> Dict[str, float]:
        attempted = delivered = 0
        latencies: List[float] = []
        hops: List[int] = []
        energy_values: List[float] = []
        sinr_values: List[float] = []
        reliabilities: List[float] = []
        previous_edges: set[Tuple[int, int]] = set()
        topology_changes = 0
        for _ in range(int(self.duration_s / self.dt_s)):
            self.step()
            edges = self.binary_edges() if model == "binary" else self.wireless_edges()
            current = set(edges.keys())
            topology_changes += len(current.symmetric_difference(previous_edges))
            previous_edges = current
            if model == "wireless":
                reliabilities.extend(q["reliability"] for q in edges.values())
            for _ in range(self.packet_attempts_per_step):
                attempted += 1
                ok, hop_count, latency_ms, energy_j, sinr_db = self.transmit(model, edges)
                if ok:
                    delivered += 1
                    latencies.append(latency_ms)
                    hops.append(hop_count)
                    energy_values.append(energy_j)
                    sinr_values.append(sinr_db)
        return {
            "model": model,
            "num_uavs": self.num_uavs,
            "seed": self.seed,
            "pdr": delivered / attempted if attempted else 0.0,
            "latency_ms": mean(latencies) if latencies else 0.0,
            "hops": mean(hops) if hops else 0.0,
            "topology_changes_per_s": topology_changes / self.duration_s,
            "mean_link_reliability": mean(reliabilities) if reliabilities else (1.0 if model == "binary" else 0.0),
            "mean_sinr_db": mean(sinr_values) if sinr_values else 0.0,
            "energy_mj_per_packet": 1000.0 * mean(energy_values) if energy_values else 0.0,
            "throughput_pkt_s": delivered / self.duration_s,
        }


def ci95(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * stdev(values) / math.sqrt(len(values))


def summarize(rows: List[Dict[str, float]], keys: Iterable[str]) -> List[Dict[str, str]]:
    groups: Dict[Tuple[str, int], List[Dict[str, float]]] = {}
    for row in rows:
        groups.setdefault((str(row["model"]), int(row["num_uavs"])), []).append(row)
    out: List[Dict[str, str]] = []
    for (model, n), subset in sorted(groups.items(), key=lambda x: (x[0][1], x[0][0])):
        result: Dict[str, str] = {"model": model, "num_uavs": str(n), "repetitions": str(len(subset))}
        for key in keys:
            vals = [float(r[key]) for r in subset]
            result[f"{key}_mean"] = f"{mean(vals):.4f}"
            result[f"{key}_sd"] = f"{stdev(vals):.4f}" if len(vals) > 1 else "0.0000"
            result[f"{key}_ci95"] = f"{ci95(vals):.4f}"
        out.append(result)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FANET probabilistic wireless-channel benchmark")
    parser.add_argument("--uavs", nargs="+", type=int, default=[10, 20, 30])
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--raw-out", type=Path, default=Path("fanet_wireless_raw.csv"))
    parser.add_argument("--summary-out", type=Path, default=Path("fanet_wireless_summary.csv"))
    return parser.parse_args()


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    raw_rows: List[Dict[str, float]] = []
    for num_uavs in args.uavs:
        for model in ("binary", "wireless"):
            for seed in range(args.seed_start, args.seed_start + args.repetitions):
                sim = WirelessFANETSimulator(num_uavs=num_uavs, seed=seed)
                raw_rows.append(sim.run_once(model))

    metric_keys = [
        "pdr",
        "latency_ms",
        "hops",
        "topology_changes_per_s",
        "mean_link_reliability",
        "mean_sinr_db",
        "energy_mj_per_packet",
        "throughput_pkt_s",
    ]
    summary_rows = summarize(raw_rows, metric_keys)

    write_csv(args.raw_out, raw_rows, list(raw_rows[0].keys()))
    write_csv(args.summary_out, summary_rows, list(summary_rows[0].keys()))
    print(f"Wrote {args.raw_out}")
    print(f"Wrote {args.summary_out}")
    for row in summary_rows:
        print(row)


if __name__ == "__main__":
    main()
