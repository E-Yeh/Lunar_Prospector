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

## Queries

Try `highest TiO2`, then `top 5`. Region and ranking controls adjust the retrieved candidates. Export the shortlist and provenance from Explore. Methods & project explains the workflow and shows source receipts.

Optional local Ollama integration translates natural language into validated query plans at localhost:11434. Enable it only with an installed running model. Offline command parsing is explicitly labeled and is not an LLM. No live model behavior has been validated here.

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
