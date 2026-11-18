# MoonScout — automatically loaded lunar prospecting

The app loads all its scientific data itself. There are no file uploaders, local-path fields, import screens, or configurable source URLs.

## Run

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

Open http://localhost:8501. First launch downloads about 1.2 GB into `.data/` beside the app. Allow several minutes and sufficient disk space. Later launches reuse cached source files and a sampled-data cache. The server needs outbound HTTPS access to the publisher endpoints. A failed load shows an error and retry button; it never substitutes generated data.

## Fixed sources

- LROC WAC TiO2: https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_TIO2
- USGS Kaguya MI OMAT: https://astrogeology.usgs.gov/search/map/kaguya_lunar_multiband_imager_mi_derived_optical_maturity_omat_50n50s_512ppd_59mpp

`rasters.py` downloads all eight WAC scientific PDS IMG abundance tiles from the LROC archive. The TIFFs under EXTRAS/BROWSE are 8-bit display products and are deliberately not used as wt% measurements. The IMG label identifies float32 TiO2 wt% values, about 400 m/pixel, and lunar projection metadata.

For OMAT the app downloads the publisher's 4 ppd scientific overview of the same 50N–50S product from the USGS Astrogeology distribution:
https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Lunar_MI_mineral_maps/index.html

This is real source data at lower resolution, not the 59 m/pixel full-resolution raster. The full-resolution product is 184320×51200 float pixels (about 38 GB uncompressed). The app labels the overview resolution in the interface and provenance. Credit JAXA/SELENE and Lemelin et al. (2016).

## Processing and provenance

A common 2-degree grid spans 180W–180E and 50S–50N. The app samples the nearest source pixel at grid centers, transforms coordinates using each raster's lunar CRS and handles longitude wrapping. It excludes missing or out-of-range samples (TiO2 0–15 wt%; OMAT 0–1). No missing measurement is fabricated or interpolated. This coarse overview cannot identify small local maxima or establish site suitability.

Atomic downloads include source URL, resolved URL, byte count and a locally calculated SHA-256 digest in `.data/`. The digest records downloaded content; it is not an independent publisher checksum. The sample cache is versioned. To refresh data, stop the server and remove `.data/` before restarting. Source URLs are fixed in code. Only successful complete downloads become cached files.

StandardScaler and KMeans use TiO2 and OMAT, k=4, n_init=10, seed 530. Terrain groups appear on Leafmap and in the candidate table. Balanced ranking is a separate heuristic: 65% TiO2 percentile and 35% inverse-OMAT percentile. Neither is a measured helium-3 concentration. WAC values below 2 wt% are below its detection limit. There are no slope, landing safety, other-element or economics layers.

## Modeled relative solar-wind exposure

