# SIMPAT-D-26-1023 — Executed R1 publication experiment package

This folder contains runnable Python scripts, the *AirSim-compatible sample* trajectory, full R1 journal benchmark CSV reruns, new reviewer-oriented synthetic experiments, plot sources, unit tests, and audit evidence.

## Re-run existing journal outputs

From this directory, with Python 3.13+ and optional matplotlib/scipy/pandas installed:

```bash
bash run_all.sh
```

`run_all.sh` executes original benchmark command configurations for routing, statistical sensitivity, wireless-channel, and unified article matrix. `raw/` and `summary/` contain the executed artifacts. The original R0 summary files were **not** overwritten; cross-version audit is in `extra/publication_audit.json`.

## Re-run new reviewer experiments

```bash
python extra/analytical_validation.py
python extra/analytical_topology.py
python extra/calibrated_channels.py
python extra/area_scaling.py
python extra/routing_timestep_sensitivity.py
python extra/audit_and_ci.py
python extra/plot_results.py
```

Run from repo root. `extra/*.csv` contains both per-seed data and summaries. All benchmark runs used Python 3.13.5 in this execution environment, whereas prior artifact README specified Windows Python 3.14; PDR means nevertheless exactly matched 42 original conditions.

## Scientific limits

- This is NOT a complete IEEE 802.11/PHY/MAC or ns-3/OMNeT++ simulation.
- No real AirSim run was collected; the supplied CSV contains `source=airsim-compatible-sample`.
- `routing_timestep_sensitivity.py` changes topology-update resolution, not real millisecond event scheduling.
- Some new comparisons are *calibration sensitivity* tests, not independent physical calibration.
- Reviewer-color classes are in `EXPERIMENT_STATUS.csv` and described in `EXPERIMENT_REPORT_TR.md`.
