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
from core import DEFAULT, fit_terrain, plan_query, rank_sites, explain, OPENAI_API_KEY, OPENAI_MODEL
from rasters import load_sources, SOURCE_PAGES

# Configure the browser page and inject the interface's compact visual styling.
st.set_page_config(page_title='MoonScout | Lunar prospecting', page_icon='🌘', layout='wide')
st.markdown('''<style>.block-container{padding-top:2rem}h1{letter-spacing:-1.8px} div[data-testid="stMetric"]{background:#151e2d;padding:12px;border-radius:12px} div[data-testid="stMetricValue"]{font-size:1.4rem} .eyebrow{color:#76e0c5;letter-spacing:3px;font-size:12px}</style>''',unsafe_allow_html=True)

# Invalidate old sessions, including data and messages from the removed demo mode.
if st.session_state.get('data_policy_version') != 3:
    st.session_state.clear()
    st.session_state.update(data_policy_version=3, data=None, silhouette=None,
                            provenance=[], plan=dict(DEFAULT), history=[])

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
st.markdown('<div class="eyebrow">MoonScout / EXPLORATORY INTELLIGENCE</div>',unsafe_allow_html=True)
st.title('Find your next lunar lead.')
st.caption('Compare titanium abundance and optical maturity. Build a shortlist for further investigation.')
st.caption('Data sources: LROC WAC TiO₂ abundance and USGS Kaguya MI OMAT only.')

# Explore loads real source data once per session, fits terrain groups,
# and stores data, silhouette, and provenance for later reruns.
if page == 'Explore':
    if st.session_state.data is None:
        try:
            with st.status('Loading approved lunar datasets…', expanded=True) as status:
                data, provenance = load_sources(st.write)
                clustered, silhouette = fit_terrain(data)
                st.session_state.update(data=clustered, silhouette=silhouette, provenance=provenance)
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
    plan=st.session_state.plan
    with st.expander('Region & ranking controls',expanded=False):
        with st.form('controls'):
            cols=st.columns(4)
            values={key:cols[i].number_input(key.title(),value=float(plan[key])) for i,key in enumerate(['west','east','south','north'])}
            cols=st.columns(3)
            values['minimum_tio2']=cols[0].number_input('Minimum TiO₂ (wt%)',0.,15.,float(plan['minimum_tio2']))
            values['top_n']=cols[1].number_input('Candidates',1,50,int(plan['top_n']))
            values['priority']=cols[2].selectbox('Rank by',['balanced','tio2','maturity'],index=['balanced','tio2','maturity'].index(plan['priority']))
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
        st.caption('Try “highest TiO2”, then “top 5”. Follow-ups retain the current region and filters.')
        with st.form('question',clear_on_submit=True):
            question=st.text_area('Prospecting question',placeholder='Find the best spots',height=105)
            run=st.form_submit_button('Find candidates',type='primary', disabled=not api_key)
        
        # On submission, parse and validate the question, rank real samples, and
        # create a grounded summary before committing the new plan and conversation.
        if run:
            try:
                with st.spinner('Plan → validate → retrieve → rank → explain'):
                    new_plan=plan_query(question,st.session_state.plan,api_key=api_key,model=model)
                    results=rank_sites(st.session_state.data,new_plan)
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
    # and the selected display field (TiO2, OMAT, or cluster ID).
    with right:
        result=rank_sites(st.session_state.data,st.session_state.plan)
        st.subheader('02 / Survey the candidates')
        a,b,c=st.columns(3)
        a.metric('Shortlisted',len(result))
        b.metric('Top TiO₂',f'{result.tio2.max():.2f} wt%' if len(result) else '—')
        c.metric('Terrain groups',result.cluster.nunique())
        layer=st.selectbox('Surface layer',['TiO₂ abundance','Optical maturity','Terrain groups'])
        
        # Simple CRS maps lunar longitude/latitude directly; Earth distance tools are disabled.
        m=leafmap.Map(center=[0,0],zoom=1,tiles=None,crs='Simple',draw_control=False,
                      measure_control=False,fullscreen_control=True,latlon_control=False,
                      search_control=False,scale_control=False)
        
        # Remove any default Earth tile layers that the map constructor may add.
        for key in list(m._children):
            if isinstance(m._children[key],folium.raster_layers.TileLayer): del m._children[key]
        data=st.session_state.data
        
        # The surface preview uses all samples inside the geographic bounds, while
        # the shortlist also applies the minimum TiO2 and candidate-count filters.
        region=data[data.longitude.between(st.session_state.plan['west'],st.session_state.plan['east']) & data.latitude.between(st.session_state.plan['south'],st.session_state.plan['north'])]
        field={'TiO₂ abundance':'tio2','Optical maturity':'omat','Terrain groups':'cluster'}[layer]
        
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
            popup=f'#{rank} · {row.site_id}<br>{row.latitude:.2f}°N, {row.longitude:.2f}°E<br>TiO₂ {row.tio2:.2f} wt%<br>OMAT {row.omat:.3f}<br>Terrain {row.cluster}'
            folium.Marker([row.latitude,row.longitude],tooltip=f'#{rank} {row.site_id}',popup=popup,
                icon=folium.DivIcon(html=f'<div style="background:#76e0c5;color:#101722;border:2px solid white;border-radius:50%;width:25px;height:25px;text-align:center;font-weight:bold">{rank}</div>')).add_to(m)
        p=st.session_state.plan
        m.fit_bounds([[p['south'],p['west']],[p['north'],p['east']]])
        m.to_streamlit(height=410)
        st.caption('Lunar longitude/latitude · sampled raster preview, not full-resolution imagery. Continuous layers: dark = low, gold = high. Terrain groups: mint 0 · gold 1 · violet 2 · pink 3.')
        if len(region) and field!='cluster':
            st.caption(f'Visible color range: {region[field].min():.3f} to {region[field].max():.3f} '+('wt%' if field=='tio2' else 'OMAT'))
        
        # Show an explicit empty-result message or offer the ranked table, CSV
        # with source links, and JSON containing the query and provenance.
        if result.empty: st.info(explain(result,p))
        else:
            st.dataframe(result[['site_id','latitude','longitude','tio2','omat','cluster','score']].round(3),hide_index=True,width='stretch')
            st.download_button('Download shortlist (CSV)',result.assign(tio2_source=SOURCE_PAGES['tio2'],omat_source=SOURCE_PAGES['omat']).to_csv(index=False),'lunar-shortlist.csv','text/csv')
            st.download_button('Download query & provenance',json.dumps({'plan':p,'provenance':st.session_state.provenance},indent=2,default=str),'provenance.json','application/json')