MoonScout computes `solar_wind_exposure` at each valid raster sample using a
**flat-surface geographic adaptation of Equation 4 in [Shukla et al. (2020)](https://doi.org/10.3390/rs12203350)**.
This is a modeled, dimensionless monthly relative exposure index, not an
observational dataset, measured particle flux, accumulated soil dose, or He-3 prediction.
No OMNI downloads or additional dependencies are required.

Let `lambda` be latitude in radians, `a = abs(wrapped east longitude)` in radians,
and `f = 0.20` the assumed completely shielded fraction of a 29.53-day orbit
(5.906 days). Longitude zero is the sub-Earth meridian. Define:

```text
G(a,f) = 2 + sin(a - pi*f) - sin(a + pi*f),  a <= pi*(0.5-f)
       = 1 + sin(a - pi*f),                 pi*(0.5-f) < a < pi*(0.5+f)
       = 2,                               a >= pi*(0.5+f)
exposure = cos(lambda) * G(a,f) / 2
```

The constant incoming-flux and local-incidence factors cancel when normalized
to the equatorial farside maximum. Unlike the paper's terrain-dependent model,
this implementation assumes a spherical surface with a constant incidence factor,
zero axial tilt, constant solar wind, and complete shielding during the chosen
orbital fraction. `f=0.20` is a scenario from the paper's tested range, not a measured
or fitted value. The function accepts `0 <= f <= 0.5` for sensitivity tests.

Reference values with `f=0.20`: equatorial central nearside = approximately
0.412215; equatorial farside = 1; 60-degree-latitude farside = 0.5. Larger values
mean greater exposure under these assumptions. This is not the fraction of all
incoming particles retained in soil. Terrain, local magnetic shielding, exposure
age, retention, saturation, and historical solar-wind changes are not modeled.

Select **Modeled solar-wind exposure** in Surface layer, or **exposure** in Rank by.
The map uses a fixed 0–1 color scale. Try `highest solar wind exposure`, then
`top 5`; current geographic and TiO2 constraints remain in effect. Measured flux,
exposure thresholds, time-dependent requests, and He-3 estimates remain unsupported.
The shortlist, marker popups, and explanations include the index. CSV exports
include the model source, version, and shielding fraction; JSON provenance includes
all assumptions separately from the downloaded raster receipts.

K-means continues to use only TiO2 and OMAT. The 65/35 balanced score is unchanged;
exposure ranking is an explicit alternative. The model is evaluated only at valid
source samples and never substitutes for missing TiO2 or OMAT. Existing raster
caches can be reused; the app resets old session data when loading this version.

### Exact notebook change locations

Cell numbers below are **1-based file order**, including Markdown cells, not execution counts.
Existing cell IDs and order are preserved.

| Cell | Stable cell ID | Change |
| --- | --- | --- |
| 2 | `804c2993` | Navigation note for analysis changes. |
| 3 | `b2e65865` | Exposure configuration, provenance, commented `geographic_exposure` function; planner schema enum. |
| 4 | `59643e57` | Attach modeled exposure after fitting the original terrain features. |
| 5 | `c5b30403` | Validate the exposure ranking priority. |
| 6 | `90139b91` | Planner instructions distinguish relative modeled exposure from unavailable measurements. |
| 7 | `d74c716c` | Descending exposure ranking with existing filters and stable tie-breaking. |
| 8 | `f2835424` | Grounded result explanation includes exposure and its qualification. |
| 14 | `11d04713` | Navigation note for interface changes. |
| 15 | `dec08d5e` | Map, controls, shortlist, popups, exports, session migration, and Methods documentation. |
| 17 | `d079472d` | Imports for model tests. |
| 18 | `3d403ed8` | Model tests and real-source UI integration checks. |

Exporting also updates `core.py`, `app.py`, and `test_app.py`; `rasters.py` is unchanged.
The generated files are required for Streamlit Cloud deployment.

Run the offline model and mocked-planner checks after exporting:

```text
python run_notebooks.py --check
python -m unittest -v test_app.GeographicExposureTests test_app.OpenAIPlannerTests
```

The model tests cover reference values, longitude wrapping, hemispheric symmetry,
branch continuity, invalid inputs, range, shielding sensitivity, and an independent
numerical orbital integration. Full `python -m unittest -v` also exercises the app
against publisher rasters and can download about 1.2 GB on first use. These checks
verify the implementation, not empirical accuracy of exposure or He-3 predictions.

## Queries

Try `highest TiO2`, then `top 5`. Region and ranking controls adjust the retrieved candidates. Export the shortlist and provenance from Explore. Methods & project explains the workflow and shows source receipts.

All questions use the OpenAI Responses API with strict Structured Outputs, followed by local plan validation. There is no Ollama service, engine toggle, or offline parser. The default model is `gpt-4.1-mini`; configure `OPENAI_MODEL` server-side to use another Responses/Structured Outputs-compatible model. The existing deterministic retrieval, K-means, ranking, and factual summary remain unchanged.

### Streamlit deployment configuration

In your published app's **Settings → Secrets**, save:

```toml
OPENAI_API_KEY = "your-key-here"
OPENAI_MODEL = "gpt-4.1-mini"
```

Locally, the same entries can go in `.streamlit/secrets.toml` (already ignored by Git), or environment variables. The notebook's core configuration cell also contains `OPENAI_API_KEY = ''` as the requested optional code-based location. Secrets take precedence over environment variables, then the code default. Never commit a real key in the notebook or generated Python files; use Streamlit secrets for the published app.

Save notebook edits and run `python run_notebooks.py --check`, then upload/commit the notebook and generated modules together. Streamlit Cloud can continue using `app.py` as its entry point; it does not export the notebook automatically. This integration uses the existing `requests` dependency, so no new package is required.

Only the submitted question and current plan are sent to OpenAI, not raster files. Requests set `store=false`. Missing credentials disable question submission; authentication, quota, network, refusal, incomplete-output, or validation failures retain previous results and show an error. Manual region controls remain available. API requests incur usage charges; public app visitors use the configured project's key. API protocol and failure handling are tested with mocked responses; live model behavior requires a configured key and has not been validated here.

References: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Streamlit secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## Checks

```text
python -m unittest -v
```

Tests use the app-loaded real source cache for the normal path, and a simulated network exception for the failure path. No generated scientific data is used. Tests verify automatic population, query behavior, absence of upload controls, and no data fallback on source failure.

## Single notebook source of truth

Edit **MoonScout.ipynb** for all application code. It contains sections for core analysis, raster loading, the Streamlit interface, and tests. The launcher `run_notebooks.py` remains a small separate bootstrap utility.

```powershell
python run_notebooks.py --check
python run_notebooks.py --test
python run_notebooks.py --port 8503
```

The launcher reads saved cells, validates all four modules, and regenerates `app.py`, `core.py`, `rasters.py`, and `test_app.py` in the project root. It then launches Streamlit unless `--check` or `--test` is selected. Existing dataset caches and theme settings are reused. No manual export or notebook kernel execution is needed.

Each source cell has a visible `# export: module.py` marker and matching `export:module` metadata tag. Duplicate a cell from the same section when adding new code; preserve the matching marker and tag. Standard Python only: cell magics are not supported. Untagged code, unknown destinations, missing modules, mismatched markers and syntax errors stop export before any file is written. Deliberate notebook-only cells may use the `notebook-only` tag.

**Do not Run All in Jupyter.** These sections are separate modules, not a single shared-kernel program. Save edits and use the terminal launcher. It uses file order within each module, not historical cell execution counts. Streamlit UI, imports, `__file__`, and test execution depend on the generated module contexts.

Stop a running server with Ctrl+C before exporting changes, then restart. Saved notebook changes are not hot-reloaded. Changes made directly to generated Python files are overwritten at the next export. Commit the notebook and regenerated Python files together for GitHub/Codespaces; dependencies and configuration remain separate files.

Potential issues: a larger notebook has more Git merge conflicts; saved outputs can bloat the file or expose secrets; moving cells can break definition order; circular imports remain possible. Syntax checks do not replace runtime tests. Writes are atomic per file, not as a four-file transaction, so rerun `--check` after an interrupted export. Avoid simultaneous exporters or editing generated files while the server is running.

The former individual notebooks were moved to a workspace backup outside the deliverable and are not used or included in new archives. Older `.notebook_runtime/` exports are no longer used. No ML, ranking, or scientific data logic was changed by this consolidation.