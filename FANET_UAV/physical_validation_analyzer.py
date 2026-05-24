#!/usr/bin/env python3
"""
Analyze DJI Tello physical-validation logs.

Inputs:
  --command-log tello_command_log.csv
  --state-log tello_state_log.csv
Optional:
  --airsim-trace airsim_trajectory_1uav.csv
  --external-position-log external_positions.csv

Outputs:
  physical_validation_metrics.csv

The analyzer reports:
  - command/ACK delay statistics
  - telemetry sampling rate and jitter
  - velocity-integrated trajectory proxy from Tello state packets
  - trajectory RMSE when an AirSim or external position trace is supplied

Tello state packets do not provide global x/y position in the standard SDK
telemetry stream. Therefore, trajectory deviation should be interpreted as a
velocity-integrated proxy unless an external localization log is supplied.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Optional, Tuple


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def as_float(value: str, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize(values: Iterable[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    xs = [x for x in values if x is not None and math.isfinite(x)]
    if not xs:
        return None, None, None, None
    return mean(xs), pstdev(xs) if len(xs) > 1 else 0.0, min(xs), max(xs)


def command_delay_metrics(command_rows: List[Dict[str, str]]) -> Dict[str, Optional[float]]:
    delays = [as_float(r.get("ack_delay_ms", "")) for r in command_rows]
    delays = [d for d in delays if d is not None]
    success_values = [as_float(r.get("success", "0"), 0.0) or 0.0 for r in command_rows]
    m, s, mn, mx = summarize(delays)
    return {
        "command_count": float(len(command_rows)),
        "command_success_rate": (sum(success_values) / len(success_values)) if success_values else None,
        "ack_delay_mean_ms": m,
        "ack_delay_std_ms": s,
        "ack_delay_min_ms": mn,
        "ack_delay_max_ms": mx,
    }


def telemetry_metrics(state_rows: List[Dict[str, str]]) -> Dict[str, Optional[float]]:
    times = [as_float(r.get("time_s", "")) for r in state_rows]
    times = [t for t in times if t is not None]
    if len(times) < 2:
        return {
            "telemetry_samples": float(len(times)),
            "telemetry_duration_s": None,
            "telemetry_sampling_rate_hz": None,
            "telemetry_jitter_std_ms": None,
        }
    times.sort()
    duration = times[-1] - times[0]
    intervals = [b - a for a, b in zip(times[:-1], times[1:]) if b > a]
    _, jitter_s, _, _ = summarize(intervals)
    return {
        "telemetry_samples": float(len(times)),
        "telemetry_duration_s": duration,
        "telemetry_sampling_rate_hz": (len(times) - 1) / duration if duration > 0 else None,
        "telemetry_jitter_std_ms": (jitter_s * 1000.0) if jitter_s is not None else None,
    }


def integrate_tello_velocity(state_rows: List[Dict[str, str]]) -> List[Tuple[float, float, float, float]]:
    """Return time, x, y, z trajectory proxy in metres.

    Standard Tello state fields vgx/vgy/vgz are in cm/s. The integration is a
    proxy and accumulates drift; it should be replaced by external tracking for
    high-accuracy trajectory validation.
    """
    parsed = []
    for r in state_rows:
        t = as_float(r.get("time_s", ""))
        if t is None:
            continue
        vx = (as_float(r.get("vgx", "0"), 0.0) or 0.0) / 100.0
        vy = (as_float(r.get("vgy", "0"), 0.0) or 0.0) / 100.0
        vz = (as_float(r.get("vgz", "0"), 0.0) or 0.0) / 100.0
        parsed.append((t, vx, vy, vz))
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        return []
    x = y = z = 0.0
    out = [(parsed[0][0], x, y, z)]
    for (t0, vx0, vy0, vz0), (t1, vx1, vy1, vz1) in zip(parsed[:-1], parsed[1:]):
        dt = max(0.0, t1 - t0)
        x += 0.5 * (vx0 + vx1) * dt
        y += 0.5 * (vy0 + vy1) * dt
        z += 0.5 * (vz0 + vz1) * dt
        out.append((t1, x, y, z))
    return out


def read_position_trace(path: Path) -> List[Tuple[float, float, float, float]]:
    rows = read_csv(path)
    out = []
    for r in rows:
        t = as_float(r.get("time_s", ""))
        x = as_float(r.get("x_m", r.get("x", "")))
        y = as_float(r.get("y_m", r.get("y", "")))
        z = as_float(r.get("z_m", r.get("z", "")))
        if None not in (t, x, y, z):
            out.append((t, x, y, z))
    out.sort(key=lambda item: item[0])
    return out


def nearest_rmse(reference: List[Tuple[float, float, float, float]], observed: List[Tuple[float, float, float, float]]) -> Optional[float]:
    if not reference or not observed:
        return None
    errors = []
    j = 0
    for t, x, y, z in observed:
        while j + 1 < len(reference) and abs(reference[j + 1][0] - t) < abs(reference[j][0] - t):
            j += 1
        _, xr, yr, zr = reference[j]
        errors.append((x - xr) ** 2 + (y - yr) ** 2 + (z - zr) ** 2)
    if not errors:
        return None
    return math.sqrt(mean(errors))


def write_metrics(path: Path, metrics: Dict[str, Optional[float]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        for k, v in metrics.items():
            writer.writerow({"metric": k, "value": "" if v is None else f"{v:.6f}"})


def write_proxy_trace(path: Path, trace: List[Tuple[float, float, float, float]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "x_m", "y_m", "z_m", "source"])
        for t, x, y, z in trace:
            writer.writerow([f"{t:.6f}", f"{x:.6f}", f"{y:.6f}", f"{z:.6f}", "tello_velocity_integrated_proxy"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-log", type=Path, required=True)
    parser.add_argument("--state-log", type=Path, required=True)
    parser.add_argument("--airsim-trace", type=Path, default=None)
    parser.add_argument("--external-position-log", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("physical_validation_metrics.csv"))
    parser.add_argument("--proxy-trace-out", type=Path, default=Path("tello_velocity_proxy_trace.csv"))
    args = parser.parse_args()

    command_rows = read_csv(args.command_log)
    state_rows = read_csv(args.state_log)
    proxy = integrate_tello_velocity(state_rows)

    metrics: Dict[str, Optional[float]] = {}
    metrics.update(command_delay_metrics(command_rows))
    metrics.update(telemetry_metrics(state_rows))
    if proxy:
        metrics["velocity_proxy_final_x_m"] = proxy[-1][1]
        metrics["velocity_proxy_final_y_m"] = proxy[-1][2]
        metrics["velocity_proxy_final_z_m"] = proxy[-1][3]

    if args.airsim_trace:
        airsim = read_position_trace(args.airsim_trace)
        metrics["airsim_vs_tello_proxy_rmse_m"] = nearest_rmse(airsim, proxy)
    if args.external_position_log:
        external = read_position_trace(args.external_position_log)
        metrics["external_vs_tello_proxy_rmse_m"] = nearest_rmse(external, proxy)

    write_metrics(args.out, metrics)
    write_proxy_trace(args.proxy_trace_out, proxy)
    print(f"Metrics written to {args.out}")
    print(f"Velocity-integrated proxy trace written to {args.proxy_trace_out}")


if __name__ == "__main__":
    main()
