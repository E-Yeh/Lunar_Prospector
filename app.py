# GENERATED FROM MoonScout.ipynb. Edit the notebook, not this file.
# MoonScout.ipynb cell 15
# export: app.py

# This cell defines the Streamlit page at module scope: Streamlit reruns it
# on interaction, while session_state preserves loaded data and user settings.
import json
import os
import numpy as np
import streamlit as st
import leafmap.foliumap as leafmap
import folium
# Altair (bundled with Streamlit) gives both comparison plots identical axes.
import altair as alt
from sklearn.metrics import adjusted_rand_score
from core import DEFAULT, fit_terrain, plan_query, rank_sites, explain, OPENAI_API_KEY, OPENAI_MODEL, EXPOSURE_MODEL, select_terrain
from rasters import load_sources, SOURCE_PAGES

# Configure the browser page and inject the interface's compact visual styling.
st.set_page_config(page_title='MoonScout | Lunar prospecting', page_icon='🌘', layout='wide')
st.markdown('''<style>.block-container{padding-top:2rem}h1{letter-spacing:-1.8px} div[data-testid="stMetric"]{background:#151e2d;padding:12px;border-radius:12px} div[data-testid="stMetricValue"]{font-size:1.4rem} .eyebrow{color:#76e0c5;letter-spacing:3px;font-size:12px}</style>''',unsafe_allow_html=True)

# Invalidate old fitted tables so every session gains both model labels and diagnostics.
if st.session_state.get('data_policy_version') != 6:
    st.session_state.clear()
    st.session_state.update(data_policy_version=6, data=None, terrain_runs={}, silhouette=None, provenance=[], plan=dict(DEFAULT), history=[])

# Read server configuration without displaying or storing credentials in chat.
# Streamlit secrets take precedence over environment variables and code defaults.
def server_setting(name, default=''):
    try:
        value = st.secrets.get(name)
    except FileNotFoundError:
        value = None
    return str(value or os.getenv(name) or default).strip()

api_key = server_setting('OPENAI_API_KEY', OPENAI_API_KEY)
model = server_setting('OPENAI_MODEL', OPENAI_MODEL)

# Navigation and query-engine status. All questions use OpenAI.
with st.sidebar:
    st.markdown('### 🌘 MoonScout')
    st.caption('LUNAR PROSPECTING WORKSPACE')
    page = st.radio('Workspace', ['Explore','Methods & project'],label_visibility='collapsed')
    # Both feature experiments are fitted once on identical source rows.
    # This selector only swaps the active table, so a visual comparison does
    # not trigger downloads/refits or alter the user's prospecting query.
    feature_set = st.selectbox('Clustering features', ['TiO2 + OMAT','TiO2 + OMAT + exposure'], key='feature_set')
    if st.session_state.terrain_runs:
        st.session_state.data = st.session_state.terrain_runs[feature_set]
        st.session_state.silhouette = st.session_state.data.attrs['terrain_comparison']['kmeans_silhouette']
    # Switching models only selects existing labels; no model is refitted on
    # each widget interaction. K-means remains the default and always works
    # even if the experimental GMM cannot converge on a particular dataset.
    available = ['K-means']
    if st.session_state.data is not None and st.session_state.data.attrs['terrain_comparison']['gmm_available']:
        available.append('GMM')
    # A failed GMM in one experiment cannot leave an invalid widget choice
    # carried over from the other experiment. Reset to the available baseline.
    if st.session_state.get('terrain_method','K-means') not in available:
        st.session_state.terrain_method = 'K-means'
    terrain_method = st.selectbox('Terrain model', available, key='terrain_method')
    st.caption('Compare both models in Methods & project. Ranking is unchanged.')
    st.divider()
    st.caption('QUERY ENGINE')
    st.caption(f'OpenAI · {model}')
    if not api_key:
        st.warning('Set OPENAI_API_KEY in the app secrets to enable questions.')
    st.divider()
    st.write('No dataset loaded' if st.session_state.data is None else 'Source raster data')
    if st.session_state.data is not None:
        st.caption(f'{len(st.session_state.data):,} valid samples · 4 terrain groups')

