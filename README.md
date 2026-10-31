# FANET UAV Simulation Framework

**FANET simulation, UAV mobility replay, routing abstractions, probabilistic wireless channels, and packet-level validation.**

This is a neutral open-source research-software project, independent of any particular journal or manuscript. The intended sole active branch is `main`.

## Framework architecture diagram

[Current FANET framework architecture diagram (Figure 1)](figures/Figure1.jpg) shows configuration inputs, mobility and trace sources, UAV state management, link and routing models, experiment execution, metric collection, and reproducible outputs. The earlier PlantUML schematic and source remain in the repository for provenance; `figures/Figure1.jpg` is the current publication-quality architecture diagram. The image is retained unchanged from its supplied source.

## Project layout

- [`FANET_UAV/`](FANET_UAV/): Python simulator, routing/channel benchmarks, trace replay and optional AirSim/DJI Tello data collection interfaces.
- [`benchmarks/python/`](benchmarks/python/): Python reruns, metric contracts, sensitivity analysis and figures.
- [`benchmarks/validation/airsim/`](benchmarks/validation/airsim/): recorded three-UAV AirSim simulator trajectory.
- [`benchmarks/validation/real_airsim_replay/`](benchmarks/validation/real_airsim_replay/): repeatable Python replay of fixed AirSim mobility.
- [`benchmarks/validation/ns3/`](benchmarks/validation/ns3/): ns-3.49 driver, schedules, packet audit, diagnostics, run records.

## Start

Python 3.13+ is recommended. From the repository root:

```bash
python -m pip install -r requirements.txt
python FANET_UAV/fanet_simulator_core.py
python -m pip install -r benchmarks/python/requirements.txt
python -m unittest discover -s benchmarks/python/tests -p 'test_metric_contract.py' -v
bash benchmarks/python/run_all.sh
```

Full ns-3 and AirSim runs additionally require those simulators installed and configured. Review [benchmark instructions](benchmarks/python/README.md), [validation instructions](benchmarks/validation/README.md), and [provenance and interpretation](DATA_PROVENANCE.md).

## Reproducibility boundaries

Python AODV-like/OLSR-like routing models are **abstractions**, whereas ns-3 AODV/OLSR are separate protocol implementations. Python latency is model-based, ns-3 latency packet-level. A 35 m link cutoff is not an experimentally calibrated RF channel.

The AirSim data represents a **recorded simulator trajectory**, not physical flight. Repeated network seeds over that fixed trajectory are not independent flights. DJI Tello support is optional; no Tello telemetry is claimed as validation for the provided comparisons. Recalculation from archived packet CSV is not a newly rerun simulation.

## Archive and citation

**Latest permanently archived release:** [FANET UAV Simulation Framework: Code and Reproducible Benchmarks, v1.1.0](https://doi.org/10.5281/zenodo.23830334), Zenodo DOI **10.5281/zenodo.23830334** (published 2026-10-31).

- [GitHub release v1.1.0](https://github.com/ErcanErkalkan/fanet-uav-simulation-artifact/releases/tag/v1.1.0) provides the versioned project source and retained experimental/validation files.
- [Zenodo v1.1.0](https://doi.org/10.5281/zenodo.23830334) is the immutable archive for that tagged software release.
- [Zenodo v1.0.0](https://doi.org/10.5281/zenodo.20369732) remains available as the historical baseline; it does **not** represent the updated data and code.
- Subsequent edits on GitHub `main` do **not** retroactively change the archived v1.1.0 release; cite the exact software version used.

## License and privacy

MIT for software; CC BY 4.0 for distributed data (`DATA_LICENSE`). Third-party simulators and libraries retain their original licenses. Private author files, editorial correspondence, and reviewer materials are outside the public repository.