# The Methods page explains the pipeline, cluster diagnostics, heuristic
# ranking, source limitations, provenance, and local-model setup.
else:
    st.subheader('A prospecting aid, with evidence in view')
    st.write('Designed for exploratory analysts comparing potential lunar prospecting regions. A successful interaction produces a traceable shortlist, not a mining or landing authorization.')
    st.markdown('### How the pieces fit')
    st.code('Question → LLM JSON plan → validation → raster sample retrieval\n                                           ↓\nPublisher rasters → common lunar grid → standardization → K-means groups\n                                           ↓\n                     proxy ranking → Leafmap + table + explanation')
    st.markdown('### Traditional ML')
    st.write('K-means groups samples using standardized TiO₂ and OMAT (4 groups, 10 initializations, seed 530). Latitude and longitude are excluded so groups represent similar proxy values rather than proximity. Group labels appear on the map and shortlist; the group summary supports comparison. Labels are arbitrary and refitted when the source sample set changes.')
    if st.session_state.silhouette is not None:
        st.metric('Sampled silhouette score',f'{st.session_state.silhouette:.3f}')
    else:
        st.caption('Model results appear after automatic source loading on Explore.')
    st.caption('Cluster separation only; this is not evidence of helium-3 prediction accuracy. Spatially correlated sampling and choice of region affect the result.')
    if st.session_state.data is not None:
        st.dataframe(st.session_state.data.groupby('cluster').agg(samples=('site_id','count'),mean_tio2=('tio2','mean'),mean_omat=('omat','mean')).round(3))
    st.markdown('### Ranking and limitations')
    st.write('Balanced score = 100 × (0.65 × TiO₂ percentile + 0.35 × inverse-OMAT percentile) within the loaded source dataset. This is an explicit exploratory heuristic, not a trained helium-3 model. Lower OMAT is treated as greater optical maturity, not a direct solar-wind exposure measurement. Pure TiO₂ and maturity rankings are also available. No helium-3 ground truth, slope, landing safety, other elements, extraction economics or direct solar-wind data are included.')
    st.write('WAC abundance values below 2 wt% are below the product detection limit; values above 15 wt% are excluded. OMAT outside 0–1 is excluded as a prototype quality check. Verify product-specific calibration and masks. Grid sampling can miss small high-value regions; nearby shortlist rows are not independent deposits.')
    st.markdown('### Product decisions')
    st.write('1. Keep conversation beside the map and table, matching the scoping sketch. Explicit region controls and a visible parsed plan make constraints inspectable.\n\n2. Load only fixed publisher sources and cache successful downloads: source failures show an error instead of substitute data. The workflow stops on unsupported questions instead of silently dropping constraints. These are implementation decisions; user testing remains to be conducted.')
    with st.expander('Loaded source provenance'):
        st.json(st.session_state.provenance)
    st.caption('OMAT uses the publisher-provided 4 ppd scientific overview of the linked 512 ppd product. The map samples every 2 degrees and cannot identify local maxima at full raster resolution. Credit: JAXA/MoonScout; Lemelin et al. (2016).')
    st.markdown('### Sources & setup')
    st.markdown('- [LROC WAC TiO₂ product and calibration](https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_TIO2)\n- [USGS Kaguya OMAT product](https://astrogeology.usgs.gov/search/map/kaguya_lunar_multiband_imager_mi_derived_optical_maturity_omat_50n50s_512ppd_59mpp)\n- [Leafmap Streamlit integration](https://leafmap.org/foliumap/)\n- [OpenAI Responses API](https://developers.openai.com/api/docs/guides/responses)')
    st.info('Questions use the OpenAI Responses API; there is no offline parser. The question and current plan are sent to OpenAI. Ranking and result summaries use deterministic code and real raster samples. Live-model evaluation and real-product calibration validation remain follow-up work.')
