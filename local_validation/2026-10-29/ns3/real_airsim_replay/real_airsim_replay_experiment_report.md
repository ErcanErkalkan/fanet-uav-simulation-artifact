# Paired ns-3.49 / R1 experiment report

**Validation:** passed — 120 ns-3 runs, 30 repetitions per condition.

## Trial-level summary

| Scenario | Simulator | Routing | n | Mean PDR | PDR 95% half-width | Mean latency (ms) | Latency 95% half-width | Latency n | Mean FlowMonitor delay (ms) | FlowMonitor 95% half-width |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C | Python_R1_abstraction | aodv | 30 | 1.0000 | 0.0000 | 14.8972 | 0.0146 | 30 | NA | NA |
| C | Python_R1_abstraction | olsr | 30 | 1.0000 | 0.0000 | 14.0540 | 0.0123 | 30 | NA | NA |
| C | ns-3.49 | aodv | 30 | 0.9957 | 0.0089 | 0.5618 | 0.0042 | 30 | 0.5618 | 0.0042 |
| C | ns-3.49 | olsr | 30 | 1.0000 | 0.0000 | 0.5628 | 0.0043 | 30 | 0.5628 | 0.0043 |
| D | Python_R1_abstraction | aodv | 30 | 0.5271 | 0.0496 | 33.5949 | 0.9679 | 30 | NA | NA |
| D | Python_R1_abstraction | olsr | 30 | 0.4796 | 0.0426 | 21.5972 | 0.8035 | 30 | NA | NA |
| D | ns-3.49 | aodv | 30 | 0.5269 | 0.0419 | 769.7751 | 112.9639 | 30 | 751.1492 | 110.2081 |
| D | ns-3.49 | olsr | 30 | 0.2229 | 0.0168 | 14.1199 | 7.0057 | 30 | 14.1199 | 7.0057 |

PDR confidence intervals use per-repetition PDR values. Latency confidence intervals use the per-repetition mean over delivered packets; unavailable latency remains `NA`. Both are two-sided Student-t intervals; the half-width is shown explicitly.

## Route events and abstract control load

| Scenario | Simulator | Routing | Route failures / run | Discoveries / run | No-path packets / run | Recovery flags / run | R1 model control packets / run |
|---|---|---|---:|---:|---:|---:|---:|
| C | Python_R1_abstraction | aodv | 40.5000 | 43.5000 | 0.0000 | 40.5000 | 174.0000 |
| C | Python_R1_abstraction | olsr | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 513.0000 |
| C | ns-3.49 | aodv | NA | NA | NA | NA | NA |
| C | ns-3.49 | olsr | NA | NA | NA | NA | NA |
| D | Python_R1_abstraction | aodv | 16.4000 | 142.1000 | 70.9333 | 10.4667 | 3044.0000 |
| D | Python_R1_abstraction | olsr | 6.8000 | 0.0000 | 78.0667 | 0.0000 | 1172.7333 |
| D | ns-3.49 | aodv | NA | NA | NA | NA | NA |
| D | ns-3.49 | olsr | NA | NA | NA | NA | NA |

R1 control packet counts are internal abstraction counters, not serialized protocol messages or bytes. ns-3 control-message/byte load is `NA`.

## Packet accounting

| Scenario | Simulator | Routing | Socket accepted / run | Socket rejected / run | FlowMonitor assumed-lost / run | App packets undelivered after drain / run |
|---|---|---|---:|---:|---:|---:|
| C | Python_R1_abstraction | aodv | NA | NA | NA | NA |
| C | Python_R1_abstraction | olsr | NA | NA | NA | NA |
| C | ns-3.49 | aodv | 599.0000 | 0.0000 | 2.6000 | 2.6000 |
| C | ns-3.49 | olsr | 599.0000 | 0.0000 | 0.0000 | 0.0000 |
| D | Python_R1_abstraction | aodv | NA | NA | NA | NA |
| D | Python_R1_abstraction | olsr | NA | NA | NA | NA |
| D | ns-3.49 | aodv | 150.0000 | 0.0000 | 84.7333 | 70.9667 |
| D | ns-3.49 | olsr | 55.2667 | 94.7333 | 21.8333 | 116.5667 |

