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
from sklearn.metrics import silhouette_score, adjusted_rand_score
from sklearn.mixture import GaussianMixture

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
                'priority': {'type': 'string', 'enum': ['balanced', 'tio2', 'maturity', 'exposure']},
            },
            'required': list(DEFAULT),
        },
    },
    'required': ['supported', 'plan'],
}

# Geographic exposure model configuration. f=0.20 is a scenario assumption
# (5.906 days per 29.53-day orbit), not a fitted or observed shielding fraction.
EXPOSURE_SHIELDED_FRACTION = 0.20
EXPOSURE_MODEL = {
    'name': 'Flat-surface normalized geographic solar-wind exposure',
    'version': '1.0',
    'source': 'https://doi.org/10.3390/rs12203350',
    'equation': '4, flat-surface simplification; divided by equatorial farside value',
    'shielded_fraction': EXPOSURE_SHIELDED_FRACTION,
    'synodic_month_days': 29.53,
    'units': 'dimensionless, 0 to 1',
    'longitude_convention': 'degrees east; 0=sub-Earth meridian, +/-180=farside',
    'assumptions': ['constant incident solar wind', 'complete shielding during fraction f',
                    'spherical Moon; zero axial tilt; constant local incidence factor'],
    'excludes': ['OMNI or other measured particle data', 'terrain and local magnetic shielding',
                 'soil exposure age, retention and saturation', 'helium-3 concentration'],
}


def geographic_exposure(latitude, longitude, shielded_fraction=EXPOSURE_SHIELDED_FRACTION):
    """Return relative monthly exposure (0..1), not flux or He-3 abundance.

    Adapted from Shukla et al. (2020), Eq. 4. A constant surface-incidence
    factor and F0 cancel on normalization by the equatorial farside maximum.
    Scalars and broadcast-compatible arrays are accepted; angles are degrees.
    """
    # Bound the physical domain before evaluating the three longitude regimes.
    if (isinstance(shielded_fraction, (bool, np.bool_)) or
            not np.isscalar(shielded_fraction)):
        raise ValueError('Shielded fraction must be a finite number from 0 to 0.5.')
    f = float(shielded_fraction)
    if not np.isfinite(f) or not 0 <= f <= 0.5:
        raise ValueError('Shielded fraction must be a finite number from 0 to 0.5.')
    lat, lon = np.broadcast_arrays(np.asarray(latitude, dtype=float),
                                  np.asarray(longitude, dtype=float))
    if not np.all(np.isfinite(lat)) or not np.all(np.isfinite(lon)) or np.any(np.abs(lat) > 90):
        raise ValueError('Coordinates must be finite and latitude must be within +/-90 degrees.')
    # Wrap either east-longitude convention to [-180,180); east/west exposure
    # is symmetric in this idealized model. This also joins the dateline cleanly.
    phi = np.deg2rad(np.abs((lon + 180.) % 360. - 180.))
    edge_near, edge_far = np.pi * (0.5 - f), np.pi * (0.5 + f)
    # Integrate the sunward projected area outside the completely shielded arc:
    # central nearside, transition toward the limbs, then unaffected farside.
    longitude_factor = np.where(
        phi <= edge_near,
        2. + np.sin(phi - f*np.pi) - np.sin(phi + f*np.pi),
        np.where(phi < edge_far, 1. + np.sin(phi - f*np.pi), 2.))
    # Division by 2 fixes a global reference, independent of the selected region.
    # Clip roundoff only; the mathematical model already lies between zero and one.
    return np.clip(np.cos(np.deg2rad(lat)) * longitude_factor / 2., 0., 1.)

# MoonScout.ipynb cell 4
# export: core.py

# Both methods use the SAME standardized features and rows. Geographic exposure
# stays outside clustering so this experiment isolates the choice of algorithm.
TERRAIN_FEATURES = ['tio2', 'omat']


def sampled_silhouette(x, labels, indices):
    """Measure hard-label separation on shared rows, or None if undefined."""
    # A fixed set of indices makes the two scores comparable. A model may assign
    # only one group in this subset, or one group per row; silhouette then has no
    # mathematical definition. Report unavailable rather than inventing a zero.
    sampled_labels = np.asarray(labels)[indices]
    if not 1 < len(np.unique(sampled_labels)) < len(indices):
        return None
    return float(silhouette_score(x[indices], sampled_labels))


