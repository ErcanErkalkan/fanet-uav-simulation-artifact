"""Audits reproducibility runs against archived baseline PDR values.
Computes Student-t 95% CI half-widths for updated summaries; doesn't overwrite baseline/current values.
"""
from pathlib import Path
import pandas as pd, numpy as np, math, csv, json
from scipy.stats import t
D=Path(__file__).resolve().parents[1]
SPECS={
 'routing': dict(keys=['protocol','num_uavs'],pdr='pdr',original='fanet_routing_summary.csv',expected_groups=12,expected_n=30),
 'statistical':dict(keys=['factor','level','protocol','num_uavs'],pdr='pdr',original='fanet_statistical_summary.csv',expected_groups=20,expected_n=30),
 'wireless': dict(keys=['model','num_uavs'],pdr='pdr',original='fanet_wireless_summary.csv',expected_groups=6,expected_n=30),
 'unified':dict(keys=['scenario'],pdr='pdr',original='fanet_unified_summary.csv',expected_groups=4,expected_n=30),
}
allrows=[]; audit=[]
for name,spec in SPECS.items():
 raw=pd.read_csv(D/'raw'/f'{name}_raw.csv')
 grouped=raw.groupby(spec['keys'],dropna=False)
 for key,sub in grouped:
  if not isinstance(key,tuple):key=(key,)
  pdr=sub[spec['pdr']].astype(float).to_numpy()
  n=len(pdr)
  row=dict(experiment=name,**dict(zip(spec['keys'],key)),n_reps=n,pdr_mean=float(np.mean(pdr)),pdr_sd=float(np.std(pdr,ddof=1)),pdr_t95_halfwidth=float(t.ppf(.975,n-1)*np.std(pdr,ddof=1)/np.sqrt(n)),ci_method='Student-t',ci_semantics='half_width')
  allrows.append(row)
 assert len(grouped)==spec['expected_groups'],(name,len(grouped))
 assert len(raw)==spec['expected_groups']*spec['expected_n'],(name,len(raw))
 assert raw['pdr'].between(0,1).all(),name
 if name in ['routing','statistical']:
  assert (raw['attempted']==raw['delivered']+raw['packets_without_routing_path']).all(),name
 if name=='wireless':
  assert (raw['attempted_packets']==raw['delivered_packets']+raw['packets_without_routing_path']+raw['failed_wireless_packets_after_routing']).all(),name
 if name=='unified':
  assert (raw['packet_attempts'] == raw['delivered_packets']+raw['packets_without_routing_path']+raw['failed_wireless_packets_after_routing']).all(),name
 orig=pd.read_csv((D.parents[1]/'FANET_UAV')/spec['original'])
 R=pd.read_csv(D/'summary'/f'{name}_summary.csv')
 merged=orig[spec['keys']+['pdr_mean']].merge(R[spec['keys']+['pdr_mean']],on=spec['keys'],how='outer',suffixes=('_R0','_R1'),indicator=True)
 assert (merged['_merge']=='both').all()
 errors=(merged.pdr_mean_R0-merged.pdr_mean_R1).abs()
 assert errors.max()<1e-12
 audit.append(dict(experiment=name,raw_rows=len(raw),summary_rows=len(R),original_rows=len(orig),pdr_matching_rows=len(merged),pdr_max_abs_error=float(errors.max()),conservation_check='passed',row_count_check='passed'))
with (D/'extra'/'student_t_ci95_recomputed.csv').open('w',newline='') as f:
 keys=list(dict.fromkeys(k for r in allrows for k in r)); w=csv.DictWriter(f,keys);w.writeheader();w.writerows(allrows)
with (D/'extra'/'baseline_audit.json').open('w') as f:json.dump(audit,f,indent=2)
print(pd.DataFrame(audit).to_string(index=False))
print('TOTAL comparisons',sum(x['pdr_matching_rows'] for x in audit))
