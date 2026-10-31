# Python FANET benchmarks

The Python suite contains routing, channel, unified mobility, metric-contract, sensitivity and baseline comparison experiments. This is general research software, not a manuscript-specific revision package.

```bash
python -m pip install -r benchmarks/python/requirements.txt
bash benchmarks/python/run_all.sh
python -m unittest discover -s benchmarks/python/tests -p 'test_metric_contract.py' -v
```

The runner creates the `raw/`, `logs/`, `summary/` and `figures/` directories and generates benchmark outputs. Historical baseline summaries are retained in `FANET_UAV/`. Analyses can be invoked from this directory:

```bash
python extra/analytical_validation.py
python extra/analytical_topology.py
python extra/calibrated_channels.py
python extra/area_scaling.py
python extra/routing_timestep_sensitivity.py
python extra/audit_and_ci.py
python extra/plot_results.py
```

The legacy `--matrix article` CLI value is preserved for backward compatibility; the program is a generic synthetic/trace benchmark. Python AODV-like/OLSR-like outputs are abstractions, not ns-3 AODV/OLSR packet-level results.
