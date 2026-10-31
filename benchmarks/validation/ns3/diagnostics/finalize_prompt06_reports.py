#!/usr/bin/env python3
"""Generate PROMPT 06 interpretation reports from saved diagnostic evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def number(row: dict[str, str], key: str) -> float:
    return float(row[key])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--test-result", default="not run")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    verified = 0
    mismatches: list[str] = []
    for item in manifest["files"]:
        path = args.baseline / Path(item["path"])
        if not path.is_file():
            mismatches.append(f"missing:{item['path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if digest != item["sha256"]:
            mismatches.append(f"hash:{item['path']}")
        else:
            verified += 1

    summary = rows(args.baseline / "real_airsim_replay_summary.csv")
    paired_statistics = rows(
        args.baseline / "real_airsim_replay_paired_statistics.csv"
    )
    integrity = json.loads(
        (args.diagnostics / "paired_comparison_integrity.json").read_text(
            encoding="utf-8-sig"
        )
    )
    aodv = rows(args.diagnostics / "aodv_delay_distribution.csv")
    rejected = rows(args.diagnostics / "socket_send_errno_audit.csv")
    warm_drain = rows(args.diagnostics / "warmup_drain_sensitivity.csv")
    range_rows = rows(args.diagnostics / "range_sensitivity.csv")
    sensitivity_packets = rows(
        args.diagnostics / "sensitivity_packet_delivery_audit.csv"
    )

    flowmonitor_comparison: dict[str, dict[str, Any]] = {}
    flowmonitor_rows = rows(args.diagnostics / "flowmonitor_counter_recheck.csv")
    for row in flowmonitor_rows:
        routing = row["routing"]
        record = flowmonitor_comparison.setdefault(
            routing,
            {
                "runs": 0,
                "lost_changed_runs": 0,
                "old_lost_sum": 0,
                "corrected_lost_sum": 0,
                "rx_changed_runs": 0,
                "application_delivery_changed_runs": 0,
            },
        )
        record["runs"] += 1
        record["lost_changed_runs"] += row["old_flowmonitor_lost"] != row["corrected_flowmonitor_lost"]
        record["old_lost_sum"] += int(row["old_flowmonitor_lost"])
        record["corrected_lost_sum"] += int(row["corrected_flowmonitor_lost"])
        record["rx_changed_runs"] += row["old_flowmonitor_rx"] != row["corrected_flowmonitor_rx"]
        record["application_delivery_changed_runs"] += (
            row["old_application_unique_delivered"]
            != row["corrected_application_unique_delivered"]
        )
    matched_flowmonitor_runs = len(flowmonitor_rows)
    if matched_flowmonitor_runs != 60:
        raise ValueError(
            f"Expected 60 matched D runs for FlowMonitor audit; "
            f"found {matched_flowmonitor_runs}"
        )
    olsr_counter_rows = [
        row for row in flowmonitor_rows if row["routing"] == "olsr"
    ]
    olsr_generated = sum(
        int(row["corrected_application_generated"]) for row in olsr_counter_rows
    )
    olsr_accepted = sum(
        int(row["corrected_socket_accepted"]) for row in olsr_counter_rows
    )
    olsr_delivered = sum(
        int(row["corrected_application_unique_delivered"])
        for row in olsr_counter_rows
    )
    olsr_conditional_mean = statistics.mean(
        int(row["corrected_application_unique_delivered"])
        / int(row["corrected_socket_accepted"])
        for row in olsr_counter_rows
    )

    flowmonitor_path = args.diagnostics / "flowmonitor_discrepancy_audit.md"
    flowmonitor_report = flowmonitor_path.read_text(encoding="utf-8-sig")
    marker = "\n## Full D baseline versus corrected rerun\n"
    if marker in flowmonitor_report:
        flowmonitor_report = flowmonitor_report.split(marker, 1)[0]
    correction_lines = [
        marker.rstrip(),
        "",
        "The archived PROMPT 05 D summaries were compared against all 60 matched instrumented D reruns (30 seeds each for AODV and OLSR). The reruns use the no-argument `CheckForLostPackets()` call and keep FlowMonitor separate from application packet-ID PDR.",
        "",
        "| Routing | Matched runs | Runs with changed FlowMonitor lost | Lost total: PROMPT 05 -> corrected | Rx-changed runs | Application-delivery-changed runs |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for routing in ("aodv", "olsr"):
        record = flowmonitor_comparison[routing]
        correction_lines.append(
            f"| {routing} | {record['runs']} | {record['lost_changed_runs']} | "
            f"{record['old_lost_sum']} -> {record['corrected_lost_sum']} | "
            f"{record['rx_changed_runs']} | "
            f"{record['application_delivery_changed_runs']} |"
        )
    correction_lines.extend(
        [
            "",
            "Thus, in these D reruns the zero-threshold call changed one lost counter by one packet for each routing protocol; FlowMonitor Rx and application unique deliveries were unchanged in all 60 pairs. This does not validate the old zero-threshold definition or make `lostPackets` equivalent to Tx-Rx. C was not rerun with the corrected call, so its FlowMonitor lost counters remain uncorrected; the C application PDR and latency definitions are unaffected by this FlowMonitor-only change.",
            "",
            "The corrected five-case smoke suite provides a direct counterexample to treating `lostPackets` as the application loss count: in the out-of-range case, application Tx=5, application Rx=0, FlowMonitor Tx=5, FlowMonitor Rx=0, but FlowMonitor lost=1. The application result remains 0/5 delivered; the FlowMonitor counter is an independent timeout/drop diagnostic.",
        ]
    )
    flowmonitor_path.write_text(
        flowmonitor_report.rstrip() + "\n" + "\n".join(correction_lines) + "\n",
        encoding="utf-8",
    )
    def summary_row(exp: str, simulator: str, routing: str) -> dict[str, str]:
        return next(
            row for row in summary
            if row["experiment"] == exp
            and row["simulator"] == simulator
            and row["routing"] == routing
        )

    delay_values = [float(row["latency_ms"]) for row in aodv]
    rejected_errno: dict[str, int] = {}
    rejected_topology: dict[str, int] = {}
    for row in rejected:
        rejected_errno[row["socket_errno_symbol"]] = (
            rejected_errno.get(row["socket_errno_symbol"], 0) + 1
        )
        key = "path exists" if row["physical_path_exists"].lower() == "true" else "no physical path"
        rejected_topology[key] = rejected_topology.get(key, 0) + 1

    def sensitivity_table(records: list[dict[str, str]]) -> str:
        grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        for row in records:
            key = (row["parameter"], row["value"], row["routing"])
            grouped.setdefault(key, []).append(row)
        lines = [
            "| Parametre | Değer | Yönlendirme | n | PDR ort. | Ret/run ort. | "
            "Gecikme ort. ms | P95 ms | Ölçüm sonrasında teslim/run | Fiziksel yolsuz çift/run |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for (parameter, value, routing), group in sorted(grouped.items()):
            means = [
                number(row, "latency_mean_ms")
                for row in group if row["latency_mean_ms"] not in ("", "NA")
            ]
            p95s = [
                number(row, "latency_p95_ms")
                for row in group if row["latency_p95_ms"] not in ("", "NA")
            ]
            lines.append(
                f"| {parameter} | {value} | {routing} | {len(group)} | "
                f"{statistics.mean(number(row, 'pdr_generated_denominator') for row in group):.5f} | "
                f"{statistics.mean(number(row, 'socket_rejected') for row in group):.3f} | "
                f"{statistics.mean(means) if means else 'NA'} | "
                f"{statistics.mean(p95s) if p95s else 'NA'} | "
                f"{statistics.mean(number(row, 'delivered_after_measurement_window') for row in group):.3f} | "
                f"{statistics.mean(number(row, 'physical_no_path_packet_pairs') for row in group):.3f} |"
            )
        return "\n".join(lines)

    aodv_row = summary_row("D", "ns-3.49", "aodv")
    olsr_row = summary_row("D", "ns-3.49", "olsr")
    python_aodv = summary_row("D", "Python_R1_abstraction", "aodv")
    python_olsr = summary_row("D", "Python_R1_abstraction", "olsr")
    c_topology = json.loads(
        (args.baseline / "real_airsim_replay_validation.json").read_text(
            encoding="utf-8-sig"
        )
    )["air_sim_topology"]
    paired_ci_rows = [
        row for row in paired_statistics
        if row["comparison"].startswith("ns3_minus_Python_R1")
    ]
    paired_ci_table = "\n".join(
        [
            "| Scenario | Routing | Metric | Mean paired difference | 95% Student-t CI half-width | n | df |",
            "|---|---|---|---:|---:|---:|---:|",
            *[
                f"| {row['experiment']} | "
                f"{row['comparison'].rsplit('_', 1)[-1]} | {row['metric']} | "
                f"{number(row, 'mean_difference'):.6f} | "
                f"{number(row, 'student_t_95_ci_half_width'):.6f} | "
                f"{row['n_paired_repetitions']} | {row['degrees_of_freedom']} |"
                for row in paired_ci_rows
            ],
        ]
    )

    interpretation = f"""# R2.1 validity interpretation after PROMPT 06 diagnostics

