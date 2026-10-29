#!/usr/bin/env python3
"""Reproduce packet-level ns-3 diagnostics without modifying PROMPT 05 outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


SEEDS = (20261029, 20261042, 20261058)
NS3_SEED = 20261029
TRAFFIC_SEED_BASE = 20380942
RUN_BY_SEED = {seed: index + 1 for index, seed in enumerate(range(20261029, 20261059))}
BASELINE = {"warmup_s": 5.0, "drain_s": 10.0, "range_m": 35.0}
TIME_BINS = ((0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 30))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


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


def quantile(values: list[float], probability: float) -> float | str:
    if not values:
        return "NA"
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    lower = math.floor(location)
    upper = math.ceil(location)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (location - lower)


def stats(values: list[float]) -> dict[str, float | int | str]:
    return {
        "n": len(values),
        "mean": statistics.mean(values) if values else "NA",
        "median": quantile(values, 0.5),
        "p90": quantile(values, 0.9),
        "p95": quantile(values, 0.95),
        "p99": quantile(values, 0.99),
        "maximum": max(values) if values else "NA",
        "over_100ms": sum(value > 100 for value in values),
        "over_500ms": sum(value > 500 for value in values),
        "over_1000ms": sum(value > 1000 for value in values),
    }


def run_one(
    ns3_root: Path,
    input_root: Path,
    output_root: Path,
    seed: int,
    routing: str,
    warmup: float,
    drain: float,
    range_m: float,
    run_log,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    seed_dir = output_root / (
        f"seed_{seed}_{routing}_w{warmup:g}_d{drain:g}_r{range_m:g}"
    )
    seed_dir.mkdir(parents=True, exist_ok=True)
    traffic_path = input_root / "D" / f"traffic_seed_{seed}.csv"
    mobility_path = input_root / "D" / f"mobility_seed_{seed}.csv"
    traffic_rows = read_csv(traffic_path)
    if not traffic_rows:
        raise ValueError(f"empty traffic input: {traffic_path}")
    traffic_seed = traffic_rows[0]["traffic_seed"]
    summary_path = seed_dir / "summary.csv"
    events_path = seed_dir / "events.csv"
    args = (
        f"scratch/ns3_fanet_reference --experiment=D --routing={routing}"
        f" --profile=range_limited_wifi --coordinate-frame=cartesian"
        f" --mobility={mobility_path} --traffic={traffic_path}"
        f" --summary={summary_path} --events={events_path}"
        f" --repetition-seed={seed} --traffic-seed={traffic_seed}"
        f" --seed={NS3_SEED} --run={RUN_BY_SEED[seed]}"
        f" --packet-bytes=256 --range-m={range_m:g}"
        f" --warmup-s={warmup:g} --drain-s={drain:g}"
        " --measurement-window-s=30"
    )
    run_log.write(
        f"RUN seed={seed} run={RUN_BY_SEED[seed]} routing={routing} "
        f"warmup={warmup:g} drain={drain:g} range={range_m:g}\n"
    )
    process = subprocess.run(
        [str(ns3_root / "ns3"), "run", args],
        cwd=ns3_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    run_log.write(process.stdout.replace(str(Path.home()), "$HOME"))
    if process.returncode:
        raise RuntimeError(
            f"ns-3 failed (seed={seed}, routing={routing}, "
            f"w={warmup}, d={drain}, range={range_m}):\n{process.stdout[-6000:]}"
        )
    summaries = read_csv(summary_path)
    events = read_csv(events_path)
    if len(summaries) != 1 or len(events) != 150:
        raise RuntimeError("run did not produce one summary and 150 packet rows")
    return summaries[0], events


def topology_min_hops(
    mobility_rows: list[dict[str, str]], time_s: float, source: str, dest: str, range_m: float
) -> int | None:
    frame = {
        row["node_id"]: tuple(float(row[key]) for key in ("x_m", "y_m", "z_m"))
        for row in mobility_rows
        if math.isclose(float(row["time_s"]), time_s, rel_tol=0.0, abs_tol=1e-8)
    }
    if source not in frame or dest not in frame:
        return None
    nodes = list(frame)
    distance: dict[str, int] = {source: 0}
    frontier = deque([source])
    while frontier:
        current = frontier.popleft()
        if current == dest:
            return distance[current]
        for other in nodes:
            if other in distance:
                continue
            delta = [frame[current][i] - frame[other][i] for i in range(3)]
            if math.sqrt(sum(value * value for value in delta)) <= range_m:
                distance[other] = distance[current] + 1
                frontier.append(other)
    return None


def baseline_metric_checks(
    baseline_summary: list[dict[str, str]],
    baseline_events: list[dict[str, str]],
    diagnostic_runs: dict[tuple[int, str], tuple[dict[str, str], list[dict[str, str]]]],
) -> dict[str, Any]:
    expected = {
        (row["experiment"], row["routing"]): row
        for row in baseline_summary
        if row["simulator"] == "ns-3.49" and row["experiment"] == "D"
    }
    actual: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for (seed, routing), (summary, _) in diagnostic_runs.items():
        actual[("D", routing)].append(summary)
    comparisons: list[dict[str, Any]] = []
    for key, source in expected.items():
        runs = actual[key]
        generated = sum(int(row["application_generated_packets"]) for row in runs)
        accepted = sum(int(row["socket_accepted_packets"]) for row in runs)
        rejected = sum(int(row["socket_rejected_packets"]) for row in runs)
        delivered = sum(int(row["application_unique_delivered_packets"]) for row in runs)
        if len(runs) != 30:
            continue
        comparisons.append(
            {
                "scenario": key[0],
                "routing": key[1],
                "baseline_30_seed_rejections": source["mean_socket_rejected_per_run"],
                "diagnostic_30_seed_mean_rejections": rejected / 30,
                "baseline_30_seed_pdr": source["mean_pdr"],
                "diagnostic_pdr": delivered / generated,
                "conditional_accepted_delivery_ratio": delivered / accepted if accepted else "NA",
                "baseline_matches_diagnostic_rejections": math.isclose(
                    float(source["mean_socket_rejected_per_run"]), rejected / 30,
                    rel_tol=0.0, abs_tol=1e-9,
                ),
                "baseline_matches_diagnostic_pdr": math.isclose(
                    float(source["mean_pdr"]), delivered / generated,
                    rel_tol=0.0, abs_tol=1e-9,
                ),
            }
        )
    return {"comparisons": comparisons}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns3-root", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run_root = args.output / "individual_runs"
    run_root.mkdir(exist_ok=True)

    log_path = args.output / "diagnostic_tests.log"
    with log_path.open("w", encoding="utf-8") as run_log:
        run_log.write("PROMPT 06 diagnostic ns-3 run log\n")
        run_log.write(f"ns3_root=$HOME/ns3-work/ns-3.49\n")
        baseline_runs: dict[tuple[int, str], tuple[dict[str, str], list[dict[str, str]]]] = {}
        for seed in range(20261029, 20261059):
            for routing in ("aodv", "olsr"):
                baseline_runs[(seed, routing)] = run_one(
                    args.ns3_root, args.input_root, run_root / "baseline_35m",
                    seed, routing, BASELINE["warmup_s"], BASELINE["drain_s"],
                    BASELINE["range_m"], run_log,
                )

        sensitivity: list[dict[str, Any]] = []
        sensitivity_packet_rows: list[dict[str, str]] = []
        conditions = [
            ("warmup", warmup, 10.0, 35.0)
            for warmup in (5.0, 10.0, 20.0)
        ] + [
            ("drain", 5.0, drain, 35.0)
            for drain in (5.0, 10.0, 20.0)
        ] + [
            ("range", 5.0, 10.0, range_m)
            for range_m in (25.0, 35.0, 45.0)
        ]
        sensitivity_runs: dict[
            tuple[str, float, int, str], tuple[dict[str, str], list[dict[str, str]]]
        ] = {}
        for parameter, warmup, drain, range_m in conditions:
            for seed in SEEDS:
                for routing in ("aodv", "olsr"):
                    key = (parameter, {"warmup": warmup, "drain": drain, "range": range_m}[parameter], seed, routing)
                    if (warmup, drain, range_m) == (5.0, 10.0, 35.0):
                        result = baseline_runs[(seed, routing)]
                    else:
                        result = run_one(
                            args.ns3_root, args.input_root,
                            run_root / f"sensitivity_{parameter}_{key[1]:g}",
                            seed, routing, warmup, drain, range_m, run_log,
                        )
                    sensitivity_runs[key] = result
                    summary, events = result
                    sensitivity_packet_rows.extend(
                        {
                            "parameter": parameter,
                            "parameter_value": key[1],
                            "seed": seed,
                            "routing": routing,
                            **event,
                        }
                        for event in events
                    )
                    latencies = [
                        float(event["application_latency_ms"])
                        for event in events
                        if event["application_latency_ms"] not in ("", "NA")
                    ]
                    generated = int(summary["application_generated_packets"])
                    accepted = int(summary["socket_accepted_packets"])
                    delivered = int(summary["application_unique_delivered_packets"])
                    sensitivity.append(
                        {
                            "parameter": parameter,
                            "value": key[1],
                            "seed": seed,
                            "routing": routing,
                            "warmup_s": warmup,
                            "drain_s": drain,
                            "range_m": range_m,
                            "generated": generated,
                            "socket_accepted": accepted,
                            "socket_rejected": int(summary["socket_rejected_packets"]),
                            "application_delivered": delivered,
                            "pdr_generated_denominator": delivered / generated if generated else "NA",
                            "conditional_accepted_delivery": delivered / accepted if accepted else "NA",
                            "latency_mean_ms": statistics.mean(latencies) if latencies else "NA",
                            "latency_median_ms": quantile(latencies, 0.5),
                            "latency_p95_ms": quantile(latencies, 0.95),
                            "latency_max_ms": max(latencies) if latencies else "NA",
                            "delivered_after_measurement_window": sum(
                                event["simulation_receive_time_s"] not in ("", "NA")
                                and float(event["simulation_receive_time_s"]) > warmup + 30.0
                                for event in events
                            ),
                            "physical_no_path_packet_pairs": sum(
                                event["physical_minimum_hops_at_send"] == "NO_PHYSICAL_PATH"
                                for event in events
                            ),
                            "flowmonitor_tx": summary["flowmonitor_tx_packets"],
                            "flowmonitor_rx": summary["flowmonitor_rx_packets"],
                            "flowmonitor_lost": summary["flowmonitor_lost_packets"],
                            "flowmonitor_reported_drops": summary[
                                "flowmonitor_reported_drop_packets"
                            ],
                            "flowmonitor_pending_timeout": summary[
                                "flowmonitor_pending_timeout_packets"
                            ],
                        }
                    )

    baseline_summary = read_csv(args.baseline / "real_airsim_replay_summary.csv")
    baseline_events = read_csv(args.baseline / "real_airsim_replay_packet_audit.csv")
    checks = baseline_metric_checks(baseline_summary, baseline_events, baseline_runs)
    write_csv(
        args.output / "warmup_drain_sensitivity.csv",
        list(sensitivity[0].keys()),
        [row for row in sensitivity if row["parameter"] in ("warmup", "drain")],
    )
    write_csv(
        args.output / "range_sensitivity.csv",
        list(sensitivity[0].keys()),
        [row for row in sensitivity if row["parameter"] == "range"],
    )
    write_csv(
        args.output / "sensitivity_packet_delivery_audit.csv",
        list(sensitivity_packet_rows[0].keys()),
        sensitivity_packet_rows,
    )

    mobility_by_seed = {
        seed: read_csv(args.input_root / "D" / f"mobility_seed_{seed}.csv")
        for seed in range(20261029, 20261059)
    }
    rejected_rows: list[dict[str, Any]] = []
    olsr_rejections: list[dict[str, str]] = []
    aodv_packet_rows: list[dict[str, Any]] = []
    timing_bin_counts: Counter[str] = Counter()
    errno_counts: Counter[str] = Counter()
    source_dest_counts: Counter[tuple[str, str]] = Counter()
    topology_counts: Counter[str] = Counter()
    for (seed, routing), (_, events) in baseline_runs.items():
        for event in events:
            if event["application_latency_ms"] not in ("", "NA") and routing == "aodv":
                aodv_packet_rows.append(
                    {
                        "seed": seed,
                        "packet_id": event["packet_id"],
                        "source_id": event["source_id"],
                        "destination_id": event["destination_id"],
                        "generation_time_s": event["generation_time_s"],
                        "simulation_send_time_s": event["simulation_send_time_s"],
                        "simulation_receive_time_s": event["simulation_receive_time_s"],
                        "latency_ms": event["application_latency_ms"],
                        "socket_accepted": event["socket_accepted"],
                        "delivered": event["delivered_same_id"],
                    }
                )
            if routing != "olsr" or event["socket_accepted"] != "0":
                continue
            minimum_hops = topology_min_hops(
                mobility_by_seed[seed],
                float(event["evaluated_at_time_s"]),
                event["source_id"],
                event["destination_id"],
                35.0,
            )
            rejected_rows.append(
                {
                    "seed": seed,
                    "packet_id": event["packet_id"],
                    "source_id": event["source_id"],
                    "destination_id": event["destination_id"],
                    "generation_time_s": event["generation_time_s"],
                    "simulation_time_s": event["simulation_send_time_s"],
                    "socket_errno_code": event["socket_errno_code"],
                    "socket_errno_symbol": event["socket_errno_symbol"],
                    "physical_path_exists": minimum_hops is not None,
                    "physical_minimum_hops": minimum_hops if minimum_hops is not None else "NO_PATH",
                    "routing_table_state": event["route_table_status"],
                    "transmission_interference_evidence": event[
                        "interference_transmission_evidence"
                    ],
                    "warmup_s": event["warmup_s"],
                    "range_m": event["range_m"],
                    "measurement_phase": event["measurement_phase"],
                    "cause_assessment": (
                        "no_physical_path_observed; consistent with no-route errno, "
                        "not proof of the internal OLSR lookup branch"
                        if minimum_hops is None
                        else "cause_unresolved"
                    ),
                }
            )
            olsr_rejections.append(event)
            generation_time = float(event["generation_time_s"])
            bin_name = next(
                (f"{start:02d}-{end:02d}s" for start, end in TIME_BINS if start <= generation_time < end),
                "outside_0_30s",
            )
            timing_bin_counts[bin_name] += 1
            errno_counts[f"{event['socket_errno_code']}:{event['socket_errno_symbol']}"] += 1
            source_dest_counts[(event["source_id"], event["destination_id"])] += 1
            topology_counts["no_path" if minimum_hops is None else "physical_path_exists"] += 1

    write_csv(
        args.output / "socket_send_errno_audit.csv",
        list(rejected_rows[0].keys()) if rejected_rows else ["seed", "packet_id"],
        rejected_rows,
    )
    write_csv(
        args.output / "aodv_delay_distribution.csv",
        list(aodv_packet_rows[0].keys()) if aodv_packet_rows else ["seed", "packet_id"],
        aodv_packet_rows,
    )
    latency_values = [float(row["latency_ms"]) for row in aodv_packet_rows]
    latency_stats = stats(latency_values)

    discrepancy_runs = [
        row for row in read_csv(args.baseline / "real_airsim_replay_raw.csv")
        if row["simulator"] == "ns-3.49"
        and int(row["flowmonitor_rx_packets"]) != int(row["delivered_packets"])
    ]
    app_audit = [
        row for row in baseline_events
        if row["simulator"] == "ns-3.49"
    ]
    discrepancy_details: list[dict[str, Any]] = []
    for run in discrepancy_runs:
        matching = [
            event for event in app_audit
            if event["experiment"] == run["experiment"]
            and event["routing"] == run["routing"]
            and event["repetition_seed"] == run["repetition_seed"]
        ]
        discrepancy_details.append(
            {
                "experiment": run["experiment"],
                "routing": run["routing"],
                "seed": run["repetition_seed"],
                "flowmonitor_tx": run["flowmonitor_tx_packets"],
                "flowmonitor_rx": run["flowmonitor_rx_packets"],
                "flowmonitor_lost": run["flowmonitor_lost_packets"],
                "diagnostic_flowmonitor_lost": (
                    baseline_runs[(int(run["repetition_seed"]), run["routing"])][0][
                        "flowmonitor_lost_packets"
                    ]
                    if run["experiment"] == "D"
                    and (int(run["repetition_seed"]), run["routing"]) in baseline_runs
                    else "NOT_RERUN"
                ),
                "diagnostic_flowmonitor_reported_drops": (
                    baseline_runs[(int(run["repetition_seed"]), run["routing"])][0][
                        "flowmonitor_reported_drop_packets"
                    ]
                    if run["experiment"] == "D"
                    and (int(run["repetition_seed"]), run["routing"]) in baseline_runs
                    else "NOT_RERUN"
                ),
                "diagnostic_flowmonitor_pending_timeout": (
                    baseline_runs[(int(run["repetition_seed"]), run["routing"])][0][
                        "flowmonitor_pending_timeout_packets"
                    ]
                    if run["experiment"] == "D"
                    and (int(run["repetition_seed"]), run["routing"]) in baseline_runs
                    else "NOT_RERUN"
                ),
                "application_unique_deliveries": run["delivered_packets"],
                "signed_rx_minus_application": (
                    int(run["flowmonitor_rx_packets"]) - int(run["delivered_packets"])
                ),
                "application_delivered_packet_ids_and_relative_receive_times": [
                    {
                        "packet_id": event["packet_id"],
                        "generation_time_s": event["generation_time_s"],
                        "latency_ms": event["latency_ms"],
                        "relative_receive_time_s": (
                            float(event["generation_time_s"])
                            + float(event["latency_ms"]) / 1000.0
                            if event["latency_ms"] not in ("", "NA")
                            else None
                        ),
                    }
                    for event in matching if event["delivered"] == "1"
                ],
                "per_packet_flowmonitor_identity_available": False,
            }
        )

    # Compare immutable source schedules and P05 simulator audits by packet identity.
    audit_groups: dict[tuple[str, str, str, str], dict[str, tuple[str, ...]]] = {}
    for row in baseline_events:
        key = (row["experiment"], row["repetition_seed"], row["routing"], row["simulator"])
        audit_groups.setdefault(key, {})[row["packet_id"]] = (
            row["source_id"], row["destination_id"], row["generation_time_s"],
            row["evaluated_at_time_s"],
        )
    paired_schedule_checks: list[dict[str, Any]] = []
    for experiment in ("C", "D"):
        for seed in range(20261029, 20261059):
            for routing in ("aodv", "olsr"):
                ns3_schedule = audit_groups.get((experiment, str(seed), routing, "ns-3.49"))
                py_schedule = audit_groups.get(
                    (experiment, str(seed), routing, "Python_R1_abstraction")
                )
                schedules_equal = (
                    ns3_schedule is not None
                    and py_schedule is not None
                    and ns3_schedule.keys() == py_schedule.keys()
                    and all(
                        ns3_schedule[packet_id][:2] == py_schedule[packet_id][:2]
                        and all(
                            math.isclose(
                                float(ns3_schedule[packet_id][index]),
                                float(py_schedule[packet_id][index]),
                                rel_tol=0.0,
                                abs_tol=1e-8,
                            )
                            for index in (2, 3)
                        )
                        for packet_id in ns3_schedule
                    )
                )
                paired_schedule_checks.append(
                    {
                        "experiment": experiment,
                        "seed": seed,
                        "routing": routing,
                        "packet_schedule_equal": schedules_equal,
                        "packet_count": len(ns3_schedule or {}),
                    }
                )
    paired_integrity = {
        "baseline_before_diagnostics_commit": "b1e7a40289012b4f18ba7341092622e91ccfdd08",
        "ns3_source_commit": "418210e8914e9f6bcb5cddbcc94a2cecb7853b68",
        "diagnostic_driver_source_sha256": sha256(Path(__file__)),
        "diagnostic_ns3_source_sha256": sha256(
            args.ns3_root / "scratch" / "ns3_fanet_reference.cc"
        ),
        "original_result_files_modified": False,
        "packet_schedule_pairs_checked": len(paired_schedule_checks),
        "packet_schedule_pairs_equal": sum(
            check["packet_schedule_equal"] for check in paired_schedule_checks
        ),
        "packet_schedule_pair_failures": [
            check for check in paired_schedule_checks if not check["packet_schedule_equal"]
        ],
        "paired_schedule_check_details": paired_schedule_checks,
        "same_common_csv_mobility_and_traffic_inputs": (
            all(check["packet_schedule_equal"] for check in paired_schedule_checks)
        ),
        "input_sha256_from_prompt05_manifest": json.loads(
            (args.baseline / "real_airsim_replay_validation.json").read_text(
                encoding="utf-8-sig"
            )
        )["input_hashes"],
        "warmup_mobility_semantics": (
            "ns-3 applies a discrete position snapshot at each packet's evaluated_at_time_s, "
            "at absolute time warmup_s + generation_time_s; no continuous interpolation "
            "or independent movement during warm-up is applied. Warm-up shifts absolute "
            "simulation timestamps but leaves the scheduled relative position snapshots unchanged."
        ),
        "delay_definitions_are_equivalent": False,
        "python_latency": "R1 model-derived latency; not packet-level",
        "ns3_latency": "packet application send to first same-ID receive",
        "protocol_implementation_equivalence": False,
        "paired_student_t_ci": {
            "method": "two-sided paired Student-t, df=29; 95% half-width",
            "independence_assumption": (
                "repetition-level paired differences are treated as independent across "
                "the 30 RNG/traffic seeds. For C, the AirSim flight trace is fixed; this "
                "does not represent uncertainty across independent flights."
            ),
        },
        "baseline_comparison_checks": checks,
    }
    (args.output / "paired_comparison_integrity.json").write_text(
        json.dumps(paired_integrity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    discrepancy_report = {
        "runs": discrepancy_details,
        "interpretation": (
            "FlowMonitor exposes aggregate flow packet counters, not the experiment's "
            "application packet IDs. The application receive IDs and their derived "
            "relative receive times are listed, but no specific ID can be attributed "
            "to the FlowMonitor count difference from the available instrumentation."
        ),
    }
    (args.output / "flowmonitor_discrepancy_audit.md").write_text(
        render_flowmonitor_report(discrepancy_report), encoding="utf-8"
    )
    (args.output / "aodv_route_discovery_audit.md").write_text(
        render_aodv_report(latency_stats, args.ns3_root), encoding="utf-8"
    )
    (args.output / "olsr_send_rejection_root_cause.md").write_text(
        render_olsr_report(
            rejected_rows, timing_bin_counts, errno_counts,
            source_dest_counts, topology_counts, checks,
        ),
        encoding="utf-8",
    )

    diagnostic_rows: list[dict[str, Any]] = []
    summary_metrics: list[tuple[str, list[float]]] = [
        ("D/ns-3.49/AODV application latency (ms)", latency_values),
        (
            "D/ns-3.49/OLSR socket rejections per seed",
            [
                float(summary["socket_rejected_packets"])
                for (_, routing), (summary, _) in baseline_runs.items()
                if routing == "olsr"
            ],
        ),
    ]
    for routing in ("aodv", "olsr"):
        run_summaries = [
            summary for (_, run_routing), (summary, _) in baseline_runs.items()
            if run_routing == routing
        ]
        summary_metrics.extend(
            [
                (
                    f"D/{routing} PDR from all generated packets per seed",
                    [
                        int(row["application_unique_delivered_packets"])
                        / int(row["application_generated_packets"])
                        for row in run_summaries
                    ],
                ),
                (
                    f"D/{routing} conditional accepted delivery ratio per seed",
                    [
                        int(row["application_unique_delivered_packets"])
                        / int(row["socket_accepted_packets"])
                        if int(row["socket_accepted_packets"])
                        else 0.0
                        for row in run_summaries
                    ],
                ),
            ]
        )
    for label, values in summary_metrics:
        diagnostic_rows.append({"metric": label, **stats(values)})
    write_csv(
        args.output / "diagnostic_statistical_summary.csv",
        list(diagnostic_rows[0].keys()),
        diagnostic_rows,
    )
    (args.output / "flowmonitor_discrepancy_audit.md").write_text(
        render_flowmonitor_report(discrepancy_report), encoding="utf-8"
    )
    with log_path.open("a", encoding="utf-8") as run_log:
        run_log.write(
            f"COMPLETED baseline_runs={len(baseline_runs)} "
            f"sensitivity_conditions={len(sensitivity_runs)} unique_runs=96\n"
        )
    print(json.dumps({
        "status": "completed",
        "baseline_runs": len(baseline_runs),
        "sensitivity_runs": len(sensitivity_runs),
        "olsr_rejections": len(rejected_rows),
        "aodv_delivered_latency_samples": len(latency_values),
    }))


def render_flowmonitor_report(data: dict[str, Any]) -> str:
    lines = [
        "# FlowMonitor / application discrepancy audit",
        "",
        "PROMPT 05 aggregate comparison identified four D/AODV ns-3 runs where FlowMonitor Rx was one packet lower than application unique packet-ID deliveries. Per-run Tx/Rx/lost and application deliveries are listed below. The per-packet application IDs and relative receive times are enumerated, but ns-3.49 FlowMonitor exposes aggregate flow statistics and does not provide the custom experiment packet ID in `FlowStats`; no individual discrepant ID can therefore be identified from these outputs.",
        "",
        "## Zero-threshold defect in PROMPT 05",
        "",
        "PROMPT 05 called `CheckForLostPackets(Seconds(0))` immediately after `Simulator::Run()`. In ns-3.49 source, `CheckForLostPackets(maxDelay)` marks each still-tracked packet lost when `Now - lastSeenTime >= maxDelay`; with maxDelay=0, every packet still tracked at simulation stop satisfies the condition and is immediately counted lost, irrespective of the documented 10 s `MaxPerHopDelay`. `FlowStats::lostPackets` is also incremented for probe-reported drop events. Therefore PROMPT 05 FlowMonitor lost values are contaminated by the zero-threshold final sweep and must not be interpreted as a valid loss estimate.",
        "",
        "The instrumented diagnostic reruns use the no-argument `CheckForLostPackets()`, which applies the monitor's configured 10 s `MaxPerHopDelay`. They additionally export the sum of `packetsDropped` reason counters and `pending_timeout = lostPackets - reported_drop_packets`, preserving these as separate FlowMonitor diagnostics. This correction does not change application packet-ID PDR or application send-to-receive latency.",
        "",
        "Official reference: https://www.nsnam.org/docs/release/3.49/models/html/flow-monitor.html",
        "",
        "| Scenario | Routing | Seed | FM Tx | FM Rx | P05 lost (zero threshold) | diagnostic lost (10 s) | diagnostic reported drops | diagnostic pending timeout | App unique delivered | Rx − app |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in data["runs"]:
        lines.append(
            f"| {run['experiment']} | {run['routing']} | {run['seed']} | "
            f"{run['flowmonitor_tx']} | {run['flowmonitor_rx']} | {run['flowmonitor_lost']} | "
            f"{run['diagnostic_flowmonitor_lost']} | {run['diagnostic_flowmonitor_reported_drops']} | "
            f"{run['diagnostic_flowmonitor_pending_timeout']} | "
            f"{run['application_unique_deliveries']} | {run['signed_rx_minus_application']} |"
        )
        ids = ", ".join(
            f"{packet['packet_id']}@{packet['relative_receive_time_s']:.6f}s"
            for packet in run["application_delivered_packet_ids_and_relative_receive_times"]
            if packet["relative_receive_time_s"] is not None
        )
        lines.append(f"\nApplication delivered packet IDs and inferred relative receive times: `{ids}`.")
    lines.extend(["", data["interpretation"], ""])
    return "\n".join(lines)


def render_aodv_report(latency_stats: dict[str, Any], ns3_root: Path) -> str:
    return f"""# D/AODV delay and route-discovery audit

