"""Create readable main and sensitivity figures from verified measured metrics."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=Path('outputs/full'));a=p.parse_args()
s=json.loads((a.results/'summary.json').read_text(encoding='utf-8'));assert s['status']=='complete'
metrics={(x['condition'],x['method']):x for x in s['metrics']}
methods=['original','repair','fixed_fusion','js_gate','oracle'];names=['Original','OCR repair','Fixed fusion','JS gate','Known-box diagnostic']
conditions=['clean','correct','wrong','neutral','block']
fig,ax=plt.subplots(figsize=(9,3.6));x=np.arange(5)
for i,(m,name) in enumerate(zip(methods,names)):
    ax.bar(x+(i-2)*.155,[100*metrics[c,m]['accuracy'] for c in conditions],.155,label=name)
ax.set_xticks(x,['Clean','Correct text','Wrong text','Non-class word','Matched block']);ax.set_ylabel('Test accuracy (%)');ax.set_ylim(0,100);ax.legend(ncol=3,fontsize=8,loc='upper center',bbox_to_anchor=(.5,1.23));ax.grid(axis='y',alpha=.2);fig.tight_layout();fig.savefig(a.results/'main_results.png',dpi=180);plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(9,3.4))
for ax,cs,labels,title in [(axes[0],['wrong_font20','wrong_font32','wrong_font44'],['20','32','44'],'Font size (pixels)'),(axes[1],['wrong_position_top','wrong_position_center','wrong_position_bottom'],['Top','Center','Bottom'],'Text position')]:
    for m,name in zip(methods[:4],names[:4]):
        if all((c,m) in metrics for c in cs):ax.plot(labels,[100*metrics[c,m]['accuracy'] for c in cs],marker='o',label=name)
    ax.set_title(title);ax.set_ylabel('Subset accuracy (%)');ax.set_ylim(0,100);ax.grid(alpha=.2)
axes[1].legend(fontsize=8);fig.tight_layout();fig.savefig(a.results/'sensitivity.png',dpi=180);plt.close(fig)
print('Saved main_results.png and sensitivity.png from measured summary.')