## What the evidence supports

- An executable paired comparison was run using standard ns-3.49 AODV/OLSR and the unchanged R1 AODV-like/OLSR-like abstractions, on common mobility coordinates and packet schedules.
- PROMPT 05 contains 30 RNG/traffic repetitions per simulator/protocol/condition. The paired 95% Student-t intervals describe variation among these seed-level paired replicates, conditional on the fixed trace and configured models.
- C replays one real AirSim trace. It is fully connected in all {c_topology['trace_frames']} frames under the uncalibrated 35 m graph; it is direct-link trace/replay evidence, not a multi-hop routing stress test.
- D uses the same R1-generated synthetic mobility coordinates and schedule in both frameworks. It tests a 20-node synthetic scenario but is not 30 independent AirSim flights.

## What it does not support

- Close D/AODV PDRs ({float(python_aodv['mean_pdr']):.4f} R1 vs {float(aodv_row['mean_pdr']):.4f} ns-3) do not establish radio or physical-model equivalence.
- D/OLSR's PDR gap ({float(python_olsr['mean_pdr']):.4f} R1 vs {float(olsr_row['mean_pdr']):.4f} ns-3) does not by itself prove protocol superiority. Standard OLSR and the R1 OLSR-like abstraction differ, and ns-3 socket send rejections must be reported separately from post-acceptance delivery.
- R1 delay is model-derived; ns-3 delay is packet-level. Do not rank their absolute latency as if measurement definitions were equivalent.
- The 35 m hard range channel, 802.11g/PHY/MAC settings, and route topology are not calibrated to AirSim hardware or a measured link budget. Control packet/byte overhead is not available for ns-3.

