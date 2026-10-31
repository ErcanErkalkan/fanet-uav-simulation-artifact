#!/usr/bin/env python3
"""Rerun *only* scenario C with corrected FlowMonitor call; never overwrite P05/P06.

Requires Ubuntu/WSL2 ns-3.49 and versioned SIMPAT validation branch. This script
has been syntax-checked, but a local ns-3 execution is still necessary.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import shlex
import subprocess
from pathlib import Path

NS3_SEED = 20261029
SEEDS = range(20261029, 20261059)
REL = Path('local_validation/2026-10-29/ns3')
SOURCE_SHA256 = 'BDEDB8C09FDE29B9146C82E8B28512D6E995FD1DC495C7F9E4087B17145AA840'

def digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for buf in iter(lambda: f.read(1024*1024), b''):
            h.update(buf)
    return h.hexdigest().upper()

def rows(p: Path) -> list[dict[str,str]]:
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def required(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path

def run(repo_root: Path, ns3_root: Path, out: Path) -> None:
    ref = repo_root / REL
    src = required(ref/'ns3_fanet_reference.cc')
    scratch = required(ns3_root/'scratch/ns3_fanet_reference.cc')
    for f in (src, scratch):
        if digest(f) != SOURCE_SHA256:
            raise RuntimeError(f'Wrong ns-3 diagnostic source SHA256 in {f}. Do not use older P05 code; compare and sync manually.')
    ns3 = required(ns3_root/'ns3')
    inp = ref/'real_airsim_replay'/'inputs'/'C'
    mobility = required(inp/'airsim_mobility.csv')
    original = rows(required(ref/'real_airsim_replay'/'real_airsim_replay_raw.csv'))
    original_idx = {(r['routing'],int(r['repetition_seed'])):r for r in original
                    if r['experiment']=='C' and r['simulator']=='ns-3.49'}
    if len(original_idx) != 60:
        raise ValueError(f'Expected 60 original C ns-3 records, observed {len(original_idx)}')
    if out.exists():
        raise FileExistsError(f'Refusing overwrite of prior C diagnostics: {out}')
    out.mkdir(parents=True)
    comparison = []
    runlogs = []
    mismatches = []
    for seed in SEEDS:
        schedule = required(inp/f'traffic_seed_{seed}.csv')
        traffic = rows(schedule)
        if len(traffic) != 599:
            raise ValueError(f'Expected 599 scheduled events at seed {seed}: {len(traffic)}')
        traffic_seed = int(traffic[0]['traffic_seed'])
        for routing in ('aodv','olsr'):
            run_out = out/f'{routing}_seed_{seed}'
            run_out.mkdir()
            summary = run_out/'summary.csv'
            events = run_out/'packet_events.csv'
            options = {
                'experiment':'C','routing':routing,'profile':'range_limited_wifi',
                'coordinate-frame':'ned','mobility':str(mobility),'traffic':str(schedule),
                'summary':str(summary),'events':str(events),
                'repetition-seed':str(seed),'traffic-seed':str(traffic_seed),
                'seed':str(NS3_SEED),'run':str(seed-20261028),'packet-bytes':'256',
                'range-m':'35','warmup-s':'5','drain-s':'10',
                'measurement-window-s':'119.7909209'}
            command = 'scratch/ns3_fanet_reference '+ ' '.join(
                shlex.quote('--'+k+'='+v) for k,v in options.items())
            proc = subprocess.run([str(ns3),'run',command],cwd=ns3_root,
                                  text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            runlogs.append({'seed':seed,'routing':routing,'exit':proc.returncode,
                            'output':proc.stdout[-1600:]})
            if proc.returncode:
                (out/'runlog.json').write_text(json.dumps(runlogs,indent=2))
                raise RuntimeError(f'ns3 failed {routing}/{seed}; see runlog.json')
            actual_rows = rows(summary)
            if len(actual_rows)!=1 or len(rows(events))!=599:
                raise RuntimeError(f'Incomplete C output for {routing}/{seed}')
            new=actual_rows[0]
            old=original_idx[(routing,seed)]
            # Compare primary application metrics, *not* FlowMonitor lostPackets.
            expected_n = int(old['delivered_packets'])
            actual_n = int(new['application_unique_delivered_packets'])
            expected_pdr=float(old['pdr']); actual_pdr=float(new['pdr'])
            expected_delay=float(old['mean_latency_ms']) if old['mean_latency_ms']!='NA' else math.nan
            actual_delay=float(new['mean_application_delay_ms']) if new['mean_application_delay_ms']!='NA' else math.nan
            matched=(expected_n==actual_n and math.isclose(expected_pdr,actual_pdr,abs_tol=1e-9)
                     and (math.isclose(expected_delay,actual_delay,rel_tol=0,abs_tol=1e-6)
                          or (math.isnan(expected_delay) and math.isnan(actual_delay))))
            if not matched:mismatches.append(f'{routing}/{seed}')
            comparison.append({'seed':seed,'routing':routing,'application_pdr_unchanged':matched,
                 'old_delivered':expected_n,'new_delivered':actual_n,
                 'old_application_pdr':expected_pdr,'new_application_pdr':actual_pdr,
                 'old_delay_ms':old['mean_latency_ms'],'new_delay_ms':new['mean_application_delay_ms'],
                 'old_flowmonitor_lost':old['flowmonitor_lost_packets'],
                 'corrected_flowmonitor_lost':new['flowmonitor_lost_packets'],
                 'old_flowmonitor_rx':old['flowmonitor_rx_packets'],
                 'corrected_flowmonitor_rx':new['flowmonitor_rx_packets']})
            print(f'Completed C {routing} seed={seed}: delivered {actual_n}/599',flush=True)
    with (out/'C_flowmonitor_comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(comparison[0]));w.writeheader();w.writerows(comparison)
    (out/'runlog.json').write_text(json.dumps(runlogs,indent=2))
    (out/'C_flowmonitor_summary.json').write_text(json.dumps({
       'status':'passed' if not mismatches else 'FAILED',
       'scenario':'C','input':'one recorded AirSim flight',
       'ns3_version':'3.49','source_sha256':SOURCE_SHA256,
       'n_runs':len(comparison),'application_mismatches':mismatches,
       'outcome':'FlowMonitor-lost diagnostic only; PDR from unique application deliveries'
       },indent=2))
    if mismatches:raise RuntimeError(f'{len(mismatches)} C primary outcome mismatches: {mismatches}')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo-root',required=True,type=Path)
    ap.add_argument('--ns3-root',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path,
                    help='A NEW, NONEXISTING output directory, not original P05/P06 results')
    a=ap.parse_args()
    run(a.repo_root.expanduser().resolve(),a.ns3_root.expanduser().resolve(),a.output.expanduser().resolve())
