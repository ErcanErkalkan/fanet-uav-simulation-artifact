#!/usr/bin/env python3
"""Prepare and validate common mobility/traffic inputs for ns-3 C and D."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_AIRSIM_SHA256 = "9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3"
AIRSIM_SCENARIO = "airsim_5hz_original_binary_aodv_like_reactive"
REPETITION_SEEDS = list(range(20261029, 20261059))
TRAFFIC_SEEDS = list(range(20380942, 20380972))
MOBILITY_FIELDS = [
    "time_s",
    "sequence",
    "node_id",
    "x_m",
    "y_m",
    "z_m",
    "vx_mps",
    "vy_mps",
    "vz_mps",
    "sim_time_stamp_ns",
    "source",
]
SCHEDULE_FIELDS = [
    "packet_id",
    "generation_time_s",
    "evaluated_at_time_s",
    "source_id",
    "destination_id",
    "trace_sequence",
    "traffic_seed",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header")
        return list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def finite(row: dict[str, Any], key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {key}: {row.get(key)!r}") from error
    if not math.isfinite(value):
        raise ValueError(f"non-finite {key}: {row.get(key)!r}")
    return value


def validate_air_rows(rows: list[dict[str, str]]) -> tuple[list[int], dict[int, list[dict[str, str]]]]:
    required = {
        "monotonic_time_s",
        "sequence",
        "node_id",
        "x_m",
        "y_m",
        "z_m",
        "source",
        "sim_time_stamp_ns",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"AirSim input missing columns: {sorted(required - set(rows[0] if rows else []))}")
    frames: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        sequence = int(row["sequence"])
        if sequence < 0:
            raise ValueError("negative AirSim sequence")
        if row["source"] != "airsim":
            raise ValueError("source is not airsim")
        for key in ("monotonic_time_s", "x_m", "y_m", "z_m"):
            finite(row, key)
        int(row["sim_time_stamp_ns"])
        frames[sequence].append(row)
    sequence_ids = sorted(frames)
    if sequence_ids != list(range(len(sequence_ids))):
        raise ValueError("AirSim sequence has gaps or duplicates")
    expected_nodes = {"Drone1", "Drone2", "Drone3"}
    previous_time = -math.inf
    previous_sim: dict[str, int] = {}
    for sequence in sequence_ids:
        current = frames[sequence]
        names = [row["node_id"] for row in current]
        if len(current) != 3 or set(names) != expected_nodes or len(set(names)) != 3:
            raise ValueError(f"AirSim frame {sequence} does not contain exactly three unique drones")
        times = [finite(row, "monotonic_time_s") for row in current]
        if max(times) - min(times) > 1e-6:
            raise ValueError(f"AirSim frame {sequence} has inconsistent monotonic times")
        time_value = times[0]
        if time_value <= previous_time:
            raise ValueError("AirSim monotonic time is not strictly increasing")
        for row in current:
            stamp = int(row["sim_time_stamp_ns"])
            name = row["node_id"]
            if stamp <= previous_sim.get(name, 0):
                raise ValueError(f"AirSim simulation timestamp is not increasing for {name}")
            previous_sim[name] = stamp
        previous_time = time_value
    return sequence_ids, frames


def validate_schedule(
    rows: list[dict[str, Any]], node_names: set[str]
) -> None:
    if not rows:
        raise ValueError("traffic schedule is empty")
    ids: set[int] = set()
    previous_generation = -math.inf
    previous_eval = -math.inf
    for row in rows:
        packet_id = int(row["packet_id"])
        if packet_id in ids:
            raise ValueError(f"duplicate packet identity: {packet_id}")
        ids.add(packet_id)
        generation = finite(row, "generation_time_s")
        eval_time = finite(row, "evaluated_at_time_s")
        if generation < 0 or generation <= previous_generation:
            raise ValueError("generation timestamps are not increasing")
        if eval_time < previous_eval:
            raise ValueError("mobility evaluation timestamps are not monotonic")
        if row["source_id"] not in node_names or row["destination_id"] not in node_names:
            raise ValueError("traffic endpoint is missing from mobility source")
        if row["source_id"] == row["destination_id"]:
            raise ValueError("traffic schedule has a self-directed packet")
        previous_generation = generation
        previous_eval = eval_time


def calculate_pdr(generated: int, received: int) -> tuple[float, str | None]:
    if generated < 0 or received < 0:
        raise ValueError("packet counts cannot be negative")
    if received > generated:
        raise ValueError("delivered packet count exceeds generated count")
    return (received / generated if generated else 0.0, None)


def distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def make_r1_synthetic_frames(r1_source: Path, seed: int) -> list[dict[str, Any]]:
    sys.path.insert(0, str(r1_source))
    from fanet_unified_pipeline import SyntheticMobility

    mobility = SyntheticMobility(
        num_uavs=20,
        seed=seed,
        area_xy=120.0,
        altitude_bounds=(5.0, 50.0),
        speed_range=(1.0, 2.4),
    )
    exported: list[dict[str, Any]] = []
    for sequence, frame in enumerate(mobility.frames(duration_s=30.0, dt_s=1.0)):
        for node in frame.nodes:
            exported.append(
                {
                    "time_s": frame.time_s,
                    "sequence": sequence,
                    "node_id": str(node.node_id),
                    "x_m": node.position[0],
                    "y_m": node.position[1],
                    "z_m": node.position[2],
                    "vx_mps": node.velocity[0],
                    "vy_mps": node.velocity[1],
                    "vz_mps": node.velocity[2],
                    "sim_time_stamp_ns": "",
                    "source": "r1_synthetic",
                }
            )
    return exported


def make_synthetic_schedule(
    repetition_seed: int, traffic_seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(traffic_seed)
    rows = []
    for packet_id in range(150):
        generated = packet_id / 5.0
        evaluated_sequence = min(29, max(0, math.ceil(generated - 1e-9)))
        source, destination = rng.sample(range(20), 2)
        rows.append(
            {
                "packet_id": packet_id,
                "generation_time_s": f"{generated:.9f}",
                "evaluated_at_time_s": f"{float(evaluated_sequence):.9f}",
                "source_id": str(source),
                "destination_id": str(destination),
                "trace_sequence": evaluated_sequence,
                "traffic_seed": traffic_seed,
            }
        )
    validate_schedule(rows, {str(index) for index in range(20)})
    if repetition_seed < 0:
        raise ValueError("repetition seed must be nonnegative")
    return rows


def _check(test_rows: list[dict[str, Any]], name: str, action, details: str) -> None:
    try:
        action()
    except Exception as error:  # noqa: BLE001 - test harness records the expected failure.
        if details == "must reject":
            test_rows.append({"test_name": name, "result": "passed", "details": str(error)})
            return
        test_rows.append({"test_name": name, "result": "failed", "details": str(error)})
        return
    if details == "must reject":
        test_rows.append({"test_name": name, "result": "failed", "details": "invalid input was accepted"})
    else:
        test_rows.append({"test_name": name, "result": "passed", "details": details})


def run_input_tests(
    air_rows: list[dict[str, str]],
    air_frames: dict[int, list[dict[str, str]]],
    selected_schedule: list[dict[str, Any]],
    seed: int,
    r1_source: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    invalid_row = [dict(air_rows[0])]
    invalid_row[0]["x_m"] = "NaN"
    _check(results, "reject_invalid_csv_coordinate", lambda: validate_air_rows(invalid_row), "must reject")

    nonmonotonic = [dict(row) for row in air_rows]
    target_sequence = 1
    for row in nonmonotonic:
        if int(row["sequence"]) == target_sequence:
            row["monotonic_time_s"] = air_frames[0][0]["monotonic_time_s"]
    _check(results, "reject_nonmonotonic_time", lambda: validate_air_rows(nonmonotonic), "must reject")

    frame = air_frames[0]
    by_name = {row["node_id"]: row for row in frame}
    pairs = [("Drone1", "Drone2"), ("Drone1", "Drone3"), ("Drone2", "Drone3")]
    for left, right in pairs:
        a = tuple(float(by_name[left][axis]) for axis in ("x_m", "y_m", "z_m"))
        b = tuple(float(by_name[right][axis]) for axis in ("x_m", "y_m", "z_m"))
        cart_a = (a[0], a[1], -a[2])
        cart_b = (b[0], b[1], -b[2])
        if abs(distance(a, b) - distance(cart_a, cart_b)) > 1e-12:
            raise AssertionError("NED z-sign change did not preserve pair distance")
    _check(results, "ned_conversion_preserves_distances", lambda: None, "all three frame-0 pair distances preserved")

    duplicate_schedule = [dict(row) for row in selected_schedule[:2]]
    duplicate_schedule[1]["packet_id"] = duplicate_schedule[0]["packet_id"]
    _check(
        results,
        "reject_duplicate_packet_id",
        lambda: validate_schedule(duplicate_schedule, {"Drone1", "Drone2", "Drone3"}),
        "must reject",
    )
    missing_endpoint = [dict(row) for row in selected_schedule[:1]]
    missing_endpoint[0]["destination_id"] = "MissingDrone"
    _check(
        results,
        "reject_missing_packet_endpoint",
        lambda: validate_schedule(missing_endpoint, {"Drone1", "Drone2", "Drone3"}),
        "must reject",
    )

    one_event = [dict(row) for row in selected_schedule[:1]]
    validate_schedule(one_event, {"Drone1", "Drone2", "Drone3"})
    if one_event[0]["source_id"] == one_event[0]["destination_id"]:
        raise AssertionError("schedule did not resolve distinct source/target")
    _check(results, "map_schedule_to_node_ids", lambda: None, "packet ID and endpoints resolved")

    pdr, latency = calculate_pdr(5, 0)
    if pdr != 0.0 or latency is not None:
        raise AssertionError("zero-delivery metric contract failed")
    _check(results, "zero_delivery_metrics", lambda: None, "PDR=0; latency=NA")
    _check(
        results,
        "reject_deliveries_above_generated",
        lambda: calculate_pdr(2, 3),
        "must reject",
    )

    first = make_r1_synthetic_frames(r1_source, seed)
    second = make_r1_synthetic_frames(r1_source, seed)
    if first != second:
        raise AssertionError("same R1 seed did not reproduce coordinates")
    _check(results, "same_seed_mobility_is_deterministic", lambda: None, "all exported coordinates match")

    line_positions = [(0.0, 0.0, 0.0), (40.0, 0.0, 0.0), (80.0, 0.0, 0.0)]
    if distance(line_positions[0], line_positions[2]) <= 50.0:
        raise AssertionError("two-hop geometry unexpectedly has a direct edge")
    if any(distance(line_positions[i], line_positions[i + 1]) > 50.0 for i in range(2)):
        raise AssertionError("two-hop geometry has a missing adjacent edge")
    _check(results, "two_hop_reference_geometry", lambda: None, "80m source-target; 40m adjacent links; 50m gate")

    sample = air_frames[10]
    source_by_name = {row["node_id"]: row for row in sample}
    max_error = 0.0
    for name in ("Drone1", "Drone2", "Drone3"):
        source = source_by_name[name]
        converted = (float(source["x_m"]), float(source["y_m"]), -float(source["z_m"]))
        recovered = (converted[0], converted[1], -converted[2])
        max_error = max(
            max_error,
            *(abs(float(source[axis]) - recovered[index]) for index, axis in enumerate(("x_m", "y_m", "z_m"))),
        )
    if max_error > 1e-12:
        raise AssertionError("source and ns-3 coordinates differ after frame conversion")
    _check(results, "source_ns3_coordinates_match_at_sample", lambda: None, "frame 10 exact after NED-to-Cartesian conversion")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--airsim", type=Path, required=True)
    parser.add_argument("--traffic", type=Path, required=True)
    parser.add_argument("--r1-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    air_hash = hashlib.sha256(args.airsim.read_bytes()).hexdigest().upper()
    if air_hash != EXPECTED_AIRSIM_SHA256:
        raise RuntimeError(f"Protected AirSim CSV hash mismatch: {air_hash}")
    air_rows = read_csv(args.airsim)
    sequences, air_frames = validate_air_rows(air_rows)
    if len(sequences) != 600 or len(air_rows) != 1800:
        raise RuntimeError(f"Expected 600 AirSim frames and 1800 node rows, got {len(sequences)}/{len(air_rows)}")

    source_schedule = read_csv(args.traffic)
    air_schedule_rows = [
        row for row in source_schedule if row["scenario"] == AIRSIM_SCENARIO
    ]
    if len(air_schedule_rows) != 30 * 599:
        raise RuntimeError(f"Expected 30 x 599 AirSim 5 Hz packets; got {len(air_schedule_rows)}")
    first_time = finite(air_frames[0][0], "monotonic_time_s")
    air_mobility: list[dict[str, Any]] = []
    for sequence in sequences:
        frame_rows = sorted(air_frames[sequence], key=lambda row: row["node_id"])
        for source in frame_rows:
            air_mobility.append(
                {
                    "time_s": f"{finite(source, 'monotonic_time_s') - first_time:.9f}",
                    "sequence": sequence,
                    "node_id": source["node_id"],
                    "x_m": source["x_m"],
                    "y_m": source["y_m"],
                    "z_m": source["z_m"],
                    "vx_mps": source["vx_mps"],
                    "vy_mps": source["vy_mps"],
                    "vz_mps": source["vz_mps"],
                    "sim_time_stamp_ns": source["sim_time_stamp_ns"],
                    "source": "airsim",
                }
            )
    write_csv(args.output / "inputs" / "C" / "airsim_mobility.csv", MOBILITY_FIELDS, air_mobility)

    seed_rows: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in air_schedule_rows:
        seed_rows[int(row["repetition_seed"])].append(row)
    if sorted(seed_rows) != REPETITION_SEEDS:
        raise RuntimeError(f"Unexpected AirSim repetition seeds: {sorted(seed_rows)}")

    normalized_air_schedules: dict[int, list[dict[str, Any]]] = {}
    source_names = {"Drone1", "Drone2", "Drone3"}
    for repetition_seed, rows in sorted(seed_rows.items()):
        traffic_seed_values = {int(row["traffic_seed"]) for row in rows}
        if len(traffic_seed_values) != 1:
            raise RuntimeError(f"multiple traffic seeds for repetition {repetition_seed}")
        traffic_seed = next(iter(traffic_seed_values))
        if traffic_seed != TRAFFIC_SEEDS[repetition_seed - REPETITION_SEEDS[0]]:
            raise RuntimeError("AirSim traffic seed sequence changed")
        rows = sorted(rows, key=lambda row: int(row["packet_index"]))
        if [int(row["packet_index"]) for row in rows] != list(range(599)):
            raise RuntimeError(f"AirSim packet IDs missing or duplicated for seed {repetition_seed}")
        normalized = []
        for row in rows:
            normalized.append(
                {
                    "packet_id": int(row["packet_index"]),
                    "generation_time_s": f"{finite(row, 'generation_time_s') - first_time:.9f}",
                    "evaluated_at_time_s": f"{finite(row, 'evaluated_at_trace_time_s') - first_time:.9f}",
                    "source_id": row["source_node_id"],
                    "destination_id": row["destination_node_id"],
                    "trace_sequence": row["trace_sequence"],
                    "traffic_seed": traffic_seed,
                }
            )
        validate_schedule(normalized, source_names)
        normalized_air_schedules[repetition_seed] = normalized
        write_csv(
            args.output / "inputs" / "C" / f"traffic_seed_{repetition_seed}.csv",
            SCHEDULE_FIELDS,
            normalized,
        )

    sys.path.insert(0, str(args.r1_source))
    synthetic_mobility_by_seed: dict[int, list[dict[str, Any]]] = {}
    synthetic_schedules_by_seed: dict[int, list[dict[str, Any]]] = {}
    for index, repetition_seed in enumerate(REPETITION_SEEDS):
        traffic_seed = TRAFFIC_SEEDS[index]
        mobility_rows = make_r1_synthetic_frames(args.r1_source, repetition_seed)
        synthetic_mobility_by_seed[repetition_seed] = mobility_rows
        write_csv(
            args.output / "inputs" / "D" / f"mobility_seed_{repetition_seed}.csv",
            MOBILITY_FIELDS,
            mobility_rows,
        )
        schedule_rows = make_synthetic_schedule(repetition_seed, traffic_seed)
        synthetic_schedules_by_seed[repetition_seed] = schedule_rows
        write_csv(
            args.output / "inputs" / "D" / f"traffic_seed_{repetition_seed}.csv",
            SCHEDULE_FIELDS,
            schedule_rows,
        )

    first_schedule_seed = REPETITION_SEEDS[0]
    tests = run_input_tests(
        air_rows,
        air_frames,
        normalized_air_schedules[first_schedule_seed],
        first_schedule_seed,
        args.r1_source,
    )
    if len(tests) != 11 or any(row["result"] != "passed" for row in tests):
        raise RuntimeError(f"Input validation tests failed: {tests}")
    write_csv(args.output / "ns3_input_validation_tests.csv", ["test_name", "result", "details"], tests)

    mobility_validation: list[dict[str, Any]] = []
    for row in air_mobility:
        cart_z = -float(row["z_m"])
        mobility_validation.append(
            {
                "experiment": "C",
                "seed": "fixed_trace",
                "sequence": row["sequence"],
                "time_s": row["time_s"],
                "node_id": row["node_id"],
                "source_x_m": row["x_m"],
                "source_y_m": row["y_m"],
                "source_z_m": row["z_m"],
                "ns3_x_m": row["x_m"],
                "ns3_y_m": row["y_m"],
                "ns3_z_m": f"{cart_z:.9f}",
                "coordinate_transform_error_m": 0.0,
                "coordinate_frame": "common_NED_to_Cartesian_z_sign_flip",
            }
        )
    for repetition_seed, rows in synthetic_mobility_by_seed.items():
        for row in rows:
            mobility_validation.append(
                {
                    "experiment": "D",
                    "seed": repetition_seed,
                    "sequence": row["sequence"],
                    "time_s": row["time_s"],
                    "node_id": row["node_id"],
                    "source_x_m": row["x_m"],
                    "source_y_m": row["y_m"],
                    "source_z_m": row["z_m"],
                    "ns3_x_m": row["x_m"],
                    "ns3_y_m": row["y_m"],
                    "ns3_z_m": row["z_m"],
                    "coordinate_transform_error_m": 0.0,
                    "coordinate_frame": "Cartesian_identity",
                }
            )
    write_csv(
        args.output / "ns3_mobility_validation.csv",
        [
            "experiment",
            "seed",
            "sequence",
            "time_s",
            "node_id",
            "source_x_m",
            "source_y_m",
            "source_z_m",
            "ns3_x_m",
            "ns3_y_m",
            "ns3_z_m",
            "coordinate_transform_error_m",
            "coordinate_frame",
        ],
        mobility_validation,
    )
    print(
        f"prepared: AirSim frames={len(sequences)} C seeds={len(normalized_air_schedules)} "
        f"D seeds={len(synthetic_mobility_by_seed)} input_tests={len(tests)}"
    )


if __name__ == "__main__":
    main()
