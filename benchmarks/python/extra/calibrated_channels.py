"""R2.4: paired synthetic trajectory/traffic, shared wireless realizations.
Three comparisons: original 35m hard binary vs uncalibrated wireless, 35m-capped
wireless, and equal-edge-budget strongest-wireless links (not same edge identities).
Preserves original scientific model; NO claim of equivalent physical fidelity.
"""
from __future__ import annotations
import sys, math, random, csv
from pathlib import Path
from itertools import combinations
from statistics import mean,stdev
from scipy.stats import t
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'src'))
from fanet_wireless_channel_model import WirelessConfig,WirelessChannel,UAVNode
from fanet_routing_protocols import make_protocol
from fanet_unified_pipeline import SyntheticMobility,distance
RANGE=35.0
NREP=30
MODES=('binary_35m','wireless_unrestricted','wireless_35m_cap','wireless_same_binary_candidates','wireless_edge_count_matched')

def mean_or_nan(x):return mean(x) if x else float('nan')

def calc_one(seed,n):
    mob=SyntheticMobility(n,seed,100.,(15.,45.),(1.5,6.))
    radio=WirelessChannel(WirelessConfig(),random.Random(seed+873221))
    flow_rng=random.Random(seed+119913)
    protocol={mode:make_protocol('aodv_like_reactive') for mode in MODES}
    for p in protocol.values():p.reset(n)
    packet_rng={mode:random.Random(seed+917031+i*101) for i,mode in enumerate(MODES)}
    sums={mode:dict(attempts=0,delivered=0,no_route=0,wireless_fail=0,latencies=[],hops=[],connections=0,out_of_range_edges=0,control=0) for mode in MODES}
    for frame in mob.frames(30.,1.):
        nodes=frame.nodes
        binary={}; wireless={}; wireless_all={}
        for a,b in combinations(nodes,2):
            d=distance(a,b)
            key=(a.node_id,b.node_id)
            if d<=RANGE:binary[key]={'reliability':1.,'hop_delay_ms':4.5,'distance':d}
            qa=radio.hop_quality(a,b,nodes);qb=radio.hop_quality(b,a,nodes)
            r=min(qa['reliability'],qb['reliability'])
            wireless_all[key]={'reliability':r,'hop_delay_ms':qa['tx_delay_ms']+qa['prop_delay_ms']+qa['queue_delay_ms'],'distance':d}
            if r>=radio.cfg.reliability_threshold:
                wireless[key]={'reliability':r,'hop_delay_ms':qa['tx_delay_ms']+qa['prop_delay_ms']+qa['queue_delay_ms'],'distance':d}
        # These are restrictions on exactly the same radio samples in this frame.
        wireless_cap={k:v for k,v in wireless.items() if v['distance']<=RANGE}
        # Fairer candidate topology: exactly the binary-35m candidate edges; no radio eligibility threshold.
        wireless_same_binary={k:wireless_all[k] for k in binary}
        # Top-K matches edge count ONLY, not receiver/degree distribution or range.
        topk=dict(sorted(wireless.items(),key=lambda item:-item[1]['reliability'])[:len(binary)])
        edge_sets=dict(zip(MODES,(binary,wireless,wireless_cap,wireless_same_binary,topk)))
        positions={q.node_id:tuple(q.position) for q in nodes}
        flow_pairs=[tuple(flow_rng.sample(range(n),2))+(flow_rng.uniform(0.,3.),) for _ in range(5)]
        for mode,edges in edge_sets.items():
            p=protocol[mode]
            p.on_topology_change(frame.time_s,set(edges),positions)
            s=sums[mode]
            s['connections']+=len(edges)
            s['out_of_range_edges']+=sum(v['distance']>RANGE for v in edges.values())
            for src,dst,jitter in flow_pairs:
                s['attempts']+=1
                dec=p.route(src,dst,set(edges),positions,frame.time_s)
                s['control']+=dec.control_packets
                if not dec.delivered or not dec.path:
                    s['no_route']+=1;continue
                latency=8.+(12. if dec.discovery else 0.)+.05*dec.control_packets+jitter
                passed=True
                for u,v in zip(dec.path[:-1],dec.path[1:]):
                    q=edges[(min(u,v),max(u,v))]
                    latency+=q['hop_delay_ms']
                    if packet_rng[mode].random()>q['reliability']:
                        s['wireless_fail']+=1; passed=False;break
                if passed:
                    s['delivered']+=1;s['latencies'].append(latency);s['hops'].append(dec.hops)
    out=[]
    for mode,s in sums.items():
        out.append(dict(seed=seed,num_uavs=n,mode=mode,attempts=s['attempts'],delivered=s['delivered'],pdr=s['delivered']/s['attempts'],no_route=s['no_route'],wireless_fail=s['wireless_fail'],mean_latency_ms=mean_or_nan(s['latencies']),mean_hops=mean_or_nan(s['hops']),mean_edges=s['connections']/30,mean_edges_beyond_35m=s['out_of_range_edges']/30,control_packets_per_second=s['control']/30))
    return out

def write(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,rows[0].keys());w.writeheader();w.writerows(rows)

def main():
    raw=[]
    for n in (10,20,30):
        for i in range(NREP):
            raw.extend(calc_one(80000+1000*n+i,n))
        print(f'Completed n={n} {NREP} seeds',flush=True)
    write(D/'extra'/'calibration_raw.csv',raw)
    summary=[]
    for n in (10,20,30):
        subset=[x for x in raw if x['num_uavs']==n]
        binmap={x['seed']:x for x in subset if x['mode']=='binary_35m'}
        for mode in MODES:
            x=[y for y in subset if y['mode']==mode]
            pdrs=[y['pdr'] for y in x];edges=[y['mean_edges'] for y in x];outs=[y['mean_edges_beyond_35m'] for y in x]
            delta=[y['pdr']-binmap[y['seed']]['pdr'] for y in x]
            dh=t.ppf(.975,len(delta)-1)*stdev(delta)/math.sqrt(len(delta))
            summary.append(dict(num_uavs=n,mode=mode,n_seeds=len(x),pdr_mean=mean(pdrs),pdr_sd=stdev(pdrs),pdr_diff_from_binary_paired_mean=mean(delta),pdr_diff_paired_t95_halfwidth=dh,mean_edge_count=mean(edges),mean_edges_over_35m=mean(outs)))
    write(D/'extra'/'calibration_summary.csv',summary)
    print('Wrote calibrated comparison csv',flush=True)
if __name__=='__main__':main()
