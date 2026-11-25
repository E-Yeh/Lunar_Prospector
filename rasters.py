# GENERATED FROM MoonScout.ipynb. Edit the notebook, not this file.
# MoonScout.ipynb cell 10
# export: rasters.py

# Import filesystem, concurrent download, hashing, HTTP, table, and raster/CRS
# tools. Rasterio reads scientific pixels; Leafmap handles display in app.py.
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

# SOURCE_PAGES records the three publisher catalog pages used in provenance.
SOURCE_PAGES = {
 'smfe':'https://astrogeology.usgs.gov/search/map/moon_selene_kaguya_mi_derived_submicroscopic_metallic_iron_mosaic_59m',
 'tio2':'https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_TIO2',
 'omat':'https://astrogeology.usgs.gov/search/map/kaguya_lunar_multiband_imager_mi_derived_optical_maturity_omat_50n50s_512ppd_59mpp',
}

# BASE is the publisher archive directory for the scientific WAC TiO2 tiles.
BASE='https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/DATA/SDP/WAC_TIO2/'

# OMAT_URL selects the publisher-provided 4-pixels-per-degree overview of
# the approved OMAT product, rather than downloading its full 512-ppd raster.
OMAT_URL='https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Lunar_MI_mineral_maps/4ppd/Lunar_Kaguya_MIMap_MineralDeconv_OpticalMaturityIndex_50N50S.tif'

# Use the scientific abundance overview, not the grayscale/color browse image.
# Retain publisher values without guessing a percent conversion: the linked
# raster label specifies base=0 and multiplier=1 but does not declare units.
SMFE_URL='https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Lunar_MI_mineral_maps/4ppd/Lunar_Kaguya_MIMap_MineralDeconv_AbundanceSMFe_50N50S.tif'

# TILES enumerates eight scientific IMG products: four longitude sectors
# for each lunar hemisphere; these are not the browse-image products.
TILES=[f'WAC_TIO2_E350{hem}{lon}.IMG' for hem in ['N','S'] for lon in ['0450','1350','2250','3150']]

# CACHE uses the launcher-provided data directory, or a .data folder next
# to the generated rasters.py file when no environment override is set.
CACHE=Path(os.environ.get('MoonScout_DATA_DIR', str(Path(__file__).parent/'.data')))

# LOCK serializes source loading within this Python process; it is not
# a filesystem lock shared by multiple running app processes.
LOCK=threading.Lock()

# VERSION identifies the sampled-table cache format; change it when cached
# samples must be rebuilt after changes to sampling or filtering.
VERSION=2

# MoonScout.ipynb cell 11
# export: rasters.py

# download(url, name) returns a cached raster path and provenance receipt,
# or downloads and validates the file before replacing the cached copy.
# The caller supplies the fixed publisher URLs and creates CACHE first.
def download(url,name):
    path=CACHE/name
    receipt=path.with_suffix(path.suffix+'.json')
    
    # Reuse a file only when its receipt URL and recorded byte count match.
    # This fast cache check does not recompute the saved SHA-256 digest.
    if path.exists() and receipt.exists():
        meta=json.loads(receipt.read_text())
        if meta.get('source_url')==url and meta.get('bytes')==path.stat().st_size:
            return path,meta
    
    # Stream to a .part file while computing byte count and a local SHA-256
    # fingerprint; this digest is not an independently verified publisher checksum.
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
    
    # Check that the downloaded product has one band and a coordinate system
    # before atomically replacing the final raster path and writing its receipt.
    with rasterio.open(temporary) as ds:
        if ds.count!=1 or not ds.crs: raise ValueError(f'Invalid scientific raster: {name}')
    os.replace(temporary,path)
    receipt.write_text(json.dumps(meta,indent=2))
    return path,meta

# MoonScout.ipynb cell 12
# export: rasters.py