# Display the shared title and approved-source description on both pages.
st.title('Find your next lunar lead.')
st.caption('Compare titanium abundance, optical maturity, and modeled solar-wind exposure. Build a shortlist for further investigation.')
st.caption('Measured-source layers: LROC WAC TiO₂ and USGS Kaguya MI OMAT. Solar-wind exposure is a geographic model.')

# Explore loads real source data once per session, fits terrain groups,
# and stores data, silhouette, and provenance for later reruns.
if page == 'Explore':
    if st.session_state.data is None:
        try:
            with st.status('Loading approved lunar datasets…', expanded=True) as status:
                data, provenance = load_sources(st.write)
                # Hold rows, group count, seed and initializations constant;
                # only the feature set differs between these paired fits.
                baseline, _ = fit_terrain(data)
                with_exposure, _ = fit_terrain(data, include_exposure=True)
                runs={'TiO2 + OMAT':baseline,'TiO2 + OMAT + exposure':with_exposure}
                clustered=runs[feature_set]
                st.session_state.update(data=clustered, terrain_runs=runs, silhouette=clustered.attrs['terrain_comparison']['kmeans_silhouette'], provenance=provenance)
                status.update(label='Source datasets loaded', state='complete', expanded=False)
            st.rerun()
        
        # A loading failure stops the page and offers retry; no substitute data is used.
        except Exception as error:
            st.error(f'The approved source datasets could not be loaded: {error}')
            st.info('No substitute data is used. Check the server connection and retry.')
            if st.button('Retry source loading'):
                st.rerun()
            st.stop()
    st.caption('Automatically loaded • LROC scientific abundance tiles + USGS OMAT 4 ppd overview • 2° sampling grid')
    
    # Read the current plan, then collect region and ranking edits in a form
    # so they are validated and applied together on submission.
    # Apply one model selection consistently to every Explore output.
    active_data=select_terrain(st.session_state.data, terrain_method)
    plan=st.session_state.plan
    with st.expander('Region & ranking controls',expanded=False):
        with st.form('controls'):
            cols=st.columns(4)
            values={key:cols[i].number_input(key.title(),value=float(plan[key])) for i,key in enumerate(['west','east','south','north'])}
            cols=st.columns(3)
            values['minimum_tio2']=cols[0].number_input('Minimum TiO₂ (wt%)',0.,15.,float(plan['minimum_tio2']))
            values['top_n']=cols[1].number_input('Candidates',1,50,int(plan['top_n']))
            values['priority']=cols[2].selectbox('Rank by',['balanced','tio2','maturity','exposure'],index=['balanced','tio2','maturity','exposure'].index(plan['priority']))
            if st.form_submit_button('Apply constraints'):
                from core import validate_plan
                try:
                    st.session_state.plan=validate_plan(values)
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
    
    # Place question controls/history in the left column and the map/table
    # in the right column; all views share the current session plan.
    left,right=st.columns([.85,1.65],gap='large')
    with left:
        st.subheader('01 / Ask & refine')
        st.caption('Try “highest TiO2”, “highest solar wind exposure”, then “top 5”. Follow-ups retain the current region and filters.')
        with st.form('question',clear_on_submit=True):
            question=st.text_area('Prospecting question',placeholder='Find the best spots',height=105)
            run=st.form_submit_button('Find candidates',type='primary', disabled=not api_key)
        
        # On submission, parse and validate the question, rank real samples, and
        # create a grounded summary before committing the new plan and conversation.
        if run:
            try:
                with st.spinner('Plan → validate → retrieve → rank → explain'):
                    new_plan=plan_query(question,st.session_state.plan,api_key=api_key,model=model)
                    results=rank_sites(active_data,new_plan)
                    response=explain(results,new_plan)
                st.session_state.plan=new_plan
                st.session_state.history.append((question,response,f'OpenAI · {model}'))
            except Exception as error:
                st.error(f'Query stopped; previous results retained. {error}')
        
        # Show the four most recent exchanges and identify which query engine ran.
        for question,response,engine in st.session_state.history[-4:]:
            with st.chat_message('user'): st.write(question)
            with st.chat_message('assistant'):
                st.write(response)
                st.caption(engine)
        if st.button('Clear conversation'):
            st.session_state.history=[]
            st.rerun()
        
        # Expose the processing steps and exact current plan for inspection.
        with st.expander('Workflow trace'):
            st.write('1. Parse request into a constrained plan.\n2. Validate bounds and available fields.\n3. Retrieve matching samples.\n4. Rank by proxies and attach fitted terrain groups.\n5. Explain using exact retrieved values.')
            st.json(st.session_state.plan)
    
    # Recompute the shortlist from current constraints and define summary metrics
    # and the selected display field (TiO2, OMAT, cluster ID, or modeled exposure).
    with right:
        result=rank_sites(active_data,st.session_state.plan)
        st.subheader('02 / Survey the candidates')
        a,b,c=st.columns(3)
        a.metric('Shortlisted',len(result))
        b.metric('Top TiO₂',f'{result.tio2.max():.2f} wt%' if len(result) else '—')
        c.metric('Terrain groups',result.cluster.nunique())
        st.caption(f'Terrain labels: {terrain_method}; features: {feature_set}. Numbers/colors are local to each fit, not matching geological classes.')
        layer=st.selectbox('Surface layer',['TiO₂ abundance','Optical maturity','Terrain groups','Modeled solar-wind exposure'])
        
        # Simple CRS maps lunar longitude/latitude directly; Earth distance tools are disabled.
        m=leafmap.Map(center=[0,0],zoom=1,tiles=None,crs='Simple',draw_control=False,
                      measure_control=False,fullscreen_control=True,latlon_control=False,
                      search_control=False,scale_control=False)
        
        # Remove any default Earth tile layers that the map constructor may add.
        for key in list(m._children):
            if isinstance(m._children[key],folium.raster_layers.TileLayer): del m._children[key]
        data=active_data
        
        # The surface preview uses all samples inside the geographic bounds, while
        # the shortlist also applies the minimum TiO2 and candidate-count filters.
        region=data[data.longitude.between(st.session_state.plan['west'],st.session_state.plan['east']) & data.latitude.between(st.session_state.plan['south'],st.session_state.plan['north'])]
        field={'TiO₂ abundance':'tio2','Optical maturity':'omat','Terrain groups':'cluster','Modeled solar-wind exposure':'solar_wind_exposure'}[layer]
        
        # Define categorical cluster colors; continuous layers use a separate ramp.
        colors=['#70e1c4','#f5b86b','#9898f0','#eb83ae']
        
        # Reconstruct the imported regular grid as a small RGBA raster overlay.
        if len(region):
            p=st.session_state.plan
            
            # Recover and crop grid axes, ordering latitude north-to-south to match
            # the image overlay's upper origin.
            xs=np.sort(np.asarray(data.attrs.get('grid_longitudes',data.longitude.unique())))
            ys=np.sort(np.asarray(data.attrs.get('grid_latitudes',data.latitude.unique())))[::-1]
            xs=xs[(xs>=p['west'])&(xs<=p['east'])]; ys=ys[(ys>=p['south'])&(ys<=p['north'])]
            if len(xs)>1 and len(ys)>1:
                
                # Initialize transparent RGBA cells; unobserved locations stay transparent.
                # Coordinate-to-index dictionaries place each real sample in its grid cell.
                grid=np.zeros((len(ys),len(xs),4),dtype=np.uint8)
                xidx={x:i for i,x in enumerate(xs)}; yidx={y:i for i,y in enumerate(ys)}
                
                # Scale continuous colors to the visible region's min/max; cluster colors
                # use discrete IDs. The fallback denominator handles a constant-valued region.
                low,high=region[field].astype(float).min(),region[field].astype(float).max()
                # Exposure uses the global 0..1 reference so colors remain comparable
                # across regions; measured layers retain their existing local scaling.
                if field == 'solar_wind_exposure':
                    low, high = 0., 1.
                for row in region.itertuples():
                    value=float(getattr(row,field)); t=(value-low)/(high-low or 1)
                    color=colors[int(row.cluster)] if field=='cluster' else None
                    rgb=[int(color[i:i+2],16) for i in (1,3,5)] if color else [int(35+210*t),int(65+130*t),int(90+30*t)]
                    grid[yidx[row.latitude],xidx[row.longitude]]=[*rgb,210]
                
                # Extend overlay bounds by half a grid spacing so samples sit at cell centers.
                dx=(xs[1]-xs[0])/2; dy=abs(ys[1]-ys[0])/2
                folium.raster_layers.ImageOverlay(grid,bounds=[[ys[-1]-dy,xs[0]-dx],[ys[0]+dy,xs[-1]+dx]],name=layer,origin='upper').add_to(m)
        
        # Add numbered shortlist markers with exact coordinates, proxy values,
        # and terrain labels, then frame the map using the selected bounds.
        for rank,row in enumerate(result.itertuples(),1):
            popup=f'#{rank} · {row.site_id}<br>{row.latitude:.2f}°N, {row.longitude:.2f}°E<br>TiO₂ {row.tio2:.2f} wt%<br>OMAT {row.omat:.3f}<br>Modeled exposure {row.solar_wind_exposure:.3f} (0–1)<br>{row.terrain_model} terrain {row.cluster}'
            folium.Marker([row.latitude,row.longitude],tooltip=f'#{rank} {row.site_id}',popup=popup,
                icon=folium.DivIcon(html=f'<div style="background:#76e0c5;color:#101722;border:2px solid white;border-radius:50%;width:25px;height:25px;text-align:center;font-weight:bold">{rank}</div>')).add_to(m)
        p=st.session_state.plan
        m.fit_bounds([[p['south'],p['west']],[p['north'],p['east']]])
        m.to_streamlit(height=410)
        st.caption('Lunar longitude/latitude · sampled raster preview, not full-resolution imagery. Continuous layers: dark = low, gold = high. Terrain groups: mint 0 · gold 1 · violet 2 · pink 3.')
        if field == 'solar_wind_exposure':
            st.caption('Modeled relative exposure: fixed 0–1 color scale; 1 = equatorial farside reference. Shielded orbit fraction f=0.20. No measured particle flux, terrain correction, or He-3 estimate.')
        elif len(region) and field!='cluster':
            st.caption(f'Visible color range: {region[field].min():.3f} to {region[field].max():.3f} '+('wt%' if field=='tio2' else 'OMAT'))
        
        # Show an explicit empty-result message or offer the ranked table, CSV
        # with source links, and JSON containing the query and provenance.
        if result.empty: st.info(explain(result,p))
        else:
            # Retain both assignments in the shortlist so switching labels is
            # auditable. Only show GMM fields when its fit actually succeeded.
            columns=['site_id','latitude','longitude','tio2','omat','solar_wind_exposure','terrain_model','terrain_features','cluster','kmeans_cluster','score']
            if 'gmm_cluster' in result:
                columns += ['gmm_cluster','gmm_max_membership']
                st.caption('GMM max membership describes group assignment under the model; it is not He-3 confidence.')
            st.dataframe(result[columns].round(3),hide_index=True,width='stretch')
            st.download_button('Download shortlist (CSV)',result.assign(tio2_source=SOURCE_PAGES['tio2'],omat_source=SOURCE_PAGES['omat'],exposure_model_source=EXPOSURE_MODEL['source'],exposure_model_version=EXPOSURE_MODEL['version'],exposure_shielded_fraction=EXPOSURE_MODEL['shielded_fraction']).to_csv(index=False),'lunar-shortlist.csv','text/csv')
            st.download_button('Download query & provenance',json.dumps({'plan':p,'provenance':st.session_state.provenance,'exposure_model':EXPOSURE_MODEL,'terrain_model':terrain_method,'terrain_comparison':active_data.attrs['terrain_comparison']},indent=2,default=str),'provenance.json','application/json')