def fit_terrain(df, k=4):
    """Fit K-means plus a GMM candidate; retain the existing two-value API.

    The returned frame keeps K-means as its active `cluster` column. Both sets
    of labels and all GMM membership probabilities are retained for comparison.
    JSON-serializable diagnostics/configuration live in attrs['terrain_comparison'].
    """
    df = df.copy().reset_index(drop=True)
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 2:
        raise ValueError('Terrain comparison requires an integer group count of at least 2.')
    features = df[TERRAIN_FEATURES].to_numpy(dtype=float)
    if not np.isfinite(features).all():
        raise ValueError('Terrain features must contain only finite values.')
    if len(df) <= k or len(df[TERRAIN_FEATURES].drop_duplicates()) < k:
        raise ValueError(f'Need more than {k} rows and at least {k} distinct TiO2/OMAT pairs.')

    # Fit the scaler once, then pass exactly the same matrix to both methods.
    # This prevents unit differences (wt% versus OMAT) from dominating distances.
    scaler = StandardScaler().fit(features)
    x = scaler.transform(features)
    km = KMeans(n_clusters=k, random_state=530, n_init=10).fit(x)
    df['kmeans_cluster'] = km.labels_.astype(str)
    df['cluster'] = df['kmeans_cluster']
    df['terrain_model'] = 'K-means'
    df['site_id'] = [f'L{i:05d}' for i in range(len(df))]
    df['solar_wind_exposure'] = geographic_exposure(df.latitude, df.longitude)
    # Ranking is deliberately independent of grouping. Switching methods must
    # not change candidate IDs/order, proxy scores, or geographic exposure.
    df['score'] = 100*(.65*df.tio2.rank(pct=True)+.35*(-df.omat).rank(pct=True))

    # Reuse a deterministic subset for both silhouette evaluations. The report
    # records the sample size and seed so evaluation can be reproduced.
    indices = np.random.RandomState(530).permutation(len(df))[:min(1500,len(df))]
    km_sil = sampled_silhouette(x, km.labels_, indices)
    report = dict(features=TERRAIN_FEATURES.copy(), groups=int(k), seed=530,
                  n_init=10, samples=len(df), silhouette_samples=len(indices),
                  scaler_mean=scaler.mean_.tolist(), scaler_scale=scaler.scale_.tolist(),
                  kmeans_silhouette=km_sil, gmm_silhouette=None,
                  adjusted_rand=None, gmm_available=False, gmm_status='Not fitted',
                  covariance_type='full', reg_covar=1e-6, max_iter=300,
                  gmm_bic=None, gmm_aic=None, gmm_iterations=None,
                  mean_max_membership=None)
    # Full covariance lets each component have its own tilted ellipse in feature
    # space. Small diagonal regularization protects nearly singular covariances.
    # Ten starts reduce dependence on initialization; the seed fixes repeatability.
    try:
        gmm = GaussianMixture(n_components=k, covariance_type='full', n_init=10,
                              random_state=530, reg_covar=1e-6, max_iter=300).fit(x)
        if not gmm.converged_:
            raise ValueError('GMM did not converge within 300 iterations.')
        probabilities = gmm.predict_proba(x)
        labels = probabilities.argmax(axis=1)
        df['gmm_cluster'] = labels.astype(str)
        # Membership is conditional on the fitted Gaussian model. It is NOT a
        # calibrated probability of a geological class, useful deposit, or He-3.
        df['gmm_max_membership'] = probabilities.max(axis=1)
        for component in range(k):
            df[f'gmm_p_{component}'] = probabilities[:,component]
        report.update(gmm_available=True, gmm_status='Converged',
                      gmm_iterations=int(gmm.n_iter_),
                      gmm_silhouette=sampled_silhouette(x,labels,indices),
                      adjusted_rand=float(adjusted_rand_score(km.labels_,labels)),
                      mean_max_membership=float(probabilities.max(axis=1).mean()),
                      gmm_bic=float(gmm.bic(x)), gmm_aic=float(gmm.aic(x)))
    except (ValueError, np.linalg.LinAlgError) as error:
        # GMM is experimental: a failed fit must not disable the working K-means
        # workflow or pretend that K-means labels are GMM output.
        report['gmm_status'] = f'Unavailable: {error}'
    df.attrs['terrain_comparison'] = report
    return df, km_sil


def select_terrain(df, method='K-means'):
    """Return a view copy with the chosen label column; never refit or rerank."""
    # A single alias keeps map colors, popups, explanations, and CSV exports in
    # agreement, while preserving both original label columns for comparison.
    if method not in ['K-means','GMM']:
        raise ValueError('Choose K-means or GMM.')
    if method == 'GMM' and not df.attrs['terrain_comparison']['gmm_available']:
        raise ValueError('GMM is unavailable; inspect the comparison report.')
    selected = df.copy()
    selected['cluster'] = selected['kmeans_cluster' if method=='K-means' else 'gmm_cluster']
    selected['terrain_model'] = method
    return selected

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
    if plan['priority'] not in ['balanced','tio2','maturity','exposure']:
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
        'top_n must be 1-50. priority is balanced, tio2, maturity, or exposure. '
        'Lower OMAT means greater optical maturity. Best spots means balanced proxy ranking. '
        'Only geographic bounds, TiO2 thresholds, candidate count, and these ranking priorities are supported. '
        'Requests for highest solar-wind exposure use priority=exposure: this is a modeled relative '
        'geographic exposure index, not measured flux or accumulated dose. '
        'Exposure thresholds and changes to shielding assumptions are unsupported. '
        'For requests requiring helium abundance, measured solar wind, time-dependent flux, slope, landing safety, other elements, '
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
        raise ValueError('This request requires unavailable data or constraints. Use lunar bounds, TiO2, optical maturity, modeled exposure ranking, and candidate count.')
    return plan

# MoonScout.ipynb cell 7
# export: core.py

# rank_sites(df, plan) returns up to top_n samples within the inclusive lunar
# bounds and above the TiO2 threshold, after validating the plan.
def rank_sites(df, plan):
    validate_plan(plan)
    eligible = df[df.longitude.between(plan['west'],plan['east']) & df.latitude.between(plan['south'],plan['north']) & (df.tio2>=plan['minimum_tio2'])].copy()
    
    # Balanced/TiO2/exposure rankings sort highest first; maturity sorts lowest OMAT first.
    # Use site_id as a stable secondary sort key when primary values tie.
    key, ascending = {'balanced':('score',False),'tio2':('tio2',False),'maturity':('omat',True),'exposure':('solar_wind_exposure',False)}[plan['priority']]
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
            f'with TiO2 {row.tio2:.2f} wt%, OMAT {row.omat:.3f}, and {row.terrain_model} terrain group {row.cluster}. '
            f'Modeled relative solar-wind exposure is {row.solar_wind_exposure:.3f} on a 0-1 scale '
            f'(shielded fraction {EXPOSURE_SHIELDED_FRACTION:.2f}; not measured flux). '
            'These proxies support follow-up investigation; they do not measure helium-3 or establish landing suitability.')