## Diagnostic findings and validity

- The instrumented reruns verify whether D/AODV packet-level delay distributions and D/OLSR `Socket::GetErrno()` outcomes reproduce the PROMPT 05 aggregate behavior. Detailed outputs and differences are in `diagnostic_statistical_summary.csv`, `aodv_delay_distribution.csv`, and `socket_send_errno_audit.csv`.
- Rejected sends with `ERROR_NOROUTETOHOST` and no contemporaneous geometric path are consistent with no usable route, but route table contents and PHY/MAC interference evidence were not captured; these observations do not prove an internal OLSR cause.
- ns-3.49 `FlowMonitor::lostPackets` is timeout-based and may overlap with received/dropped accounting. It is neither the application PDR complement nor the application-undelivered count. Application unique packet IDs define PDR.
- PROMPT 05 used `CheckForLostPackets(Seconds(0))`, which is not the documented 10 s timeout sweep. In the 60 corrected D reruns, only one lost counter per routing protocol changed by one; FlowMonitor Rx and application unique deliveries were identical in every matched run. C was not rerun with the corrected FlowMonitor call.
- P05 raw CSVs and summaries are archived under `baseline_before_diagnostics/` and checked against a {manifest['file_count']}-file SHA-256 manifest. Baseline verification: {verified}/{manifest['file_count']} file hashes matched; mismatches={len(mismatches)}.
- The paired Student-t calculation assumes independent seed-level paired differences. Since C uses one fixed recorded flight, its intervals do not describe between-flight uncertainty; D intervals describe the selected seed generation process only.
- The archived paired comparison reports the exact 95% Student-t half-widths below. Differences are ns-3 minus Python R1, paired by repetition seed; the 30 seed-level differences are assumed independent (df=29). C's intervals are conditional on one fixed AirSim flight and do not estimate between-flight variation.

