# Data provenance

The retained AirSim simulator recording has 1,800 rows, 600 frames and three UAVs. Original logger SHA-256: `9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3`. The replay CSV is a derived, time-origin-normalized file, not an independent recording. AirSim outputs are simulated motion, not real UAV measurements.

The paired ns-3/Python audit includes a retained 89,880-row packet-event record across 240 run identifiers. Derived PDR and delay can be recomputed from the audit, but doing so does not rerun ns-3 or AirSim. Thirty traffic/RNG seeds on one AirSim trace do not constitute thirty independent flights.

The AODV-like and OLSR-like Python models are abstractions; ns-3 AODV/OLSR are packet-level protocol implementations with different execution semantics. The modeled 35 m cutoff is not a calibrated physical radio model.

The immutable [Zenodo v1.0.0 baseline](https://doi.org/10.5281/zenodo.20369732) is not the current expanded experiment snapshot. Before issuing a new archive, verify full C/D run trees, input data, exact source/runtime versions, hash manifests, license eligibility and the release-to-DOI linkage.

Source and output CSVs may have separately specified CC BY 4.0 rights. Third-party tools retain their licenses. Public repositories must not contain confidential editorial documents.
