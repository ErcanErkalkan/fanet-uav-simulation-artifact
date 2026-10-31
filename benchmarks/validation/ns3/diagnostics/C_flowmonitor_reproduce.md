# Scenario C corrected FlowMonitor reproduction

All commands below run inside WSL Ubuntu, from the repository root. Requirements:
Python 3.12 standard library, Git, and the existing built ns-3.49 installation.
The source in `scratch/ns3_fanet_reference.cc` must already match SHA-256
`BDEDB8C09FDE29B9146C82E8B28512D6E995FD1DC495C7F9E4087B17145AA840`.
The scripts refuse mismatching source bytes. No traffic is generated.

```bash
git switch revision/simpat-2026-validation
repo_root=$(git rev-parse --show-toplevel)
ns3_root="$HOME/ns3-work/ns-3.49"
diagnostics="$repo_root/local_validation/2026-10-29/ns3/diagnostics"
export PYTHONDONTWRITEBYTECODE=1

# Use the independent test commands below to check the recorded final evidence.
```

The published final-tests log already exists and is preserved. To rerun without
overwriting it, use the independent unittest commands instead:

```bash
python3 -B -m unittest discover -s revisions/2026-10-29/tests -v
python3 -B -m unittest discover -s local_validation/2026-10-29/ns3/tests -v
python3 -B -m unittest discover -s "$diagnostics" -p test_prompt06_diagnostics.py -v
python3 -B -m unittest discover -s "$diagnostics" -p test_C_flowmonitor_final.py -v
```

For a **new** pilot and 60-run experiment, keep the recorded final directory and
choose a fresh output directory. These commands use the supplied runner through
the gate wrapper; they do not change its bytes. The wrapper records the actual
ns-3 stdout receipts and stops on any pilot or test failure.

```bash
output="$diagnostics/C_flowmonitor_new_$(date -u +%Y%m%dT%H%M%SZ)"
python3 -B "$diagnostics/verify_C_flowmonitor.py" preflight --ns3-root "$ns3_root" --output "$output"
python3 -B "$diagnostics/verify_C_flowmonitor.py" existing-tests --output "$output"
python3 -B "$diagnostics/verify_C_flowmonitor.py" pilot --ns3-root "$ns3_root" --output "$output"
python3 -B "$diagnostics/verify_C_flowmonitor.py" main --ns3-root "$ns3_root" --output "$output"
python3 -B "$diagnostics/analyze_C_flowmonitor.py" --output "$output"
```

After the pilot has independently passed, the original runner can also be invoked
directly for the 60 main runs with a fresh directory:

```bash
python3 "$diagnostics/run_C_corrected_flowmonitor.py" \
  --repo-root "$repo_root" --ns3-root "$ns3_root" \
  --output "$diagnostics/C_direct_new_$(date -u +%Y%m%dT%H%M%SZ)"
```

The independent analysis uses per-run summaries and all 35,940 main packet rows;
it retains FlowMonitor lostPackets directly instead of substituting Tx minus Rx.
Student-t intervals use 30 per-run means and df=29. Delay comparison uses an
absolute tolerance of 1e-6 ms, with an observed final maximum difference of 0 ms.

The supplied `runlog.json` and `C_flowmonitor_summary.json` are immutable receipts.
The richer independent validation is in `C_flowmonitor_validation.json`.
