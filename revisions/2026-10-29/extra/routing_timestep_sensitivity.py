"""R2.2 and R2.3: routing policy parameter and topology-step sensitivity.
Latency is model-derived; tests DO NOT implement subsecond packet-event scheduling.
"""
from pathlib import Path
import sys,csv, math
from statistics import mean, stdev
from scipy.stats import t
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'src'))
from fanet_routing_protocols import AODVLikeReactive, OLSRLikeProactive, RoutingBenchmarkSimulator

REPS=30

def write(path,rows):
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,rows[0].keys());w.writeheader();w.writerows(rows)

def calc(case,parameter,value,seed,n,dt,duration,packets):
  protocol=AODVLikeReactive(route_ttl_s=value) if case=='aodv_ttl' else (OLSRLikeProactive(update_interval_s=value) if case=='olsr_update' else AODVLikeReactive(route_ttl_s=8.))
  sim=RoutingBenchmarkSimulator(num_uavs=n,protocol=protocol,seed=seed,duration_s=duration,dt_s=dt,communication_range=35.,packets_per_step=packets)
  return dict(sim.run(),experiment=case,parameter=parameter,parameter_value=value,dt_s=dt,packets_per_step=packets)

def main():
 raw=[]
 for case,param,values,dt,packets in [('aodv_ttl','route_cache_ttl_s',[2.,4.,8.,16.],1.,5),('olsr_update','routing_update_interval_s',[1.,2.,5.],1.,5),('topology_timestep','dt_s',[.25,.5,1.,2.],None,None)]:
  for val in values:
   simdt=val if dt is None else dt
   traffic=(int(round(4*simdt)) if packets is None else packets)
   for rep in range(REPS):
    seed=900000+rep
    raw.append(calc(case,param,val,seed,20,simdt,120.,traffic))
   print(case, val,'done',flush=True)
 write(D/'extra'/'routing_timestep_raw.csv',raw)
 summary=[]
 for case,param,values,_,__ in [('aodv_ttl','route_cache_ttl_s',[2.,4.,8.,16.],None,None),('olsr_update','routing_update_interval_s',[1.,2.,5.],None,None),('topology_timestep','dt_s',[.25,.5,1.,2.],None,None)]:
  for val in values:
   x=[r for r in raw if r['experiment']==case and r['parameter_value']==val]
   result=dict(experiment=case,parameter=param,parameter_value=val,n_reps=len(x),dt_s=x[0]['dt_s'],packets_per_step=x[0]['packets_per_step'])
   for m in ['pdr','avg_latency_ms','control_packets_per_s','route_failures','packets_without_routing_path','stale_route_failures']:
    nums=[float(r[m]) for r in x if math.isfinite(float(r[m]))]
    result[m+'_mean']=mean(nums) if nums else float('nan')
    result[m+'_t95_halfwidth']=t.ppf(.975,len(nums)-1)*stdev(nums)/(len(nums)**.5) if len(nums)>1 else float('nan')
   summary.append(result)
 write(D/'extra'/'routing_timestep_summary.csv',summary)
 print('Routing parameter and step sensitivity saved',flush=True)
if __name__=='__main__':main()