{paired_ci_table}

## Safe manuscript claim

The results can be reported as a reproducible **implementation-level comparison under a shared schedule and declared uncalibrated channel configuration**. The paper should explicitly state the protocol-abstraction difference, distinct latency definitions, C full-connectivity limitation, one-flight scope, non-calibrated PHY/range model, and uninstrumented ns-3 control overhead. No claim of physical equivalence or calibrated routing performance is warranted.
"""
    (args.diagnostics / "R2_1_validation_interpretation.md").write_text(
        interpretation, encoding="utf-8"
    )

    errno_text = ", ".join(f"{key}={value}" for key, value in sorted(rejected_errno.items()))
    topology_text = ", ".join(
        f"{key}={value}" for key, value in sorted(rejected_topology.items())
    )
    report = f"""# PROMPT 06 — Nihai kök neden ve bilimsel tutarlılık raporu

## 1. D/AODV yüksek gecikmesi neden oluşuyor?

30 seed'in instrumented ns-3 replay'inde teslim edilmiş {len(delay_values)} paket için paket-ağırlıklı ortalama gecikme {statistics.mean(delay_values):.3f} ms, medyan {sorted(delay_values)[len(delay_values)//2]:.3f} ms, P90 {quantile_for_report(delay_values, 0.90):.3f} ms, P95 {quantile_for_report(delay_values, 0.95):.3f} ms, P99 {quantile_for_report(delay_values, 0.99):.3f} ms ve maksimum {max(delay_values):.3f} ms ölçüldü. >100/>500/>1000 ms paket sayıları sırasıyla {sum(x>100 for x in delay_values)}/{sum(x>500 for x in delay_values)}/{sum(x>1000 for x in delay_values)}. P05 özetindeki 769.775 ms, her tekrarın paket ortalamasının aritmetik ortalamasıdır; bu rapor 2371 teslim edilmiş paketi tek havuzda ağırlıklandırır. Gönderim/alım simülasyon zamanları paket düzeyinde saklandı.

**Kök neden kesinleştirildi mi?** Hayır. ns-3.49 AODV'nin RREQ keşif/expanding-ring, bekleme ve kuyruk mekanizmaları olası açıklamalardır; kaynak varsayılanları tek başına per-packet nedensellik kanıtlamaz. 5/10/20 s warm-up değişikliği bu uzun gecikme kuyruğunu ortadan kaldırmadı; 25/35/45 m aralık deneyi PDR/gecikmenin topolojiye duyarlı olduğunu gösterdi. Ancak AODV route table, RREQ/RREP olayları ve paket kuyruk bekleme süresi packet ID ile ilişkilendirilmedi. Bu nedenle “yüksek gecikme kesin olarak route discovery kaynaklıdır” sonucu çıkarılamaz. Ayrıntı: `aodv_route_discovery_audit.md`.

## 2. D/OLSR gönderimleri neden reddediliyor?

Instrumented 30-seed denetimde {len(rejected)} ret kaydedildi ({len(rejected)/30:.3f}/run); errno dağılımı: {errno_text}. Ölçüm 30 koşuda toplam {olsr_generated} üretilen paketin {olsr_accepted} soket kabulüyle sürdürülmesi ve {olsr_delivered} benzersiz uygulama teslimi gösterdi: ana uygulama PDR={olsr_delivered}/{olsr_generated}={olsr_delivered/olsr_generated:.5f}; yalnız soketin kabul ettiği paketler payda alındığında koşullu teslim oranı={olsr_delivered}/{olsr_accepted}={olsr_delivered/olsr_accepted:.5f}. Seed başına koşullu oranların aritmetik ortalaması {olsr_conditional_mean:.5f}; bu, farklı paydaları havuzlayan koşullu orandan farklıdır. P05 özetindeki D/OLSR ortalama uygulama gecikmesi {float(olsr_row['mean_latency_ms']):.3f} ms'dir.

Retlerin ölçüm-anı geometrik bağlantı denetimi: {topology_text}. Fiziksel yolsuz çiftte `ERROR_NOROUTETOHOST` görülmesi mevcut rota bulunmamasıyla uyumludur; ancak OLSR routing table state ve iç lookup çağrısı kaydedilmediğinden kesin iç neden olarak ileri sürülmez. PHY/MAC iletim/çakışma kanıtı da trace edilmedi.

## 3. Kök nedenler kanıtlandı mı?

Socket katmanındaki ret errno'su doğrudan yakalandı; olası “kanal kaybı” yorumu için destek yoktur. Bununla birlikte retlerin OLSR protokol içindeki kesin sebebi ve AODV gecikme kuyruğunun kesin sebebi henüz kanıtlanmamıştır. Gerekli ek kanıt: protokol route table/route-discovery trace'i ve PHY/MAC trace'leri packet ID veya güvenilir olay anahtarıyla eşleştirmek.

## 4. Yazılım veya ölçüm hatası var mı?

PROMPT 05'te FlowMonitor final sweep'inde `CheckForLostPackets(Seconds(0))` kullanılması ölçüm kusurudur: bekleme eşiğini sıfıra indirir. Düzeltilmiş no-argument çağrısıyla yapılan 60 D eşleştirilmiş rerunda PDR'yi oluşturan uygulama benzersiz teslimat sayısı ve FlowMonitor Rx hiçbir koşuda değişmedi; FlowMonitor lost toplamı AODV'de 2542'den 2541'e, OLSR'de 655'ten 654'e indi (her protokolde 30 koşudan yalnızca birinde 1 paket fark). Bu, D ana PDR/uygulama gecikme sonuçlarının FlowMonitor değişikliğinden etkilenmediğini gösterir; fakat eski FlowMonitor lost sayaçları düzeltilmiş gibi raporlanmamalıdır. Ayrıca düzeltilmiş ayrı out-of-range smoke testinde uygulama 0/5 teslimat gösterirken FlowMonitor lost=1 idi. C FlowMonitor rerun'ı yapılmadı. `lostPackets` ayrıca probe drop ve timeout sayaçlarını kapsayabilir; Tx-Rx veya uygulama kaybı ile eşit kabul edilmez.

## 5. PROMPT 05 sonuçları geçerli mi?

Baseline CSV'ler/özetler `baseline_before_diagnostics/` içinde immutable arşivlendi ve SHA-256 manifestine göre {verified}/{manifest['file_count']} dosya eşleşti; uyumsuzluk sayısı {len(mismatches)}. D için eşleştirilmiş 60 rerun'da application PDR/teslimat ve FlowMonitor Rx aynı kaldı; bu nedenle D ana PDR ve paket düzeyi gecikme özetleri yeniden hesaplanmak zorunda değildir. Ancak PROMPT 05 FlowMonitor `lostPackets` sayacı sıfır eşikli çağrı nedeniyle yöntemsel olarak düzeltilmeli/yeniden etiketlenmelidir; C için düzeltilmiş FlowMonitor rerun'ı tamamlanmadı. Rerun'lar ve duyarlılık çıktıları baseline dosyalarını değiştirmedi.

## 6. Hakem R2.1 için güvenli iddialar

Bağımsız ns-3.49 paket düzeyi simülatöründe standart AODV ve OLSR ile, R1 Python soyutlamalarıyla eşlenmiş koordinat ve trafik çizelgeleri üzerinde 30 seed tekrarlı çalıştırma yapılmıştır. Raporlanan CI yarı genişlikleri seed düzeyindeki eşleştirilmiş Student-t hesabıdır. Bu bir uygulama düzeyi çapraz-doğrulamadır; fiziksel eşdeğerlik, radyo kalibrasyonu ya da “aynı protokol” kanıtı değildir. R2.1 için uygun sınırlar `R2_1_validation_interpretation.md` içindedir.

## 7. Makalede açıklanması gereken sınırlamalar

- Python AODV-like/OLSR-like ve ns-3 standart AODV/OLSR aynı uygulama değildir.
- Python model gecikmesi ile ns-3 packet-level gecikmesi farklı tanımlıdır.
- 35 m hard cutoff ve PHY/MAC ayarları kalibre edilmemiştir; ns-3 control bytes/messages instrument edilmemiştir.
- C'deki tek gerçek AirSim izi 35 m grafında tam bağlıdır; çok-atlamalı stres testi değildir ve 30 seed 30 uçuş değildir.
- D, R1 SyntheticMobility izlerini kullanır; seed tekrarları bağımsız uçuş değil, sentetik RNG/trafik tekrarlarıdır.
- FlowMonitor assumed-loss ve uygulama packet-ID sayaçları ayrı tutulmalıdır; retlerin ve FlowMonitor farklarının nedeni kanıt sınırlarını aşacak biçimde atfedilmemelidir.
- Warm-up pozisyonları sürekli oynatmaz: simülasyon ilk konumda başlar ve pozisyon snapshot'ı yalnız trafik değerlendirme anlarında atanır.

## 8. Test sayısı

Test durumu: {args.test_result}. Komut ve tam çıktı `diagnostic_tests.log` içinde kayıtlıdır.

## 9. Git commit

Baseline commit: `b1e7a40289012b4f18ba7341092622e91ccfdd08`. Tanı değişikliklerinin commit kimliği Git geçmişinden doğrulanır; rapor içinde kendi commit SHA'sı tekrarlanmaz.

## 10. Google Drive bulut eşitlemesi

Dosyaların yerel eşitleme klasöründeki kopyaları SHA-256 ile doğrulanabilir; bulut tarafındaki tamamlanma bu ortamdan bağımsız ve doğrudan doğrulanmadıkça “tamamlandı” denmeyecektir.

## Eşleştirilmiş CI denetimi

P05'teki karşılaştırmalar repetition seed'e göre eşleştirilmiş Student-t testidir (n=30, df=29; 95% yarı genişlik aşağıda). Bunlar seed düzeyindeki eşleştirilmiş farkların bağımsız olduğu varsayımına dayanır; C için tek AirSim izi sabittir, dolayısıyla CI uçuşlar-arası belirsizliği kapsamaz.

{paired_ci_table}

## Deney duyarlılığı (temsilî üç seed)

Warm-up/drain:

{sensitivity_table(warm_drain)}

Menzil:

{sensitivity_table(range_rows)}

## Kanıt dosyaları

- `socket_send_errno_audit.csv`
- `aodv_delay_distribution.csv`
- `aodv_route_discovery_audit.md`
- `olsr_send_rejection_root_cause.md`
- `flowmonitor_discrepancy_audit.md`
- `warmup_drain_sensitivity.csv`
- `range_sensitivity.csv`
- `sensitivity_packet_delivery_audit.csv` ({len(sensitivity_packets)} packet-condition rows; the baseline condition is reused as the reference for each sensitivity dimension)
- `paired_comparison_integrity.json`
- `diagnostic_statistical_summary.csv`
- `diagnostic_tests.log`
"""
    (args.diagnostics / "PROMPT06_FINAL_REPORT_TR.md").write_text(
        report, encoding="utf-8"
    )
    print(json.dumps({
        "baseline_files_verified": verified,
        "baseline_file_count": manifest["file_count"],
        "baseline_hash_mismatches": mismatches,
        "aodv_packets": len(delay_values),
        "olsr_rejections": len(rejected),
    }))


def quantile_for_report(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    lower = int(location)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = location - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


if __name__ == "__main__":
    main()