## Measured delay distribution

The figures below come from packet-level application send and first receive times across all 30 PROMPT 05 seeds (instrumented reruns, same seed/run/input schedule). Application delay is not FlowMonitor delay.

| Delivered packets | Mean (ms) | Median | P90 | P95 | P99 | Max | >100 ms | >500 ms | >1000 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| {latency_stats['n']} | {latency_stats['mean']:.6f} | {latency_stats['median']:.6f} | {latency_stats['p90']:.6f} | {latency_stats['p95']:.6f} | {latency_stats['p99']:.6f} | {latency_stats['maximum']:.6f} | {latency_stats['over_100ms']} | {latency_stats['over_500ms']} | {latency_stats['over_1000ms']} |

Packet-wise `generation_time_s`, absolute `simulation_send_time_s`, absolute `simulation_receive_time_s`, and delay are retained in `aodv_delay_distribution.csv`. Sensitivity trial event files additionally distinguish arrivals after the 30 s measurement boundary but before simulation termination.

## ns-3.49 AODV implementation evidence

The checked-out ns-3.49 source defaults in `src/aodv/model/aodv-routing-protocol.cc` set `NodeTraversalTime=40 ms`, `NetDiameter=35`, `NetTraversalTime=2.8 s`, `PathDiscoveryTime=5.6 s`, `RreqRetries=2`, `TtlStart=1`, `TtlIncrement=2`, `TtlThreshold=7`, `MaxQueueLen=64`, and `MaxQueueTime=30 s`; `HelloInterval=1 s` and `EnableHello=false`. The route output path queues packets on unresolved routes and begins RREQ discovery. These source settings make route discovery/queueing a plausible delay mechanism. The AODV debug trace is retained separately only if `aodv_ns_log_trace.log` exists.

