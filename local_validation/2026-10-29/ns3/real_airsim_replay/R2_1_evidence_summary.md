# R2.1 evidence summary

## Evidence delivered

- **Independent packet-level reference:** ns-3 3.49 with the standard AODV and OLSR modules; 120 completed runs across C and D.
- **Paired inputs:** 30 traffic/RNG repetitions per condition in the full run, identical packet schedules and mobility coordinate files consumed by ns-3 and the R1 abstractions.
- **C:** protected real AirSim trace, 600 frames, three UAVs; monotonic replay clock; independent 35 m graph validation shows full connectivity in all frames.
- **D:** 20-UAV, 30 s R1-generated mobility input, with matching traffic schedules; mobility and traffic seed files are retained.
- **Measured outputs:** application PDR, packet-level ns-3 delay, FlowMonitor delay/counters, R1 abstraction delay/hops, packet identities, loss accounting, topology counts, and paired Student-t 95% confidence half-widths.

## Results

| Scenario | Simulator | Routing | Mean PDR | PDR 95% half-width | Mean latency (ms) | Latency 95% half-width (ms) |
|---|---|---|---:|---:|---:|---:|
| C | Python_R1_abstraction | aodv | 1.0000 | 0.0000 | 14.8972 | 0.0146 |
| C | Python_R1_abstraction | olsr | 1.0000 | 0.0000 | 14.0540 | 0.0123 |
| C | ns-3.49 | aodv | 0.9957 | 0.0089 | 0.5618 | 0.0042 |
| C | ns-3.49 | olsr | 1.0000 | 0.0000 | 0.5628 | 0.0043 |
| D | Python_R1_abstraction | aodv | 0.5271 | 0.0496 | 33.5949 | 0.9679 |
| D | Python_R1_abstraction | olsr | 0.4796 | 0.0426 | 21.5972 | 0.8035 |
| D | ns-3.49 | aodv | 0.5269 | 0.0419 | 769.7751 | 112.9639 |
| D | ns-3.49 | olsr | 0.2229 | 0.0168 | 14.1199 | 7.0057 |

## Claims and limitations

This evidence demonstrates an executable, reproducible comparison against an independent packet-level network simulator. It does **not** establish physical-model equivalence or calibrated radio accuracy: Python AODV-like/OLSR-like are abstractions, ns-3 AODV/OLSR are standard protocol implementations, and the 35 m cutoff is an uncalibrated topology model. Python latency is model-based; ns-3 latency is packet-level. R1 control counters are abstraction-specific; ns-3 control-message and byte overhead is `NA`. FlowMonitor `lostPackets` is timeout-based and may overlap with Rx; it is not application loss, and application packet identity defines PDR. Socket rejection causes are not inferred. The fully connected C trace is not a multi-hop routing result.

Files: `real_airsim_replay_raw.csv`, `real_airsim_replay_summary.csv`, `real_airsim_replay_packet_audit.csv`, `real_airsim_replay_paired_statistics.csv`, `real_airsim_replay_topology_validation.csv`, `real_airsim_replay_validation.json`, `ns3_experiment_settings.json`, and `real_airsim_replay_experiment_report.md`.
