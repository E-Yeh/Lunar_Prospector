# GENERATED FROM SELENE.ipynb. Edit the notebook, not this file.
# SELENE.ipynb cell 3
# export: core.py
"""Deterministic data tools used by the prospecting workflow."""
import json
import re
import numpy as np
import pandas as pd
import requests
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

DEFAULT = dict(west=-60., east=60., south=-40., north=40., minimum_tio2=2., top_n=8, priority='balanced')



# SELENE.ipynb cell 4
# export: core.py
def fit_terrain(df, k=4):
    df = df.copy().reset_index(drop=True)
    if len(df)<k or len(df[['tio2','omat']].drop_duplicates())<k:
        raise ValueError('Need at least four distinct valid TiO2/OMAT samples.')
    x = StandardScaler().fit_transform(df[['tio2','omat']])
    model = KMeans(n_clusters=k, random_state=530, n_init=10).fit(x)
    df['cluster'] = model.labels_.astype(str)
    df['site_id'] = [f'L{i:05d}' for i in range(len(df))]
    df['score'] = 100*(.65*df.tio2.rank(pct=True)+.35*(-df.omat).rank(pct=True))
    sil = silhouette_score(x, model.labels_, sample_size=min(1500,len(df)), random_state=530)
    return df, float(sil)



# SELENE.ipynb cell 5
# export: core.py
def validate_plan(plan):
    if set(plan) != set(DEFAULT):
        raise ValueError('The query plan has unexpected or missing fields.')
    for key in ['west','east','south','north','minimum_tio2','top_n']:
        if isinstance(plan[key], bool) or not isinstance(plan[key], (float,int)) or not np.isfinite(plan[key]):
            raise ValueError(f'Invalid numeric value for {key}.')
    if not -180<=plan['west']<plan['east']<=180 or not -90<=plan['south']<plan['north']<=90:
        raise ValueError('Use ordered lunar bounds: west < east, south < north. Split dateline-crossing regions.')
    if not 0<=plan['minimum_tio2']<=15 or not 1<=plan['top_n']<=50 or int(plan['top_n'])!=plan['top_n']:
        raise ValueError('TiO2 must be 0–15 wt%; candidate count must be an integer from 1–50.')
    if plan['priority'] not in ['balanced','tio2','maturity']:
        raise ValueError('Unsupported ranking priority.')
    return plan



# SELENE.ipynb cell 6
# export: core.py
def plan_query(query, current, use_llm=False, model='gemma3:4b'):
    if not query.strip():
        raise ValueError('Enter a prospecting question.')
    if use_llm:
        system = ('Translate lunar prospecting requests into JSON. Only fields in the current plan are allowed. '
                  'Preserve prior values unless changed by the user. priority is balanced, tio2, or maturity. '
                  'Bounds are degrees east [-180,180] and north [-90,90]. minimum_tio2 is wt%. '
                  'For unsupported requests (helium abundance, solar wind, slope, landing safety, other elements) '
                  'return {"error":"Explain missing data"}. Do not invent measurements. Current plan: '+json.dumps(current))
        response = requests.post('http://localhost:11434/api/chat', json=dict(model=model,
            messages=[dict(role='system',content=system),dict(role='user',content=query)],
            format='json', stream=False, options={'temperature':0}), timeout=(5,90))
        response.raise_for_status()
        plan = json.loads(response.json()['message']['content'])
        if 'error' in plan:
            raise ValueError(str(plan['error']))
        return validate_plan(plan)
    q = query.lower().strip().rstrip('.?!')
    plan = dict(current)
    # Explicit, limited offline grammar: never silently ignore an arbitrary constraint.
    if q in ['find the best spots','find me the best spot for helium-3 mining','balanced']:
        plan['priority'] = 'balanced'
    elif q in ['highest tio2','show highest tio2','rank by tio2']:
        plan['priority'] = 'tio2'
    elif q in ['most mature','rank by maturity']:
        plan['priority'] = 'maturity'
    elif re.fullmatch(r'top \d+',q):
        plan['top_n'] = int(q.split()[1])
    elif re.fullmatch(r'minimum tio2 \d+(\.\d+)?',q):
        plan['minimum_tio2'] = float(q.split()[-1])
    else:
        raise ValueError('Offline mode supports: highest TiO2; most mature; top 5; minimum TiO2 4; find the best spots. Use the region controls or connect Ollama for flexible questions. Solar wind, other elements and landing safety are not available.')
    return validate_plan(plan)



# SELENE.ipynb cell 7
# export: core.py
def rank_sites(df, plan):
    validate_plan(plan)
    eligible = df[df.longitude.between(plan['west'],plan['east']) & df.latitude.between(plan['south'],plan['north']) & (df.tio2>=plan['minimum_tio2'])].copy()
    key, ascending = {'balanced':('score',False),'tio2':('tio2',False),'maturity':('omat',True)}[plan['priority']]
    return eligible.sort_values([key,'site_id'],ascending=[ascending,True]).head(int(plan['top_n']))



# SELENE.ipynb cell 8
# export: core.py
def explain(result, plan):
    if result.empty:
        return 'No samples meet these constraints. Expand the region or lower the minimum TiO2; constraints have not been relaxed automatically.'
    row = result.iloc[0]
    prefix = 'Imported raster samples: '
    return (f'{prefix}{len(result)} candidates ranked by {plan["priority"]}. '
            f'Leading sample {row.site_id} is at {row.latitude:.2f}°N, {row.longitude:.2f}°E, '
            f'with TiO2 {row.tio2:.2f} wt%, OMAT {row.omat:.3f}, and terrain group {row.cluster}. '
            'These proxies support follow-up investigation; they do not measure helium-3 or establish landing suitability.')

