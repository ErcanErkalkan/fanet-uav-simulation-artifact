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
- Use `monotonic_time_s` as the ns-3 replay clock, relative to its first sample; schedule WaypointMobilityModel updates from the measured common coordinates. Convert NED down-positive z to Cartesian up-positive z by sign inversion; horizontal axes may be retained because the selected isotropic model depends on Euclidean distance.
- Run ns-3 AODV and OLSR independently over identical mobility and application schedules. Start with an equal total 5 packet/s schedule; record each source/destination pair and packet timestamp.
- Under 35 m binary range, all pairs are in range in the source trace. Do not claim multi-hop performance from this case. Wireless PHY parameters remain uncalibrated unless separate AirSim radio measurements are provided.

## D. Twenty-UAV synthetic configuration

- Match the R1 baseline values: 20 UAVs, 35 m abstract range, medium speed profile, random-waypoint family, 30 s duration, 1 s R1 observation interval, and 5 packets per interval (5 packets/s total).
- R1 synthetic area default is 120 m × 120 m × 50 m. The inspected R1 implementation samples target positions within the area, samples a 3D target-speed magnitude of 1.0–2.4 m/s, advances/clips positions at 1 s updates, and picks a new target within 2 m. ns-3 `RandomWaypointMobilityModel` is not identical to this update/speed/boundary process; use an explicit imported R1 trace or a custom ns-3 mobility model before claiming movement equivalence.
- Use a declared seed/run matrix and identical application generation schedules across routing implementations. Do not equate Python and ns-3 RNG streams.

## Execution order

1. Build and verify the selected ns-3 modules and run short core/Wi-Fi test suites.
2. From Windows PowerShell, run `.\run_ns3_smoke_tests.ps1`; it stages the C++ source into the WSL Linux scratch directory because the Google Drive volume is not mounted inside WSL.
3. Validate the scenario driver against A/B smoke expectations before implementing trace ingestion.
4. Implement C and D as separate experiment drivers, validating inputs and schedule equivalence before collecting results.
5. Only after radio parameters and traffic are calibrated/matched should a cross-framework comparison be interpreted quantitatively.

No experiment C or D result is generated in this setup phase.
