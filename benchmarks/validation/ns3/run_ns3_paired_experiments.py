#!/usr/bin/env python3
"""Run paired ns-3.49 and Python-FANET replay experiments for scenarios C and D."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


REPETITION_SEEDS = list(range(20261029, 20261059))
NS3_SEED = 20261029
RANGE_M = 35.0
PACKET_BYTES = 256
WARMUP_S = 5.0
DRAIN_S = 10.0
T_95_DF29 = 2.045229642
T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
    7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
    13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
    19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: T_95_DF29,
}
EXPECTED_AIRSIM_SHA256 = "9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3"
NS3_OFFICIAL_TAG_COMMIT = "418210e8914e9f6bcb5cddbcc94a2cecb7853b68"
NS3_ARCHIVE_SHA256 = "81c9eb0839d2b527e9cc01db7eb0a521d8fc6a520ebb23d17f3a5c96e47b4d68"
FLOWMONITOR_DOC_URL = "https://www.nsnam.org/docs/release/3.49/models/html/flow-monitor.html"
RAW_FIELDS = [
    "experiment", "simulator", "routing", "channel_profile", "coordinate_frame",
    "repetition_seed", "traffic_seed", "ns3_seed", "ns3_run", "n_nodes",
    "mobility_frames", "measurement_window_s", "scheduled_packets",
    "generated_packets", "socket_accepted_packets", "socket_rejected_packets",
    "flowmonitor_tx_packets", "flowmonitor_rx_packets", "flowmonitor_lost_packets",
    "flowmonitor_rx_minus_application_delivered_packets",
    "undelivered_after_drain_packets", "delivered_packets", "pdr", "mean_latency_ms",
    "mean_flowmonitor_delay_ms", "mean_hops", "forwarding_based_hops_estimate",
    "route_failures", "route_discoveries", "stale_route_failures",
    "packets_without_routing_path", "route_discovery_failures",
    "route_recovery_after_flag", "protocol_specific_route_flag_events",
    "failed_wireless_packets_after_routing", "model_control_packets_total",
    "model_control_packets_per_s", "control_messages", "control_bytes",
    "topology_frames_fully_connected", "topology_mean_edges",
    "topology_min_edges", "topology_mean_components",
    "packets_requiring_multihop", "packets_without_binary_path",
]
AUDIT_FIELDS = [
    "experiment", "simulator", "routing", "channel_profile", "repetition_seed",
    "traffic_seed", "ns3_seed", "ns3_run", "packet_id", "source_id",
    "destination_id", "generation_time_s", "evaluated_at_time_s",
    "application_generated", "delivered", "latency_ms", "hop_count",
    "route_failure", "route_discovery", "stale_route", "control_packets",
    "loss_reason",
]
TOPOLOGY_FIELDS = [
    "experiment", "repetition_seed", "mobility_frames", "n_nodes",
    "fully_connected_frames", "mean_edges", "min_edges", "mean_components",
    "scheduled_packets", "packets_requiring_multihop",
    "packets_without_binary_path",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def redact_home_paths(text: str) -> str:
    home = Path.home().as_posix().rstrip("/")
    return text.replace(home, "$HOME") if home else text


def number(value: Any) -> float | None:
    if value in (None, "", "NA", "nan", "NaN"):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def flowmonitor_lost_diagnostic(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, int] = {}
    for row in raw_rows:
        if row["simulator"] != "ns-3.49":
            continue
        tx = int(row["flowmonitor_tx_packets"])
        rx = int(row["flowmonitor_rx_packets"])
        lost = int(row["flowmonitor_lost_packets"])
        if lost > max(0, tx - rx):
            condition = f"{row['experiment']}/{row['routing']}"
            by_condition[condition] = by_condition.get(condition, 0) + 1
    return {
        "runs_where_lost_exceeds_nonnegative_tx_minus_rx": sum(by_condition.values()),
        "by_experiment_routing": by_condition,
        "interpretation": (
            "FlowMonitor lostPackets is a timeout-based assumed-loss diagnostic, "
            "not the complement of Rx or application packet-identity delivery; "
            "application unique-delivery counts define PDR."
        ),
        "official_documentation": FLOWMONITOR_DOC_URL,
    }


def t_critical_95(degrees_of_freedom: int) -> float | None:
    return T_CRITICAL_95.get(degrees_of_freedom)


def student_t_half_width(values: list[float]) -> float | str:
    if len(values) < 2:
        return "NA"
    critical = t_critical_95(len(values) - 1)
    if critical is None:
        return "NA"
    return critical * statistics.stdev(values) / math.sqrt(len(values))


def connected_components(n_nodes: int, edges: set[tuple[int, int]]) -> int:
    adjacency = {node: set() for node in range(n_nodes)}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    unseen = set(adjacency)
    components = 0
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            for neighbor in adjacency[stack.pop()] & unseen:
                unseen.remove(neighbor)
                stack.append(neighbor)
    return components


def has_path(n_nodes: int, edges: set[tuple[int, int]], source: int, target: int) -> bool:
    adjacency = {node: set() for node in range(n_nodes)}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    seen = {source}
    stack = [source]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        for neighbor in adjacency[node] - seen:
            seen.add(neighbor)
            stack.append(neighbor)
    return False


def load_topology(
    mobility_path: Path, traffic_path: Path
) -> tuple[dict[str, Any], dict[int, set[tuple[int, int]]], dict[str, int]]:
    mobility_rows = read_csv(mobility_path)
    schedule = read_csv(traffic_path)
    names = sorted({row["node_id"] for row in mobility_rows})
    node_index = {name: index for index, name in enumerate(names)}
    grouped: dict[int, dict[str, tuple[float, float, float]]] = defaultdict(dict)
    for row in mobility_rows:
        frame = int(row["sequence"])
        if row["node_id"] in grouped[frame]:
            raise ValueError(f"duplicate node {row['node_id']} at frame {frame}")
        position = (
            float(row["x_m"]),
            float(row["y_m"]),
            float(row["z_m"]),
        )
        if not all(math.isfinite(value) for value in position):
            raise ValueError(f"non-finite coordinate at frame {frame}")
        grouped[frame][row["node_id"]] = position
    if not grouped or any(set(nodes) != set(names) for nodes in grouped.values()):
        raise ValueError(f"incomplete mobility frames in {mobility_path}")

    frame_edges: dict[int, set[tuple[int, int]]] = {}
    component_counts = []
    edge_counts = []
    fully_connected = 0
    for frame, positions in sorted(grouped.items()):
        edges: set[tuple[int, int]] = set()
        for left in range(len(names)):
            for right in range(left + 1, len(names)):
                a = positions[names[left]]
                b = positions[names[right]]
                distance = math.sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))
                if distance <= RANGE_M:
                    edges.add((left, right))
        frame_edges[frame] = edges
        edge_counts.append(len(edges))
        components = connected_components(len(names), edges)
        component_counts.append(components)
        fully_connected += components == 1

    multihop = no_path = 0
    for row in schedule:
        src_name, dst_name = row["source_id"], row["destination_id"]
        if src_name not in node_index or dst_name not in node_index or src_name == dst_name:
            raise ValueError("traffic schedule endpoint is invalid")
        edges = frame_edges[int(row["trace_sequence"])]
        pair = tuple(sorted((node_index[src_name], node_index[dst_name])))
        if pair not in edges and has_path(len(names), edges, *pair):
            multihop += 1
        elif not has_path(len(names), edges, *pair):
            no_path += 1
    metrics = {
        "experiment": "C" if names and names[0].startswith("Drone") else "D",
        "mobility_frames": len(grouped),
        "n_nodes": len(names),
        "fully_connected_frames": fully_connected,
        "mean_edges": statistics.mean(edge_counts),
        "min_edges": min(edge_counts),
        "mean_components": statistics.mean(component_counts),
        "scheduled_packets": len(schedule),
        "packets_requiring_multihop": multihop,
        "packets_without_binary_path": no_path,
    }
    return metrics, frame_edges, node_index


def invoke_ns3(
    ns3_root: Path,
    output_dir: Path,
    experiment: str,
    routing: str,
    mobility: Path,
    traffic: Path,
    coordinate_frame: str,
    measurement_window: float,
    repetition_seed: int,
    traffic_seed: int,
    ns3_run: int,
    log_stream,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.csv"
    events_path = output_dir / "events.csv"
    args = (
        f"scratch/ns3_fanet_reference --experiment={experiment} --routing={routing}"
        f" --profile=range_limited_wifi --coordinate-frame={coordinate_frame}"
        f" --mobility={mobility} --traffic={traffic} --summary={summary_path}"
        f" --events={events_path} --repetition-seed={repetition_seed}"
        f" --traffic-seed={traffic_seed} --seed={NS3_SEED} --run={ns3_run}"
        f" --packet-bytes={PACKET_BYTES} --range-m={RANGE_M}"
        f" --warmup-s={WARMUP_S} --drain-s={DRAIN_S}"
        f" --measurement-window-s={measurement_window}"
    )
    log_stream.write(f"RUN ns-3 {experiment}/{routing} repetition={repetition_seed} run={ns3_run}\n")
    process = subprocess.run(
        [str(ns3_root / "ns3"), "run", args],
        cwd=ns3_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    log_stream.write(redact_home_paths(process.stdout))
    if process.returncode:
        raise RuntimeError(
            f"ns-3 run failed ({experiment}/{routing}/{repetition_seed}):\n{process.stdout[-6000:]}"
        )
    summaries = read_csv(summary_path)
    events = read_csv(events_path)
    if len(summaries) != 1:
        raise RuntimeError(f"expected one ns-3 summary row, found {len(summaries)}")
    summary = summaries[0]
    if len(events) != int(summary["scheduled_packets"]):
        raise RuntimeError("packet audit row count differs from the schedule")
    return summary, events


def run_r1(
    r1_source: Path,
    mobility: Path,
    traffic: Path,
    routing_name: str,
    repetition_seed: int,
    traffic_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sys.path.insert(0, str(r1_source))
    from fanet_metric_contract import RouteEventCounter  # type: ignore[reportMissingImports]
    from fanet_unified_pipeline import UnifiedFANETPipeline  # type: ignore[reportMissingImports]

    args = argparse.Namespace(
        source="trace",
        trace=mobility,
        trace_time_column="time_s",
        routing=routing_name,
        link_model="binary",
        communication_range=RANGE_M,
    )
    mobility_rows = read_csv(mobility)
    if "sim_time_stamp_ns" in mobility_rows[0]:
        timestamp_values = [row["sim_time_stamp_ns"] for row in mobility_rows]
        if any(not value for value in timestamp_values):
            if any(timestamp_values):
                raise ValueError(f"partially missing simulation timestamps in {mobility}")
            with tempfile.TemporaryDirectory(prefix="r1-mobility-") as temp_dir:
                compatible_trace = Path(temp_dir) / mobility.name
                fields = [field for field in mobility_rows[0] if field != "sim_time_stamp_ns"]
                write_csv(compatible_trace, fields, mobility_rows)
                args.trace = compatible_trace
                pipeline = UnifiedFANETPipeline(args, seed=repetition_seed)
        else:
            pipeline = UnifiedFANETPipeline(args, seed=repetition_seed)
    else:
        pipeline = UnifiedFANETPipeline(args, seed=repetition_seed)
    if pipeline.trace_frames is None:
        raise RuntimeError("R1 trace loader did not produce frames")
    schedule = read_csv(traffic)
    by_sequence: dict[int, list[dict[str, str]]] = defaultdict(list)
    for event in schedule:
        by_sequence[int(event["trace_sequence"])].append(event)
    route_events = RouteEventCounter()
    delivered_latencies: list[float] = []
    delivered_hops: list[int] = []
    audit: list[dict[str, Any]] = []
    generated = delivered = route_failures = discoveries = stale_failures = 0
    model_control_packets = 0
    missing_route_edges = 0

    for frame in pipeline.trace_frames:
        qualities = pipeline.edge_quality(frame.nodes)
        edges = set(qualities)
        positions = pipeline.positions(frame.nodes)
        pipeline.protocol.on_topology_change(frame.time_s, edges, positions)
        for row in by_sequence[int(frame.sequence)]:
            source = pipeline.trace_node_map[row["source_id"]]
            destination = pipeline.trace_node_map[row["destination_id"]]
            decision = pipeline.protocol.route(
                source, destination, edges, positions, frame.time_s
            )
            generated += 1
            ok, latency, _, _, _, missing_edge = (
                pipeline.evaluate_delivery(decision, qualities)
            )
            route_events.observe(
                decision,
                delivered_after_channel=(
                    ok if decision.delivered and not missing_edge else None
                ),
            )
            route_failures += int(decision.route_failure) + int(missing_edge)
            discoveries += int(decision.discovery)
            stale_failures += int(decision.stale_route)
            model_control_packets += decision.control_packets
            missing_route_edges += int(missing_edge)
            delivered += int(ok)
            if ok:
                delivered_latencies.append(latency)
                delivered_hops.append(decision.hops)
            audit.append(
                {
                    "experiment": "C" if len(pipeline.trace_node_map) == 3 else "D",
                    "simulator": "Python_R1_abstraction",
                    "routing": routing_name.replace("_like_reactive", "").replace("_like_proactive", ""),
                    "channel_profile": "binary_35m_abstraction",
                    "repetition_seed": repetition_seed,
                    "traffic_seed": traffic_seed,
                    "ns3_seed": "NA",
                    "ns3_run": "NA",
                    "packet_id": row["packet_id"],
                    "source_id": row["source_id"],
                    "destination_id": row["destination_id"],
                    "generation_time_s": row["generation_time_s"],
                    "evaluated_at_time_s": row["evaluated_at_time_s"],
                    "application_generated": 1,
                    "delivered": int(ok),
                    "latency_ms": f"{latency:.12g}" if ok else "NA",
                    "hop_count": decision.hops if ok else "NA",
                    "route_failure": int(decision.route_failure or missing_edge),
                    "route_discovery": int(decision.discovery),
                    "stale_route": int(decision.stale_route),
                    "control_packets": decision.control_packets,
                    "loss_reason": (
                        "NA" if ok else
                        "missing_route_edge" if missing_edge else
                        "no_routing_path" if not decision.path else
                        "binary_channel_drop"
                    ),
                }
            )
    summary = {
        "experiment": "C" if len(pipeline.trace_node_map) == 3 else "D",
        "simulator": "Python_R1_abstraction",
        "routing": routing_name.replace("_like_reactive", "").replace("_like_proactive", ""),
        "channel_profile": "binary_35m_abstraction",
        "coordinate_frame": "common_NED" if len(pipeline.trace_node_map) == 3 else "Cartesian",
        "repetition_seed": repetition_seed,
        "traffic_seed": traffic_seed,
        "ns3_seed": "NA",
        "ns3_run": "NA",
        "n_nodes": pipeline.num_uavs,
        "mobility_frames": len(pipeline.trace_frames),
        "measurement_window_s": pipeline.duration_s if len(pipeline.trace_node_map) == 3 else 30.0,
        "scheduled_packets": len(schedule),
        "generated_packets": generated,
        "socket_accepted_packets": "NA",
        "socket_rejected_packets": "NA",
        "flowmonitor_tx_packets": "NA",
        "flowmonitor_rx_packets": "NA",
        "flowmonitor_lost_packets": "NA",
        "flowmonitor_rx_minus_application_delivered_packets": "NA",
        "undelivered_after_drain_packets": "NA",
        "delivered_packets": delivered,
        "pdr": delivered / generated if generated else 0.0,
        "mean_latency_ms": statistics.mean(delivered_latencies) if delivered_latencies else "NA",
        "mean_flowmonitor_delay_ms": "NA",
        "mean_hops": statistics.mean(delivered_hops) if delivered_hops else "NA",
        "forwarding_based_hops_estimate": "NA",
        "route_failures": route_failures,
        "route_discoveries": discoveries,
        "stale_route_failures": stale_failures,
        "packets_without_routing_path": route_events.packets_without_routing_path,
        "route_discovery_failures": route_events.route_discovery_failures,
        "route_recovery_after_flag": route_events.route_recovery_after_flag,
        "protocol_specific_route_flag_events": route_events.protocol_specific_route_flag_events,
        "failed_wireless_packets_after_routing": route_events.failed_wireless_packets_after_routing,
        "model_control_packets_total": model_control_packets,
        "model_control_packets_per_s": (
            model_control_packets / (pipeline.duration_s if len(pipeline.trace_node_map) == 3 else 30.0)
        ),
        "control_messages": "NA",
        "control_bytes": "NA",
    }
    return summary, audit


def validate_ns3_run(
    summary: dict[str, str],
    events: list[dict[str, str]],
    expected_packets: int,
    label: str,
) -> None:
    numeric_fields = (
        "scheduled_packets", "application_generated_packets", "socket_accepted_packets",
        "socket_rejected_packets",
        "application_unique_delivered_packets", "application_duplicate_receives",
        "invalid_packet_receives", "flowmonitor_tx_packets", "flowmonitor_rx_packets",
    )
    counts = {field: int(summary[field]) for field in numeric_fields}
    if counts["scheduled_packets"] != expected_packets:
        raise RuntimeError(f"{label}: scheduled packet count mismatch")
    if counts["application_generated_packets"] != expected_packets:
        raise RuntimeError(f"{label}: application generation count mismatch")
    if counts["socket_accepted_packets"] + counts["socket_rejected_packets"] != expected_packets:
        raise RuntimeError(f"{label}: generated packets do not reconcile to socket outcomes")
    if counts["application_unique_delivered_packets"] > expected_packets:
        raise RuntimeError(f"{label}: delivery count exceeds generation count")
    if counts["application_duplicate_receives"] or counts["invalid_packet_receives"]:
        raise RuntimeError(f"{label}: duplicate or invalid packet identities observed")
    if counts["flowmonitor_tx_packets"] != counts["socket_accepted_packets"]:
        raise RuntimeError(f"{label}: FlowMonitor Tx and socket-accepted counts differ")
    if len({event["packet_id"] for event in events}) != expected_packets:
        raise RuntimeError(f"{label}: packet IDs are missing or duplicated")


def ns3_raw_row(
    summary: dict[str, str], topology: dict[str, Any], routing: str
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "experiment": summary["experiment"],
        "simulator": "ns-3.49",
        "routing": routing,
        "channel_profile": summary["profile"],
        "coordinate_frame": summary["coordinate_frame"],
        "repetition_seed": summary["repetition_seed"],
        "traffic_seed": summary["traffic_seed"],
        "ns3_seed": summary["ns3_seed"],
        "ns3_run": summary["ns3_run"],
        "n_nodes": summary["n_nodes"],
        "mobility_frames": summary["mobility_frames"],
        "measurement_window_s": summary["measurement_s"],
        "scheduled_packets": summary["scheduled_packets"],
        "generated_packets": summary["application_generated_packets"],
        "socket_accepted_packets": summary["socket_accepted_packets"],
        "socket_rejected_packets": summary["socket_rejected_packets"],
        "flowmonitor_tx_packets": summary["flowmonitor_tx_packets"],
        "flowmonitor_rx_packets": summary["flowmonitor_rx_packets"],
        "flowmonitor_lost_packets": summary["flowmonitor_lost_packets"],
        "flowmonitor_rx_minus_application_delivered_packets": (
            int(summary["flowmonitor_rx_packets"])
            - int(summary["application_unique_delivered_packets"])
        ),
        "undelivered_after_drain_packets": summary["undelivered_after_drain_packets"],
        "delivered_packets": summary["application_unique_delivered_packets"],
        "pdr": summary["pdr"],
        "mean_latency_ms": summary["mean_application_delay_ms"],
        "mean_flowmonitor_delay_ms": summary["mean_flowmonitor_delay_ms"],
        "mean_hops": "NA",
        "forwarding_based_hops_estimate": summary["forwarding_based_hops_estimate"],
        "route_failures": "NA",
        "route_discoveries": "NA",
        "stale_route_failures": "NA",
        "packets_without_routing_path": "NA",
        "route_discovery_failures": "NA",
        "route_recovery_after_flag": "NA",
        "protocol_specific_route_flag_events": "NA",
        "failed_wireless_packets_after_routing": "NA",
        "model_control_packets_total": "NA",
        "model_control_packets_per_s": "NA",
        "control_messages": "NA",
        "control_bytes": "NA",
        "topology_frames_fully_connected": topology["fully_connected_frames"],
        "topology_mean_edges": topology["mean_edges"],
        "topology_min_edges": topology["min_edges"],
        "topology_mean_components": topology["mean_components"],
        "packets_requiring_multihop": topology["packets_requiring_multihop"],
        "packets_without_binary_path": topology["packets_without_binary_path"],
    }
    return row


def _mean_numeric(rows: list[dict[str, Any]], field: str) -> float | str:
    values = [value for row in rows if (value := number(row.get(field))) is not None]
    return statistics.mean(values) if values else "NA"


def summarize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["experiment"]), str(row["simulator"]), str(row["routing"]))].append(row)
    result = []
    for (experiment, simulator, routing), group in sorted(groups.items()):
        pdrs = [float(row["pdr"]) for row in group]
        latencies = [
            value for row in group
            if (value := number(row["mean_latency_ms"])) is not None
        ]
        flowmonitor_delays = [
            value for row in group
            if (value := number(row["mean_flowmonitor_delay_ms"])) is not None
        ]
        model_control_packets = [
            value for row in group
            if (value := number(row.get("model_control_packets_total"))) is not None
        ]
        result.append(
            {
                "experiment": experiment,
                "simulator": simulator,
                "routing": routing,
                "n_repetitions": len(group),
                "mean_pdr": statistics.mean(pdrs),
                "pdr_t95_half_width": (
                    student_t_half_width(pdrs)
                ),
                "pdr_t_critical": t_critical_95(len(pdrs) - 1) if len(pdrs) > 1 else "NA",
                "pdr_ci_method": "two-sided Student-t, df=n-1",
                "latency_n_repetitions": len(latencies),
                "mean_latency_ms": statistics.mean(latencies) if latencies else "NA",
                "latency_t95_half_width_ms": (
                    student_t_half_width(latencies)
                ),
                "latency_t_critical": t_critical_95(len(latencies) - 1) if len(latencies) > 1 else "NA",
                "latency_ci_method": "two-sided Student-t, df=n-1; per-run delivered-packet mean",
                "flowmonitor_delay_n_repetitions": len(flowmonitor_delays),
                "mean_flowmonitor_delay_ms": (
                    statistics.mean(flowmonitor_delays) if flowmonitor_delays else "NA"
                ),
                "flowmonitor_delay_t95_half_width_ms": student_t_half_width(flowmonitor_delays),
                "flowmonitor_delay_t_critical": (
                    t_critical_95(len(flowmonitor_delays) - 1)
                    if len(flowmonitor_delays) > 1 else "NA"
                ),
                "mean_model_control_packets_per_run": (
                    statistics.mean(model_control_packets) if model_control_packets else "NA"
                ),
                "model_control_packets_t95_half_width": student_t_half_width(
                    model_control_packets
                ),
                "model_control_packets_n_repetitions": len(model_control_packets),
                "mean_route_failures_per_run": _mean_numeric(group, "route_failures"),
                "mean_route_discoveries_per_run": _mean_numeric(group, "route_discoveries"),
                "mean_packets_without_routing_path_per_run": _mean_numeric(
                    group, "packets_without_routing_path"
                ),
                "mean_route_recovery_after_flag_per_run": _mean_numeric(
                    group, "route_recovery_after_flag"
                ),
                "mean_socket_accepted_per_run": _mean_numeric(
                    group, "socket_accepted_packets"
                ),
                "mean_socket_rejected_per_run": _mean_numeric(
                    group, "socket_rejected_packets"
                ),
                "mean_flowmonitor_lost_per_run": _mean_numeric(
                    group, "flowmonitor_lost_packets"
                ),
                "mean_undelivered_after_drain_per_run": _mean_numeric(
                    group, "undelivered_after_drain_packets"
                ),
                "mean_delivered_packets_per_run": statistics.mean(
                    int(row["delivered_packets"]) for row in group
                ),
            }
        )
    return result


def paired_statistics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed = {
        (str(row["experiment"]), str(row["simulator"]), str(row["routing"]),
         int(row["repetition_seed"])): row
        for row in rows
    }
    comparisons: list[tuple[str, str, str, str, str]] = []
    for experiment in ("C", "D"):
        for routing in ("aodv", "olsr"):
            comparisons.append(
                (experiment, f"ns3_minus_Python_R1_{routing}", "ns-3.49",
                 "Python_R1_abstraction", routing)
            )
        for simulator in ("ns-3.49", "Python_R1_abstraction"):
            comparisons.append(
                (experiment, f"{simulator}_aodv_minus_olsr", simulator,
                 simulator, "protocol_contrast")
            )
    output = []
    for experiment, label, left_model, right_model, routing in comparisons:
        for metric in ("pdr", "mean_latency_ms"):
            deltas = []
            for seed in REPETITION_SEEDS:
                if routing == "protocol_contrast":
                    left = keyed.get((experiment, left_model, "aodv", seed))
                    right = keyed.get((experiment, right_model, "olsr", seed))
                else:
                    left = keyed.get((experiment, left_model, routing, seed))
                    right = keyed.get((experiment, right_model, routing, seed))
                if not left or not right:
                    continue
                left_value = number(left[metric])
                right_value = number(right[metric])
                if left_value is not None and right_value is not None:
                    deltas.append(left_value - right_value)
            output.append(
                {
                    "experiment": experiment,
                    "comparison": label,
                    "metric": metric,
                    "difference_definition": "left minus right; paired by repetition_seed",
                    "n_paired_repetitions": len(deltas),
                    "mean_difference": statistics.mean(deltas) if deltas else "NA",
                    "student_t_95_ci_half_width": (
                        student_t_half_width(deltas)
                    ),
                    "degrees_of_freedom": len(deltas) - 1 if deltas else "NA",
                    "t_critical": t_critical_95(len(deltas) - 1) if len(deltas) > 1 else "NA",
                }
            )
    return output


def display(value: Any, digits: int = 4) -> str:
    numeric = number(value)
    return "NA" if numeric is None else f"{numeric:.{digits}f}"


def write_reports(
    output: Path,
    summary_rows: list[dict[str, Any]],
    paired_rows: list[dict[str, Any]],
    validation: dict[str, Any],
) -> None:
    report = [
        "# Paired ns-3.49 / R1 experiment report",
        "",
        f"**Validation:** {validation['status']} — {validation['ns3_runs_completed']} ns-3 runs, "
        f"{validation['replications_per_condition']} repetitions per condition.",
        "",
        "## Trial-level summary",
        "",
        "| Scenario | Simulator | Routing | n | Mean PDR | PDR 95% half-width | Mean latency (ms) | Latency 95% half-width | Latency n | Mean FlowMonitor delay (ms) | FlowMonitor 95% half-width |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        report.append(
            f"| {row['experiment']} | {row['simulator']} | {row['routing']} | "
            f"{row['n_repetitions']} | {display(row['mean_pdr'])} | "
            f"{display(row['pdr_t95_half_width'])} | {display(row['mean_latency_ms'])} | "
            f"{display(row['latency_t95_half_width_ms'])} | {row['latency_n_repetitions']} | "
            f"{display(row['mean_flowmonitor_delay_ms'])} | "
            f"{display(row['flowmonitor_delay_t95_half_width_ms'])} |"
        )
    report.extend(
        [
            "",
            "PDR confidence intervals use per-repetition PDR values. Latency confidence intervals use the per-repetition mean over delivered packets; unavailable latency remains `NA`. Both are two-sided Student-t intervals; the half-width is shown explicitly.",
            "",
            "## Route events and abstract control load",
            "",
            "| Scenario | Simulator | Routing | Route failures / run | Discoveries / run | No-path packets / run | Recovery flags / run | R1 model control packets / run |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary_rows:
        report.append(
            f"| {row['experiment']} | {row['simulator']} | {row['routing']} | "
            f"{display(row['mean_route_failures_per_run'])} | "
            f"{display(row['mean_route_discoveries_per_run'])} | "
            f"{display(row['mean_packets_without_routing_path_per_run'])} | "
            f"{display(row['mean_route_recovery_after_flag_per_run'])} | "
            f"{display(row['mean_model_control_packets_per_run'])} |"
        )
    report.extend(
        [
            "",
            "R1 control packet counts are internal abstraction counters, not serialized protocol messages or bytes. ns-3 control-message/byte load is `NA`.",
            "",
            "## Packet accounting",
            "",
            "| Scenario | Simulator | Routing | Socket accepted / run | Socket rejected / run | FlowMonitor assumed-lost / run | App packets undelivered after drain / run |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in summary_rows:
        report.append(
            f"| {row['experiment']} | {row['simulator']} | {row['routing']} | "
            f"{display(row['mean_socket_accepted_per_run'])} | "
            f"{display(row['mean_socket_rejected_per_run'])} | "
            f"{display(row['mean_flowmonitor_lost_per_run'])} | "
            f"{display(row['mean_undelivered_after_drain_per_run'])} |"
        )
    fm = validation["flowmonitor_application_rx_discrepancies"]
    fm_loss = validation["flowmonitor_lost_vs_tx_minus_rx"]
    report.extend(
        [
            "",
            f"FlowMonitor Rx differed from application unique-delivery counts in {fm['runs_with_nonzero_difference']} runs (signed aggregate FlowMonitor Rx minus app deliveries: {fm['sum_signed_flowmonitor_rx_minus_application_delivered']}). These are separately defined counters; application packet identity is the PDR basis.",
            f"ns-3.49 documents FlowMonitor `lostPackets` as packets assumed lost when not reported for 10 seconds; packets queued below IP at simulation end can be counted as lost and may still count toward received or dropped packets. In {fm_loss['runs_where_lost_exceeds_nonnegative_tx_minus_rx']} runs, FlowMonitor lost exceeded max(Tx minus Rx, 0) (by condition: {fm_loss['by_experiment_routing']}). Treat this as a FlowMonitor diagnostic, not as application loss or a complement of Rx. See {fm_loss['official_documentation']}.",
            "",
            "## Paired differences",
            "",
            "Differences are paired by repetition seed. Positive `ns3_minus_Python_R1` means the ns-3 metric is higher. R1 latency is model-based and ns-3 latency is packet-level; the latency difference is descriptive, not a calibrated physical comparison.",
            "",
            "| Scenario | Comparison | Metric | n paired | Mean difference | Student-t 95% half-width |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for row in paired_rows:
        report.append(
            f"| {row['experiment']} | {row['comparison']} | {row['metric']} | "
            f"{row['n_paired_repetitions']} | {display(row['mean_difference'])} | "
            f"{display(row['student_t_95_ci_half_width'])} |"
        )
    report.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- The AirSim trace uses `monotonic_time_s` for replay and is fully connected under the 35 m graph cutoff for every frame; it is not a multi-hop routing stress case.",
            "- D imports identical R1 `SyntheticMobility` coordinates into ns-3 and Python. It is not RandomWaypoint, and the 30 seeds are reproducible trajectory/traffic replays, not separate flights.",
            "- ns-3 uses standard AODV/OLSR; R1 uses AODV-like/OLSR-like abstractions. They are not identical implementations.",
            "- The 35 m hard range channel is uncalibrated. ns-3 control-message/byte overhead is `NA` because it is not instrumented; R1 control counters are abstraction-specific. A protocol-event flag or socket rejection is not automatically equivalent to a lost application packet.",
            "- See `real_airsim_replay_methodology.md`, `real_airsim_replay_validation.json`, and the packet audit for definitions, input hashes, and run-level accounting.",
            "",
        ]
    )
    (output / "real_airsim_replay_experiment_report.md").write_text(
        "\n".join(report), encoding="utf-8"
    )

    evidence = [
        "# R2.1 evidence summary",
        "",
        "## Evidence delivered",
        "",
        f"- **Independent packet-level reference:** ns-3 {validation['ns3_version']} with the standard AODV and OLSR modules; {validation['ns3_runs_completed']} completed runs across C and D.",
        f"- **Paired inputs:** 30 traffic/RNG repetitions per condition in the full run, identical packet schedules and mobility coordinate files consumed by ns-3 and the R1 abstractions.",
        "- **C:** protected real AirSim trace, 600 frames, three UAVs; monotonic replay clock; independent 35 m graph validation shows full connectivity in all frames.",
        "- **D:** 20-UAV, 30 s R1-generated mobility input, with matching traffic schedules; mobility and traffic seed files are retained.",
        "- **Measured outputs:** application PDR, packet-level ns-3 delay, FlowMonitor delay/counters, R1 abstraction delay/hops, packet identities, loss accounting, topology counts, and paired Student-t 95% confidence half-widths.",
        "",
        "## Results",
        "",
        "| Scenario | Simulator | Routing | Mean PDR | PDR 95% half-width | Mean latency (ms) | Latency 95% half-width (ms) |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        evidence.append(
            f"| {row['experiment']} | {row['simulator']} | {row['routing']} | "
            f"{display(row['mean_pdr'])} | {display(row['pdr_t95_half_width'])} | "
            f"{display(row['mean_latency_ms'])} | {display(row['latency_t95_half_width_ms'])} |"
        )
    evidence.extend(
        [
            "",
            "## Claims and limitations",
            "",
            "This evidence demonstrates an executable, reproducible comparison against an independent packet-level network simulator. It does **not** establish physical-model equivalence or calibrated radio accuracy: Python AODV-like/OLSR-like are abstractions, ns-3 AODV/OLSR are standard protocol implementations, and the 35 m cutoff is an uncalibrated topology model. Python latency is model-based; ns-3 latency is packet-level. R1 control counters are abstraction-specific; ns-3 control-message and byte overhead is `NA`. FlowMonitor `lostPackets` is timeout-based and may overlap with Rx; it is not application loss, and application packet identity defines PDR. Socket rejection causes are not inferred. The fully connected C trace is not a multi-hop routing result.",
            "",
            "Files: `real_airsim_replay_raw.csv`, `real_airsim_replay_summary.csv`, `real_airsim_replay_packet_audit.csv`, `real_airsim_replay_paired_statistics.csv`, `real_airsim_replay_topology_validation.csv`, `real_airsim_replay_validation.json`, `ns3_experiment_settings.json`, and `real_airsim_replay_experiment_report.md`.",
            "",
        ]
    )
    (output / "network_replay_evidence_summary.md").write_text(
        "\n".join(evidence), encoding="utf-8"
    )

    source_methodology = Path(__file__).with_name("real_airsim_replay_methodology.md")
    if source_methodology.exists():
        (output / source_methodology.name).write_bytes(source_methodology.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns3-root", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--r1-source", type=Path, required=True)
    parser.add_argument("--airsim-csv", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pilot-only", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()

    for required in (args.ns3_root / "ns3", args.input_root / "C" / "airsim_mobility.csv",
                     args.input_root / "D", args.r1_source / "fanet_unified_pipeline.py",
                     args.airsim_csv, args.driver):
        if not required.exists():
            raise FileNotFoundError(required)
    args.output.mkdir(parents=True, exist_ok=True)
    if sha256(args.airsim_csv) != EXPECTED_AIRSIM_SHA256:
        raise RuntimeError("protected AirSim source CSV SHA-256 does not match the recorded input")
    if args.summarize_only:
        raw_path = args.output / "real_airsim_replay_raw.csv"
        summary_path = args.output / "real_airsim_replay_summary.csv"
        paired_path = args.output / "real_airsim_replay_paired_statistics.csv"
        validation_path = args.output / "real_airsim_replay_validation.json"
        settings_path = args.output / "ns3_experiment_settings.json"
        raw_rows = read_csv(raw_path)
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        recorded_r1_hashes = settings["input_hashes"]["r1_source_sha256"]
        current_r1_hashes = {
            path.name: sha256(path) for path in sorted(args.r1_source.glob("*.py"))
        }
        if recorded_r1_hashes != current_r1_hashes:
            raise RuntimeError("R1 source hashes differ from the completed experiment manifest")
        python_audit: list[dict[str, Any]] = []
        for row in raw_rows:
            if row["simulator"] != "Python_R1_abstraction":
                continue
            experiment = row["experiment"]
            repetition_seed = int(row["repetition_seed"])
            routing_name = (
                "aodv_like_reactive" if row["routing"] == "aodv"
                else "olsr_like_proactive"
            )
            if experiment == "C":
                mobility = args.input_root / "C" / "airsim_mobility.csv"
                traffic = args.input_root / "C" / f"traffic_seed_{repetition_seed}.csv"
            else:
                mobility = args.input_root / "D" / f"mobility_seed_{repetition_seed}.csv"
                traffic = args.input_root / "D" / f"traffic_seed_{repetition_seed}.csv"
            traffic_rows = read_csv(traffic)
            traffic_seed = int(traffic_rows[0]["traffic_seed"])
            replayed, packet_events = run_r1(
                args.r1_source, mobility, traffic, routing_name,
                repetition_seed, traffic_seed,
            )
            for field in ("generated_packets", "delivered_packets"):
                if int(row[field]) != int(replayed[field]):
                    raise RuntimeError(
                        f"R1 recomputation changed {field} for {experiment}/{routing_name}/{repetition_seed}"
                    )
            for field in ("pdr", "mean_latency_ms", "mean_hops"):
                before, after = number(row.get(field)), number(replayed.get(field))
                if before is None and after is None:
                    continue
                if before is None or after is None or not math.isclose(
                    before, after, rel_tol=0.0, abs_tol=1e-9
                ):
                    raise RuntimeError(
                        f"R1 recomputation changed {field} for {experiment}/{routing_name}/{repetition_seed}"
                    )
            for field in (
                "route_failures", "route_discoveries", "stale_route_failures",
                "packets_without_routing_path", "route_discovery_failures",
                "route_recovery_after_flag", "protocol_specific_route_flag_events",
                "failed_wireless_packets_after_routing", "model_control_packets_total",
                "model_control_packets_per_s", "control_messages", "control_bytes",
            ):
                row[field] = replayed[field]
            python_audit.extend(packet_events)
        audit_path = args.output / "real_airsim_replay_packet_audit.csv"
        ns3_audit = [
            row for row in read_csv(audit_path)
            if row["simulator"] == "ns-3.49"
        ]
        for row in ns3_audit:
            row["control_packets"] = "NA"
        write_csv(audit_path, AUDIT_FIELDS, ns3_audit + python_audit)
        write_csv(raw_path, RAW_FIELDS, raw_rows)
        summary_rows = summarize_rows(raw_rows)
        paired_rows = paired_statistics(raw_rows)
        write_csv(summary_path, list(summary_rows[0].keys()), summary_rows)
        write_csv(paired_path, list(paired_rows[0].keys()), paired_rows)
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        validation["ns3_source_commit"] = NS3_OFFICIAL_TAG_COMMIT
        validation["ns3_local_source_commit"] = None
        validation["ns3_release_archive_sha256"] = NS3_ARCHIVE_SHA256
        validation["trial_rows_including_python_r1"] = len(raw_rows)
        validation["r1_metrics_recomputed_and_matched"] = True
        validation["flowmonitor_lost_vs_tx_minus_rx"] = flowmonitor_lost_diagnostic(raw_rows)
        validation["limitations"] = [
            "ns-3 and Python routing implementations are not protocol-equivalent",
            "35 m hard range gate is not a calibrated radio model",
            "Python latency is model-based and cannot be compared as packet-level latency",
            "ns-3 control-message/byte overhead is not instrumented and is NA",
            "FlowMonitor lostPackets is timeout-based and may overlap with received/dropped accounting; application packet-identity delivery defines PDR",
            "one fixed AirSim trajectory is replayed with 30 traffic/RNG replications; not 30 flights",
            "mobility is applied as discrete snapshots at packet evaluation times without interpolation",
        ]
        validation["status"] = "passed" if all(
            item["passed"] for item in validation["checks"]
        ) else "failed"
        settings["ns3_source_commit"] = NS3_OFFICIAL_TAG_COMMIT
        settings["ns3_local_source_commit"] = None
        settings["ns3_release_archive_sha256"] = NS3_ARCHIVE_SHA256
        settings["r1_model_control_counters"] = (
            "recomputed from decision.control_packets; abstract counters, not protocol wire messages/bytes"
        )
        settings["flowmonitor_accounting"] = (
            "FlowMonitor IP counters are retained separately from application-level "
            "same-packet-ID delivery. lostPackets is timeout-based, may overlap with "
            "Rx, and is not the complement of Rx; see the official ns-3.49 documentation."
        )
        settings_path.write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validation_path.write_text(
            json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        write_reports(args.output, summary_rows, paired_rows, validation)
        print(json.dumps({"status": validation["status"], "rows": len(raw_rows), "summarized_only": True}))
        return
    run_root = args.output / "per_run"
    ns3_scratch = args.ns3_root / "scratch"
    destination_driver = ns3_scratch / "ns3_fanet_reference.cc"
    if args.driver.resolve() != destination_driver.resolve():
        destination_driver.write_bytes(args.driver.read_bytes())

    ns3_version = "3.49"
    local_source_commit = None
    commit_result = subprocess.run(
        ["git", "-C", str(args.ns3_root), "rev-parse", "HEAD"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    if commit_result.returncode == 0:
        local_source_commit = commit_result.stdout.strip()
    source_commit = local_source_commit or NS3_OFFICIAL_TAG_COMMIT

    log_path = args.output / "real_ns3_run.log"
    raw_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    topology_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    run_count = 0
    deterministic_repeat_ok = False
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"ns-3 version: {ns3_version}; source commit: {source_commit or 'not recorded'}\n")
        log.write(f"ns-3 seed: {NS3_SEED}; range: {RANGE_M} m; packet bytes: {PACKET_BYTES}\n")
        build = subprocess.run(
            [str(args.ns3_root / "ns3"), "build", "-j", "2"],
            cwd=args.ns3_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, check=False,
        )
        log.write("BUILD ns-3_fanet_reference\n" + redact_home_paths(build.stdout))
        if build.returncode:
            raise RuntimeError(f"ns-3 driver build failed:\n{build.stdout[-8000:]}")

        trial_specs = []
        for experiment in ("C", "D"):
            for repetition_seed in REPETITION_SEEDS:
                if experiment == "C":
                    mobility = args.input_root / "C" / "airsim_mobility.csv"
                    traffic = args.input_root / "C" / f"traffic_seed_{repetition_seed}.csv"
                    frame = read_csv(mobility)
                    times = [float(row["time_s"]) for row in frame]
                    measurement_window = max(times) - min(times)
                    coordinate_frame = "ned"
                else:
                    mobility = args.input_root / "D" / f"mobility_seed_{repetition_seed}.csv"
                    traffic = args.input_root / "D" / f"traffic_seed_{repetition_seed}.csv"
                    measurement_window = 30.0
                    coordinate_frame = "cartesian"
                schedule = read_csv(traffic)
                traffic_seeds = {int(row["traffic_seed"]) for row in schedule}
                if len(traffic_seeds) != 1:
                    raise ValueError(f"traffic seed mismatch in {traffic}")
                traffic_seed = next(iter(traffic_seeds))
                topology, _, _ = load_topology(mobility, traffic)
                topology["repetition_seed"] = repetition_seed
                topology_by_key[(experiment, repetition_seed)] = topology
                topology_rows.append(topology)
                trial_specs.append(
                    (experiment, repetition_seed, traffic_seed, mobility, traffic,
                     coordinate_frame, measurement_window, topology, len(schedule))
                )

        if len(trial_specs) != 60:
            raise RuntimeError(f"expected 60 paired repetition schedules; got {len(trial_specs)}")
        trial_specs.sort(
            key=lambda spec: (
                spec[1] != REPETITION_SEEDS[0],
                spec[0],
                spec[1],
            )
        )
        if args.pilot_only:
            trial_specs = [
                spec for spec in trial_specs
                if spec[1] == REPETITION_SEEDS[0]
            ]
        air_topology = [row for row in topology_rows if row["experiment"] == "C"]
        if any(row["fully_connected_frames"] != 600 for row in air_topology):
            raise RuntimeError("AirSim trace failed independent full-connectivity validation")
        if any(row["packets_without_binary_path"] > row["scheduled_packets"] for row in topology_rows):
            raise RuntimeError("invalid topology path audit")

        for experiment, repetition_seed, traffic_seed, mobility, traffic, coord, window, topology, n_packets in trial_specs:
            for routing in ("aodv", "olsr"):
                per_run = run_root / f"{experiment}_{routing}_{repetition_seed}"
                summary, events = invoke_ns3(
                    args.ns3_root, per_run, experiment, routing, mobility, traffic,
                    coord, window, repetition_seed, traffic_seed,
                    REPETITION_SEEDS.index(repetition_seed) + 1, log,
                )
                validate_ns3_run(
                    summary, events, n_packets,
                    f"ns-3 {experiment}/{routing}/{repetition_seed}",
                )
                raw_rows.append(ns3_raw_row(summary, topology, routing))
                for event in events:
                    audit_rows.append(
                        {
                            "experiment": experiment, "simulator": "ns-3.49",
                            "routing": routing, "channel_profile": "range_limited_wifi",
                            "repetition_seed": repetition_seed, "traffic_seed": traffic_seed,
                            "ns3_seed": NS3_SEED,
                            "ns3_run": REPETITION_SEEDS.index(repetition_seed) + 1,
                            "packet_id": event["packet_id"],
                            "source_id": event["source_id"],
                            "destination_id": event["destination_id"],
                            "generation_time_s": event["generation_time_s"],
                            "evaluated_at_time_s": event["evaluated_at_time_s"],
                            "application_generated": event["application_generated"],
                            "delivered": event["delivered_same_id"],
                            "latency_ms": event["application_latency_ms"],
                            "hop_count": "NA",
                            "route_failure": "NA",
                            "route_discovery": "NA",
                            "stale_route": "NA",
                            "control_packets": "NA",
                            "loss_reason": event["loss_reason"],
                        }
                    )
                run_count += 1
                if run_count % 20 == 0:
                    log.write(f"PROGRESS completed_ns3_runs={run_count}\n")

            for routing in ("aodv_like_reactive", "olsr_like_proactive"):
                summary, events = run_r1(
                    args.r1_source, mobility, traffic, routing,
                    repetition_seed, traffic_seed,
                )
                summary["topology_frames_fully_connected"] = topology["fully_connected_frames"]
                summary["topology_mean_edges"] = topology["mean_edges"]
                summary["topology_min_edges"] = topology["min_edges"]
                summary["topology_mean_components"] = topology["mean_components"]
                summary["packets_requiring_multihop"] = topology["packets_requiring_multihop"]
                summary["packets_without_binary_path"] = topology["packets_without_binary_path"]
                if summary["generated_packets"] != n_packets:
                    raise RuntimeError("R1 did not process every scheduled packet")
                raw_rows.append(summary)
                audit_rows.extend(events)

            # Seed 1 runs as the pilot gate before the remaining replications.
            if experiment == "D" and repetition_seed == REPETITION_SEEDS[0]:
                base_summary_path = run_root / f"D_aodv_{repetition_seed}" / "summary.csv"
                base_event_path = run_root / f"D_aodv_{repetition_seed}" / "events.csv"
                repeat_dir = run_root / f"D_aodv_{repetition_seed}_determinism_repeat"
                repeat_summary, repeat_events = invoke_ns3(
                    args.ns3_root, repeat_dir, "D", "aodv", mobility, traffic,
                    coord, window, repetition_seed, traffic_seed, 1, log,
                )
                validate_ns3_run(repeat_summary, repeat_events, n_packets, "determinism repeat")
                deterministic_repeat_ok = (
                    base_summary_path.read_bytes() == (repeat_dir / "summary.csv").read_bytes()
                    and base_event_path.read_bytes() == (repeat_dir / "events.csv").read_bytes()
                )
                if not deterministic_repeat_ok:
                    raise RuntimeError("identical ns-3 D/AODV seed and run did not reproduce byte-identical outputs")
                log.write("DETERMINISM repeat: byte-identical D/AODV seed/run output\n")

    expected_repetitions = 1 if args.pilot_only else 30
    expected_ns3_runs = 4 * expected_repetitions
    if run_count != expected_ns3_runs:
        raise RuntimeError(
            f"expected {expected_ns3_runs} completed ns-3 runs; got {run_count}"
        )
    expected_rows = 8 * expected_repetitions
    if len(raw_rows) != expected_rows:
        raise RuntimeError(f"expected {expected_rows} trial rows including R1; got {len(raw_rows)}")
    write_csv(args.output / "real_airsim_replay_raw.csv", RAW_FIELDS, raw_rows)
    write_csv(args.output / "real_airsim_replay_packet_audit.csv", AUDIT_FIELDS, audit_rows)
    write_csv(args.output / "real_airsim_replay_topology_validation.csv", TOPOLOGY_FIELDS, topology_rows)
    summary_rows = summarize_rows(raw_rows)
    write_csv(
        args.output / "real_airsim_replay_summary.csv",
        list(summary_rows[0].keys()), summary_rows,
    )
    paired_rows = paired_statistics(raw_rows)
    write_csv(
        args.output / "real_airsim_replay_paired_statistics.csv",
        list(paired_rows[0].keys()), paired_rows,
    )

    input_hashes = {
        "airsim_csv_sha256": sha256(args.airsim_csv),
        "driver_sha256": sha256(args.driver),
        "r1_source_sha256": {
            path.name: sha256(path) for path in sorted(args.r1_source.glob("*.py"))
        },
        "input_csv_sha256": {
            str(path.relative_to(args.input_root)): sha256(path)
            for path in sorted(args.input_root.rglob("*.csv"))
        },
    }
    airsim_rows = read_csv(args.airsim_csv)
    monotonic_times = [float(row["monotonic_time_s"]) for row in airsim_rows]
    simulation_timestamps = [int(row["sim_time_stamp_ns"]) for row in airsim_rows]
    airsim_time_metadata = {
        "replay_axis": "monotonic_time_s",
        "monotonic_wall_duration_s": max(monotonic_times) - min(monotonic_times),
        "airsim_simulation_duration_s": (
            max(simulation_timestamps) - min(simulation_timestamps)
        ) / 1e9,
        "difference_s": (
            max(monotonic_times) - min(monotonic_times)
            - (max(simulation_timestamps) - min(simulation_timestamps)) / 1e9
        ),
    }
    config = {
        "ns3_version": ns3_version,
        "ns3_source_commit": source_commit,
        "ns3_local_source_commit": local_source_commit,
        "ns3_release_archive_sha256": NS3_ARCHIVE_SHA256,
        "ns3_seed": NS3_SEED,
        "ns3_runs": "run number is repetition index 1..30; common seed across paired protocols",
        "repetition_seeds": REPETITION_SEEDS,
        "traffic_seed_schedule": "stored per normalized traffic CSV; identical across simulators/protocols",
        "range_m": RANGE_M,
        "packet_bytes_including_identity_header": PACKET_BYTES,
        "warmup_s": WARMUP_S,
        "drain_s": DRAIN_S,
        "wireless_profile": {
            "model": "ns-3 RangePropagationLossModel hard gate",
            "wifi": "802.11g adhoc, channel 1, 20 MHz",
            "tx_power_dbm": 16.0,
            "fixed_rate_mbps": 6.0,
            "rx_sensitivity_dbm": -101.0,
            "frame_retry_limit": 7,
            "calibrated": False,
        },
        "r1_link_model": "binary 35 m abstraction",
        "python_model_latency": (
            "R1 analytical abstraction: 8 ms base + 4.5 ms per hop + routing "
            "penalties + seeded uniform jitter; not packet-level latency"
        ),
        "ns3_latency": "application send to first same-ID receive; measured packet-level",
        "routing": {
            "ns3": "standard ns-3.49 AODV and OLSR modules",
            "python": "R1 AODV-like reactive and OLSR-like proactive abstractions; not identical implementations",
        },
        "control_overhead": "NA for ns-3 because control packet/byte tracing is not instrumented",
        "flowmonitor_accounting": (
            "FlowMonitor IP counters are retained separately from application-level "
            "same-packet-ID delivery. lostPackets is timeout-based, may overlap with "
            "Rx, and is not the complement of Rx; see the official ns-3.49 "
            "FlowMonitor documentation."
        ),
        "student_t_ci": {
            "confidence": 0.95,
            "distribution": "two-sided Student-t",
            "critical_value_df_29": T_95_DF29,
            "interval_reported": "half-width",
        },
        "input_hashes": input_hashes,
        "airsim_time_metadata": airsim_time_metadata,
    }
    (args.output / "ns3_experiment_settings.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    run_groups: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in raw_rows:
        run_groups[(str(row["experiment"]), str(row["simulator"]), str(row["routing"]))] += 1
    checks = [
        ("all_expected_ns3_runs_completed", run_count == expected_ns3_runs),
        ("all_expected_replications_per_condition", all(count == expected_repetitions for count in run_groups.values())),
        ("air_sim_trace_fully_connected_all_frames", all(row["fully_connected_frames"] == 600 for row in air_topology)),
        ("deterministic_ns3_repeat", deterministic_repeat_ok),
        ("all_ns3_event_audits_written", len([row for row in audit_rows if row["simulator"] == "ns-3.49"]) > 0),
        ("r1_paired_results_written", len([row for row in raw_rows if row["simulator"] == "Python_R1_abstraction"]) == 4 * expected_repetitions),
        ("packet_identity_and_flowmonitor_checks_passed", True),
    ]
    flowmonitor_differences = [
        int(row["flowmonitor_rx_minus_application_delivered_packets"])
        for row in raw_rows
        if row["simulator"] == "ns-3.49"
        and number(row["flowmonitor_rx_minus_application_delivered_packets"]) not in (None, 0.0)
    ]
    validation = {
        "status": "passed" if all(value for _, value in checks) else "failed",
        "checks": [{"name": name, "passed": passed} for name, passed in checks],
        "ns3_version": ns3_version,
        "ns3_source_commit": source_commit,
        "ns3_local_source_commit": local_source_commit,
        "ns3_release_archive_sha256": NS3_ARCHIVE_SHA256,
        "ns3_runs_completed": run_count,
        "replications_per_condition": expected_repetitions,
        "trial_rows_including_python_r1": len(raw_rows),
        "packet_audit_rows": len(audit_rows),
        "flowmonitor_application_rx_discrepancies": {
            "runs_with_nonzero_difference": len(flowmonitor_differences),
            "sum_signed_flowmonitor_rx_minus_application_delivered": sum(flowmonitor_differences),
            "interpretation": (
                "FlowMonitor IP-level counters and application packet-identity delivery "
                "are distinct measures; PDR uses application unique-delivery counts."
            ),
        },
        "flowmonitor_lost_vs_tx_minus_rx": flowmonitor_lost_diagnostic(raw_rows),
        "condition_repetitions": {
            f"{experiment}/{simulator}/{routing}": count
            for (experiment, simulator, routing), count in sorted(run_groups.items())
        },
        "air_sim_topology": {
            "trace_frames": 600,
            "fully_connected_frames": min(row["fully_connected_frames"] for row in air_topology),
            "directed_traffic_requiring_multihop": sum(
                row["packets_requiring_multihop"] for row in air_topology
            ),
            "interpretation": "not a multihop routing stress test",
        },
        "limitations": [
            "ns-3 and Python routing implementations are not protocol-equivalent",
            "35 m hard range gate is not a calibrated radio model",
            "Python latency is model-based and cannot be compared as packet-level latency",
            "ns-3 control-message/byte overhead is not instrumented and is NA",
            "FlowMonitor lostPackets is timeout-based and may overlap with received/dropped accounting; application packet-identity delivery defines PDR",
            "one fixed AirSim trajectory is replayed with 30 traffic/RNG replications; not 30 flights",
            "mobility is applied as discrete snapshots at packet evaluation times without interpolation",
        ],
        "input_hashes": input_hashes,
        "airsim_time_metadata": airsim_time_metadata,
    }
    (args.output / "real_airsim_replay_validation.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not all(passed for _, passed in checks):
        raise RuntimeError("one or more final validation checks failed")
    write_reports(args.output, summary_rows, paired_rows, validation)
    print(json.dumps({"status": validation["status"], "ns3_runs": run_count, "rows": len(raw_rows)}))


if __name__ == "__main__":
    main()
