# D/AODV delay and route-discovery audit

## Measured delay distribution

The figures below come from packet-level application send and first receive times across all 30 PROMPT 05 seeds (instrumented reruns, same seed/run/input schedule). Application delay is not FlowMonitor delay.

| Delivered packets | Mean (ms) | Median | P90 | P95 | P99 | Max | >100 ms | >500 ms | >1000 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2371 | 767.541035 | 13.998719 | 3477.675743 | 4742.191816 | 10320.508066 | 10330.394640 | 819 | 582 | 424 |

Packet-wise `generation_time_s`, absolute `simulation_send_time_s`, absolute `simulation_receive_time_s`, and delay are retained in `aodv_delay_distribution.csv`. Sensitivity trial event files additionally distinguish arrivals after the 30 s measurement boundary but before simulation termination.

## ns-3.49 AODV implementation evidence

The checked-out ns-3.49 source defaults in `src/aodv/model/aodv-routing-protocol.cc` set `NodeTraversalTime=40 ms`, `NetDiameter=35`, `NetTraversalTime=2.8 s`, `PathDiscoveryTime=5.6 s`, `RreqRetries=2`, `TtlStart=1`, `TtlIncrement=2`, `TtlThreshold=7`, `MaxQueueLen=64`, and `MaxQueueTime=30 s`; `HelloInterval=1 s` and `EnableHello=false`. The route output path queues packets on unresolved routes and begins RREQ discovery. These source settings make route discovery/queueing a plausible delay mechanism. The AODV debug trace is retained separately only if `aodv_ns_log_trace.log` exists.

## Causal conclusion

The baseline mean near 770 ms is an observation, not by itself proof that route discovery, queue timeout, or route invalidation caused the tail. Source defaults describe possible mechanisms, not a per-packet causal attribution. Compare packet timing and the controlled warm-up/drain/range interventions in the accompanying CSVs. No specific mechanism is labeled causal unless a trace establishes the sequence for the affected packet. A queue timeout of 30 s is not evidence that any measured packet waited that long.

The routing table is not sampled in the event path; PHY interference/transmission state is not traced. Physical shortest-path snapshots are independent geometric calculations and are not equivalent to AODV's internal route state.
