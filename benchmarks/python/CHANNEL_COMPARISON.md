# Binary-range and probabilistic wireless-channel sensitivity

This study evaluates how candidate connectivity, link eligibility, sampled hop delivery, and graph density affect modeled FANET packet delivery. It does **not** calibrate a real RF receiver or establish physical superiority of one wireless technology.

## Reproduction source

- Generator: [`extra/calibrated_channels.py`](extra/calibrated_channels.py)
- Published results: [`extra/calibration_summary.csv`](extra/calibration_summary.csv)
- Archived software snapshot: [Zenodo v1.1.0](https://doi.org/10.5281/zenodo.23830334)

The experiment uses 10, 20 and 30 UAV nodes, each with 30 common synthetic mobility and traffic seeds. Five packets are scheduled per topology frame. Mode-specific Bernoulli success draws have different random-number streams, even though trajectories and traffic schedules are shared.

## Intervention definitions

| Mode | Candidate links | Radio eligibility threshold | Packet success | Physical interpretation |
| --- | --- | --- | --- | --- |
| `binary_35m` | Distance <= 35 m | Not used | Deterministic in-range | Binary graph baseline |
| `wireless_unrestricted` | All pairs eligible for link-quality evaluation | Applied | Bernoulli per hop | No hard geographic cap |
| `wireless_35m_cap` | Distance <= 35 m | Applied | Bernoulli per hop | Cap and reliability gate both active |
| `wireless_same_binary_candidates` | Exactly binary 35 m pairs | **Not applied** | Bernoulli per hop | Candidate-edge identity held fixed |
| `wireless_edge_count_matched` | Reliability-eligible wireless pairs sorted by reliability; top K where K is binary-edge count | Applied | Bernoulli per hop | Frame-wise edge budget targeted, link identities and range **not** fixed |

The top-K mode selects up to K edges; if fewer qualifying wireless edges exist, exact equality need not hold. Mean graph-edge counts are not equivalent to matched link budgets, per-frame node degrees, or path-loss measurements.

## PDR and network size

Each entry below is the published mean paired wireless-minus-binary PDR difference ± two-sided Student-t 95% confidence-interval **half-width** over 30 seeds.

| UAVs | Unrestricted | 35 m capped | Identical binary candidate pairs | Edge-count matched |
| ---: | ---: | ---: | ---: | ---: |
| 10 | +0.3658 ± 0.0448 | -0.2860 ± 0.0279 | -0.3313 ± 0.0352 | +0.2196 ± 0.0251 |
| 20 | +0.0238 ± 0.0306 | -0.5067 ± 0.0255 | -0.7169 ± 0.0272 | +0.0987 ± 0.0301 |
| 30 | -0.0542 ± 0.0120 | -0.3951 ± 0.0232 | -0.8191 ± 0.0137 | +0.0122 ± 0.0093 |

At 20 UAVs, the binary 35 m graph has 45.65 mean edges and PDR 0.88356. The unrestricted wireless graph has 68.26 mean edges, **46.17 outside 35 m**, and PDR 0.90733. The capped wireless graph retains 22.09 edges and PDR 0.37689. Using the exact binary candidate pairs retains 45.65 edges but yields PDR 0.16667 with sampled per-hop delivery. The matched-count top-K condition retains 45.50 edges and PDR 0.98222, but **31.83 mean edges (69.96%) are beyond 35 m**. Therefore edge-count matching is not range matching.

The unrestricted contrast changes sign between 10 and 30 UAVs, rejecting an unconditional PDR superiority claim. The standalone binary-versus-wireless benchmark and this five-mode paired sensitivity study have **different experiment matrices**; numerical baselines must not be interchanged.

## Data-provenance limitations

The versioned v1.1.0 release includes the generator and 15-condition summary. The **seed-level `extra/calibration_raw.csv` was not present in the v1.1.0 tagged file tree** during source review. Thus the published paired-interval half-widths are available from the summary and their calculation is specified by source code, but an independent recomputation from a published per-seed raw CSV is not claimed. Re-running the script is a separate experiment requiring the documented Python environment.

The wireless model is a synthetic abstraction. In particular, millisecond-scale model latency is not equivalent to measured packet-level network delay. No received-signal-strength, radio-link-budget, or hardware RF calibration is implied.
