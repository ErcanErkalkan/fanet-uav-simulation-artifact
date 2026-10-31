"""R1.8: small/medium/large 3D deployment area sensitivity (synthetic only)."""
import sys,csv,math
from pathlib import Path
from statistics import mean,stdev
from scipy.stats import t
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'src'))
from fanet_statistical_sensitivity import StatisticalFANETSimulator
from fanet_routing_protocols import make_protocol
LENGTHS=(120.,250.,500.)
NODES=(20,40)
REPETITIONS=30
DURATION=30.

def write(path,rows):
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,rows[0].keys());w.writeheader();w.writerows(rows)

def main():
 raw=[]
 for n in NODES:
  for L in LENGTHS:
   for mode in ('fixed_35m','scaled_relative_range'):
    R=35. if mode=='fixed_35m' else 35.*L/120.
    for rep in range(REPETITIONS):
     seed=206000+n*1000+rep
     sim=StatisticalFANETSimulator(num_uavs=n,communication_range=R,speed_profile='medium',packets_per_step=5,mobility_model='random_waypoint',protocol=make_protocol('aodv_like_reactive'),seed=seed,duration_s=DURATION,dt_s=1.,area=(L,L,L*50/120))
     result=sim.run()
     raw.append(dict(result,area_xy_m=L,area_z_m=L*50/120,range_mode=mode,range_m=R))
   print(f'Area={L}m nodes={n} completed',flush=True)
 write(D/'extra'/'area_scaling_raw.csv',raw)
 summ=[]
 for n in NODES:
  for L in LENGTHS:
   for mode in ('fixed_35m','scaled_relative_range'):
    a=[r for r in raw if r['num_uavs']==n and r['area_xy_m']==L and r['range_mode']==mode]
    pdr=[float(r['pdr']) for r in a]
    hw=t.ppf(.975,29)*stdev(pdr)/math.sqrt(30)
    summ.append(dict(num_uavs=n,area_xy_m=L,area_z_m=L*50/120,range_m=a[0]['range_m'],range_mode=mode,n_reps=len(a),pdr_mean=mean(pdr),pdr_sd=stdev(pdr),pdr_t95_halfwidth=hw,mean_packets_without_routing_path=mean(float(r.get('packets_without_routing_path',float('nan'))) for r in a)))
 write(D/'extra'/'area_scaling_summary.csv',summ)
 print('Area scaling outputs saved',flush=True)
if __name__=='__main__':main()
