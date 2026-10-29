# ns-3 setup limitations

- Only environment setup, source/API validation, and simple deterministic smoke cases are in scope. No scientific cross-framework comparison is claimed.
- The official ns-3 AODV/OLSR implementations are not the Python R1 AODV-like/OLSR-like abstractions.
- A `RangePropagationLossModel` cutoff is a deterministic topology fixture, not an RF propagation calibration. The current smoke Wi-Fi configuration is not calibrated to AirSim or a real radio.
- The real three-UAV trace is completely connected at 35 m for all 600 frames; it does not exercise a changing multi-hop route.
- The AirSim wall/monotonic trace duration is about 119.791 s while AirSim simulation time is about 118.284 s. Replay uses monotonic time and records the clock-domain difference.
- Python packet events do not define serialized UDP packet size, MAC headers, PHY airtime, or retransmission behavior. A shared explicit traffic schedule is needed for quantitative matching.
- FlowMonitor reports IP-level flow statistics, not PHY delivery, routing control overhead, or necessarily the exact hop metric used by Python.
- Standard validation here is limited to the `simulator` and `wifi-channel-settings` QUICK test suites plus the four custom smoke cases; the full ns-3 test suite was not run.
- Smoke delay and forwarding-derived hop estimates are specific to this fixed-rate, hard-range, 20 s test configuration. The AODV estimate (2.2) is not an exact per-packet route-length assertion.
- CMake optional modules/features not required by the selected experiment modules (GSL, SQLite, LibXML2, Eigen, GTK/visualizer, Python bindings, and docs toolchain) remain disabled.
- Experiment C (AirSim trace replay), experiment D (20-UAV synthetic scenario), multi-seed comparisons, and radio calibration are not performed by the initial smoke suite.