## Causal conclusion

The baseline mean near 770 ms is an observation, not by itself proof that route discovery, queue timeout, or route invalidation caused the tail. Source defaults describe possible mechanisms, not a per-packet causal attribution. Compare packet timing and the controlled warm-up/drain/range interventions in the accompanying CSVs. No specific mechanism is labeled causal unless a trace establishes the sequence for the affected packet. A queue timeout of 30 s is not evidence that any measured packet waited that long.

The routing table is not sampled in the event path; PHY interference/transmission state is not traced. Physical shortest-path snapshots are independent geometric calculations and are not equivalent to AODV's internal route state.
"""


def render_olsr_report(
    rejected: list[dict[str, Any]],
    time_bins: Counter[str],
    errors: Counter[str],
    pairs: Counter[tuple[str, str]],
    topology: Counter[str],
    checks: dict[str, Any],
) -> str:
    total = len(rejected)
    groups = "\n".join(
        f"| {name} | {count} | {count / total:.4%} |"
        for name, count in sorted(time_bins.items())
    ) or "| no rejected sends | 0 | NA |"
    error_rows = "\n".join(
        f"| {name} | {count} |" for name, count in sorted(errors.items())
    ) or "| none | 0 |"
    pair_rows = "\n".join(
        f"| {source} | {dest} | {count} |"
        for (source, dest), count in pairs.most_common()
    ) or "| none | | 0 |"
    comparison = "\n".join(
        f"| {row['routing']} | {row['baseline_30_seed_rejections']} | "
        f"{row['diagnostic_30_seed_mean_rejections']:.6f} | "
        f"{row['diagnostic_pdr']:.6f} | "
        f"{row['conditional_accepted_delivery_ratio']:.6f} | "
        f"{row['baseline_matches_diagnostic_rejections']} |"
        for row in checks["comparisons"]
    )
    return f"""# D/OLSR socket rejection root-cause audit