# sample(ds, lon, lat) returns scaled nearest-pixel values for matching lunar
# longitude/latitude arrays; uncovered or masked locations remain NaN.
def sample(ds,lon,lat):
    
    # Check for a Moon-sized ellipsoid, then transform from this raster
    # CRS's own geographic coordinates instead of assuming an Earth datum.
    crs=CRS.from_user_input(ds.crs)
    if not 1700000<crs.ellipsoid.semi_major_metre<1800000:
        raise ValueError('Publisher raster does not have a lunar CRS.')
    transformer=Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True,force_over=True)
    values=np.full(len(lon),np.nan)
    
    # Try equivalent longitude ranges to accommodate publisher tiles using
    # different wrapping conventions, filling only locations still missing.
    for shift in [0,360,-360]:
        x,y=transformer.transform(lon+shift,lat); x=np.asarray(x); y=np.asarray(y)
        inside=(x>=ds.bounds.left)&(x<ds.bounds.right)&(y>ds.bounds.bottom)&(y<=ds.bounds.top)&np.isnan(values)
        ids=np.flatnonzero(inside)
        if len(ids):
            a=np.ma.vstack(list(ds.sample(zip(x[ids],y[ids]),indexes=1,masked=True))).astype(float)
            
            # Convert masked pixels to NaN and apply the band's scale and offset.
            values[ids]=a.filled(np.nan).ravel()*ds.scales[0]+ds.offsets[0]
    return values

# MoonScout.ipynb cell 13
# export: rasters.py

