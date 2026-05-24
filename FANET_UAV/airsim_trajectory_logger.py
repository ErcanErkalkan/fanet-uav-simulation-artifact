"""
AirSim trajectory logger for multi-UAV FANET experiments.

Purpose
-------
This script records time-stamped UAV positions from AirSim/Unreal Engine and
exports them in the CSV schema consumed by fanet_trace_replay.py. It is intended
for the AirSim-coupled experiment in the manuscript.

Requirements
------------
1. AirSim Python package installed: pip install airsim
2. Unreal Engine project running with AirSim multirotor vehicles configured.
3. Vehicle names in settings.json such as Drone1, Drone2, ..., DroneN.

Example
-------
python airsim_trajectory_logger.py --vehicles Drone1 Drone2 Drone3 --duration 120 \
    --sample-period 0.1 --out airsim_trajectory_3uav.csv --mission square
"""
from __future__ import annotations

import argparse
import csv
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    import airsim  # type: ignore
except Exception:  # pragma: no cover - AirSim is optional outside Unreal runtime
    airsim = None


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    z: float
    speed: float


def build_square_mission(vehicle_index: int, altitude: float = -8.0) -> List[Waypoint]:
    """Return a simple offset square mission for one UAV.

    AirSim uses NED coordinates, so negative z means altitude above the takeoff
    point. Offsets avoid all UAVs occupying the same path.
    """
    offset = 10.0 * vehicle_index
    speed = 3.0
    return [
        Waypoint(0.0 + offset, 0.0, altitude, speed),
        Waypoint(20.0 + offset, 0.0, altitude, speed),
        Waypoint(20.0 + offset, 20.0, altitude, speed),
        Waypoint(0.0 + offset, 20.0, altitude, speed),
        Waypoint(0.0 + offset, 0.0, altitude, speed),
    ]


def build_line_mission(vehicle_index: int, altitude: float = -8.0) -> List[Waypoint]:
    offset = 8.0 * vehicle_index
    speed = 3.0
    return [
        Waypoint(0.0, offset, altitude, speed),
        Waypoint(35.0, offset, altitude, speed),
        Waypoint(0.0, offset, altitude, speed),
    ]


def connect_client():
    if airsim is None:
        raise RuntimeError(
            "The 'airsim' Python package is not available. Install it and run this "
            "script while an AirSim Unreal environment is active."
        )
    client = airsim.MultirotorClient()
    client.confirmConnection()
    return client


def prepare_vehicles(client, vehicles: Iterable[str]) -> None:
    for vehicle in vehicles:
        client.enableApiControl(True, vehicle_name=vehicle)
        client.armDisarm(True, vehicle_name=vehicle)
    tasks = [client.takeoffAsync(vehicle_name=v) for v in vehicles]
    for task in tasks:
        task.join()


def launch_missions(client, vehicles: List[str], mission_name: str) -> None:
    for idx, vehicle in enumerate(vehicles):
        waypoints = build_square_mission(idx) if mission_name == "square" else build_line_mission(idx)
        # Execute missions asynchronously. The logger below samples states while
        # AirSim moves vehicles from waypoint to waypoint.
        def _start(vehicle_name: str, mission: List[Waypoint]):
            for wp in mission:
                client.moveToPositionAsync(
                    wp.x, wp.y, wp.z, wp.speed, vehicle_name=vehicle_name
                ).join()
        # Use AirSim's async primitive for the first waypoint; subsequent commands
        # are handled sequentially by a lightweight background thread.
        import threading
        threading.Thread(target=_start, args=(vehicle, waypoints), daemon=True).start()


def get_vehicle_row(client, vehicle: str, elapsed: float, sequence: int) -> dict:
    state = client.getMultirotorState(vehicle_name=vehicle)
    kin = state.kinematics_estimated
    pos = kin.position
    vel = kin.linear_velocity
    return {
        "time_s": f"{elapsed:.6f}",
        "sequence": sequence,
        "node_id": vehicle,
        "x_m": f"{pos.x_val:.6f}",
        "y_m": f"{pos.y_val:.6f}",
        "z_m": f"{pos.z_val:.6f}",
        "vx_mps": f"{vel.x_val:.6f}",
        "vy_mps": f"{vel.y_val:.6f}",
        "vz_mps": f"{vel.z_val:.6f}",
        "source": "airsim",
    }


def log_trajectories(
    vehicles: List[str],
    duration: float,
    sample_period: float,
    out_path: Path,
    mission: str,
) -> None:
    client = connect_client()
    prepare_vehicles(client, vehicles)
    launch_missions(client, vehicles, mission)

    fieldnames = [
        "time_s", "sequence", "node_id", "x_m", "y_m", "z_m",
        "vx_mps", "vy_mps", "vz_mps", "source",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    next_sample = start
    sequence = 0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        while True:
            now = time.perf_counter()
            elapsed = now - start
            if elapsed > duration:
                break
            if now >= next_sample:
                for vehicle in vehicles:
                    writer.writerow(get_vehicle_row(client, vehicle, elapsed, sequence))
                sequence += 1
                next_sample += sample_period
            time.sleep(min(sample_period / 10.0, 0.01))

    for vehicle in vehicles:
        client.hoverAsync(vehicle_name=vehicle).join()
        client.landAsync(vehicle_name=vehicle).join()
        client.armDisarm(False, vehicle_name=vehicle)
        client.enableApiControl(False, vehicle_name=vehicle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record AirSim UAV trajectories for FANET replay.")
    parser.add_argument("--vehicles", nargs="+", required=True, help="AirSim vehicle names, e.g. Drone1 Drone2 Drone3")
    parser.add_argument("--duration", type=float, default=120.0, help="Logging duration in seconds")
    parser.add_argument("--sample-period", type=float, default=0.1, help="Sampling period in seconds")
    parser.add_argument("--out", type=Path, default=Path("airsim_trajectory.csv"), help="Output CSV path")
    parser.add_argument("--mission", choices=["square", "line"], default="square", help="Mission pattern")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    log_trajectories(args.vehicles, args.duration, args.sample_period, args.out, args.mission)
