# FANET UAV simulation artifact — reproducibility status (2026-10-31)

**Research:** A Reproducible Python Simulation Framework for FANET-Based UAV Systems with Trace Replay, Routing, and Probabilistic Wireless-Channel Abstractions  
**Journal tracking ID:** SIMPAT-D-26-1023  
**Public status:** Research software and experimental evidence under validation; **not** a final author-approved journal submission or a new archived software release.

## Authoritative source and scope

- The single authoritative GitHub repository is [fanet-uav-simulation-artifact](https://github.com/ErcanErkalkan/fanet-uav-simulation-artifact); `main` remains its default branch.
- The existing [2026-10-29 experimental snapshot](./) preserves earlier Python simulation and sensitivity evidence.
- The [validation branch](https://github.com/ErcanErkalkan/fanet-uav-simulation-artifact/tree/revision/simpat-2026-validation) additionally contains AirSim/ns-3 reference work. It is **not merged into `main`** as of this record; keeping a validation branch temporarily does not create a second authoritative repository.
- Working manuscript, author/editor correspondence, and review-response documents remain **private** and must not be put in the public repository or GitHub releases.

## Distinguish validation types

### Python simulation and sensitivity tests

The public experimental snapshot includes seeded FANET routing/channel comparisons and numerical sensitivity checks. Python AODV-like and OLSR-like methods are **abstractions**; their outputs must not be presented as results from standards-compliant ns-3 protocol implementations. Reproduction of selected numeric tables is not physical RF calibration.

### AirSim trajectory provenance

The retained original AirSim simulator logger and normalized replay files each contain **1,800 records** from **600 frames** and **three simulated UAVs**. Recorded field values, source hashes, and normalized replay input were independently compared in the project audit. The replay time was shifted to a zero origin. This is one fixed simulator-generated trajectory, **not a measured physical UAV flight**, and the provenance check did **not** rerun AirSim. Repeated network seeds over the same trace are not independent flights.

### ns-3 packet evidence

The connected private evidence archive contains a packet-level audit covering **89,880 records** across **240 run identifiers** and **eight scenario/simulator/routing condition groups**. In a separate audit, PDR, delivered-packet mean delay, and Student-t 95% confidence-interval half-widths were recalculated from retained CSV data; reported differences were at output-rounding precision. These calculations **do not constitute newly executed ns-3 simulations**. The network reference environment is documented as ns-3.49, and scenario C/D comparisons are conditional on their specified mobility and traffic inputs.

## Known limitations and release gates

1. Check hashes and provenance for the **complete** new C/D 30-seed input/output trees, beyond the selected retained audit records.
2. Confirm licenses, permissible redistribution, environment/test commands, and separation of public source from private editorial materials.
3. Reconcile `main` and `revision/simpat-2026-validation` only after reviewing the full change set and completing tests. No force-push or branch deletion should be necessary.
4. Validate a consistent public release tag, README, `CITATION.cff`, Zenodo metadata, code commit, and dataset checksums.
5. The existing [Zenodo 1.0.0 archive](https://doi.org/10.5281/zenodo.20369732) is a **baseline**. It does not document the entire newer AirSim/ns-3 evidence snapshot. No new Zenodo DOI, version, or completed synchronization is claimed.
6. Editorial submission and author declarations are outside this public software repository.

**Interpretation:** The current evidence supports reproducibility checks for stored simulator traces and selected packet-level aggregates. It does not by itself establish a calibrated physical wireless channel, independent AirSim-flight repetitions, or an immutable public archive of all post-review experiments.