FlowMonitor Rx differed from application unique-delivery counts in 4 runs (signed aggregate FlowMonitor Rx minus app deliveries: -4). These are separately defined counters; application packet identity is the PDR basis.
ns-3.49 documents FlowMonitor `lostPackets` as packets assumed lost when not reported for 10 seconds; packets queued below IP at simulation end can be counted as lost and may still count toward received or dropped packets. In 30 runs, FlowMonitor lost exceeded max(Tx minus Rx, 0) (by condition: {'D/aodv': 30}). Treat this as a FlowMonitor diagnostic, not as application loss or a complement of Rx. See https://www.nsnam.org/docs/release/3.49/models/html/flow-monitor.html.

## Paired differences

Differences are paired by repetition seed. Positive `ns3_minus_Python_R1` means the ns-3 metric is higher. R1 latency is model-based and ns-3 latency is packet-level; the latency difference is descriptive, not a calibrated physical comparison.

| Scenario | Comparison | Metric | n paired | Mean difference | Student-t 95% half-width |
|---|---|---|---:|---:|---:|
| C | ns3_minus_Python_R1_aodv | pdr | 30 | -0.0043 | 0.0089 |
| C | ns3_minus_Python_R1_aodv | mean_latency_ms | 30 | -14.3354 | 0.0169 |
| C | ns3_minus_Python_R1_olsr | pdr | 30 | 0.0000 | 0.0000 |
| C | ns3_minus_Python_R1_olsr | mean_latency_ms | 30 | -13.4913 | 0.0148 |
| C | ns-3.49_aodv_minus_olsr | pdr | 30 | -0.0043 | 0.0089 |
| C | ns-3.49_aodv_minus_olsr | mean_latency_ms | 30 | -0.0010 | 0.0008 |
| C | Python_R1_abstraction_aodv_minus_olsr | pdr | 30 | 0.0000 | 0.0000 |
| C | Python_R1_abstraction_aodv_minus_olsr | mean_latency_ms | 30 | 0.8432 | 0.0065 |
| D | ns3_minus_Python_R1_aodv | pdr | 30 | -0.0002 | 0.0187 |
| D | ns3_minus_Python_R1_aodv | mean_latency_ms | 30 | 736.1801 | 112.8189 |
| D | ns3_minus_Python_R1_olsr | pdr | 30 | -0.2567 | 0.0366 |
| D | ns3_minus_Python_R1_olsr | mean_latency_ms | 30 | -7.4773 | 6.9385 |
| D | ns-3.49_aodv_minus_olsr | pdr | 30 | 0.3040 | 0.0382 |
| D | ns-3.49_aodv_minus_olsr | mean_latency_ms | 30 | 755.6552 | 114.5234 |
| D | Python_R1_abstraction_aodv_minus_olsr | pdr | 30 | 0.0476 | 0.0111 |
| D | Python_R1_abstraction_aodv_minus_olsr | mean_latency_ms | 30 | 11.9978 | 0.3740 |

## Interpretation boundary

- The AirSim trace uses `monotonic_time_s` for replay and is fully connected under the 35 m graph cutoff for every frame; it is not a multi-hop routing stress case.
- D imports identical R1 `SyntheticMobility` coordinates into ns-3 and Python. It is not RandomWaypoint, and the 30 seeds are reproducible trajectory/traffic replays, not separate flights.
- ns-3 uses standard AODV/OLSR; R1 uses AODV-like/OLSR-like abstractions. They are not identical implementations.
- The 35 m hard range channel is uncalibrated. ns-3 control-message/byte overhead is `NA` because it is not instrumented; R1 control counters are abstraction-specific. A protocol-event flag or socket rejection is not automatically equivalent to a lost application packet.
- See `real_airsim_replay_methodology.md`, `real_airsim_replay_validation.json`, and the packet audit for definitions, input hashes, and run-level accounting.
