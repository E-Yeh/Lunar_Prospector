# GENERATED FROM MoonScout.ipynb. Edit the notebook, not this file.
# MoonScout.ipynb cell 10
# export: rasters.py
"""Fixed publisher sources. No user-supplied files, URLs, or generated measurements."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import threading
import requests
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer

SOURCE_PAGES = {
 'tio2':'https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_TIO2',
 'omat':'https://astrogeology.usgs.gov/search/map/kaguya_lunar_multiband_imager_mi_derived_optical_maturity_omat_50n50s_512ppd_59mpp',
}
BASE='https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/DATA/SDP/WAC_TIO2/'
OMAT_URL='https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Lunar_MI_mineral_maps/4ppd/Lunar_Kaguya_MIMap_MineralDeconv_OpticalMaturityIndex_50N50S.tif'
TILES=[f'WAC_TIO2_E350{hem}{lon}.IMG' for hem in ['N','S'] for lon in ['0450','1350','2250','3150']]
CACHE=Path(os.environ.get('MoonScout_DATA_DIR', str(Path(__file__).parent/'.data')))
LOCK=threading.Lock()
VERSION=1



# MoonScout.ipynb cell 11
# export: rasters.py
def download(url,name):
    path=CACHE/name
    receipt=path.with_suffix(path.suffix+'.json')
    if path.exists() and receipt.exists():
        meta=json.loads(receipt.read_text())
        if meta.get('source_url')==url and meta.get('bytes')==path.stat().st_size:
            return path,meta
    temporary=path.with_suffix(path.suffix+'.part')
    digest=hashlib.sha256(); count=0
    with requests.get(url,stream=True,timeout=(15,90)) as response:
        response.raise_for_status()
        with temporary.open('wb') as out:
            for chunk in response.iter_content(1024*1024):
                out.write(chunk); digest.update(chunk); count+=len(chunk)
        expected=response.headers.get('Content-Length')
        if expected and int(expected)!=count: raise ValueError(f'Incomplete source download: {name}')
        meta={'source_url':url,'resolved_url':response.url,'bytes':count,'sha256':digest.hexdigest()}
    with rasterio.open(temporary) as ds:
        if ds.count!=1 or not ds.crs: raise ValueError(f'Invalid scientific raster: {name}')
    os.replace(temporary,path)
    receipt.write_text(json.dumps(meta,indent=2))
    return path,meta



# MoonScout.ipynb cell 12
# export: rasters.py
def sample(ds,lon,lat):
    crs=CRS.from_user_input(ds.crs)
    if not 1700000<crs.ellipsoid.semi_major_metre<1800000:
        raise ValueError('Publisher raster does not have a lunar CRS.')
    transformer=Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True,force_over=True)
    values=np.full(len(lon),np.nan)
    for shift in [0,360,-360]:
        x,y=transformer.transform(lon+shift,lat); x=np.asarray(x); y=np.asarray(y)
        inside=(x>=ds.bounds.left)&(x<ds.bounds.right)&(y>ds.bounds.bottom)&(y<=ds.bounds.top)&np.isnan(values)
        ids=np.flatnonzero(inside)
        if len(ids):
            a=np.ma.vstack(list(ds.sample(zip(x[ids],y[ids]),indexes=1,masked=True))).astype(float)
            values[ids]=a.filled(np.nan).ravel()*ds.scales[0]+ds.offsets[0]
    return values



# MoonScout.ipynb cell 13
# export: rasters.py
def load_sources(progress=lambda message: None):
    with LOCK:
        CACHE.mkdir(exist_ok=True)
        saved=CACHE/'samples.json'
        if saved.exists():
            payload=json.loads(saved.read_text())
            if payload.get('version')==VERSION:
                df=pd.DataFrame(payload['rows']); df.attrs=payload['attrs']
                return df,payload['provenance']
        progress('Downloading scientific LROC tiles and USGS OMAT. First load may take several minutes (about 1.2 GB); later visits use the local cache.')
        jobs=[(BASE+n,n) for n in TILES]+[(OMAT_URL,'omat-4ppd.tif')]
        with ThreadPoolExecutor(max_workers=4) as pool:
            files=list(pool.map(lambda job:download(*job),jobs))
        lon,lat=np.meshgrid(np.arange(-179.,180.,2.),np.arange(49.,-50.,-2.))
        df=pd.DataFrame({'longitude':lon.ravel(),'latitude':lat.ravel()})
        tio=np.full(len(df),np.nan); provenance=[]
        for (path,meta),name in zip(files[:-1],TILES):
            progress(f'Sampling {name}')
            with rasterio.open(path) as ds:
                if ds.dtypes[0]!='float32': raise ValueError('Expected scientific float32 WAC product, not browse imagery.')
                a=sample(ds,df.longitude.to_numpy(),df.latitude.to_numpy())
                good=np.isfinite(a)&(a>=0)&(a<=15)
                tio[good]=a[good]
                provenance.append({**meta,'source_page':SOURCE_PAGES['tio2'],'product':name,'units':'wt%','native_resolution':'about 400 m/pixel','scale':ds.scales[0],'offset':ds.offsets[0]})
        path,meta=files[-1]
        with rasterio.open(path) as ds:
            df['omat']=sample(ds,df.longitude.to_numpy(),df.latitude.to_numpy())
        df['tio2']=tio
        valid=np.isfinite(df[['tio2','omat']]).all(axis=1)&df.omat.between(0,1)
        df=df[valid].reset_index(drop=True)
        if len(df)<5: raise ValueError('Source products yielded too few valid overlapping samples.')
        df.attrs={'grid_longitudes':lon[0].tolist(),'grid_latitudes':lat[:,0].tolist()}
        provenance.append({**meta,'source_page':SOURCE_PAGES['omat'],'product':'Kaguya MI Optical Maturity Index 50N50S','resolution':'Publisher-provided 4 ppd overview of the 512 ppd dataset','credit':'JAXA/SELENE; Lemelin et al. (2016)'})
        provenance.append({'sampling':'Nearest pixel at 2-degree grid centers; no missing values filled','valid_samples':len(df),'excluded_samples':int((~valid).sum()),'coverage':'180W–180E, 50S–50N','quality_filter':'TiO2 0–15 wt%; OMAT 0–1'})
        payload={'version':VERSION,'rows':df.to_dict('records'),'attrs':df.attrs,'provenance':provenance}
        tmp=saved.with_suffix('.tmp'); tmp.write_text(json.dumps(payload,allow_nan=False)); os.replace(tmp,saved)
        return df,provenance

