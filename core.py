# GENERATED FROM MoonScout.ipynb. Edit the notebook, not this file.
# MoonScout.ipynb cell 3
# export: core.py

# Import JSON/regex helpers, numerical tables, HTTP requests, and scikit-learn tools
# Used for deterministic analysis and optional Ollama query planning.
import json
import re
import numpy as np
import pandas as pd
import requests
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

# DEFAULT defines the initial search region in degrees, minimum TiO2 in wt%,
# maximum shortlist size, and ranking priority. Callers copy it before editing.
DEFAULT = dict(west=-60., east=60., south=-40., north=40., minimum_tio2=2., top_n=8, priority='balanced')

# MoonScout.ipynb cell 4
# export: core.py

# fit_terrain(df, k) returns a copied sample table with cluster labels, site IDs,
# proxy scores, and a sampled silhouette score; the input table is not modified.
def fit_terrain(df, k=4):
    df = df.copy().reset_index(drop=True)
    # Require enough rows and distinct feature pairs for the requested cluster count.
    if len(df)<k or len(df[['tio2','omat']].drop_duplicates())<k:
        raise ValueError('Need at least four distinct valid TiO2/OMAT samples.')
    
    # Standardize TiO2 and OMAT so their different numerical scales do not dominate
    # Euclidean distances. Geographic coordinates are not clustering features.
    x = StandardScaler().fit_transform(df[['tio2','omat']])
    
    # Fit k groups with ten initializations and a fixed seed for repeatability.
    # Cluster numbers are arbitrary identifiers, not an ordering of resource quality.
    model = KMeans(n_clusters=k, random_state=530, n_init=10).fit(x)
    df['cluster'] = model.labels_.astype(str)
    df['site_id'] = [f'L{i:05d}' for i in range(len(df))]
    
    # Rank samples separately from K-means: favor higher TiO2 and lower OMAT.
    # The 65/35 percentile weighting is an exploratory heuristic, not helium-3 abundance.
    df['score'] = 100*(.65*df.tio2.rank(pct=True)+.35*(-df.omat).rank(pct=True))
   
    # Estimate group separation using at most 1,500 standardized samples.
    # Silhouette measures clustering structure, not geological prediction accuracy.
    sil = silhouette_score(x, model.labels_, sample_size=min(1500,len(df)), random_state=530)
    return df, float(sil)

# MoonScout.ipynb cell 5
# export: core.py

# validate_plan(plan) checks the complete query schema and returns the same plan
# on success; invalid fields, bounds, counts, or priorities raise ValueError.
def validate_plan(plan):
    if set(plan) != set(DEFAULT):
        raise ValueError('The query plan has unexpected or missing fields.')
    
    # Reject booleans, nonnumeric values, NaN, and infinity in numeric fields.
    for key in ['west','east','south','north','minimum_tio2','top_n']:
        if isinstance(plan[key], bool) or not isinstance(plan[key], (float,int)) or not np.isfinite(plan[key]):
            raise ValueError(f'Invalid numeric value for {key}.')
    
    # Require ordered lunar bounds; a single region cannot cross the date line.
    if not -180<=plan['west']<plan['east']<=180 or not -90<=plan['south']<plan['north']<=90:
        raise ValueError('Use ordered lunar bounds: west < east, south < north. Split dateline-crossing regions.')
    
    # Constrain the TiO2 threshold and require a whole-number shortlist size.
    if not 0<=plan['minimum_tio2']<=15 or not 1<=plan['top_n']<=50 or int(plan['top_n'])!=plan['top_n']:
        raise ValueError('TiO2 must be 0–15 wt%; candidate count must be an integer from 1–50.')
    if plan['priority'] not in ['balanced','tio2','maturity']:
        raise ValueError('Unsupported ranking priority.')
    return plan

# MoonScout.ipynb cell 6
# export: core.py

# plan_query translates a question into a validated search plan, retaining prior
# settings unless the supported request changes them. It does not retrieve data.
def plan_query(query, current, use_llm=False, model='gemma3:4b'):
    if not query.strip():
        raise ValueError('Enter a prospecting question.')
    
    # Optional Ollama mode asks a model on this server for JSON only; requests for
    # unavailable measurements are instructed to return an error.
    if use_llm:
        system = ('Translate lunar prospecting requests into JSON. Only fields in the current plan are allowed. '
                  'Preserve prior values unless changed by the user. priority is balanced, tio2, or maturity. '
                  'Bounds are degrees east [-180,180] and north [-90,90]. minimum_tio2 is wt%. '
                  'For unsupported requests (helium abundance, solar wind, slope, landing safety, other elements) '
                  'return {"error":"Explain missing data"}. Do not invent measurements. Current plan: '+json.dumps(current))
        
        # Send the current plan and question to the local chat endpoint. Connection and
        # response timeouts keep an unavailable model from waiting indefinitely.
        response = requests.post('http://localhost:11434/api/chat', json=dict(model=model,
            messages=[dict(role='system',content=system),dict(role='user',content=query)],
            format='json', stream=False, options={'temperature':0}), timeout=(5,90))
        response.raise_for_status()
        plan = json.loads(response.json()['message']['content'])
        if 'error' in plan:
            raise ValueError(str(plan['error']))
        
        # Validate model output with the same deterministic rules as manual controls.
        return validate_plan(plan)
    
    # Offline mode normalizes case and trailing punctuation, then copies the plan
    # and accepts only the explicit commands below; unsupported questions fail.
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

# MoonScout.ipynb cell 7
# export: core.py

# rank_sites(df, plan) returns up to top_n samples within the inclusive lunar
# bounds and above the TiO2 threshold, after validating the plan.
def rank_sites(df, plan):
    validate_plan(plan)
    eligible = df[df.longitude.between(plan['west'],plan['east']) & df.latitude.between(plan['south'],plan['north']) & (df.tio2>=plan['minimum_tio2'])].copy()
    
    # Balanced/TiO2 rankings sort highest first; maturity sorts lowest OMAT first.
    # Use site_id as a stable secondary sort key when primary values tie.
    key, ascending = {'balanced':('score',False),'tio2':('tio2',False),'maturity':('omat',True)}[plan['priority']]
    return eligible.sort_values([key,'site_id'],ascending=[ascending,True]).head(int(plan['top_n']))

# MoonScout.ipynb cell 8
# export: core.py

# explain(result, plan) builds a deterministic text summary from the actual
# shortlist and its leading sample; no LLM or additional measurements are used.
def explain(result, plan):
    
    # Report an empty shortlist explicitly rather than silently relaxing constraints.
    if result.empty:
        return 'No samples meet these constraints. Expand the region or lower the minimum TiO2; constraints have not been relaxed automatically.'
    
    # Use the first ranked row and state the limits of these prospecting proxies.
    row = result.iloc[0]
    prefix = 'Imported raster samples: '
    return (f'{prefix}{len(result)} candidates ranked by {plan["priority"]}. '
            f'Leading sample {row.site_id} is at {row.latitude:.2f}°N, {row.longitude:.2f}°E, '
            f'with TiO2 {row.tio2:.2f} wt%, OMAT {row.omat:.3f}, and terrain group {row.cluster}. '
            'These proxies support follow-up investigation; they do not measure helium-3 or establish landing suitability.')
