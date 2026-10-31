# ns-3 reference experiment plan

## Scope and comparison boundary

The ns-3 implementation is a separate packet-level reference, not a port of the R1 abstract simulator. Python `AODV-like` and `OLSR-like` are custom abstractions; ns-3 `AodvHelper` and `OlsrHelper` install the standard ns-3 AODV and OLSR protocol implementations. No equivalence or calibration is assumed.

Use the R1 AirSim replay's `monotonic_time_s` as the trace replay axis. AirSim simulation timestamps remain provenance and are not rescaled. The observed AirSim trace has 600 samples / 119.791 s monotonic elapsed and 118.284 s AirSim simulation elapsed. Convert common NED coordinates consistently for ns-3 Cartesian mobility; preserve all inter-node distances.

The real three-UAV AirSim trace is fully connected under a 35 m binary cutoff in all 600 frames. It can validate mobility ingestion and direct-link packet behavior, but it is not a multi-hop routing evaluation. Use experiment B for a true two-hop path.

## A. Fixed two-node single-hop UDP

- Two stationary nodes separated by 20 m; hard-cutoff range profile configured to 50 m for the smoke test (35 m for controlled reference runs).
- Ad hoc 802.11g Wi-Fi, fixed 6 Mbps data/control mode, UDP sink/client, low-rate short packet stream.
- Record sent/received packets, PDR, FlowMonitor delay, and forwarding count. Do not interpret the range-only propagation model as calibrated radio behavior.
- Baseline acceptance: all scheduled application packets arrive for the deterministic high-connectivity smoke case.

## B. Three-node linear two-hop UDP

- Nodes at x = 0, 40, and 80 m; 50 m range cutoff. Source and destination are 80 m apart and therefore cannot communicate directly; both adjacent links are 40 m.
- Run standard ns-3 AODV and OLSR separately. Allow route discovery / control convergence before the application stream and retain warm-up time in the simulation.
- Record FlowMonitor end-to-end UDP counters/delay and forwarding count. Confirm no direct source-destination radio edge using the same cutoff model.
- This is a deterministic topology smoke test, not a paper result.

## C. AirSim three-UAV mobility trace

- Ingest the unchanged 19-column real AirSim CSV, 600 frames, three UAVs, `source=airsim`; validate sequence, finite coordinates, and monotonic times before replay.
- Use `monotonic_time_s` as the replay clock, relative to its first sample. The ns-3 driver applies each exact `evaluated_at_time_s` coordinate snapshot to `ConstantPositionMobilityModel` when a packet is generated; it does not interpolate between frames. Convert common NED down-positive z to ns-3 Cartesian up-positive z by sign inversion; this preserves Euclidean distances.
- Run ns-3 AODV and OLSR independently over identical mobility and application schedules. Start with an equal total 5 packet/s schedule; record each source/destination pair and packet timestamp.
- Under 35 m binary range, all pairs are in range in the source trace. Do not claim multi-hop performance from this case. Wireless PHY parameters remain uncalibrated unless separate AirSim radio measurements are provided.

## D. Twenty-UAV synthetic configuration

- Match the R1 baseline values: 20 UAVs, 35 m binary cutoff, 30 s duration, 1 s observation interval, and 5 packets/s total. The actual R1 `SyntheticMobility` implementation initializes a heading and velocity for each UAV and advances it with boundary reflection; it is not RandomWaypoint mobility.
- Generate one R1 mobility CSV per repetition seed and import those exact coordinates into ns-3. R1 synthetic bounds are 120 m × 120 m horizontally and 5–50 m altitude; horizontal speed magnitude is sampled from 1.0–2.4 m/s and vertical velocity independently from -0.5–0.5 m/s. This uses the R1 trace as a shared coordinate input, but the ns-3 driver samples positions at packet evaluation times without interpolation.
- Use a declared seed/run matrix and identical application generation schedules across routing implementations. Do not equate Python and ns-3 RNG streams.

## Execution order

1. Build and verify the selected ns-3 modules and run short core/Wi-Fi test suites.
2. From Windows PowerShell, run `.\run_ns3_smoke_tests.ps1`; it stages the C++ source into the WSL Linux scratch directory because the Google Drive volume is not mounted inside WSL.
3. Validate the scenario driver against A/B smoke expectations before implementing trace ingestion.
4. Run C and D through the shared paired driver after input, packet-identity, topology, and deterministic-seed checks pass.
5. Treat reported Python latency as model-based and ns-3 latency as packet-level. Do not infer physical superiority until PHY/channel calibration and metric equivalence are established.

No experiment C or D result is generated in this setup phase.