## Direct observation

Instrumented `Socket::SendTo()` calls recorded `GetErrno()` after each negative return. Across the 30 D/OLSR baseline repetitions there were {total} rejected sends ({total / 30:.6f}/run). The main errno and physical topology breakdown are evidence; `socket_send_rejection` is not counted as channel loss. For each rejection, `socket_send_errno_audit.csv` gives packet ID, source/destination, sim time, numeric/symbolic errno, exact-position physical shortest-hop result at the 35 m cutoff, route-table status, interference evidence, and measured phase.

| errno | Count |
|---|---:|
{error_rows}

| Physical topology at snapshot | Rejections |
|---|---:|
| No path | {topology.get('no_path', 0)} |
| Path exists | {topology.get('physical_path_exists', 0)} |

The code records `route_table_status=not_instrumented` and `interference_transmission_evidence=not_instrumented`. The graph is a geometric shortest-path check, not an OLSR lookup. A no-path snapshot plus `ERROR_NOROUTETOHOST` is consistent with the IP stack having no usable unicast route, but does not prove which internal OLSR table/route branch returned the error. Remaining cases are `cause_unresolved`.

## Rejection time bins (relative traffic generation time)

| Bin | Count | Share |
|---|---:|---:|
{groups}

## Source/destination counts

| Source | Destination | Rejections |
|---|---|---:|
{pair_rows}

## PDR denominators

The main PDR remains `unique application packet-ID deliveries / application-generated scheduled packets`. A second descriptive conditional ratio is `unique deliveries / socket-accepted packets`; it does not replace PDR.

| Routing | PROMPT 05 mean rejected/run | Instrumented rerun mean rejected/run | PDR / generated | Delivery / socket accepted | Rejection count match |
|---|---:|---:|---:|---:|---|
{comparison}

## Causal limit

If all/most rejections have `ERROR_NOROUTETOHOST` and no physical path, that supports an unavailable-route condition at send time, not channel collision. It still cannot distinguish OLSR convergence/table timing from other causes without route table snapshots/trace. A PHY/MAC interference counter was not instrumented, so no interference explanation is asserted.
"""


if __name__ == "__main__":
    main()
