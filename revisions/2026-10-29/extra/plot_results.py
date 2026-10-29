from pathlib import Path
from scipy.stats import t
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=Path(__file__).resolve().parents[1]
F=D/'figures'
F.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.titlesize':11,'axes.labelsize':10,'legend.fontsize':8,'figure.dpi':180,'savefig.dpi':240})

def save(fig,stem):
 fig.tight_layout()
 fig.savefig(F/(stem+'.png'),bbox_inches='tight')
 fig.savefig(F/(stem+'.svg'),bbox_inches='tight')
 plt.close(fig)

cal=pd.read_csv(D/'extra'/'calibration_summary.csv')
fig,ax=plt.subplots(figsize=(8.0,4.8))
for mode,subset in cal.groupby('mode',sort=False):
 subset=subset.sort_values('num_uavs')
 ax.errorbar(subset.num_uavs,subset.pdr_mean, yerr=t.ppf(.975,29)*subset.pdr_sd/(30**.5),marker='o',capsize=3,label=mode.replace('_',' '))
ax.set(title='Sensitivity to wireless-link selection and calibration',xlabel='Number of UAVs',ylabel='Packet delivery ratio (PDR)',xticks=[10,20,30],ylim=(0,1.05))
ax.grid(alpha=.25);ax.legend(loc='center left',bbox_to_anchor=(1.02, .5),frameon=False)
save(fig,'fig_R2_4_calibration_pdr')

area=pd.read_csv(D/'extra'/'area_scaling_summary.csv')
fig,ax=plt.subplots(figsize=(8.0,4.7))
for (n,mode),s in area.groupby(['num_uavs','range_mode'],sort=True):
 s=s.sort_values('area_xy_m')
 ax.errorbar(s.area_xy_m,s.pdr_mean,yerr=s.pdr_t95_halfwidth,label=f'{n} UAVs — {"fixed 35 m" if mode=="fixed_35m" else "scaled range"}',marker='o',capsize=3)
ax.set(title='Large-area sensitivity under fixed vs scaled communication range',xlabel='Deployment square side length (m)',ylabel='Packet delivery ratio (PDR)',xticks=[120,250,500],ylim=(-.05,1.07))
ax.grid(alpha=.25);ax.legend(frameon=False,fontsize=8)
save(fig,'fig_R1_8_area_scaling_pdr')

route=pd.read_csv(D/'extra'/'routing_timestep_summary.csv')
s=route[route.experiment=='olsr_update']
fig,ax=plt.subplots(figsize=(7.4,4.6))
ax.errorbar(s.parameter_value,s.pdr_mean,yerr=s.pdr_t95_halfwidth,marker='o',capsize=3,label='PDR')
ax.set(title='OLSR-like update interval sensitivity',xlabel='Routing-table update interval (s)',ylabel='Packet delivery ratio (PDR)',xticks=[1,2,5],ylim=(0,1))
ax.grid(alpha=.25);save(fig,'fig_R2_2_olsr_pdr')

s=route[route.experiment=='topology_timestep']
fig,ax=plt.subplots(figsize=(7.4,4.6))
ax.errorbar(s.parameter_value,s.pdr_mean,yerr=s.pdr_t95_halfwidth,marker='o',capsize=3)
ax.set(title='Topology update time-step sensitivity (4 packets/s)',xlabel='Mobility/topology time step (s)',ylabel='Packet delivery ratio (PDR)',xticks=[.25,.5,1,2],ylim=(0,1))
ax.grid(alpha=.25)
save(fig,'fig_R2_3_timestep_pdr')

print('Created figures:',[(p.name, p.stat().st_size) for p in F.glob('fig_*')])
