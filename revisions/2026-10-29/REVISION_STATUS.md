# SIMPAT-D-26-1023 — R1 experimental evidence (2026-10-29)

Status: RESEARCH REVISION IN PROGRESS; NOT AN ACCEPTED OR SUBMISSION-READY REVISION.

Repository: ErcanErkalkan/fanet-uav-simulation-artifact
Related journal manuscript: A Reproducible Python Simulation Framework for FANET-Based UAV Systems with Trace Replay, Routing, and Probabilistic Wireless-Channel Abstractions.

## Provenance and storage
- R0 manuscript and submission PDF are preserved unchanged in the private Google Drive SIMPAT folder.
- R1 working LaTeX, revision master plan, response drafts, and reviewer notes are kept in Google Drive, not in this public repository.
- This versioned public release contains reproducible Python experiments, new sensitivity/analytical checks, summary and raw CSV outputs, figures, script runner, SHA-256 manifest, and full ZIP archive.
- The pre-revision code and published dataset remain in the existing repository paths; R1 is an additive versioned snapshot.
- This experimental package DOES NOT supersede the Zenodo record; no new Zenodo DOI or release is implied.

## Work completed
- Core FANET simulation, routing comparison (30 runs / 120s), statistical sensitivity (30 runs / 30s), probabilistic-vs-binary model comparison (30 runs), and unified synthetic/trace benchmark (30 runs) were executed.
- Analytical binary-connectivity validation, hop-level Monte Carlo checks, routing TTL/update interval sensitivity, time step sensitivity, deployment-area scaling, and channel range/effective-edge sensitivity were executed.
- A live 120-second AirSim Blocks 1.8.1 trajectory was recorded for Drone1/Drone2/Drone3 and independently validated; evidence is under `local_validation/2026-10-29/airsim/`.
- Earlier baseline PDR summary values: 42 of 42 reproduced according to `extra/publication_audit.json`.
- Metric contract tests: 11 of 11 passed in the experiment run log.
- Some metrics and uncertainty intervals have updated definitions; see METRIC_DICTIONARY.csv and student_t_ci95_recomputed.csv.

## Still NOT completed
- ns-3 / OMNeT++ packet-level validation.
- True sub-second discrete-event packet scheduler.
- Final author-approved manuscript edits, final figures/tables, and a complete reviewer response document.

## Reviewer color convention (for private revised manuscript)
- R1 only: BLUE #175CD3
- R2 only: ORANGE #B45309
- Both reviewers: PURPLE #6D28D9

## Reproduction
The complete frozen experiment bundle is provided as `SIMPAT_R1_Full_Experiments_20261029.zip` alongside this README; unpack and run `run_all.sh` from the extracted project directory on a compatible Python installation. See bundle README and ENVIRONMENT for dependencies and notes.
