# Independent simulator validation

- `airsim/` contains the source three-UAV trajectory and acquisition settings.
- `real_airsim_replay/` contains code, deterministic traffic, and outputs from replay of that AirSim trajectory in the Python FANET model.
- `ns3/` contains paired ns-3.49 run driver, deterministic traffic/mobility inputs and packet-level evidence and diagnostics.

AirSim requires its own Unreal/Blocks simulator setup. Running ns-3 simulations requires the documented ns-3.49 implementation and toolchain. Reading CSV outputs is only a provenance/statistical audit, not simulation rerun.

See [DATA_PROVENANCE.md](../../DATA_PROVENANCE.md) for model, confidence-interval and physical interpretation limits.
