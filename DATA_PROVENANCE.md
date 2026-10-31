# Data provenance

The retained AirSim simulator recording has 1,800 rows, 600 frames and three UAVs. Original logger SHA-256: `9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3`. The replay CSV is a derived, time-origin-normalized file, not an independent recording. AirSim outputs are simulated motion, not real UAV measurements.

The paired ns-3/Python audit includes a retained 89,880-row packet-event record across 240 run identifiers. Derived PDR and delay can be recomputed from the audit, but doing so does not rerun ns-3 or AirSim. Thirty traffic/RNG seeds on one AirSim trace do not constitute thirty independent flights.

The AODV-like and OLSR-like Python models are abstractions; ns-3 AODV/OLSR are packet-level protocol implementations with different execution semantics. The modeled 35 m cutoff is not a calibrated physical radio model.

The [Zenodo v1.1.0 software release](https://doi.org/10.5281/zenodo.23830334) permanently archives the tagged source snapshot and files distributed in the corresponding GitHub release. The [Zenodo v1.0.0 baseline](https://doi.org/10.5281/zenodo.20369732) remains a distinct earlier version. GitHub `main` may continue to change after v1.1.0 without modifying its permanent archive. For a fully independent simulator re-execution, verify full C/D run trees, source inputs, AirSim/ns-3 versions, hash manifests, and third-party licenses. Retained-output recalculation and complete simulator rerunning are different reproducibility levels.

Source and output CSVs may have separately specified CC BY 4.0 rights. Third-party tools retain their licenses. Public repositories must not contain confidential editorial documents.
