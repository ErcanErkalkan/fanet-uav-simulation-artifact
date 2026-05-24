#!/usr/bin/env python3
"""
DJI Tello physical-validation logger for FANET/UAV simulation studies.

The script records two synchronized logs:
  1. command_log.csv: command send time, response time, ACK/response delay
  2. state_log.csv: decoded Tello telemetry state packets with timestamps

Safety note:
  By default the script only enters SDK mode, queries battery, and listens to
  telemetry. Movement commands are sent only when --flight-plan is supplied and
  --execute-flight-plan is explicitly enabled.

Typical usage:
  python tello_validation_logger.py --duration 60 --out-dir tello_run_01
  python tello_validation_logger.py --flight-plan tello_plan.csv \
      --execute-flight-plan --duration 120 --out-dir tello_run_02

Example flight-plan CSV columns:
  delay_s,command,expected_distance_cm
  2,takeoff,
  3,forward 50,50
  2,right 50,50
  2,back 50,50
  2,left 50,50
  2,land,
"""

from __future__ import annotations

import argparse
import csv
import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TELLO_IP = "192.168.10.1"
TELLO_CMD_PORT = 8889
TELLO_STATE_PORT = 8890
LOCAL_CMD_PORT = 9000


@dataclass
class CommandRecord:
    sequence: int
    command: str
    send_time_s: float
    response_time_s: Optional[float]
    ack_delay_ms: Optional[float]
    response: str
    success: bool


class TelloPhysicalLogger:
    def __init__(self, out_dir: Path, local_cmd_port: int = LOCAL_CMD_PORT):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.tello_addr = (TELLO_IP, TELLO_CMD_PORT)
        self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.command_socket.bind(("", local_cmd_port))
        self.command_socket.settimeout(7.0)

        self.state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.state_socket.bind(("", TELLO_STATE_PORT))
        self.state_socket.settimeout(1.0)

        self._stop_state = threading.Event()
        self._state_rows: List[Dict[str, str]] = []
        self._state_thread: Optional[threading.Thread] = None
        self._start_perf = time.perf_counter()
        self._start_wall = time.time()

    def _elapsed(self) -> float:
        return time.perf_counter() - self._start_perf

    @staticmethod
    def _parse_state_packet(packet: str) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        for item in packet.strip().split(";"):
            if not item or ":" not in item:
                continue
            key, value = item.split(":", 1)
            fields[key.strip()] = value.strip()
        return fields

    def start_state_listener(self) -> None:
        def listen() -> None:
            while not self._stop_state.is_set():
                try:
                    data, _ = self.state_socket.recvfrom(4096)
                except socket.timeout:
                    continue
                now = self._elapsed()
                raw = data.decode("utf-8", errors="replace")
                parsed = self._parse_state_packet(raw)
                row: Dict[str, str] = {
                    "time_s": f"{now:.6f}",
                    "wall_time_s": f"{time.time():.6f}",
                    "raw_state": raw.strip(),
                }
                row.update(parsed)
                self._state_rows.append(row)

        self._state_thread = threading.Thread(target=listen, daemon=True)
        self._state_thread.start()

    def stop_state_listener(self) -> None:
        self._stop_state.set()
        if self._state_thread:
            self._state_thread.join(timeout=2.0)

    def send_command(self, sequence: int, command: str, timeout_s: float = 7.0) -> CommandRecord:
        send_t = self._elapsed()
        response = ""
        response_t: Optional[float] = None
        ack_delay_ms: Optional[float] = None
        success = False
        self.command_socket.settimeout(timeout_s)
        self.command_socket.sendto(command.encode("utf-8"), self.tello_addr)
        try:
            data, _ = self.command_socket.recvfrom(1024)
            response_t = self._elapsed()
            response = data.decode("utf-8", errors="replace").strip()
            ack_delay_ms = (response_t - send_t) * 1000.0
            success = response.lower() == "ok" or len(response) > 0
        except socket.timeout:
            response = "TIMEOUT"
            success = False
        return CommandRecord(sequence, command, send_t, response_t, ack_delay_ms, response, success)

    def write_logs(self, command_records: List[CommandRecord]) -> Tuple[Path, Path]:
        command_path = self.out_dir / "tello_command_log.csv"
        state_path = self.out_dir / "tello_state_log.csv"

        with command_path.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "sequence",
                    "command",
                    "send_time_s",
                    "response_time_s",
                    "ack_delay_ms",
                    "response",
                    "success",
                ],
            )
            writer.writeheader()
            for r in command_records:
                writer.writerow({
                    "sequence": r.sequence,
                    "command": r.command,
                    "send_time_s": f"{r.send_time_s:.6f}",
                    "response_time_s": "" if r.response_time_s is None else f"{r.response_time_s:.6f}",
                    "ack_delay_ms": "" if r.ack_delay_ms is None else f"{r.ack_delay_ms:.3f}",
                    "response": r.response,
                    "success": int(r.success),
                })

        # State packets may not contain identical keys across firmware versions.
        fieldnames = ["time_s", "wall_time_s", "raw_state"]
        for row in self._state_rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
        with state_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in self._state_rows:
                writer.writerow(row)
        return command_path, state_path

    def close(self) -> None:
        self.stop_state_listener()
        self.command_socket.close()
        self.state_socket.close()


def load_flight_plan(path: Path) -> List[Tuple[float, str]]:
    rows: List[Tuple[float, str]] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            delay = float(row.get("delay_s", "0") or 0)
            command = (row.get("command") or "").strip()
            if command:
                rows.append((delay, command))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=30.0, help="Telemetry listening duration in seconds.")
    parser.add_argument("--out-dir", type=Path, default=Path("tello_validation_run"))
    parser.add_argument("--flight-plan", type=Path, default=None, help="CSV file with delay_s and command columns.")
    parser.add_argument("--execute-flight-plan", action="store_true", help="Required to send movement commands.")
    parser.add_argument("--local-cmd-port", type=int, default=LOCAL_CMD_PORT)
    args = parser.parse_args()

    logger = TelloPhysicalLogger(args.out_dir, local_cmd_port=args.local_cmd_port)
    records: List[CommandRecord] = []
    try:
        logger.start_state_listener()
        # Enter SDK mode and query battery. These commands are non-movement commands.
        records.append(logger.send_command(0, "command"))
        records.append(logger.send_command(1, "battery?"))

        seq = 2
        if args.flight_plan is not None:
            plan = load_flight_plan(args.flight_plan)
            if not args.execute_flight_plan:
                print("Flight plan supplied but not executed. Add --execute-flight-plan to send it.")
            else:
                for delay_s, command in plan:
                    time.sleep(max(0.0, delay_s))
                    records.append(logger.send_command(seq, command, timeout_s=15.0))
                    seq += 1

        end_time = time.perf_counter() + max(0.0, args.duration)
        while time.perf_counter() < end_time:
            time.sleep(0.1)
    finally:
        command_path, state_path = logger.write_logs(records)
        logger.close()
        print(f"Command log written to {command_path}")
        print(f"State log written to {state_path}")


if __name__ == "__main__":
    main()
