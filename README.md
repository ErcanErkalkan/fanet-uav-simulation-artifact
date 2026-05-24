# FANET UAV Simulation Artifact

This repository contains the executable code and reproducible data artifact for a Python-based FANET UAV simulation framework. It excludes manuscript source files, review notes, and writing-only material.

Persistent archive: https://doi.org/10.5281/zenodo.20369732

GitHub repository: https://github.com/ErcanErkalkan/fanet-uav-simulation-artifact

## Contents

- `FANET_UAV/*.py`: simulation, routing, wireless-channel, trace-replay, and optional logging scripts.
- `FANET_UAV/*.csv`: generated raw and summary outputs, sample AirSim-compatible trajectory data, and sample replay outputs.
- `requirements.txt`: optional Python package dependencies.
- `.zenodo.json`: Zenodo release metadata.
- `CITATION.cff`: citation metadata for GitHub and Zenodo.

## Environment

- Tested with Python 3.14 on Windows.
- Core benchmark scripts use only the Python standard library.
- `matplotlib` is optional for the baseline latency plot.
- `airsim` is optional and only required when collecting new AirSim trajectories.

Install optional dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Reproduce Included Outputs

Run commands from the repository root.

### Minimal baseline

```powershell
Push-Location FANET_UAV
python .\fanet_simulator_core.py
Pop-Location
```

Output:

- `FANET_UAV/fanet_results.csv`

### Routing comparison

```powershell
python .\FANET_UAV\fanet_routing_protocols.py `
  --uavs 5 10 20 `
  --repetitions 30 `
  --duration 120 `
  --dt 1 `
  --communication-range 35 `
  --packets-per-step 5 `
  --seed 2026 `
  --raw-out .\FANET_UAV\fanet_routing_raw.csv `
  --summary-out .\FANET_UAV\fanet_routing_summary.csv
```

Outputs:

- `FANET_UAV/fanet_routing_raw.csv`
- `FANET_UAV/fanet_routing_summary.csv`

### Statistical sensitivity

```powershell
Push-Location FANET_UAV
python .\fanet_statistical_sensitivity.py `
  --repetitions 30 `
  --duration 30 `
  --dt 1 `
  --protocol aodv_like_reactive `
  --seed 5100 `
  --raw-out .\fanet_statistical_raw.csv `
  --summary-out .\fanet_statistical_summary.csv
Pop-Location
```

Outputs:

- `FANET_UAV/fanet_statistical_raw.csv`
- `FANET_UAV/fanet_statistical_summary.csv`

### Wireless-channel benchmark

```powershell
python .\FANET_UAV\fanet_wireless_channel_model.py `
  --uavs 10 20 30 `
  --repetitions 30 `
  --seed-start 1000 `
  --raw-out .\FANET_UAV\fanet_wireless_raw.csv `
  --summary-out .\FANET_UAV\fanet_wireless_summary.csv
```

Outputs:

- `FANET_UAV/fanet_wireless_raw.csv`
- `FANET_UAV/fanet_wireless_summary.csv`

### Unified synthetic/trace pipeline

```powershell
python .\FANET_UAV\fanet_unified_pipeline.py `
  --matrix article `
  --repetitions 30 `
  --seed 7300 `
  --raw-out .\FANET_UAV\fanet_unified_raw.csv `
  --summary-out .\FANET_UAV\fanet_unified_summary.csv
```

Outputs:

- `FANET_UAV/fanet_unified_raw.csv`
- `FANET_UAV/fanet_unified_summary.csv`

The matrix includes four scenarios:

- synthetic mobility + binary link model + AODV-like routing
- synthetic mobility + probabilistic wireless link model + AODV-like routing
- AirSim-compatible sample trace + binary link model + AODV-like routing
- AirSim-compatible sample trace + probabilistic wireless link model + AODV-like routing

### AirSim-compatible topology replay

```powershell
Push-Location FANET_UAV
python .\fanet_trace_replay.py `
  --trace .\sample_airsim_trajectory_3uav.csv `
  --range 35 `
  --packets-per-sample 5 `
  --seed 123 `
  --out .\sample_airsim_replay_metrics.csv
Pop-Location
```

Output:

- `FANET_UAV/sample_airsim_replay_metrics.csv`

## Optional External Interfaces

### AirSim trajectory logging

Requires AirSim and a running Unreal/AirSim multirotor environment.

```powershell
python .\FANET_UAV\airsim_trajectory_logger.py `
  --vehicles Drone1 Drone2 Drone3 `
  --duration 30 `
  --sample-period 0.2 `
  --out .\FANET_UAV\airsim_trajectory_3uav.csv
```

### DJI Tello logging

Requires a DJI Tello connected through its SDK Wi-Fi network. Movement commands are not sent unless `--execute-flight-plan` is explicitly provided.

```powershell
python .\FANET_UAV\tello_validation_logger.py `
  --duration 60 `
  --out-dir .\FANET_UAV\tello_run_01
```

## Reproducibility Notes

The included numerical outputs are generated from deterministic seeds and bundled sample data. External AirSim trajectory logs or DJI Tello telemetry logs are not required to reproduce the included CSV outputs.

## License

Code is licensed under the MIT License. Data files are licensed under CC BY 4.0; see `DATA_LICENSE`.

## Citation

Use the metadata in `CITATION.cff` or cite the archived Zenodo record:

Erkalkan, E. (2026). FANET UAV Simulation Artifact. Zenodo. https://doi.org/10.5281/zenodo.20369732
