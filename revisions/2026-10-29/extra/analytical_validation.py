"""Independent closed-form single-hop and two-hop sanity validation.
Only validates selected deterministic mathematical components and Monte Carlo implementation;
it does NOT validate physical UAV radio propagation or real MAC behavior.
"""
from __future__ import annotations
import sys, csv, math, random, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from fanet_wireless_channel_model import WirelessChannel, WirelessConfig, UAVNode

OUT = Path(__file__).resolve().parents[1]/'extra'
rng = random.Random(20261029)
config = WirelessConfig(shadowing_sigma_db=0, obstacle_probability=0,orientation_loss_max_db=0,interfering_tx_probability=0,mac_collision_penalty=0,path_loss_exponent_los=2,path_loss_exponent_nlos=2,sinr_threshold_db=39,logistic_slope=3,reliability_threshold=0.01)
channel = WirelessChannel(config,random.Random(1))
tx = UAVNode(0,[0.,0.,20.],[0,0,0],0)
rx1 = UAVNode(1,[45.,0.,20.],[0,0,0],0)
rx2 = UAVNode(2,[105.,0.,20.],[0,0,0],0)

def independent(distance):
    speed_of_light=299_792_458
    lam=speed_of_light/config.frequency_hz
    fspl=20*math.log10(4*math.pi/lam)
    pathloss=fspl+10*2*math.log10(distance)
    received=config.tx_power_dbm-pathloss
    noise_dbm=-174+10*math.log10(config.bandwidth_hz)+config.noise_figure_db
    sinr=received-noise_dbm
    p=1/(1+math.exp(-(sinr-config.sinr_threshold_db)/config.logistic_slope))
    txms=8*config.packet_size_bytes/config.bandwidth_hz*1000
    propms=distance/speed_of_light*1000
    queue=config.queue_base_ms
    return {'distance_m':distance,'expected_rx_power_dbm':received,'expected_sinr_db':sinr,'expected_reliability':p,'expected_tx_delay_ms':txms,'expected_prop_delay_ms':propms,'expected_queue_delay_ms':queue}

rows=[]
for u,v in ((tx,rx1),(rx1,rx2)):
    d=channel.distance(u,v)
    actual=channel.hop_quality(u,v,[u,v])
    expected=independent(d)
    for k,ak in [('expected_rx_power_dbm','rx_power_dbm'),('expected_sinr_db','sinr_db'),('expected_reliability','reliability'),('expected_tx_delay_ms','tx_delay_ms'),('expected_prop_delay_ms','prop_delay_ms'),('expected_queue_delay_ms','queue_delay_ms')]:
        assert abs(expected[k]-actual[ak]) <1e-9,(k,expected[k],actual[ak])
    rows.append(dict(hop=f'{u.node_id}-{v.node_id}',**expected,**{f'actual_{k}':v for k,v in actual.items()}))
N=20000
p1,p2=(r['expected_reliability'] for r in rows)
single_success=sum(rng.random()<p1 for _ in range(N))
two_success=sum((rng.random()<p1) and (rng.random()<p2) for _ in range(N))
from scipy.stats import binomtest
for label,p,count in [('one_hop',p1,single_success),('two_hop',p1*p2,two_success)]:
    interval=binomtest(count,N).proportion_ci(confidence_level=.95,method='exact')
    rows.append({'hop':label,'expected_reliability':p,'observed_reliability':count/N,'n_trials':N,'successes':count,'ci_low':interval.low,'ci_high':interval.high,'within_exact_ci':interval.low<=p<=interval.high})
with (OUT/'analytical_validation.csv').open('w',newline='') as f:
    keys=list(dict.fromkeys(k for row in rows for k in row))
    w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rows)
with (OUT/'analytical_validation_report.json').open('w') as f:
    json.dump({'interpretation':'Validation of selected closed-form radio model equations and random-draw logic only, NOT external real-world physical validation.','all_equations_match':True,'monte_carlo':rows[-2:]},f,indent=2)
print('closed-form power/SINR/delay cross-check: PASS')
for x in rows[-2:]: print(x)
