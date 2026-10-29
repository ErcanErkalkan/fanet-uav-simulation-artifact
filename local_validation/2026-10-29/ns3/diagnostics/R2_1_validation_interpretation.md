# R2.1 validity interpretation after PROMPT 06 diagnostics

## What the evidence supports

- An executable paired comparison was run using standard ns-3.49 AODV/OLSR and the unchanged R1 AODV-like/OLSR-like abstractions, on common mobility coordinates and packet schedules.
- PROMPT 05 contains 30 RNG/traffic repetitions per simulator/protocol/condition. The paired 95% Student-t intervals describe variation among these seed-level paired replicates, conditional on the fixed trace and configured models.
- C replays one real AirSim trace. It is fully connected in all 600 frames under the uncalibrated 35 m graph; it is direct-link trace/replay evidence, not a multi-hop routing stress test.
- D uses the same R1-generated synthetic mobility coordinates and schedule in both frameworks. It tests a 20-node synthetic scenario but is not 30 independent AirSim flights.

## What it does not support

- Close D/AODV PDRs (0.5271 R1 vs 0.5269 ns-3) do not establish radio or physical-model equivalence.
- D/OLSR's PDR gap (0.4796 R1 vs 0.2229 ns-3) does not by itself prove protocol superiority. Standard OLSR and the R1 OLSR-like abstraction differ, and ns-3 socket send rejections must be reported separately from post-acceptance delivery.
- R1 delay is model-derived; ns-3 delay is packet-level. Do not rank their absolute latency as if measurement definitions were equivalent.
- The 35 m hard range channel, 802.11g/PHY/MAC settings, and route topology are not calibrated to AirSim hardware or a measured link budget. Control packet/byte overhead is not available for ns-3.

## Diagnostic findings and validity

- The instrumented reruns verify whether D/AODV packet-level delay distributions and D/OLSR `Socket::GetErrno()` outcomes reproduce the PROMPT 05 aggregate behavior. Detailed outputs and differences are in `diagnostic_statistical_summary.csv`, `aodv_delay_distribution.csv`, and `socket_send_errno_audit.csv`.
- Rejected sends with `ERROR_NOROUTETOHOST` and no contemporaneous geometric path are consistent with no usable route, but route table contents and PHY/MAC interference evidence were not captured; these observations do not prove an internal OLSR cause.
- ns-3.49 `FlowMonitor::lostPackets` is timeout-based and may overlap with received/dropped accounting. It is neither the application PDR complement nor the application-undelivered count. Application unique packet IDs define PDR.
- PROMPT 05 used `CheckForLostPackets(Seconds(0))`, which is not the documented 10 s timeout sweep. In the 60 corrected D reruns, only one lost counter per routing protocol changed by one; FlowMonitor Rx and application unique deliveries were identical in every matched run. C was not rerun with the corrected FlowMonitor call.
- P05 raw CSVs and summaries are archived under `baseline_before_diagnostics/` and checked against a 105-file SHA-256 manifest. Baseline verification: 105/105 file hashes matched; mismatches=0.
- The paired Student-t calculation assumes independent seed-level paired differences. Since C uses one fixed recorded flight, its intervals do not describe between-flight uncertainty; D intervals describe the selected seed generation process only.
- The archived paired comparison reports the exact 95% Student-t half-widths below. Differences are ns-3 minus Python R1, paired by repetition seed; the 30 seed-level differences are assumed independent (df=29). C's intervals are conditional on one fixed AirSim flight and do not estimate between-flight variation.

| Scenario | Routing | Metric | Mean paired difference | 95% Student-t CI half-width | n | df |
|---|---|---|---:|---:|---:|---:|
| C | aodv | pdr | -0.004341 | 0.008877 | 30 | 29 |
| C | aodv | mean_latency_ms | -14.335398 | 0.016882 | 30 | 29 |
| C | olsr | pdr | 0.000000 | 0.000000 | 30 | 29 |
| C | olsr | mean_latency_ms | -13.491264 | 0.014785 | 30 | 29 |
| D | aodv | pdr | -0.000222 | 0.018737 | 30 | 29 |
| D | aodv | mean_latency_ms | 736.180111 | 112.818856 | 30 | 29 |
| D | olsr | pdr | -0.256667 | 0.036631 | 30 | 29 |
| D | olsr | mean_latency_ms | -7.477301 | 6.938477 | 30 | 29 |

## Safe manuscript claim

The results can be reported as a reproducible **implementation-level comparison under a shared schedule and declared uncalibrated channel configuration**. The paper should explicitly state the protocol-abstraction difference, distinct latency definitions, C full-connectivity limitation, one-flight scope, non-calibrated PHY/range model, and uninstrumented ns-3 control overhead. No claim of physical equivalence or calibrated routing performance is warranted.
