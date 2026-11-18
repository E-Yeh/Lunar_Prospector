# GENERATED FROM MoonScout.ipynb. Edit the notebook, not this file.
# MoonScout.ipynb cell 3
# export: core.py

# Import JSON/regex helpers, numerical tables, HTTP requests, and scikit-learn tools
# Used for deterministic analysis and OpenAI query planning.
import json
import os
import numpy as np
import pandas as pd
import requests
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

# DEFAULT defines the initial search region in degrees, minimum TiO2 in wt%,
# maximum shortlist size, and ranking priority. Callers copy it before editing.
DEFAULT = dict(west=-60., east=60., south=-40., north=40., minimum_tio2=2., top_n=8, priority='balanced')

# OpenAI configuration: an environment variable can select another model that
# supports Responses API Structured Outputs. The app also reads Streamlit secrets.
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')

# Optional code-based key location requested by the project owner. Leave empty
# for a published repository and configure OPENAI_API_KEY in Streamlit secrets.
OPENAI_API_KEY = ''

# A strict envelope lets the model explicitly decline unsupported requests.
# Every plan field is required; validate_plan still enforces numeric/business rules.
PLAN_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'supported': {'type': 'boolean'},
        'plan': {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                **{key: {'type': 'number'} for key in
                   ['west', 'east', 'south', 'north', 'minimum_tio2']},
                'top_n': {'type': 'integer'},
                'priority': {'type': 'string', 'enum': ['balanced', 'tio2', 'maturity']},
            },
            'required': list(DEFAULT),
        },
    },
    'required': ['supported', 'plan'],
}

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

# plan_query sends a question and current constraints to OpenAI and returns a
# validated plan. It never sends raster files, executes model code, or uses an
# offline parser. Failed requests leave state management to the calling UI.
def plan_query(query, current, api_key=None, model=OPENAI_MODEL):
    if not query.strip():
        raise ValueError('Enter a prospecting question.')
    validate_plan(current)
    key = (api_key or os.getenv('OPENAI_API_KEY') or OPENAI_API_KEY).strip()
    if not key:
        raise ValueError('Configure OPENAI_API_KEY in Streamlit secrets or the server environment.')
    system = (
        'Translate lunar prospecting requests into the supplied JSON schema. '
        'Preserve current plan values unless the user changes them. '
        'Bounds are degrees east [-180,180] and north [-90,90]; minimum_tio2 is wt%. '
        'top_n must be 1-50. priority is balanced, tio2, or maturity. '
        'Lower OMAT means greater optical maturity. Best spots means balanced proxy ranking. '
        'Only geographic bounds, TiO2 thresholds, candidate count, and these ranking priorities are supported. '
        'For requests requiring helium abundance, solar wind, slope, landing safety, other elements, '
        'mining feasibility, or any unavailable constraint, set supported=false and return the current plan unchanged. '
        'Never silently drop an unsupported constraint or invent measurements. '
        'For supported requests set supported=true. Current plan: ' + json.dumps(current)
    )
    # REST avoids an additional SDK dependency. Disable response storage and bound
    # connection/read waits. Credentials stay in the server-side Authorization header.
    try:
        response = requests.post(
            'https://api.openai.com/v1/responses',
            headers={'Authorization': f'Bearer {key}'},
            json={
                'model': model, 'store': False, 'max_output_tokens': 1200,
                'input': [{'role': 'system', 'content': system},
                          {'role': 'user', 'content': query}],
                'text': {'format': {'type': 'json_schema', 'name': 'lunar_query',
                                    'strict': True, 'schema': PLAN_SCHEMA}},
            }, timeout=(10, 90),
        )
    except requests.RequestException:
        raise ValueError('OpenAI could not be reached. Please retry shortly.') from None
    # Do not echo raw provider errors, request headers, or keys into the public UI.
    if response.status_code in (401, 403):
        raise ValueError('OpenAI authentication failed. Check the server API key and project access.')
    if response.status_code == 429:
        raise ValueError('OpenAI quota or rate limit reached. Check billing or retry later.')
    if response.status_code != 200:
        raise ValueError('OpenAI request failed. Check the configured model and service availability.')
    try:
        payload = response.json()
        if payload.get('status') != 'completed':
            raise ValueError('incomplete')
        # Responses may contain non-message items. Read only assistant text and
        # reject refusals instead of treating them as a valid query plan.
        content = [part for item in payload.get('output', [])
                   if item.get('type') == 'message' for part in item.get('content', [])]
        if any(part.get('type') == 'refusal' for part in content):
            raise ValueError('refused')
        envelope = json.loads(''.join(part['text'] for part in content
                                      if part.get('type') == 'output_text'))
        if set(envelope) != {'supported', 'plan'} or type(envelope['supported']) is not bool:
            raise ValueError('invalid envelope')
        plan = validate_plan(envelope['plan'])
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('OpenAI did not return a complete valid query plan. Please rephrase or retry.') from None
    if not envelope['supported']:
        raise ValueError('This request requires unavailable data or constraints. Use lunar bounds, TiO2, optical maturity, and candidate count.')
    return plan

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
