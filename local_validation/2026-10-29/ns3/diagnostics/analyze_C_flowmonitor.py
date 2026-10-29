#!/usr/bin/env python3
"""Independently reconcile actual Scenario C packet receipts with PROMPT 05.

Uses only standard-library arithmetic. Never writes historical data or runner
runlog/summary files. Student-t intervals describe simulator repeats conditional
on one recorded flight, not independent AirSim flights.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import verify_C_flowmonitor as gate

HERE, REPO, REF = gate.HERE, gate.REPO, gate.REF
OUT = HERE / 'C_flowmonitor_final'
SEEDS = range(20261029, 20261059)
T95_DF29 = 2.045229642132703
ABS_DELAY_MS = 1e-6


def rows(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, records):
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader(); writer.writerows(records)


def number_equal(left, right, tolerance=ABS_DELAY_MS):
    if left == 'NA' or right == 'NA':
        return left == right
    a, b = float(left), float(right)
    return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=0, abs_tol=tolerance)


def interval(values):
    gate.ensure(len(values) == 30, 'Student-t interval requires 30 simulator repeats')
    return statistics.mean(values), T95_DF29 * statistics.stdev(values) / math.sqrt(30)


def baseline_index():
    raw = rows(REF / 'real_airsim_replay/real_airsim_replay_raw.csv')
    selected = [r for r in raw if r['experiment'] == 'C' and r['simulator'] == 'ns-3.49']
    index = {(r['routing'], int(r['repetition_seed'])): r for r in selected}
    gate.ensure(len(selected) == len(index) == 60, 'Duplicate or missing baseline run')
    return index


def baseline_packets():
    index = defaultdict(dict)
    with (REF / 'real_airsim_replay/real_airsim_replay_packet_audit.csv').open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['experiment'] == 'C' and r['simulator'] == 'ns-3.49':
                key = (r['routing'], int(r['repetition_seed']))
                gate.ensure(r['packet_id'] not in index[key], 'Duplicate historical packet ID')
                index[key][r['packet_id']] = r
    gate.ensure(len(index) == 60 and all(len(v) == 599 for v in index.values()),
                'Historical packet coverage incomplete')
    return index


METRICS = {
    'generated': ('generated_packets', 'application_generated_packets'),
    'delivered': ('delivered_packets', 'application_unique_delivered_packets'),
    'application_pdr': ('pdr', 'pdr'),
    'delay_ms': ('mean_latency_ms', 'mean_application_delay_ms'),
    'socket_accepted': ('socket_accepted_packets', 'socket_accepted_packets'),
    'socket_rejected': ('socket_rejected_packets', 'socket_rejected_packets'),
    'flowmonitor_tx': ('flowmonitor_tx_packets', 'flowmonitor_tx_packets'),
    'flowmonitor_rx': ('flowmonitor_rx_packets', 'flowmonitor_rx_packets'),
    'flowmonitor_lost': ('flowmonitor_lost_packets', 'flowmonitor_lost_packets'),
    'undelivered_after_drain': ('undelivered_after_drain_packets', 'undelivered_after_drain_packets'),
}


def compare_run(old, new, events, old_packets, traffic):
    result = {'seed': int(new['repetition_seed']), 'routing': new['routing']}
    for label, (old_key, new_key) in METRICS.items():
        result['old_' + label] = old[old_key]
        result['new_' + label] = new[new_key]
        tolerance = ABS_DELAY_MS if label == 'delay_ms' else 1e-12 if label == 'application_pdr' else 0
        result[label + '_unchanged'] = number_equal(old[old_key], new[new_key], tolerance)
    result['corrected_flowmonitor_reported_drops'] = int(new['flowmonitor_reported_drop_packets'])
    result['corrected_flowmonitor_pending_timeout'] = int(new['flowmonitor_pending_timeout_packets'])
    current = {e['packet_id']: e for e in events}
    gate.ensure(len(current) == len(events) == 599, 'Current packet IDs incomplete/duplicated')
    gate.ensure(set(current) == set(old_packets) == set(traffic), 'Packet ID coverage changed')
    mismatches = Counter()
    max_delay_difference = 0.0
    for packet_id, e in current.items():
        old_event, scheduled = old_packets[packet_id], traffic[packet_id]
        for key in ('source_id', 'destination_id'):
            mismatches['schedule'] += e[key] != scheduled[key]
            mismatches['baseline_identity'] += e[key] != old_event[key]
        for key in ('generation_time_s', 'evaluated_at_time_s'):
            mismatches['schedule'] += not number_equal(e[key], scheduled[key], 1e-9)
            mismatches['baseline_identity'] += not number_equal(e[key], old_event[key], 1e-9)
        mismatches['generated'] += e['application_generated'] != old_event['application_generated']
        mismatches['delivery'] += e['delivered_same_id'] != old_event['delivered']
        mismatches['delay'] += not number_equal(e['application_latency_ms'], old_event['latency_ms'])
        if e['application_latency_ms'] != 'NA' and old_event['latency_ms'] != 'NA':
            max_delay_difference = max(max_delay_difference,
                                      abs(float(e['application_latency_ms']) - float(old_event['latency_ms'])))
    for key in ('schedule', 'baseline_identity', 'generated', 'delivery', 'delay'):
        result[f'packet_{key}_mismatches'] = mismatches[key]
    result['packet_delay_max_abs_difference_ms'] = max_delay_difference
    result['packet_ids_checked'] = len(current)
    result['flowmonitor_check_method_old'] = 'CheckForLostPackets(Seconds(0))'
    result['flowmonitor_check_method_corrected'] = 'CheckForLostPackets()'
    primary = ('generated', 'delivered', 'application_pdr', 'delay_ms', 'socket_accepted',
               'socket_rejected', 'undelivered_after_drain')
    result['application_metrics_match'] = all(result[k + '_unchanged'] for k in primary)
    result['packet_metrics_match'] = not any(mismatches.values())
    return result


def collect(out=OUT):
    gate.verify_runs(out / 'main', SEEDS)
    historical_count = gate.verify_frozen(out)
    baseline, packets = baseline_index(), baseline_packets()
    comparison, summaries = [], []
    for seed in SEEDS:
        traffic = {r['packet_id']: r for r in rows(REF / f'real_airsim_replay/inputs/C/traffic_seed_{seed}.csv')}
        paired_schedule = []
        for routing in ('aodv', 'olsr'):
            directory = out / 'main' / f'{routing}_seed_{seed}'
            new = rows(directory / 'summary.csv')[0]
            events = rows(directory / 'packet_events.csv')
            gate.ensure(new['routing'] == routing and int(new['repetition_seed']) == seed,
                        'Directory/run metadata mismatch')
            expected = {'experiment': 'C', 'profile': 'range_limited_wifi', 'coordinate_frame': 'ned',
                        'n_nodes': '3', 'mobility_frames': '600', 'packet_bytes': '256',
                        'warmup_s': '5', 'drain_s': '10', 'scheduled_packets': '599',
                        'ns3_seed': '20261029', 'ns3_run': str(seed - 20261028)}
            for key, value in expected.items():
                gate.ensure(new[key] == value, f'Run metadata mismatch: {key}')
            gate.ensure(number_equal(new['measurement_s'], '119.7909209', 1e-10), 'Wrong measurement window')
            gate.ensure(all(number_equal(e['range_m'], '35', 0) for e in events), 'Wrong range')
            pair = tuple((e['packet_id'], e['source_id'], e['destination_id'],
                          e['generation_time_s'], e['evaluated_at_time_s']) for e in events)
            paired_schedule.append(pair)
            comparison.append(compare_run(baseline[(routing, seed)], new, events,
                                          packets[(routing, seed)], traffic))
            summaries.append(new)
        gate.ensure(paired_schedule[0] == paired_schedule[1], 'Protocols used different traffic')
    gate.ensure(all(r['application_metrics_match'] and r['packet_metrics_match'] for r in comparison),
                'FAILED: application or packet-level baseline mismatch')
    return comparison, summaries, historical_count


def analyze(out=OUT):
    comparison, summaries, historical_count = collect(out)
    write_csv(out / 'C_flowmonitor_comparison.csv', comparison)
    statistics_rows = []
    for routing in ('aodv', 'olsr'):
        selected = [s for s in summaries if s['routing'] == routing]
        compared = [r for r in comparison if r['routing'] == routing]
        pdr, pdr_hw = interval([float(s['pdr']) for s in selected])
        delay, delay_hw = interval([float(s['mean_application_delay_ms']) for s in selected])
        statistics_rows.append({
            'routing': routing, 'simulator_repeats': len(selected), 'independent_recorded_flights': 1,
            'mean_pdr': pdr, 'pdr_student_t95_half_width': pdr_hw,
            'mean_application_delay_ms': delay, 'delay_student_t95_half_width_ms': delay_hw,
            'old_flowmonitor_lost_total': sum(int(r['old_flowmonitor_lost']) for r in compared),
            'corrected_flowmonitor_lost_total': sum(int(s['flowmonitor_lost_packets']) for s in selected),
            'flowmonitor_lost_changed_runs': sum(not r['flowmonitor_lost_unchanged'] for r in compared),
            'pdr_changed_seeds': sum(not r['application_pdr_unchanged'] for r in compared),
            'delay_changed_seeds': sum(not r['delay_ms_unchanged'] for r in compared),
            'delivery_changed_seeds': sum(not r['delivered_unchanged'] for r in compared),
            'packet_delivery_mismatches': sum(r['packet_delivery_mismatches'] for r in compared),
            'packet_delay_mismatches': sum(r['packet_delay_mismatches'] for r in compared),
            'generated_total': sum(int(s['application_generated_packets']) for s in selected),
            'unique_delivered_total': sum(int(s['application_unique_delivered_packets']) for s in selected),
            'socket_accepted_total': sum(int(s['socket_accepted_packets']) for s in selected),
            'socket_rejected_total': sum(int(s['socket_rejected_packets']) for s in selected),
            'flowmonitor_tx_total': sum(int(s['flowmonitor_tx_packets']) for s in selected),
            'flowmonitor_rx_total': sum(int(s['flowmonitor_rx_packets']) for s in selected),
            'undelivered_after_drain_total': sum(int(s['undelivered_after_drain_packets']) for s in selected),
        })
    write_csv(out / 'C_flowmonitor_statistical_summary.csv', statistics_rows)
    # Exact copies: the supplied runner's receipts remain byte-for-byte intact.
    for name in ('runlog.json', 'C_flowmonitor_summary.json'):
        target = out / name
        if target.exists():
            gate.ensure(gate.sha(target) == gate.sha(out / 'main' / name), 'Receipt copy changed')
        else:
            shutil.copyfile(out / 'main' / name, target)
    validations = {
        'status': 'passed', 'actual_main_runs': 60, 'pilot_runs_separate': 2,
        'main_run_counts': dict(Counter(s['routing'] for s in summaries)),
        'seeds': list(SEEDS), 'events_per_run': 599, 'main_packet_rows_checked': 35940,
        'primary_pdr_definition': 'unique_delivered_application_packet_ids / application_generated_packets',
        'source_sha256': gate.EXPECTED_SOURCE, 'supplied_runner_sha256': gate.EXPECTED_RUNNER,
        'preserved_historical_files': historical_count,
        'application_mismatch_runs': sum(not r['application_metrics_match'] for r in comparison),
        'packet_mismatch_runs': sum(not r['packet_metrics_match'] for r in comparison),
        'packet_delay_max_abs_difference_ms': max(r['packet_delay_max_abs_difference_ms'] for r in comparison),
        'flowmonitor_tx_changed_runs': sum(not r['flowmonitor_tx_unchanged'] for r in comparison),
        'flowmonitor_rx_changed_runs': sum(not r['flowmonitor_rx_unchanged'] for r in comparison),
        'flowmonitor_lost_changed_runs': sum(not r['flowmonitor_lost_unchanged'] for r in comparison),
        'flowmonitor_lost_is_not_tx_minus_rx_or_application_loss': True,
        'flowmonitor_pending_timeout_definition': 'lostPackets - sum(packetsDropped)',
        'delay_comparison_absolute_tolerance_ms': ABS_DELAY_MS,
        'pdr_comparison_absolute_tolerance': 1e-12,
        'confidence_interval': {'distribution': 'Student-t', 'confidence': 0.95,
            'df': 29, 'critical_value': T95_DF29, 'measure': 'half width of per-run mean'},
        'sampling_scope': '30 simulator repeats per protocol conditional on one recorded AirSim flight',
        'runner_summary_sha256': gate.sha(out / 'main/C_flowmonitor_summary.json'),
        'runner_runlog_sha256': gate.sha(out / 'main/runlog.json'),
        'statistics': statistics_rows,
        'execution': gate.read_json(out / 'main_validation.json'),
        'existing_tests': gate.read_json(out / 'existing_tests.json'),
    }
    if (out / 'final_tests.json').exists():
        tests = gate.read_json(out / 'final_tests.json')
        gate.ensure(all(t['exit'] == 0 for t in tests), 'Final tests failed')
        validations['final_tests'] = tests
        validations['final_test_count'] = sum(t['tests'] for t in tests)
    if (out / 'original_workspace_preservation.json').exists():
        preservation = gate.read_json(out / 'original_workspace_preservation.json')
        gate.ensure(preservation['status'] == 'passed', 'Original workspace changed')
        validations['original_workspace_preservation'] = preservation
    gate.save(out / 'C_flowmonitor_validation.json', validations)
    print(json.dumps(statistics_rows, indent=2), flush=True)


def manifest(out=OUT):
    lines = []
    for p in sorted(out.rglob('*')):
        if p.is_file() and p.name != 'C_flowmonitor_sha256_manifest.txt':
            lines.append(f'{gate.sha(p)}  {p.relative_to(out).as_posix()}')
    for p in (HERE / 'run_C_corrected_flowmonitor.py', Path(__file__), HERE / 'verify_C_flowmonitor.py',
              HERE / 'test_C_flowmonitor_final.py', REF / 'ns3_fanet_reference.cc'):
        if p.is_file():
            lines.append(f'{gate.sha(p)}  {Path(os.path.relpath(p, out)).as_posix()}')
    (out / 'C_flowmonitor_sha256_manifest.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    if args.manifest_only:
        manifest(args.output)
    else:
        analyze(args.output)