# load_sources(progress) returns a real sample DataFrame and provenance list.
# The optional progress callback receives status strings; its default lambda
# does nothing. Loading and cache writes are serialized within this process.
def load_sources(progress=lambda message: None):
    with LOCK:
        CACHE.mkdir(exist_ok=True)
        saved=CACHE/'samples.json'
        
        # A matching sample-cache version bypasses downloads and sampling, restoring
        # the table attributes used to reconstruct the display grid.
        legacy=None
        if saved.exists():
            payload=json.loads(saved.read_text())
            if payload.get('version')==VERSION:
                df=pd.DataFrame(payload['rows']); df.attrs=payload['attrs']
                return df,payload['provenance']
            # Version 1 already contains real TiO2/OMAT samples on this exact
            # grid. Reuse them only if all expected source URLs are present;
            # adding SMFe does not require downloading those large rasters again.
            # Source provenance is retained, and SMFe is still sampled directly.
            expected_urls={BASE+name for name in TILES}|{OMAT_URL}
            cached_urls={item.get('source_url') for item in payload.get('provenance',[]) if 'source_url' in item}
            if payload.get('version')==1 and cached_urls==expected_urls:
                legacy=payload

        if legacy is None:
            progress('Downloading scientific LROC tiles and USGS OMAT/SMFe. First load may take several minutes (about 1.2 GB); later visits use the local cache.')
        
        # Download the eight fixed TiO2 tiles and two Kaguya scientific overviews with four workers.
        # The lambda unpacks each (URL, filename) job into download; map preserves order.
        jobs=([(BASE+n,n) for n in TILES]+[(OMAT_URL,'omat-4ppd.tif')] if legacy is None else [])
        jobs.append((SMFE_URL,'smfe-4ppd.tif'))
        if legacy is not None:
            progress('Reusing TiO2/OMAT sample cache with matching source URLs; adding SMFe on the same grid.')
        with ThreadPoolExecutor(max_workers=4) as pool:
            files=list(pool.map(lambda job:download(*job),jobs))
        
        # Define sampling coordinates every two degrees within shared coverage.
        # This creates locations only: all measurement values come from the rasters.
        lon,lat=np.meshgrid(np.arange(-179.,180.,2.),np.arange(49.,-50.,-2.))
        if legacy is None:
            df=pd.DataFrame({'longitude':lon.ravel(),'latitude':lat.ravel()})
            tio=np.full(len(df),np.nan); provenance=[]
        
            # Read each scientific TiO2 tile, retain finite values from 0 to 15 wt%,
            # and record the source receipt, units, resolution, and band calibration.
            for (path,meta),name in zip(files[:len(TILES)],TILES):
                progress(f'Sampling {name}')
                with rasterio.open(path) as ds:
                    if ds.dtypes[0]!='float32': raise ValueError('Expected scientific float32 WAC product, not browse imagery.')
                    a=sample(ds,df.longitude.to_numpy(),df.latitude.to_numpy())
                    good=np.isfinite(a)&(a>=0)&(a<=15)
                    tio[good]=a[good]
                    provenance.append({**meta,'source_page':SOURCE_PAGES['tio2'],'product':name,'units':'wt%','native_resolution':'about 400 m/pixel','scale':ds.scales[0],'offset':ds.offsets[0]})
        
            # Sample OMAT at the same lunar coordinates so each row pairs the two proxies.
            path,meta=files[len(TILES)]
            with rasterio.open(path) as ds:
                df['omat']=sample(ds,df.longitude.to_numpy(),df.latitude.to_numpy())
            provenance.append({**meta,'source_page':SOURCE_PAGES['omat'],'product':'Kaguya MI Optical Maturity Index 50N50S','resolution':'Publisher-provided 4 ppd overview','credit':'JAXA/SELENE; Lemelin et al. (2016)'})
            df['tio2']=tio
        else:
            df=pd.DataFrame(legacy['rows'])
            # Keep the nine original receipts, replacing the old sampling summary
            # below with a summary of the new shared three-raster validity mask.
            provenance=[item for item in legacy['provenance'] if 'source_url' in item]
        # Sample SMFe at exactly the same coordinates; never infer it from OMAT.
        # All feature experiments use the intersection of valid raster rows,
        # including the baseline, so missing-data differences cannot mimic a
        # clustering effect. This common mask can change the previous shortlist.
        path,meta=files[-1]
        with rasterio.open(path) as ds:
            if ds.dtypes[0]!='float32':
                raise ValueError('Expected scientific float32 SMFe abundance raster.')
            df['smfe']=sample(ds,df.longitude.to_numpy(),df.latitude.to_numpy())
            provenance.append({**meta,'source_page':SOURCE_PAGES['smfe'],
                'product':'Kaguya MI derived SMFe abundance 50N50S',
                'units':'publisher abundance units (no percent conversion)',
                'resolution':'Publisher-provided 4 ppd scientific overview',
                'scale':ds.scales[0],'offset':ds.offsets[0],
                'credit':'JAXA/SELENE; Lemelin et al. (2016)'})
        
        # Keep overlapping finite measurements, OMAT in [0, 1], and SMFe >= 0. Missing
        # measurements are excluded, never interpolated or filled with substitute data.
        valid=np.isfinite(df[['tio2','omat','smfe']]).all(axis=1)&df.tio2.between(0,15)&df.omat.between(0,1)&df.smfe.ge(0)
        df=df[valid].reset_index(drop=True)
        if len(df)<7: raise ValueError('Source products yielded too few valid overlapping samples.')
        
        # Preserve the full coordinate axes for map reconstruction, including holes
        # left by invalid samples, and describe the sampling choices in provenance.
        df.attrs={'grid_longitudes':lon[0].tolist(),'grid_latitudes':lat[:,0].tolist()}
        provenance.append({'sampling':'Nearest pixel at 2-degree grid centers; no missing values filled','valid_samples':len(df),'excluded_samples':int(lon.size-len(df)),'reused_v1_samples':legacy is not None,'coverage':'180W–180E, 50S–50N','quality_filter':'TiO2 0–15 wt%; OMAT 0–1; SMFe finite and nonnegative; common mask for all experiments'})
        
        # Serialize rows, grid attributes, and provenance together; reject NaN in
        # JSON and replace the sample-cache file only after writing completes.
        payload={'version':VERSION,'rows':df.to_dict('records'),'attrs':df.attrs,'provenance':provenance}
        tmp=saved.with_suffix('.tmp'); tmp.write_text(json.dumps(payload,allow_nan=False)); os.replace(tmp,saved)
        return df,provenance
