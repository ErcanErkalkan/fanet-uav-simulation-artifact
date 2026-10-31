#!/usr/bin/env python3
"""Auditable gates around the unmodified, supplied Scenario C runner.

No traffic generation and no overwriting of completed output directories.
The analysis and tests are separate from the supplied runner's JSON receipts.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
REF = HERE.parent
RUNNER = HERE / 'run_C_corrected_flowmonitor.py'
EXPECTED_RUNNER = '34389574CE70ECDEB55CEA14CD519B8DD1676389132E003095D7864D2896F1A4'
EXPECTED_SOURCE = 'BDEDB8C09FDE29B9146C82E8B28512D6E995FD1DC495C7F9E4087B17145AA840'
EXPECTED_AIRSIM = '9C09B80E19CC6321BA61899565D34CA96EA4D0C02C3B0E0E4F969DD7F93115E3'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def load_runner():
    if sha(RUNNER) != EXPECTED_RUNNER:
        raise ValueError('Supplied runner bytes changed')
    spec = importlib.util.spec_from_file_location('supplied_C_runner', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def historical_files():
    new_names = {RUNNER.name, Path(__file__).name, 'analyze_C_flowmonitor.py',
                 'test_C_flowmonitor_final.py'}
    return sorted(p for p in (REPO / 'local_validation').rglob('*')
                  if p.is_file() and 'C_flowmonitor_final' not in p.parts
                  and '__pycache__' not in p.parts and p.name not in new_names)


def verify_frozen(out):
    frozen = read_json(out / 'historical_sha256_before.json')
    mismatches = [name for name, expected in frozen.items()
                  if not (REPO / name).is_file() or sha(REPO / name) != expected]
    ensure(not mismatches, f'Historical files changed: {mismatches}')
    return len(frozen)


def preflight(ns3, out):
    module = load_runner()
    for path in (REF / 'ns3_fanet_reference.cc', ns3 / 'scratch/ns3_fanet_reference.cc'):
        ensure(sha(path) == EXPECTED_SOURCE, 'Wrong diagnostic source SHA256')
        code = path.read_text()
        ensure('CheckForLostPackets();' in code, 'Missing corrected call')
        ensure(not re.search(r'CheckForLostPackets\s*\(\s*Seconds\s*\(\s*0', code),
               'Zero-threshold call present')
    ensure((ns3 / 'VERSION').read_text().strip() == '3.49', 'Wrong ns-3 version')
    ensure(sha(REPO / 'local_validation/2026-10-29/airsim/airsim_real_3uav_120s.csv')
           == EXPECTED_AIRSIM, 'Original AirSim CSV hash changed')
    branch = subprocess.check_output(['git', '-C', str(REPO), 'branch', '--show-current'], text=True).strip()
    ensure(branch == 'revision/simpat-2026-validation', 'Wrong working branch')
    settings = read_json(REF / 'real_airsim_replay/ns3_experiment_settings.json')
    inputs = REF / 'real_airsim_replay/inputs'
    hashes = settings['input_hashes']['input_csv_sha256']
    for name, expected in hashes.items():
        if name.startswith('C/'):
            ensure(sha(inputs / name) == expected, f'Input hash mismatch: {name}')
    mobility = module.rows(inputs / 'C/airsim_mobility.csv')
    ensure(len(mobility) == 1800 and len({r['node_id'] for r in mobility}) == 3
           and len({r['sequence'] for r in mobility}) == 600, 'Wrong C mobility shape')
    for seed in module.SEEDS:
        rows = module.rows(inputs / f'C/traffic_seed_{seed}.csv')
        ensure(len(rows) == 599 and len({r['packet_id'] for r in rows}) == 599,
               f'Wrong traffic shape: {seed}')
        ensure(all(r['source_id'] != r['destination_id'] for r in rows), 'Self traffic')
    baseline = module.rows(REF / 'real_airsim_replay/real_airsim_replay_raw.csv')
    baseline = [r for r in baseline if r['experiment'] == 'C' and r['simulator'] == 'ns-3.49']
    ensure(len(baseline) == 60 and len({(r['routing'], r['repetition_seed']) for r in baseline}) == 60,
           'Baseline is not 60 unique C runs')
    ensure(not out.exists(), 'New output directory already exists')
    frozen = {p.relative_to(REPO).as_posix(): sha(p) for p in historical_files()}
    out.mkdir(parents=True)
    save(out / 'historical_sha256_before.json', frozen)
    save(out / 'preflight.json', {'status': 'passed', 'historical_files': len(frozen),
         'source_sha256': EXPECTED_SOURCE, 'runner_sha256': EXPECTED_RUNNER,
         'airsim_sha256': EXPECTED_AIRSIM, 'traffic_schedules': 30,
         'events_per_schedule': 599, 'mobility_rows': 1800, 'mobility_frames': 600,
         'nodes': 3, 'branch': branch,
         'base_commit': subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip(),
         'ns3_version': '3.49', 'python_version': sys.version.split()[0],
         'timestamp_utc': datetime.now(timezone.utc).isoformat()})


def run_tests(out, final=False):
    groups = [('R1_metrics_and_real_AirSim', REPO / 'revisions/2026-10-29/tests', 'test_*.py'),
              ('ns3_input_validation', REF / 'tests', 'test_*.py'),
              ('PROMPT06_diagnostics', HERE, 'test_prompt06_diagnostics.py')]
    if final:
        groups.append(('C_flowmonitor_final', HERE, 'test_C_flowmonitor_final.py'))
    records = []
    with (out / ('final_tests.log' if final else 'existing_tests.log')).open('x') as log:
        for name, directory, pattern in groups:
            proc = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover',
                                   '-s', str(directory), '-p', pattern, '-v'],
                                  cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = proc.stdout.replace(str(REPO), '$REPO').replace(str(Path.home()), '$HOME')
            log.write(f'\n{name}\n{output}\n'); log.flush()
            print(f'TEST {name}: exit={proc.returncode}', flush=True)
            match = re.search(r'Ran (\d+) tests?', output)
            records.append({'group': name, 'exit': proc.returncode,
                            'tests': int(match.group(1)) if match else 0})
    save(out / ('final_tests.json' if final else 'existing_tests.json'), records)
    ensure(all(r['exit'] == 0 and r['tests'] > 0 for r in records), 'Test gate failed')


def verify_runs(directory, seeds):
    module = load_runner()
    expected_dirs = {f'{p}_seed_{s}' for s in seeds for p in ('aodv', 'olsr')}
    ensure({p.name for p in directory.iterdir() if p.is_dir()} == expected_dirs,
           'Wrong completed run directory set')
    runlog = read_json(directory / 'runlog.json')
    ensure(len(runlog) == len(expected_dirs) and all(r['exit'] == 0 for r in runlog),
           'Execution receipts incomplete')
    for seed in seeds:
        traffic = module.rows(REF / f'real_airsim_replay/inputs/C/traffic_seed_{seed}.csv')
        traffic = {r['packet_id']: r for r in traffic}
        for protocol in ('aodv', 'olsr'):
            target = directory / f'{protocol}_seed_{seed}'
            summaries = module.rows(target / 'summary.csv')
            events = module.rows(target / 'packet_events.csv')
            ensure(len(summaries) == 1 and len(events) == 599, 'Incomplete run outputs')
            s = summaries[0]
            ensure(int(s['application_generated_packets']) == 599, 'Wrong generated count')
            ensure(len({e['packet_id'] for e in events}) == 599, 'Duplicate event IDs')
            generated = sum(int(e['application_generated']) for e in events)
            delivered = sum(int(e['delivered_same_id']) for e in events)
            accepted = sum(int(e['socket_accepted']) for e in events)
            ensure(generated == 599 and delivered == int(s['application_unique_delivered_packets']),
                   'Event delivery and summary disagree')
            ensure(accepted == int(s['socket_accepted_packets']), 'Socket counts disagree')
            ensure(generated - accepted == int(s['socket_rejected_packets']), 'Rejected counts disagree')
            ensure(generated - delivered == int(s['undelivered_after_drain_packets']), 'Drain counts disagree')
            ensure(math.isclose(delivered / generated, float(s['pdr']), rel_tol=0, abs_tol=1e-12),
                   'PDR is not unique application deliveries / generated')
            delays = [float(e['application_latency_ms']) for e in events if e['delivered_same_id'] == '1']
            ensure(bool(delays) and math.isclose(sum(delays) / len(delays),
                   float(s['mean_application_delay_ms']), rel_tol=0, abs_tol=1e-8), 'Delay accounting failed')
            ensure(int(s['flowmonitor_lost_packets']) == int(s['flowmonitor_reported_drop_packets'])
                   + int(s['flowmonitor_pending_timeout_packets']), 'FlowMonitor components disagree')
            for e in events:
                t = traffic[e['packet_id']]
                ensure(e['source_id'] == t['source_id'] and e['destination_id'] == t['destination_id'],
                       'Traffic endpoints changed')
                for key in ('generation_time_s', 'evaluated_at_time_s'):
                    ensure(math.isclose(float(e[key]), float(t[key]), rel_tol=0, abs_tol=1e-9),
                           'Traffic timeline changed')
    receipt = read_json(directory / 'C_flowmonitor_summary.json')
    ensure(receipt['status'] == 'passed' and receipt['n_runs'] == len(expected_dirs)
           and not receipt['application_mismatches'], 'Runner summary contradicts outputs')


class Tee:
    def __init__(self, stream, ns3):
        self.stream, self.ns3 = stream, ns3

    def write(self, value):
        sys.__stdout__.write(value); sys.__stdout__.flush()
        value = value.replace(str(REPO), '$REPO').replace(str(self.ns3), '$NS3_ROOT')
        value = value.replace(str(Path.home()), '$HOME')
        self.stream.write(value); self.stream.flush()

    def flush(self):
        self.stream.flush()


def execute(ns3, out, pilot):
    ensure(read_json(out / 'preflight.json')['status'] == 'passed', 'Preflight required')
    ensure(all(r['exit'] == 0 for r in read_json(out / 'existing_tests.json')), 'Existing tests required')
    verify_frozen(out)
    module = load_runner()
    if pilot:
        module.SEEDS = (20261029,)
    else:
        ensure(read_json(out / 'pilot_validation.json')['status'] == 'passed', 'Pilot required')
        verify_runs(out / 'pilot', (20261029,))
    phase = 'pilot' if pilot else 'main'
    start = datetime.now(timezone.utc).isoformat()
    with (out / 'C_flowmonitor_execution.log').open('a', encoding='utf-8') as log:
        with contextlib.redirect_stdout(Tee(log, ns3)):
            print(f'{phase.upper()} START {start}', flush=True)
            module.run(REPO, ns3, out / phase)
            verify_runs(out / phase, module.SEEDS)
            frozen_count = verify_frozen(out)
            print(f'{phase.upper()} PASSED; historical files unchanged={frozen_count}', flush=True)
    save(out / f'{phase}_validation.json', {'status': 'passed', 'runs': 2 if pilot else 60,
         'started_utc': start, 'finished_utc': datetime.now(timezone.utc).isoformat(),
         'source_sha256': sha(ns3 / 'scratch/ns3_fanet_reference.cc'),
         'historical_files_unchanged': frozen_count})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('preflight', 'existing-tests', 'pilot', 'main', 'final-tests'))
    parser.add_argument('--ns3-root', type=Path, default=Path.home() / 'ns3-work/ns-3.49')
    parser.add_argument('--output', type=Path, default=HERE / 'C_flowmonitor_final')
    args = parser.parse_args()
    ns3, out = args.ns3_root.resolve(), args.output.resolve()
    if args.phase == 'preflight':
        preflight(ns3, out)
    elif args.phase in ('existing-tests', 'final-tests'):
        run_tests(out, final=args.phase == 'final-tests')
    else:
        execute(ns3, out, pilot=args.phase == 'pilot')


if __name__ == '__main__':
    main()
