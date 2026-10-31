#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NS3_DIR="${NS3_DIR:-$HOME/ns3-work/ns-3.49}"
RESULTS="${RESULTS:-$SCRIPT_DIR/ns3_smoke_test_results.csv}"
LOG="${LOG:-$SCRIPT_DIR/ns3_smoke_test.log}"

if [[ ! -x "$NS3_DIR/ns3" ]]; then
    echo "ns-3 wrapper not found at: $NS3_DIR/ns3" >&2
    exit 2
fi

if [[ "$SCRIPT_DIR/ns3_reference_smoke.cc" != "$NS3_DIR/scratch/ns3_reference_smoke.cc" ]]; then
    cp "$SCRIPT_DIR/ns3_reference_smoke.cc" "$NS3_DIR/scratch/ns3_reference_smoke.cc"
fi
printf '%s\n' \
    'profile,scenario,routing,n_nodes,source_destination_distance_m,range_m,simulation_duration_s,packet_size_bytes,offered_packets,application_tx_packets,flow_tx_packets,flow_rx_packets,application_rx_packets,pdr,mean_delay_ms,legacy_integer_mean_delay_ms,times_forwarded,forwarding_based_hops_estimate,undelivered_at_end_packets,control_overhead_packets,seed,result' \
    > "$RESULTS"
: > "$LOG"

run_case() {
    local scenario="$1"
    local routing="$2"
    local profile="${3:-range_limited_wifi}"
    local command_output
    if ! command_output="$("$NS3_DIR/ns3" run \
        "scratch/ns3_reference_smoke --scenario=$scenario --routing=$routing --profile=$profile --seed=20261029" 2>&1)"; then
        printf '%s\n' "$command_output" |
            sed -E 's#(/home/)[^/[:space:]]+#\1<user>#g' >> "$LOG"
        echo "Smoke case failed to execute: $scenario/$routing/$profile" >&2
        return 1
    fi
    printf '%s\n' "$command_output" |
        sed -E 's#(/home/)[^/[:space:]]+#\1<user>#g' >> "$LOG"
    local result_line
    result_line="$(printf '%s\n' "$command_output" | grep '^RESULT,' || true)"
    if [[ -z "$result_line" ]]; then
        echo "No RESULT record emitted for $scenario/$routing/$profile" >&2
        return 1
    fi
    printf '%s\n' "${result_line#RESULT,}" >> "$RESULTS"
}

failures=0
run_case single-hop global || failures=$((failures + 1))
run_case out-of-range global || failures=$((failures + 1))
run_case linear-chain aodv || failures=$((failures + 1))
run_case linear-chain olsr || failures=$((failures + 1))
run_case single-hop global log_distance_wifi || failures=$((failures + 1))

echo "Wrote four ns-3 smoke results to $RESULTS"
echo "Execution log: $LOG"
if [[ "$failures" -ne 0 ]]; then
    echo "$failures smoke case(s) failed; inspect the execution log." >> "$LOG"
    exit 1
fi
