"""R2.1 analytic reference: exact two-point 2D-square distance CDF (r<=side).
This independently checks binary-range spatial topology only, not physical PHY/MAC.
"""
from pathlib import Path
import sys,random,math,json,csv
from scipy.stats import binomtest
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'src'))
from fanet_wireless_channel_model import WirelessFANETSimulator
seed=27511; L=100.;R=35.;n_trials=50000
u=R/L
analytical=math.pi*u*u-(8/3)*u**3+.5*u**4
s=WirelessFANETSimulator(num_uavs=2,seed=seed,area_xy=L,altitude_bounds=(0.,0.),binary_range_m=R)
rng=random.Random(seed+7)
found=0
for _ in range(n_trials):
 for q in s.nodes:
  q.position=[rng.uniform(0,L),rng.uniform(0,L),0.]
 found+=(len(s.binary_edges())==1)
observed=found/n_trials
ci=binomtest(found,n_trials).proportion_ci(confidence_level=.95,method='exact')
row=dict(geometry='two_independent_uniform_nodes_in_2D_square',area_side_m=L,range_m=R,n_trials=n_trials,analytical_link_probability=analytical,observed_link_probability=observed,abs_error=abs(analytical-observed),exact_ci_low=ci.low,exact_ci_high=ci.high,analytical_in_ci=ci.low<=analytical<=ci.high)
with (D/'extra'/'analytical_topology.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,row);w.writeheader();w.writerow(row)
with (D/'extra'/'analytical_topology.json').open('w') as f:json.dump({'formula':'Pr(distance<=r)=pi*(r/L)^2-(8/3)*(r/L)^3+(1/2)*(r/L)^4, for 0<=r/L<=1, two independent uniform points in a 2D square','result':row,'limitations':'2D, fixed-height, ideal binary direct links only. Does not validate 3D mobility or probabilistic radio.'},f,indent=2)
assert row['analytical_in_ci']
print(row)
