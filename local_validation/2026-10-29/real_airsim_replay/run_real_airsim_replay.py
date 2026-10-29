"""Replay real AirSim motion in the R1 FANET abstraction and write evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
R1_SRC = ROOT / "revisions" / "2026-10-29" / "src"
sys.path.insert(0, str(R1_SRC))

from fanet_unified_pipeline import UnifiedFANETPipeline, distance, load_trace_frames


OUTPUT_DIR = Path(__file__).resolve().parent
TRACE = ROOT / "local_validation" / "2026-10-29" / "airsim" / "airsim_real_3uav_120s.csv"
TIME_COLUMN = "monotonic_time_s"
EXPECTED_NODES = ["Drone1", "Drone2", "Drone3"]
REPETITIONS = 30
BASE_SEED = 20261029
TRAFFIC_SEED_OFFSET = 119913
TRAFFIC_RATE_PPS = 5.0
COMMUNICATION_RANGE_M = 35.0
STUDENT_T_975_DF29 = 2.045229642132703
LINK_MODELS = ("binary", "wireless", "wireless_35m_cap")
ROUTING_PROTOCOLS = ("aodv_like_reactive", "olsr_like_proactive")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"{path.name}: CSV header is missing")
        return list(reader.fieldnames), list(reader)


def validate_source_trace(
    path: Path,
) -> tuple[list[dict[str, str]], dict[str, object], list[dict[str, object]]]:
    expected_columns = [
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
    columns, rows = read_csv_rows(path)
    if columns != expected_columns:
        raise ValueError(f"CSV schema differs from the expected 19-column order: {columns}")
    if len(rows) != 1800:
        raise ValueError(f"Expected 1,800 source rows, found {len(rows)}")

    frames: dict[int, list[dict[str, str]]] = defaultdict(list)
    values_by_vehicle: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        try:
            sequence = int(row["sequence"])
            node = row["node_id"]
            if row["vehicle_name"] != node:
                raise ValueError("vehicle_name differs from node_id")
            if row["source"] != "airsim":
                raise ValueError(f"source is {row['source']!r}, not 'airsim'")
            if row["flight_state"] not in {"Flying", "Landed", "Unknown"}:
                raise ValueError(f"unexpected flight_state {row['flight_state']!r}")
            monotonic = float(row[TIME_COLUMN])
            simulation_ns = int(row["sim_time_stamp_ns"])
            position = [float(row[key]) for key in ("x_m", "y_m", "z_m")]
            velocity = [float(row[key]) for key in ("vx_mps", "vy_mps", "vz_mps")]
            for key in ("time_s", "wall_elapsed_s"):
                if not math.isfinite(float(row[key])):
                    raise ValueError(f"{key} is non-finite")
            if not math.isfinite(monotonic) or simulation_ns <= 0:
                raise ValueError("invalid monotonic or simulation timestamp")
            if not all(math.isfinite(value) for value in position + velocity):
                raise ValueError("non-finite position or velocity")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Source CSV line {row_number}: {exc}") from exc
        frames[sequence].append(row)
        values_by_vehicle[node].append(
            {
                "monotonic": monotonic,
                "sim_ns": simulation_ns,
                "position": position,
                "velocity": velocity,
            }
        )

    if sorted(values_by_vehicle) != EXPECTED_NODES:
        raise ValueError(f"Unexpected vehicles in source trace: {sorted(values_by_vehicle)}")
    if sorted(frames) != list(range(600)):
        raise ValueError("Source frame sequence is not exactly the contiguous range 0..599")
    for sequence, frame_rows in frames.items():
        if len(frame_rows) != len(EXPECTED_NODES):
            raise ValueError(f"Frame {sequence} has {len(frame_rows)} rows")
        names = {row["node_id"] for row in frame_rows}
        if names != set(EXPECTED_NODES):
            raise ValueError(f"Frame {sequence} does not contain all three UAVs")
        times = [float(row[TIME_COLUMN]) for row in frame_rows]
        if max(times) - min(times) > 1e-6:
            raise ValueError(f"Frame {sequence} has inconsistent monotonic timestamps")

    for node, values in values_by_vehicle.items():
        for previous, current in zip(values, values[1:]):
            if current["monotonic"] <= previous["monotonic"]:
                raise ValueError(f"{node} monotonic timestamps are not increasing")
            if current["sim_ns"] <= previous["sim_ns"]:
                raise ValueError(f"{node} AirSim timestamps are not increasing")
    monotonic_start = float(rows[0][TIME_COLUMN])
    monotonic_end = float(rows[-1][TIME_COLUMN])
    simulation_start = min(values[0]["sim_ns"] for values in values_by_vehicle.values())
    simulation_end = max(values[-1]["sim_ns"] for values in values_by_vehicle.values())
    wall_elapsed = max(float(row["wall_elapsed_s"]) for row in rows) - min(
        float(row["wall_elapsed_s"]) for row in rows
    )
    sim_elapsed = (simulation_end - simulation_start) / 1e9
    metadata = {
        "source_file": path.name,
        "source_sha256": sha256_file(path),
        "source": "airsim",
        "source_column_count": len(columns),
        "source_columns": columns,
        "source_row_count": len(rows),
        "frame_count": len(frames),
        "vehicles": EXPECTED_NODES,
        "rows_per_vehicle": {node: len(values) for node, values in values_by_vehicle.items()},
        "sequence_contiguous": True,
        "monotonic_timestamp_strictly_increasing_per_vehicle": True,
        "simulation_timestamp_strictly_increasing_per_vehicle": True,
        "position_and_velocity_finite": True,
        "shared_ned_preserved": True,
        "wall_elapsed_s_from_csv": wall_elapsed,
        "monotonic_elapsed_s": monotonic_end - monotonic_start,
        "air_sim_simulation_elapsed_s": sim_elapsed,
        "simulation_minus_wall_elapsed_s": sim_elapsed - wall_elapsed,
        "replay_time_axis": TIME_COLUMN,
        "replay_time_axis_reason": (
            "Use per-sample monotonic wall-clock time for traffic scheduling; "
            "retain original AirSim simulation nanosecond timestamps as separate "
            "provenance and compare elapsed domains without rescaling."
        ),
    }

    frames_loaded, node_map, source = load_trace_frames(path, time_column=TIME_COLUMN)
    if len(frames_loaded) != 600 or source != "airsim":
        raise ValueError("R1 trace loader did not preserve the 600-frame AirSim trace")
    if set(node_map) != set(EXPECTED_NODES):
        raise ValueError(f"R1 trace loader returned an unexpected node map: {node_map}")
    return rows, metadata, frames_loaded


def derive_one_hz_trace(source_rows: list[dict[str, str]], path: Path) -> list[int]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in source_rows:
        grouped[int(row["sequence"])].append(row)
    original_sequences = sorted(grouped)
    first_time = float(grouped[original_sequences[0]][0][TIME_COLUMN])
    last_time = float(grouped[original_sequences[-1]][0][TIME_COLUMN])
    selected: list[int] = []
    for offset in range(int(math.floor(last_time - first_time)) + 1):
        target = first_time + offset
        sequence = min(
            original_sequences,
            key=lambda seq: abs(float(grouped[seq][0][TIME_COLUMN]) - target),
        )
        if not selected or sequence > selected[-1]:
            selected.append(sequence)
    if len(selected) != 120:
        raise ValueError(f"1 Hz derived trace must contain 120 frames, got {len(selected)}")
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(source_rows[0]))
        writer.writeheader()
        for sequence in selected:
            writer.writerows(grouped[sequence])
    return selected


def validate_binary_topology(frames) -> dict[str, object]:
    pair_values: dict[str, list[float]] = {
        "Drone1-Drone2": [],
        "Drone1-Drone3": [],
        "Drone2-Drone3": [],
    }
    fully_connected_frames = 0
    for frame in frames:
        by_name = {
            EXPECTED_NODES[node.node_id]: node
            for node in frame.nodes
        }
        edges = 0
        for first, second in combinations(EXPECTED_NODES, 2):
            separation = distance(by_name[first], by_name[second])
            pair_values[f"{first}-{second}"].append(separation)
            if separation <= COMMUNICATION_RANGE_M:
                edges += 1
        if edges == 3:
            fully_connected_frames += 1
    return {
        "frames_checked": len(frames),
        "binary_range_m": COMMUNICATION_RANGE_M,
        "possible_undirected_edges": 3,
        "fully_connected_frames": fully_connected_frames,
        "all_600_frames_fully_connected": (
            len(frames) == 600 and fully_connected_frames == 600
        ),
        "pairwise_distance_ranges_m": {
            pair: {"minimum": min(values), "maximum": max(values)}
            for pair, values in pair_values.items()
        },
        "routing_claim_limit": (
            "All pairs are within one hop under the binary 35 m model. These "
            "results do not demonstrate dynamic multi-hop routing success."
        ),
    }


def finite_values(rows: list[dict[str, object]], metric: str) -> list[float]:
    values = []
    for row in rows:
        try:
            value = float(row[metric])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def summarize_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    group_keys = [
        "trace_resolution",
        "link_model",
        "routing_protocol",
        "traffic_rate_pps",
    ]
    metrics = [
        "packet_attempts",
        "delivered_packets",
        "pdr",
        "avg_latency_ms",
        "std_latency_ms",
        "avg_hops",
        "throughput_pps",
        "topology_changes_per_s",
        "initial_active_links",
        "control_packets_per_s",
        "route_discoveries",
        "route_failures",
        "stale_route_failures",
        "packets_without_routing_path",
        "route_discovery_failures",
        "route_recovery_after_flag",
        "channel_failures",
        "failed_wireless_packets_after_routing",
        "mean_link_reliability",
        "mean_sinr_db",
        "energy_mj_per_packet",
        "energy_mj_per_delivered_packet_including_failed_attempts",
        "mean_completed_link_episode_s",
    ]
    groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in group_keys)].append(row)
    summary = []
    for key, subset in sorted(groups.items(), key=lambda item: tuple(map(str, item[0]))):
        result: dict[str, object] = {
            name: value for name, value in zip(group_keys, key)
        }
        result["repetitions"] = len(subset)
        result["confidence_interval"] = "two-sided 95% Student-t across RNG repeats"
        result["confidence_interval_halfwidth"] = True
        for metric in metrics:
            values = finite_values(subset, metric)
            result[f"{metric}_n_valid"] = len(values)
            if not values:
                result[f"{metric}_mean"] = "NA"
                result[f"{metric}_sd"] = "NA"
                result[f"{metric}_t95_halfwidth"] = "NA"
            else:
                result[f"{metric}_mean"] = statistics.mean(values)
                result[f"{metric}_sd"] = (
                    statistics.stdev(values) if len(values) > 1 else "NA"
                )
                if len(values) == REPETITIONS:
                    result[f"{metric}_t95_halfwidth"] = (
                        STUDENT_T_975_DF29
                        * statistics.stdev(values)
                        / math.sqrt(REPETITIONS)
                    )
                else:
                    result[f"{metric}_t95_halfwidth"] = "NA"
        summary.append(result)
    return summary


def save_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_scenarios(trace_path: Path, resolution: str, repetitions: int):
    from argparse import Namespace

    source, dt = "trace", 0.2
    return [
        (
            Namespace(
                scenario_name=f"airsim_{resolution}_{link_model}_{routing}",
                source=source,
                trace=trace_path,
                trace_time_column=TIME_COLUMN,
                num_uavs=3,
                duration=120.0,
                dt=dt,
                area_xy=100.0,
                altitude_min=-100.0,
                altitude_max=100.0,
                speed_min=0.0,
                speed_max=0.0,
                communication_range=COMMUNICATION_RANGE_M,
                packets_per_step=1,
                traffic_rate_pps=TRAFFIC_RATE_PPS,
                routing=routing,
                link_model=link_model,
            ),
            link_model,
            routing,
        )
        for link_model in LINK_MODELS
        for routing in ROUTING_PROTOCOLS
    ]


def write_validation_plot(summary: list[dict[str, object]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    resolutions = ("5hz_original", "1hz_derived")
    colors = {"binary": "#175CD3", "wireless": "#D97706", "wireless_35m_cap": "#059669"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for resolution_index, resolution in enumerate(resolutions):
        for link_model in LINK_MODELS:
            for routing in ROUTING_PROTOCOLS:
                row = next(
                    item
                    for item in summary
                    if item["trace_resolution"] == resolution
                    and item["link_model"] == link_model
                    and item["routing_protocol"] == routing
                )
                offset = (
                    (LINK_MODELS.index(link_model) - 1) * 0.12
                    + (ROUTING_PROTOCOLS.index(routing) - 0.5) * 0.035
                )
                x = resolution_index + offset
                pdr = float(row["pdr_mean"])
                pdr_ci = float(row["pdr_t95_halfwidth"])
                latency = float(row["avg_latency_ms_mean"])
                latency_ci = float(row["avg_latency_ms_t95_halfwidth"])
                label = f"{link_model}, {routing.replace('_like_', '/')}"
                axes[0].errorbar(
                    x, pdr, yerr=pdr_ci, fmt="o", capsize=3,
                    color=colors[link_model], label=label,
                )
                axes[1].errorbar(
                    x, latency, yerr=latency_ci, fmt="o", capsize=3,
                    color=colors[link_model], label=label,
                )
    axes[0].set_ylabel("PDR")
    axes[0].set_ylim(0, 1.05)
    axes[1].set_ylabel("Mean model latency (ms)")
    for axis in axes:
        axis.set_xticks(range(len(resolutions)), ["Original 5 Hz", "Derived 1 Hz"])
        axis.grid(alpha=0.25)
    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    fig.legend(unique.values(), unique.keys(), loc="lower center", ncol=3, fontsize=8)
    fig.suptitle("Real AirSim trace replay; 5 packet/s; 95% Student-t half-widths")
    fig.tight_layout(rect=(0, 0.17, 1, 0.93))
    fig.savefig(path, dpi=170)
    plt.close(fig)


def write_methodology(
    path: Path,
    validation: dict[str, object],
    topology: dict[str, object],
    summary: list[dict[str, object]],
) -> None:
    lines = [
        "# Gerçek AirSim izinin FANET R1 pipeline'ında yeniden oynatılması",
        "",
        "## Veri, zaman ekseni ve koruma",
        "",
        f"- Kaynak: `{TRACE.name}`; SHA-256 `{validation['source_sha256']}`.",
        "- Orijinal AirSim CSV'si salt okunur girdi olarak kullanıldı; 19 sütun ve 1.800 satır doğrulandı.",
        "- Ortak NED konumları, hız vektörleri, `source=airsim`, araç adları ve orijinal sıra numaraları değişmeden korundu.",
        f"- Replay saati: `{TIME_COLUMN}` (monotonik kayıt zamanı). AirSim simülasyon nanosanı ayrıca doğrulandı ve kaynakta saklandı.",
        f"- Duvar saati/monotonik zaman aralığı: {validation['monotonic_elapsed_s']:.6f} s; AirSim simülasyon zamanı: {validation['air_sim_simulation_elapsed_s']:.6f} s; fark: {validation['simulation_minus_wall_elapsed_s']:.6f} s.",
        "- Zaman eksenleri birbirine ölçeklenmedi. AirSim simülasyon zamanının duvar saatinden yavaş ilerlemesi simülatör kayıt hızına aittir; replay zamanlaması monotonic kayıttır.",
        "",
        "## Trafik ve kontrollü koşullar",
        "",
        f"- Her koşulda toplam trafik hedefi deterministik zaman tabanlı üreticiyle {TRAFFIC_RATE_PPS:.1f} paket/s; trafik zamanları ilk monotonic kareye göre 0,2 s aralıklarla üretilir.",
        "- Her paket için source-destination çifti `random.Random(traffic_seed)` ile seçildi; `traffic_seed = repetition_seed + 119913`. Trafik RNG'si kanal RNG'sinden ayrıdır, aynı tekrar seed'inde koşullar arasında paket çiftleri eşleşir.",
        "- Bir paket üretim anı iki hareket karesi arasındaysa, routing ve link değerlendirmesi bir sonraki örneklenmiş kare konumunda yapılır; ara-konum interpolasyonu yoktur.",
        "- 1 Hz türetilmiş iz, orijinalden her 1 saniyeye en yakın kare seçilerek oluşturuldu; orijinal CSV değiştirilmedi. Trafik hızı aynı 5 paket/s kaldığından 1 Hz karede yaklaşık beş paket aynı örneklenmiş topoloji/konum üzerinde değerlendirilir.",
        "- 30 RNG tekrarı koşul başına; seed'ler 20261029–20261058. Bunlar 30 bağımsız uçuş değildir; aynı sabit hareket izi üzerinde model RNG tekrarlarıdır.",
        "- Binary 35 m, unrestricted WirelessChannel varsayılan R1 profili ve mevcut R1 kalibrasyon duyarlılık çalışmasındaki 35 m-capped wireless topoloji duyarlılığı kullanıldı. AirSim radyo ölçümleriyle ampirik kalibrasyon bulunmadığından WirelessChannel'ı fiziksel olarak AirSim'e kalibre edilmiş saymıyoruz ve binary-wireless fiziksel üstünlük iddiası kurmuyoruz.",
        "- 35 m-capped profil, wireless link reliability eşiğini ve 35 m aday mesafe sınırını birlikte uygular. R1 `calibrated_channels.py` eşit kenar bütçesi/kapsama duyarlılığı içindir; AirSim'e özgü fiziksel parametre kalibrasyonu değildir.",
        "- AODV-like ve OLSR-like uygulamaları protokol soyutlamalarıdır; ns-3/OMNeT++ protokol yığını değildir.",
        "",
        "## Topoloji ve iddia sınırı",
        "",
        f"- Bağımsız geometrik denetim: {topology['fully_connected_frames']}/{topology['frames_checked']} karede binary 35 m ağı tam bağlı; üç olası kenarın tamamı mevcut.",
        "- Her UAV çifti menzil içinde olduğu için bu iz çok-atlamalı routing faydasını test etmez. AODV/OLSR sonuçları yalnızca doğrudan bağlı topolojideki routing/model davranışıdır.",
        "- PDR %100 iken route flag görülmesi çelişki değildir: `route_failures` ve `route_recovery_after_flag` protokol olaylarıdır; bir flag, geçerli yol bulunduğu veya sonraki paket teslim edildiği halde raporlanabilir. `packets_without_routing_path` yalnızca route kararında geçerli yol bulunamayan paketleri sayar; PDR ise link/channel sonrasındaki teslim oranıdır.",
        "",
        "## İstatistik",
        "",
        f"- Her link-model × routing × iz çözünürlüğü koşulunda n={REPETITIONS} RNG tekrar vardır. Özet CSV, metrik ortalaması, örnek SD ve iki taraflı Student-t %95 güven aralığı yarı genişliğini ayrı sütunlarda verir; df=29, t(0.975,29)={STUDENT_T_975_DF29:.12f}.",
        "- PDR, gecikme, hop, rota, kontrol ve topoloji metrikleri FANET R1 kodunun simülasyon çıktılarıdır; AirSim'den ölçülmüş ağ/PHY gecikmesi, gerçek paket teslimi veya gerçek protokol kontrol trafiği değildir.",
        "",
        "## Deney koşulu özetleri",
        "",
        "| İz | Link modeli | Routing | PDR (ortalama ± t95 yarı genişlik) | Model gecikmesi ms (ortalama ± t95 yarı genişlik) | Ortalama hop | route_failures | packets_without_routing_path | route_recovery_after_flag | control packets/s |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary:
        pdr_ci = row["pdr_t95_halfwidth"]
        latency_ci = row["avg_latency_ms_t95_halfwidth"]
        lines.append(
            "| {trace_resolution} | {link_model} | {routing_protocol} | "
            "{pdr_mean:.4f} ± {pdr_ci} | {latency_mean} ± {latency_ci} | "
            "{hops} | {route_failures:.3f} | {without_path:.3f} | "
            "{recovery:.3f} | {control:.3f} |".format(
                trace_resolution=row["trace_resolution"],
                link_model=row["link_model"],
                routing_protocol=row["routing_protocol"],
                pdr_mean=float(row["pdr_mean"]),
                pdr_ci=f"{float(pdr_ci):.4f}" if pdr_ci != "NA" else "NA",
                latency_mean=f"{float(row['avg_latency_ms_mean']):.3f}",
                latency_ci=(
                    f"{float(latency_ci):.3f}" if latency_ci != "NA" else "NA"
                ),
                hops=(
                    f"{float(row['avg_hops_mean']):.3f}"
                    if row["avg_hops_mean"] != "NA" else "NA"
                ),
                route_failures=float(row["route_failures_mean"]),
                without_path=float(row["packets_without_routing_path_mean"]),
                recovery=float(row["route_recovery_after_flag_mean"]),
                control=float(row["control_packets_per_s_mean"]),
            )
        )
    lines.extend(
        [
            "",
            "## Tekrar üretimi",
            "",
            "Çalıştırma komutu: `python run_real_airsim_replay.py`. Script SHA-256'i, giriş doğrulamalarını, topoloji testini, paket olay planını, RNG seed'lerini, ham run satırlarını, özetleri, grafiği ve kendi çalışma günlüğünü üretir.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUTPUT_DIR / "real_airsim_replay_run.log"
    started = utc_now()
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write(f"Started UTC: {started}\n")
        log.write(f"Input: {TRACE.name}\n")
        log.write(f"Replay time axis: {TIME_COLUMN}\n")
        log.flush()
        try:
            if not TRACE.is_file():
                raise FileNotFoundError(f"Required real AirSim trace not found: {TRACE}")
            source_rows, trace_metadata, trace_frames = validate_source_trace(TRACE)
            topology = validate_binary_topology(trace_frames)
            if not topology["all_600_frames_fully_connected"]:
                raise ValueError("Not all 600 frames are fully connected under binary 35 m")
            log.write(
                f"Input validation passed: sha256={trace_metadata['source_sha256']}; "
                f"frames={trace_metadata['frame_count']}; "
                f"rows={trace_metadata['source_row_count']}\n"
            )
            log.write(
                f"Binary topology: {topology['fully_connected_frames']}/600 "
                "frames fully connected; no multi-hop claim.\n"
            )
            derived_trace = OUTPUT_DIR / "real_airsim_replay_1hz_derived_trace.csv"
            selected_sequences = derive_one_hz_trace(
                source_rows, derived_trace
            )
            raw_rows: list[dict[str, object]] = []
            traffic_schedule: dict[tuple[str, int], list[dict[str, object]]] = {}
            for resolution, trace_path in (
                ("5hz_original", TRACE),
                ("1hz_derived", derived_trace),
            ):
                scenarios = make_scenarios(trace_path, resolution, REPETITIONS)
                for repetition in range(REPETITIONS):
                    seed = BASE_SEED + repetition
                    traffic_seed = seed + TRAFFIC_SEED_OFFSET
                    for scenario_args, link_model, routing in scenarios:
                        pipeline = UnifiedFANETPipeline(scenario_args, seed)
                        pipeline.traffic_seed = traffic_seed
                        pipeline.traffic_rng.seed(traffic_seed)
                        row = pipeline.run_once()
                        row["trace_resolution"] = resolution
                        row["link_model"] = link_model
                        row["routing_protocol"] = routing
                        row["repetition_seed"] = seed
                        row["traffic_seed"] = traffic_seed
                        row["traffic_rate_pps"] = TRAFFIC_RATE_PPS
                        row["trace_time_axis"] = TIME_COLUMN
                        if row["trace_source"] != "airsim":
                            raise ValueError(
                                f"Source label changed during replay: {row['trace_source']!r}"
                            )
                        if row["packet_attempts"] != len(pipeline.packet_events):
                            raise ValueError("Packet event count differs from attempts")
                        if row["packet_attempts"] == 0:
                            raise ValueError("No deterministic traffic packets were generated")
                        schedule_key = (resolution, seed)
                        schedule = pipeline.packet_events
                        previous_schedule = traffic_schedule.get(schedule_key)
                        if previous_schedule is None:
                            traffic_schedule[schedule_key] = schedule
                        elif [
                            (e["generation_time_s"], e["source_node_id"], e["destination_node_id"])
                            for e in previous_schedule
                        ] != [
                            (e["generation_time_s"], e["source_node_id"], e["destination_node_id"])
                            for e in schedule
                        ]:
                            raise ValueError(
                                f"Traffic schedule is not paired across conditions: {schedule_key}"
                            )
                        raw_rows.append(row)
                    if (repetition + 1) % 5 == 0:
                        log.write(
                            f"Completed {resolution} repetition "
                            f"{repetition + 1}/{REPETITIONS} "
                            f"at {utc_now()}\n"
                        )
                        log.flush()

            if len(raw_rows) != 360:
                raise ValueError(f"Expected 360 replay runs, got {len(raw_rows)}")
            summary = summarize_rows(raw_rows)
            if len(summary) != 12:
                raise ValueError(f"Expected 12 summary conditions, got {len(summary)}")
            raw_path = OUTPUT_DIR / "real_airsim_replay_raw.csv"
            summary_path = OUTPUT_DIR / "real_airsim_replay_summary.csv"
            schedule_path = OUTPUT_DIR / "real_airsim_replay_traffic_schedule.csv"
            save_csv(raw_path, raw_rows)
            save_csv(summary_path, summary)
            save_csv(
                schedule_path,
                [
                    {
                        **event,
                        "trace_resolution": resolution,
                        "repetition_seed": seed,
                    }
                    for (resolution, seed), events in sorted(traffic_schedule.items())
                    for event in events
                ],
            )

            plot_path = OUTPUT_DIR / "real_airsim_replay_comparison.png"
            write_validation_plot(summary, plot_path)
            validation = {
                "status": "passed",
                "started_utc": started,
                "finished_utc": utc_now(),
                "input_trace": trace_metadata,
                "time_axis": {
                    "selected": TIME_COLUMN,
                    "air_sim_simulation_timestamp_ns": "retained and validated, not used as replay clock",
                    "wall_elapsed_s": trace_metadata["wall_elapsed_s_from_csv"],
                    "monotonic_elapsed_s": trace_metadata["monotonic_elapsed_s"],
                    "simulation_elapsed_s": trace_metadata["air_sim_simulation_elapsed_s"],
                    "simulation_minus_wall_s": trace_metadata["simulation_minus_wall_elapsed_s"],
                },
                "source_trace_validation": {
                    "all_19_columns_checked": True,
                    "rows": trace_metadata["source_row_count"],
                    "frames": trace_metadata["frame_count"],
                    "rows_per_vehicle": trace_metadata["rows_per_vehicle"],
                    "source_airsim_preserved": True,
                    "node_ids_and_vehicle_names_match": True,
                    "sequence_contiguous": True,
                    "all_positions_and_velocities_finite": True,
                    "monotonic_and_simulation_timestamps_increasing": True,
                    "shared_ned_coordinates_changed": False,
                },
                "binary_topology_validation": topology,
                "traffic": {
                    "generation": "deterministic time-based",
                    "target_packets_per_second_total": TRAFFIC_RATE_PPS,
                    "traffic_seed_rule": "repetition_seed + 119913",
                    "traffic_rng_independent_of_channel_rng": True,
                    "paired_source_destination_schedules_across_models": True,
                    "packet_events_written": sum(
                        len(events) for events in traffic_schedule.values()
                    ),
                    "source_destination_event_file": schedule_path.name,
                },
                "experiment_design": {
                    "link_models": list(LINK_MODELS),
                    "binary_range_m": COMMUNICATION_RANGE_M,
                    "routing_protocols": list(ROUTING_PROTOCOLS),
                    "trace_resolutions": ["5hz_original", "1hz_derived"],
                    "derived_1hz_frames": len(selected_sequences),
                    "rng_repetitions_per_condition": REPETITIONS,
                    "repetition_seed_range": [BASE_SEED, BASE_SEED + REPETITIONS - 1],
                    "repetitions_are_independent_airsim_flights": False,
                    "total_runs": len(raw_rows),
                    "conditions": len(summary),
                    "wireless_physical_calibration_claim": False,
                    "multi_hop_routing_claim": False,
                },
                "statistical_method": {
                    "interval": "two-sided Student-t 95% confidence interval",
                    "reported_quantity": "half-width",
                    "degrees_of_freedom": REPETITIONS - 1,
                    "critical_value": STUDENT_T_975_DF29,
                    "independent_observation_unit": "RNG-seeded replay run on the fixed trace",
                },
                "outputs": {
                    name: name
                    for name in (
                        "real_airsim_replay_raw.csv",
                        "real_airsim_replay_summary.csv",
                        "real_airsim_replay_traffic_schedule.csv",
                        "real_airsim_replay_comparison.png",
                        "real_airsim_replay_methodology.md",
                        "real_airsim_replay_run.log",
                        "R2_5_evidence_summary.md",
                        "real_airsim_replay_validation.json",
                    )
                },
            }
            write_methodology(
                OUTPUT_DIR / "real_airsim_replay_methodology.md",
                trace_metadata,
                topology,
                summary,
            )
            validation_path = OUTPUT_DIR / "real_airsim_replay_validation.json"
            validation_path.write_text(
                json.dumps(validation, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            write_r2_5_summary(
                OUTPUT_DIR / "R2_5_evidence_summary.md",
                validation,
                summary,
            )
            # Include final output file hashes and verify the source remained unchanged.
            validation["outputs_sha256"] = {
                name: sha256_file(OUTPUT_DIR / name)
                for name in (
                    "real_airsim_replay_raw.csv",
                    "real_airsim_replay_summary.csv",
                    "real_airsim_replay_traffic_schedule.csv",
                    "real_airsim_replay_comparison.png",
                    "real_airsim_replay_methodology.md",
                    "R2_5_evidence_summary.md",
                )
            }
            validation["source_hash_after_replay"] = sha256_file(TRACE)
            validation["source_hash_unchanged"] = (
                validation["source_hash_after_replay"]
                == trace_metadata["source_sha256"]
            )
            if not validation["source_hash_unchanged"]:
                raise RuntimeError("Original AirSim CSV SHA-256 changed during replay")
            validation_path.write_text(
                json.dumps(validation, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            log.write(
                f"PASS: {len(raw_rows)} runs; {len(summary)} conditions; "
                f"{validation['traffic']['packet_events_written']} traffic events; "
                f"source sha256 unchanged.\n"
            )
            log.write(f"Finished UTC: {validation['finished_utc']}\n")
            log.flush()
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "runs": len(raw_rows),
                        "conditions": len(summary),
                        "traffic_events": validation["traffic"]["packet_events_written"],
                        "source_sha256": trace_metadata["source_sha256"],
                        "outputs": validation["outputs"],
                    },
                    indent=2,
                )
            )
            return 0
        except Exception:
            log.write(f"FAILED UTC: {utc_now()}\n")
            log.write(traceback.format_exc())
            log.flush()
            raise


def write_r2_5_summary(
    path: Path,
    validation: dict[str, object],
    summary: list[dict[str, object]],
) -> None:
    lines = [
        "# Hakem 2 R2.5 — gerçek AirSim izinden sağlanan kanıt",
        "",
        "Yerel depoda Hakem 2 R2.5 yorumunun tam metni bulunmadığından aşağıdaki kanıt, madde metninin tamamına verilmiş yanıt olarak sunulmamalıdır.",
        "",
        "## Gerçek AirSim hareket izi",
        "",
        f"- Kaynak gerçek AirSim CSV'si: SHA-256 `{validation['input_trace']['source_sha256']}`; 19 sütun, 1.800 satır, 600 kare ve üç UAV.",
        "- `source=airsim`, node kimlikleri, monotonik sıra, sonlu NED konum/hız ve AirSim simülasyon timestamp'leri denetlendi; ortak NED koordinatları oynatma sırasında değiştirilmedi.",
        f"- Replay zamanı `monotonic_time_s`; duvar/monotonik aralık {validation['time_axis']['monotonic_elapsed_s']:.3f} s, AirSim sim zamanı {validation['time_axis']['simulation_elapsed_s']:.3f} s (fark {validation['time_axis']['simulation_minus_wall_s']:.3f} s).",
        "- Binary 35 m menzil altında bağımsız hesaplama 600/600 karede tam bağlantı gösterdi; bu nedenle bu iz çok-atlamalı routing başarısı kanıtlamaz.",
        "",
        "## Replay deneyleri",
        "",
        f"- {validation['experiment_design']['total_runs']} kontrollü model replay'i: üç bağlantı profili (binary 35 m, varsayılan wireless model, wireless 35 m sınır duyarlılığı), AODV-like ve OLSR-like, orijinal 5 Hz ve türetilmiş 1 Hz, koşul başına 30 RNG tekrarı.",
        f"- Her koşulda aynı deterministik 5 paket/s üretici kullanıldı; aynı seed için kaynak-hedef çiftleri koşullar arasında eşleştirildi. 30 tekrar 30 uçuş değildir.",
        "- Wireless profili AirSim radyo ölçümlerine göre ampirik olarak kalibre edilmemiştir; fiziksel binary-vs-wireless üstünlük iddiası yapılmaz. Gecikme, hop, PDR, control/topology ve route event metrikleri R1 soyutlama model çıktılarıdır.",
        "- Koşul bazında PDR, model gecikmesi ve Student-t %95 güven aralığı yarı genişliği aşağıdaki tabloda verilmiştir.",
        "",
        "| İz | Link modeli | Routing | PDR mean | PDR t95 half-width | Model latency ms | Latency t95 half-width |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary:
        lines.append(
            "| {trace_resolution} | {link_model} | {routing_protocol} | "
            "{pdr:.4f} | {pdr_ci} | {latency} | {latency_ci} |".format(
                trace_resolution=row["trace_resolution"],
                link_model=row["link_model"],
                routing_protocol=row["routing_protocol"],
                pdr=float(row["pdr_mean"]),
                pdr_ci=(
                    f"{float(row['pdr_t95_halfwidth']):.4f}"
                    if row["pdr_t95_halfwidth"] != "NA" else "NA"
                ),
                latency=(
                    f"{float(row['avg_latency_ms_mean']):.3f}"
                    if row["avg_latency_ms_mean"] != "NA" else "NA"
                ),
                latency_ci=(
                    f"{float(row['avg_latency_ms_t95_halfwidth']):.3f}"
                    if row["avg_latency_ms_t95_halfwidth"] != "NA" else "NA"
                ),
            )
        )
    lines.extend(
        [
            "",
            "## Sınırlar",
            "",
            "- Hareket ve kinematik kaynakta AirSim gerçeğidir; paket taşınımı AirSim içinde çalıştırılmamıştır.",
            "- R1 route protocols, kanal, gecikme ve PDR metrikleri model tabanlıdır; ns-3/OMNeT++ packet-level doğrulama değildir.",
            "- Üç düğümlü iz tam bağlı olduğundan dinamik multi-hop protokol üstünlüğü hakkında sonuç çıkarılamaz.",
            "- R2.5'in tam metni sağlanırsa kanıtlar yoruma birebir eşlenmelidir.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
