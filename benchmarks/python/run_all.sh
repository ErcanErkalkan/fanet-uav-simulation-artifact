#!/usr/bin/env bash
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
cd "$D"
mkdir -p raw logs summary figures
export PYTHONHASHSEED=0
for cmd in baseline routing statistical wireless unified; do
  echo "START $cmd $(date -u +%FT%TZ)" | tee -a logs/experiment_status.log
  case "$cmd" in
  baseline) (cd raw && python ../src/fanet_simulator_core.py) > logs/baseline.log 2>&1; mv raw/fanet_results.csv raw/baseline_results.csv; if [ -f raw/fanet_latency_plot.png ]; then mv raw/fanet_latency_plot.png figures/baseline_latency_plot.png; fi ;;
  routing) python src/fanet_routing_protocols.py --uavs 5 10 20 --repetitions 30 --duration 120 --dt 1 --communication-range 35 --packets-per-step 5 --seed 2026 --raw-out raw/routing_raw.csv --summary-out summary/routing_summary.csv > logs/routing.log 2>&1 ;;
  statistical) python src/fanet_statistical_sensitivity.py --repetitions 30 --duration 30 --dt 1 --protocol aodv_like_reactive --seed 5100 --raw-out raw/statistical_raw.csv --summary-out summary/statistical_summary.csv > logs/statistical.log 2>&1 ;;
  wireless) python src/fanet_wireless_channel_model.py --uavs 10 20 30 --repetitions 30 --seed-start 1000 --raw-out raw/wireless_raw.csv --summary-out summary/wireless_summary.csv > logs/wireless.log 2>&1 ;;
  unified) python src/fanet_unified_pipeline.py --matrix article --repetitions 30 --seed 7300 --raw-out raw/unified_raw.csv --summary-out summary/unified_summary.csv > logs/unified.log 2>&1 ;;
  esac
  echo "DONE $cmd $(date -u +%FT%TZ)" | tee -a logs/experiment_status.log
done
