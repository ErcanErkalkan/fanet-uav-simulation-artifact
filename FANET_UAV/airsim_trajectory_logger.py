"""
Record multi-UAV AirSim trajectories in the shared NED frame.

The shared frame is formed by adding each vehicle's configured settings.json
spawn offset to its local state position. This translation is valid for the
zero-yaw vehicle configuration used by the current experiment; nonzero vehicle
orientations are rejected rather than transformed without verification.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import airsim  # type: ignore
except ImportError:  # AirSim is optional outside an active simulator runtime.
    airsim = None


LAND_COMMAND_TIMEOUT_SECONDS = 60.0
DEFAULT_LANDING_TIMEOUT_SECONDS = 480.0


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    z: float
    speed: float


def build_square_mission(vehicle_index: int, altitude: float = -8.0) -> List[Waypoint]:
    """Return the original offset square mission."""
    offset = 10.0 * vehicle_index
    speed = 3.0
    return [
        Waypoint(offset, 0.0, altitude, speed),
        Waypoint(20.0 + offset, 0.0, altitude, speed),
        Waypoint(20.0 + offset, 20.0, altitude, speed),
        Waypoint(offset, 20.0, altitude, speed),
        Waypoint(offset, 0.0, altitude, speed),
    ]


def build_line_mission(vehicle_index: int, altitude: float = -8.0) -> List[Waypoint]:
    """Return the original offset line mission."""
    offset = 8.0 * vehicle_index
    speed = 3.0
    return [
        Waypoint(0.0, offset, altitude, speed),
        Waypoint(35.0, offset, altitude, speed),
        Waypoint(0.0, offset, altitude, speed),
    ]


def build_safe_square_mission() -> List[Waypoint]:
    """Return a compact local-NED route that preserves configured separation."""
    altitude = -2.0
    speed = 1.0
    return [
        Waypoint(0.0, 0.0, altitude, speed),
        Waypoint(2.0, 0.0, altitude, speed),
        Waypoint(2.0, 2.0, altitude, speed),
        Waypoint(0.0, 2.0, altitude, speed),
        Waypoint(0.0, 0.0, altitude, speed),
    ]


def load_vehicle_origins(settings_path: Path, vehicles: Iterable[str]) -> Dict[str, Tuple[float, float, float]]:
    """Load verified, zero-orientation spawn offsets from AirSim settings."""
    with settings_path.open("r", encoding="utf-8") as settings_file:
        settings = json.load(settings_file)
    if settings.get("SimMode") != "Multirotor":
        raise ValueError("AirSim settings must use SimMode=Multirotor")

    configured = settings.get("Vehicles", {})
    origins: Dict[str, Tuple[float, float, float]] = {}
    for vehicle in vehicles:
        if vehicle not in configured:
            raise ValueError(f"{vehicle} is missing from {settings_path}")
        entry = configured[vehicle]
        if entry.get("VehicleType") != "SimpleFlight":
            raise ValueError(f"{vehicle} must use VehicleType=SimpleFlight")
        for angle in ("Yaw", "Pitch", "Roll"):
            if not math.isclose(float(entry.get(angle, 0.0)), 0.0, abs_tol=1e-9):
                raise ValueError(
                    f"{vehicle} has nonzero {angle}; the verified translation-only "
                    "frame transform does not support rotated vehicle frames"
                )
        origin = tuple(float(entry[axis]) for axis in ("X", "Y", "Z"))
        if not all(math.isfinite(value) for value in origin):
            raise ValueError(f"{vehicle} has an invalid settings origin")
        origins[vehicle] = origin
    return origins


def to_common_ned(
    local_position: Tuple[float, float, float],
    spawn_origin: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """Translate a local NED position into the shared Player-Start NED frame."""
    common = tuple(local_position[index] + spawn_origin[index] for index in range(3))
    if not all(math.isfinite(value) for value in common):
        raise ValueError("AirSim returned a non-finite position")
    return common


def connect_client():
    if airsim is None:
        raise RuntimeError(
            "The AirSim Python package is unavailable; activate the AirSim "
            "virtual environment and run this script while Blocks is active."
        )
    client = airsim.MultirotorClient()
    client.confirmConnection()
    return client


def prepare_vehicles(client, vehicles: Iterable[str]) -> List[str]:
    controlled: List[str] = []
    try:
        for vehicle in vehicles:
            client.enableApiControl(True, vehicle_name=vehicle)
            client.armDisarm(True, vehicle_name=vehicle)
            controlled.append(vehicle)
        tasks = [client.takeoffAsync(vehicle_name=vehicle) for vehicle in vehicles]
        for task in tasks:
            task.join()
    except Exception:
        _land_and_verify(
            client, controlled, timeout_seconds=DEFAULT_LANDING_TIMEOUT_SECONDS
        )
        raise
    return controlled


def _mission_worker(
    vehicles: List[str],
    missions: Dict[str, List[Waypoint]],
    stop: threading.Event,
    errors: List[str],
) -> None:
    try:
        if airsim is None:
            raise RuntimeError("AirSim package is unavailable in mission worker")
        client = airsim.MultirotorClient()
        client.confirmConnection()
        while not stop.is_set():
            for waypoint_index in range(len(missions[vehicles[0]])):
                if stop.is_set():
                    return
                tasks = []
                for vehicle in vehicles:
                    waypoint = missions[vehicle][waypoint_index]
                    tasks.append(
                        client.moveToPositionAsync(
                            waypoint.x,
                            waypoint.y,
                            waypoint.z,
                            waypoint.speed,
                            timeout_sec=15,
                            vehicle_name=vehicle,
                        )
                    )
                for task in tasks:
                    task.join()
    except Exception as exc:
        errors.append(f"mission controller: {type(exc).__name__}: {exc}")
        stop.set()


def launch_missions(
    vehicles: List[str],
    mission_name: str,
) -> Tuple[threading.Event, List[threading.Thread], List[str]]:
    stop = threading.Event()
    errors: List[str] = []
    missions = {}
    for index, vehicle in enumerate(vehicles):
        if mission_name == "safe-square":
            waypoints = build_safe_square_mission()
        elif mission_name == "square":
            waypoints = build_square_mission(index)
        else:
            waypoints = build_line_mission(index)
        missions[vehicle] = waypoints
    worker = threading.Thread(
        target=_mission_worker,
        args=(vehicles, missions, stop, errors),
        name="airsim-mission-controller",
        daemon=True,
    )
    worker.start()
    return stop, [worker], errors


def _flight_state(state) -> str:
    landed_state = int(state.landed_state)
    if airsim is not None and landed_state == int(airsim.LandedState.Landed):
        return "Landed"
    if airsim is not None and landed_state == int(airsim.LandedState.Flying):
        return "Flying"
    return f"Unknown({landed_state})"


def _fresh_landing_followup(
    vehicles: Iterable[str], timeout_seconds: float = 180.0
) -> dict:
    """Recheck timed-out landing states over an independent RPC connection."""
    names = list(vehicles)
    followup = {
        "poll_started_utc": datetime.now(timezone.utc).isoformat(),
        "poll_timeout_seconds": timeout_seconds,
        "connection_confirmed": False,
        "vehicles": {},
    }
    if airsim is None:
        followup["error"] = "AirSim package is unavailable"
        return followup
    try:
        observer = airsim.MultirotorClient()
        observer.confirmConnection()
        followup["connection_confirmed"] = True
        pending = set(names)
        deadline = time.monotonic() + timeout_seconds
        while pending and time.monotonic() < deadline:
            for name in tuple(pending):
                try:
                    state = observer.getMultirotorState(vehicle_name=name)
                    values = {
                        "landed_state": int(state.landed_state),
                        "state": _flight_state(state),
                        "position_ned_m": [
                            state.kinematics_estimated.position.x_val,
                            state.kinematics_estimated.position.y_val,
                            state.kinematics_estimated.position.z_val,
                        ],
                        "velocity_ned_mps": [
                            state.kinematics_estimated.linear_velocity.x_val,
                            state.kinematics_estimated.linear_velocity.y_val,
                            state.kinematics_estimated.linear_velocity.z_val,
                        ],
                        "sim_time_stamp_ns": int(state.timestamp),
                    }
                    collision = observer.simGetCollisionInfo(vehicle_name=name)
                    values["collision"] = {
                        "has_collided": bool(collision.has_collided),
                        "object_name": collision.object_name,
                        "time_stamp": int(collision.time_stamp),
                    }
                    values["landed_and_stationary"] = (
                        values["landed_state"] == int(airsim.LandedState.Landed)
                        and all(
                            abs(component) <= 0.05
                            for component in values["velocity_ned_mps"]
                        )
                    )
                    followup["vehicles"][name] = values
                    if values["landed_and_stationary"]:
                        pending.remove(name)
                except Exception as exc:
                    followup["vehicles"][name] = {
                        "error": f"{type(exc).__name__}: {exc}"
                    }
            if pending:
                time.sleep(0.5)
    except Exception as exc:
        followup["error"] = f"{type(exc).__name__}: {exc}"
    followup["poll_finished_utc"] = datetime.now(timezone.utc).isoformat()
    followup["all_landed_and_stationary"] = (
        followup["connection_confirmed"]
        and len(followup["vehicles"]) == len(names)
        and all(
            item.get("landed_and_stationary", False)
            for item in followup["vehicles"].values()
        )
    )
    return followup


def get_vehicle_row(
    client,
    vehicle: str,
    spawn_origin: Tuple[float, float, float],
    elapsed: float,
    wall_elapsed: float,
    wall_time_utc: str,
    sequence: int,
) -> dict:
    state = client.getMultirotorState(vehicle_name=vehicle)
    kin = state.kinematics_estimated
    local_position = (kin.position.x_val, kin.position.y_val, kin.position.z_val)
    position = to_common_ned(local_position, spawn_origin)
    velocity = (
        kin.linear_velocity.x_val,
        kin.linear_velocity.y_val,
        kin.linear_velocity.z_val,
    )
    timestamp = int(state.timestamp)
    if timestamp <= 0:
        raise ValueError(f"{vehicle}: invalid AirSim simulation timestamp {timestamp}")
    if not all(math.isfinite(value) for value in velocity):
        raise ValueError(f"{vehicle}: AirSim returned a non-finite velocity")
    collision = client.simGetCollisionInfo(vehicle_name=vehicle)
    return {
        "time_s": f"{elapsed:.9f}",
        "monotonic_time_s": f"{elapsed:.9f}",
        "wall_elapsed_s": f"{wall_elapsed:.9f}",
        "wall_time_utc": wall_time_utc,
        "sim_time_stamp_ns": timestamp,
        "sequence": sequence,
        "vehicle_name": vehicle,
        "node_id": vehicle,
        "x_m": f"{position[0]:.9f}",
        "y_m": f"{position[1]:.9f}",
        "z_m": f"{position[2]:.9f}",
        "vx_mps": f"{velocity[0]:.9f}",
        "vy_mps": f"{velocity[1]:.9f}",
        "vz_mps": f"{velocity[2]:.9f}",
        "flight_state": _flight_state(state),
        "collision_state": "collision" if collision.has_collided else "clear",
        "collision_object": collision.object_name,
        "collision_time_stamp_ns": int(collision.time_stamp),
        "source": "airsim",
    }


def _land_and_verify(client, vehicles: Iterable[str], timeout_seconds: float) -> dict:
    """Record landing-command completion separately from landed-state confirmation."""
    names = list(vehicles)
    results = {
        name: {
            "land_command_sent": False,
            "land_command_completed": False,
            "landed_state_confirmed": False,
            "landing_timeout": False,
        }
        for name in names
    }
    hover_tasks = {}
    for name in names:
        try:
            hover_tasks[name] = client.hoverAsync(vehicle_name=name)
        except Exception as exc:
            results[name]["hover_command_error"] = f"{type(exc).__name__}: {exc}"

    for name, task in hover_tasks.items():
        try:
            task.join()
        except Exception as exc:
            results[name]["hover_command_error"] = f"{type(exc).__name__}: {exc}"

    tasks = {}
    for name in names:
        try:
            results[name]["land_command_started_utc"] = datetime.now(timezone.utc).isoformat()
            results[name]["land_command_timeout_seconds"] = (
                LAND_COMMAND_TIMEOUT_SECONDS
            )
            tasks[name] = client.landAsync(
                timeout_sec=LAND_COMMAND_TIMEOUT_SECONDS, vehicle_name=name
            )
            results[name]["land_command_sent"] = True
        except Exception as exc:
            results[name]["land_command_error"] = f"{type(exc).__name__}: {exc}"

    for name, task in tasks.items():
        try:
            task.join()
            results[name]["land_command_completed"] = True
            results[name]["land_command_completed_utc"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            results[name]["land_command_error"] = f"{type(exc).__name__}: {exc}"

    poll_started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + timeout_seconds
    pending = set(tasks)
    while pending and time.monotonic() < deadline:
        for name in tuple(pending):
            try:
                state = client.getMultirotorState(vehicle_name=name)
                if airsim is not None and int(state.landed_state) == int(airsim.LandedState.Landed):
                    kin = state.kinematics_estimated
                    results[name]["landed_state_confirmed"] = True
                    results[name]["landed_state_confirmed_utc"] = datetime.now(timezone.utc).isoformat()
                    results[name]["final_sim_time_stamp_ns"] = int(state.timestamp)
                    results[name]["final_position_ned_m"] = [
                        kin.position.x_val,
                        kin.position.y_val,
                        kin.position.z_val,
                    ]
                    results[name]["final_velocity_ned_mps"] = [
                        kin.linear_velocity.x_val,
                        kin.linear_velocity.y_val,
                        kin.linear_velocity.z_val,
                    ]
                    collision = client.simGetCollisionInfo(vehicle_name=name)
                    results[name]["final_collision"] = {
                        "has_collided": bool(collision.has_collided),
                        "object_name": collision.object_name,
                        "time_stamp": int(collision.time_stamp),
                    }
                    pending.remove(name)
            except Exception as exc:
                results[name]["landed_state_poll_error"] = f"{type(exc).__name__}: {exc}"
        if pending:
            time.sleep(0.25)
    for name in pending:
        results[name]["landing_timeout"] = True
        results[name]["landing_timeout_seconds"] = timeout_seconds
    followup = _fresh_landing_followup(pending) if pending else None
    if followup is not None:
        for name, state in followup.get("vehicles", {}).items():
            results[name]["independent_post_timeout_state_check"] = state
            results[name]["landed_state_confirmed_by_followup"] = state.get(
                "landed_and_stationary", False
            )
    return {
        "status": (
            "passed"
            if all(
                results[name]["land_command_completed"]
                and results[name]["landed_state_confirmed"]
                for name in names
            )
            else (
                "passed_with_delayed_landing_verification"
                if followup is not None
                and followup.get("all_landed_and_stationary", False)
                and all(results[name]["land_command_completed"] for name in names)
                else "failed"
            )
        ),
        "timeout_seconds": timeout_seconds,
        "land_state_poll_started_utc": poll_started,
        "land_state_poll_finished_utc": datetime.now(timezone.utc).isoformat(),
        "independent_post_timeout_check": followup,
        "vehicles": results,
    }


def log_trajectories(
    vehicles: List[str],
    duration: float,
    sample_period: float,
    out_path: Path,
    mission: str,
    settings_path: Path,
    landing_timeout: float,
    result_path: Path | None = None,
) -> dict:
    if duration <= 0 or sample_period <= 0:
        raise ValueError("duration and sample_period must be positive")
    if not vehicles or len(set(vehicles)) != len(vehicles):
        raise ValueError("vehicle names must be nonempty and unique")

    origins = load_vehicle_origins(settings_path, vehicles)
    client = connect_client()
    client.reset()
    time.sleep(2.0)
    client.confirmConnection()
    available = set(client.listVehicles())
    missing = set(vehicles) - available
    if missing:
        raise RuntimeError(f"Configured vehicles missing from AirSim: {sorted(missing)}")

    initial_common = {}
    state_pose_differences = {}
    for vehicle in vehicles:
        state = client.getMultirotorState(vehicle_name=vehicle)
        kin = state.kinematics_estimated
        local = (kin.position.x_val, kin.position.y_val, kin.position.z_val)
        initial_common[vehicle] = to_common_ned(local, origins[vehicle])
        pose = client.simGetVehiclePose(vehicle_name=vehicle).position
        pose_position = (pose.x_val, pose.y_val, pose.z_val)
        state_pose_differences[vehicle] = math.dist(local, pose_position)
        if state_pose_differences[vehicle] > 0.05:
            raise RuntimeError(
                f"{vehicle}: simGetVehiclePose and getMultirotorState disagree "
                f"by {state_pose_differences[vehicle]:.3f} m before takeoff"
            )
    initial_geometry = {}
    for index, first in enumerate(vehicles):
        for second in vehicles[index + 1:]:
            expected_distance = math.dist(origins[first], origins[second])
            observed_distance = math.dist(initial_common[first], initial_common[second])
            error = abs(observed_distance - expected_distance)
            initial_geometry[f"{first}-{second}"] = {
                "expected_distance_m": expected_distance,
                "observed_distance_m": observed_distance,
                "absolute_error_m": error,
            }
            if error > 0.25:
                raise RuntimeError(
                    f"{first}-{second}: reset geometry differs from settings by "
                    f"{error:.3f} m"
                )

    preflight_collisions = {}
    for vehicle in vehicles:
        collision = client.simGetCollisionInfo(vehicle_name=vehicle)
        preflight_collisions[vehicle] = {
            "has_collided": bool(collision.has_collided),
            "object_name": collision.object_name,
            "time_stamp": int(collision.time_stamp),
        }
    controlled = prepare_vehicles(client, vehicles)
    mission_stop = None
    mission_threads: List[threading.Thread] = []
    mission_errors: List[str] = []
    rows_written = 0
    missed_ticks = 0
    sample_times: Dict[str, int] = {}
    previous_sim_timestamp: Dict[str, int] = {}
    landing_result = {"status": "not_run", "vehicles": {}}
    run_error = None
    try:
        mission_stop, mission_threads, mission_errors = launch_missions(
            vehicles, mission
        )
        fieldnames = [
            "time_s",
            "monotonic_time_s",
            "wall_elapsed_s",
            "wall_time_utc",
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
            "flight_state",
            "collision_state",
            "collision_object",
            "collision_time_stamp_ns",
            "source",
        ]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        monotonic_start = time.perf_counter()
        wall_start = time.time()
        next_tick = monotonic_start
        sequence = 0
        with out_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            while True:
                scheduled = monotonic_start + sequence * sample_period
                wait = scheduled - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                now = time.perf_counter()
                elapsed = now - monotonic_start
                if elapsed >= duration:
                    break
                if mission_errors:
                    raise RuntimeError(
                        f"Mission worker failed: {mission_errors[0]}"
                    )
                wall_now = time.time()
                wall_iso = datetime.now(timezone.utc).isoformat()
                for vehicle in vehicles:
                    row = get_vehicle_row(
                        client,
                        vehicle,
                        origins[vehicle],
                        elapsed,
                        wall_now - wall_start,
                        wall_iso,
                        sequence,
                    )
                    mono = float(row["monotonic_time_s"])
                    sim_timestamp = int(row["sim_time_stamp_ns"])
                    previous_mono = sample_times.get(vehicle)
                    if previous_mono is not None and mono <= previous_mono:
                        raise ValueError(f"{vehicle}: duplicate or non-increasing monotonic timestamp")
                    previous_sim = previous_sim_timestamp.get(vehicle)
                    if previous_sim is not None and sim_timestamp <= previous_sim:
                        raise ValueError(f"{vehicle}: duplicate or non-increasing simulation timestamp")
                    sample_times[vehicle] = mono
                    previous_sim_timestamp[vehicle] = sim_timestamp
                    writer.writerow(row)
                    rows_written += 1
                sequence += 1
                next_scheduled = monotonic_start + sequence * sample_period
                finished_sampling = time.perf_counter()
                if finished_sampling - next_scheduled >= sample_period:
                    skipped = int(
                        (finished_sampling - next_scheduled) // sample_period
                    ) + 1
                    sequence += skipped
                    missed_ticks += skipped
                csv_file.flush()
        mission_stop.set()
        for worker in mission_threads:
            worker.join(timeout=20.0)
            if worker.is_alive():
                raise TimeoutError(f"Mission worker did not stop: {worker.name}")
        if mission_errors:
            raise RuntimeError(f"Mission worker failed: {mission_errors[0]}")
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
    finally:
        if mission_stop is not None:
            mission_stop.set()
        landing_result = _land_and_verify(client, controlled, landing_timeout)
        for vehicle in controlled:
            try:
                client.armDisarm(False, vehicle_name=vehicle)
                client.enableApiControl(False, vehicle_name=vehicle)
            except Exception as exc:
                landing_result["vehicles"][vehicle]["control_cleanup_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )

    result = {
        "status": "failed" if run_error else landing_result["status"],
        "run_error": run_error,
        "mission_errors": mission_errors,
        "requested_duration_s": duration,
        "sample_period_s": sample_period,
        "sample_rate_hz": 1.0 / sample_period,
        "mission": mission,
        "vehicles": vehicles,
        "shared_ned_spawn_origins_m": {name: list(origins[name]) for name in vehicles},
        "initial_common_positions_ned_m": {
            name: list(initial_common[name]) for name in vehicles
        },
        "initial_geometry": initial_geometry,
        "state_pose_difference_m": state_pose_differences,
        "preflight_collision_baseline": preflight_collisions,
        "rows_written": rows_written,
        "sample_frames_written": rows_written // len(vehicles),
        "missed_ticks_estimate": missed_ticks,
        "landing": landing_result,
    }
    if result_path is not None:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2))
    if result["status"] not in {
        "passed",
        "passed_with_delayed_landing_verification",
    }:
        raise RuntimeError(
            f"AirSim trajectory run failed; see recorded run result: {result}"
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log timestamped AirSim UAV trajectories in shared NED.")
    parser.add_argument("--vehicles", nargs="+", required=True, help="AirSim vehicle names")
    parser.add_argument("--duration", type=float, default=120.0, help="Recording duration in seconds")
    parser.add_argument("--sample-period", type=float, default=0.2, help="Sampling period in seconds")
    parser.add_argument("--out", type=Path, default=Path("airsim_trajectory.csv"), help="Output CSV path")
    parser.add_argument("--mission", choices=["square", "line", "safe-square"], default="safe-square")
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path.home() / "Documents" / "AirSim" / "settings.json",
        help="AirSim settings.json used for the shared-frame origin offsets",
    )
    parser.add_argument(
        "--landing-timeout",
        type=float,
        default=DEFAULT_LANDING_TIMEOUT_SECONDS,
        help="Maximum seconds to confirm Landed after landAsync completes",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path for the run and separately verified landing result",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    log_trajectories(
        args.vehicles,
        args.duration,
        args.sample_period,
        args.out,
        args.mission,
        args.settings,
        args.landing_timeout,
        args.result_json,
    )