# The Methods page explains the pipeline, cluster diagnostics, heuristic
# ranking, source limitations, provenance, and local-model setup.
else:
    st.subheader('A prospecting aid, with evidence in view')
    st.write('Designed for exploratory analysts comparing potential lunar prospecting regions. A successful interaction produces a traceable shortlist, not a mining or landing authorization.')
    st.markdown('### How the pieces fit')
    st.code('Question → LLM JSON plan → validation → raster sample retrieval\n                                           ↓\nPublisher rasters → common lunar grid → standardization → K-means / GMM comparison\n                                           ↓\n                     proxy ranking → Leafmap + table + explanation')
    st.markdown('### Compare K-means and GMM')
    st.write('Both methods fit the same samples with four groups, ten starts and seed 530. The Clustering features selector adds modeled exposure as a third standardized feature. Coordinates are never direct features, but exposure introduces geographic structure. GMM uses full covariance and soft memberships. K-means with TiO₂ + OMAT remains the default.')
    st.caption(f'Active feature set: {feature_set}. Every selected feature has unit variance after scaling; this is not a scientific reliability weighting.')
    if st.session_state.data is None:
        st.info('Open Explore to load samples and fit the comparison.')
    else:
        data = st.session_state.data
        report = data.attrs['terrain_comparison']
        # None metrics are genuinely undefined, not zero. Both silhouettes use
        # the same standardized rows; ARI compares partitions without matching IDs.
        def metric_text(value):
            """Format optional diagnostics without implying unavailable values are zero."""
            return 'Unavailable' if value is None else f'{value:.3f}'
        a,b,c = st.columns(3)
        a.metric('K-means silhouette',metric_text(report['kmeans_silhouette']))
        b.metric('GMM silhouette',metric_text(report['gmm_silhouette']))
        c.metric('Adjusted Rand agreement',metric_text(report['adjusted_rand']))
        st.caption('Silhouette: higher indicates stronger distance separation of hard labels, not better He-3 prediction. It can favor compact K-means groups. ARI: 1 means identical partitions up to label renaming; near 0 is chance-level agreement. Agreement is not accuracy.')
        st.write('GMM status: '+report['gmm_status'])
        if report['gmm_available']:
            st.caption(f"GMM mean maximum membership: {report['mean_max_membership']:.3f}. BIC: {report['gmm_bic']:.1f}; AIC: {report['gmm_aic']:.1f}. Lower BIC/AIC can compare GMM configurations on the same data and scaling; these are not comparisons against K-means. This screen fits four components only.")
        else:
            st.warning('GMM is unavailable. K-means remains usable; inspect the diagnostics below.')
        # Show group profiles in ORIGINAL units for interpretation, including
        # group sizes. GMM soft means and hard-assignment averages can differ;
        # the table intentionally describes the displayed hard assignments.
        methods = [('K-means','kmeans_cluster')]
        if report['gmm_available']:
            methods.append(('GMM','gmm_cluster'))
        panels=st.columns(len(methods))
        # The plots use exactly the same deterministic rows, fixed axis ranges,
        # and units. Sampling limits browser work without changing the fitted data.
        plot_data=data.sample(n=min(2000,len(data)),random_state=530)
        for panel,(name,label) in zip(panels,methods):
            with panel:
                st.markdown(f'#### {name}')
                # Exposure averages help explain geographic splits even in
                # the baseline, where exposure is not a clustering input.
                profile=data.groupby(label).agg(samples=('site_id','count'),mean_tio2=('tio2','mean'),mean_omat=('omat','mean'),mean_exposure=('solar_wind_exposure','mean')).reset_index().rename(columns={label:'group'})
                st.dataframe(profile.round(3),hide_index=True)
                # Fix scales explicitly: independently auto-scaled panels can
                # make the same sample distribution look different by accident.
                chart=alt.Chart(plot_data).mark_circle(size=18,opacity=.45).encode(
                    x=alt.X('tio2:Q',title='TiO₂ (wt%)',scale=alt.Scale(domain=[0,15])),
                    y=alt.Y('omat:Q',title='OMAT',scale=alt.Scale(domain=[0,1])),
                    color=alt.Color(f'{label}:N',title='Group',scale=alt.Scale(
                        domain=['0','1','2','3'],range=['#70e1c4','#f5b86b','#9898f0','#eb83ae'])),
                    tooltip=['site_id','tio2','omat',label]).properties(height=280)
                st.altair_chart(chart,use_container_width=True)
                # A second projection makes splits along the new exposure
                # dimension visible; the TiO2/OMAT chart alone hides them.
                exposure_chart=chart.encode(y=alt.Y('solar_wind_exposure:Q',title='Modeled exposure (0–1)',scale=alt.Scale(domain=[0,1])),tooltip=['site_id','tio2','omat','solar_wind_exposure',label])
                st.altair_chart(exposure_chart,use_container_width=True)
        if report['gmm_available']:
            # A cross-tab reveals how groups split/merge. Comparing numeric IDs
            # directly would be misleading because each algorithm names arbitrarily.
            st.markdown('#### Assignment cross-tab (all samples)')
            import pandas as pd
            st.dataframe(pd.crosstab(data.kmeans_cluster,data.gmm_cluster))
            st.markdown('#### Most ambiguous GMM assignments')
            st.caption('Lowest maximum membership first. These are ambiguous group assignments, not necessarily poor prospecting candidates.')
            probability_columns=[column for column in data if column.startswith('gmm_p_')]
            st.dataframe(data.nsmallest(10,'gmm_max_membership')[['site_id','tio2','omat','gmm_cluster','gmm_max_membership']+probability_columns].round(3),hide_index=True)
        st.caption('Labels/colors do not correspond across models. Both methods partition continuous proxies and may not recover real geological classes. Spatial correlation, feature choice and initialization affect results. No model is selected automatically from these metrics.')
        with st.expander('Comparison settings and diagnostics'):
            st.json(report)
        # Export all rows and posterior columns for independent analysis. Include
        # configuration and source receipts separately so the comparison is repeatable.
        st.download_button('Download terrain comparison (CSV)',data.drop(columns=['cluster','terrain_model']).to_csv(index=False),'terrain-comparison.csv','text/csv')
        st.download_button('Download comparison diagnostics (JSON)',json.dumps({'comparison':report,'source_provenance':st.session_state.provenance},indent=2,default=str),'terrain-comparison.json','application/json')
        st.markdown('### What changes when exposure is included?')
        # Compare each algorithm against ITSELF across feature sets. ARI
        # ignores arbitrary group numbering, unlike a raw label mismatch
        # percentage. Cross-tabs show splits and merges without asserting
        # that baseline group 0 should correspond to exposure group 0.
        import pandas as pd
        baseline=st.session_state.terrain_runs['TiO2 + OMAT']
        augmented=st.session_state.terrain_runs['TiO2 + OMAT + exposure']
        paired=baseline[['site_id','latitude','longitude','tio2','omat','solar_wind_exposure']].copy()
        experiment_metrics=[]
        for name,label,metric in [('K-means','kmeans_cluster','kmeans_silhouette'),('GMM','gmm_cluster','gmm_silhouette')]:
            if label not in baseline or label not in augmented:
                st.info(f'{name} before/after comparison unavailable because one fit failed.')
                continue
            # Join by stable site ID, not incidental row order. Validate a
            # one-to-one pairing so each observation is counted once.
            assignments=baseline[['site_id',label]].merge(augmented[['site_id',label]],on='site_id',validate='one_to_one',suffixes=('_baseline','_exposure'))
            before,after=assignments[label+'_baseline'],assignments[label+'_exposure']
            ari=float(adjusted_rand_score(before,after))
            experiment_metrics.append({'model':name,'before_after_ARI':ari,'baseline_2D_silhouette':baseline.attrs['terrain_comparison'][metric],'exposure_3D_silhouette':augmented.attrs['terrain_comparison'][metric]})
            st.markdown(f'#### {name}: baseline versus exposure')
            st.caption(f'Before/after ARI: {ari:.3f}. Rows = baseline groups; columns = exposure groups; counts include all source samples.')
            st.dataframe(pd.crosstab(before,after))
            paired=paired.merge(assignments,on='site_id',validate='one_to_one')
        st.dataframe(pd.DataFrame(experiment_metrics).round(3),hide_index=True)
        st.caption('ARI describes how much the partition changes, not whether it improves. The 2D and 3D silhouettes use different distance spaces: do not treat their difference as proof of improvement. BIC/AIC are also not comparable across these feature sets. Exposure can produce broad latitude/longitude divisions because it is modeled from geography.')
        st.download_button('Download exposure experiment assignments (CSV)',paired.to_csv(index=False),'exposure-experiment.csv','text/csv')
        st.download_button('Download exposure experiment settings (JSON)',json.dumps({'runs':{key:value.attrs['terrain_comparison'] for key,value in st.session_state.terrain_runs.items()},'before_after':experiment_metrics,'source_provenance':st.session_state.provenance},indent=2,default=str),'exposure-experiment.json','application/json')
    st.markdown('### Ranking and limitations')
    st.write('Balanced score = 100 × (0.65 × TiO₂ percentile + 0.35 × inverse-OMAT percentile) within the loaded source dataset. This is an explicit exploratory heuristic, not a trained helium-3 model. Lower OMAT is treated as greater optical maturity, not a direct solar-wind exposure measurement. Pure TiO₂ and maturity rankings are also available. No helium-3 ground truth, slope, landing safety, other elements, extraction economics or direct solar-wind data are included.')
    st.write('WAC abundance values below 2 wt% are below the product detection limit; values above 15 wt% are excluded. OMAT outside 0–1 is excluded as a prototype quality check. Verify product-specific calibration and masks. Grid sampling can miss small high-value regions; nearby shortlist rows are not independent deposits.')
    # Keep model provenance distinct from receipts for downloaded measurements.
    st.markdown('### Modeled relative solar-wind exposure')
    st.write('Flat-surface adaptation of Shukla et al. (2020), Eq. 4: integrate geographic incidence outside an assumed fully shielded 20% of the lunar orbit, then normalize to the equatorial farside maximum. Longitude 0° is the sub-Earth meridian. Values are dimensionless, not measured flux, accumulated dose, or helium-3 concentration. No OMNI data, terrain correction, local magnetic shielding, soil age, retention, or saturation is included.')
    st.write('Exposure ranking sorts by this index. Adding exposure to clustering is a separate experiment controlled by Clustering features; balanced ranking stays unchanged. No missing raster measurement is filled. CSV and JSON exports identify the feature set, model source and shielding assumption.')
    st.markdown('[Model reference: Shukla et al. (2020), Eq. 4](https://doi.org/10.3390/rs12203350)')
    with st.expander('Exposure model assumptions & provenance'):
        st.json(EXPOSURE_MODEL)
    st.markdown('### Product decisions')
    st.write('1. Keep conversation beside the map and table, matching the scoping sketch. Explicit region controls and a visible parsed plan make constraints inspectable.\n\n2. Load only fixed publisher sources and cache successful downloads: source failures show an error instead of substitute data. The workflow stops on unsupported questions instead of silently dropping constraints. These are implementation decisions; user testing remains to be conducted.')
    with st.expander('Loaded source provenance'):
        st.json(st.session_state.provenance)
    st.caption('OMAT uses the publisher-provided 4 ppd scientific overview of the linked 512 ppd product. The map samples every 2 degrees and cannot identify local maxima at full raster resolution. Credit: JAXA/MoonScout; Lemelin et al. (2016).')
    st.markdown('### Sources & setup')
    st.markdown('- [LROC WAC TiO₂ product and calibration](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_TIO2)\n- [USGS Kaguya OMAT product](https://astrogeology.usgs.gov/search/map/kaguya_lunar_multiband_imager_mi_derived_optical_maturity_omat_50n50s_512ppd_59mpp)\n- [Leafmap Streamlit integration](https://leafmap.org/foliumap/)\n- [OpenAI Responses API](https://developers.openai.com/api/docs/guides/responses)')
    st.info('Questions use the OpenAI Responses API; there is no offline parser. The question and current plan are sent to OpenAI. Ranking and result summaries use deterministic code and real raster samples. Live-model evaluation and real-product calibration validation remain follow-up work.')
