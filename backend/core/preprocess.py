"""Spatial preprocessing module for SIPEKA-Banjir 3D.

Handles:
1. Reading SHP (ZIP) / GPKG vector layers and GeoTIFF DEM(s) (with automatic mosaicking).
2. Validating CRS, fixing invalid geometries with `make_valid`, and checking overlap.
3. Reprojecting all spatial data to WGS 84 / UTM Zone 47N (EPSG:32647).
4. Constructing the 30 m x 30 m reference raster grid aligned to the city boundary.
5. Resampling DEM via bilinear interpolation and masking pixels outside the city boundary.
6. Parsing and validating rainfall station data (annual or daily/monthly aggregated).
"""

from __future__ import annotations

import math
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.merge import merge as rio_merge
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject
from shapely import make_valid
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import unary_union

from backend.core.config import (
    NODATA_FLOAT,
    PIXEL_SIZE,
    TARGET_CRS_STR,
    TARGET_EPSG,
)


@dataclass
class ReferenceGrid:
    """Represents the standardized 30 m x 30 m reference grid for Kota Pekanbaru."""

    crs: CRS
    transform: Affine
    width: int
    height: int
    bounds: Tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax)
    pixel_size: float
    city_mask: np.ndarray  # bool array (height, width): True inside city boundary
    city_polygon: Any
    kecamatan_gdf: gpd.GeoDataFrame
    kecamatan_column: str
    warnings: List[str] = field(default_factory=list)

    @property
    def shape(self) -> Tuple[int, int]:
        """Return (rows, cols) i.e. (height, width)."""
        return (self.height, self.width)

    @property
    def valid_pixel_count(self) -> int:
        """Return total number of valid pixels inside the city boundary."""
        return int(np.count_nonzero(self.city_mask))


def read_vector_file(file_path: Union[str, Path]) -> Tuple[gpd.GeoDataFrame, List[str]]:
    """Read a vector dataset (.gpkg, .shp, .geojson, or .zip containing a shapefile).

    Validates that a CRS is present and repairs any invalid geometries using `make_valid`.

    Args:
        file_path: Path to the vector file.

    Returns:
        Tuple of (GeoDataFrame, list of warning messages).

    Raises:
        ValueError: If file cannot be read, is empty, or has no CRS defined.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File vektor tidak ditemukan: {path.name}")

    warnings_list: List[str] = []

    try:
        if path.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(path, "r") as zf:
                    zf.extractall(tmpdir)
                shp_files = list(Path(tmpdir).rglob("*.shp"))
                gpkg_files = list(Path(tmpdir).rglob("*.gpkg"))
                if shp_files:
                    gdf = gpd.read_file(shp_files[0])
                elif gpkg_files:
                    gdf = gpd.read_file(gpkg_files[0])
                else:
                    raise ValueError(
                        f"Arsip ZIP '{path.name}' tidak berisi file .shp atau .gpkg."
                    )
        else:
            gdf = gpd.read_file(path)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Gagal membaca file vektor '{path.name}': {exc}") from exc

    if gdf.empty:
        raise ValueError(f"Layer vektor '{path.name}' kosong (tidak memiliki fitur).")

    if gdf.crs is None:
        raise ValueError(
            f"Layer '{path.name}' tidak memiliki sistem koordinat (CRS hilang). "
            "Pastikan file .prj (untuk Shapefile) atau definisi CRS tersedia."
        )

    # Remove null/empty geometries
    null_cnt = int(gdf.geometry.isna().sum() + gdf.geometry.is_empty.sum())
    if null_cnt > 0:
        gdf = gdf[~(gdf.geometry.isna() | gdf.geometry.is_empty)].copy()
        warnings_list.append(
            f"Layer '{path.name}': {null_cnt} geometri kosong/null telah diabaikan."
        )

    if gdf.empty:
        raise ValueError(f"Seluruh geometri pada '{path.name}' kosong atau tidak valid.")

    # Repair invalid geometries using shapely.make_valid
    invalid_mask = ~gdf.geometry.is_valid
    invalid_cnt = int(invalid_mask.sum())
    if invalid_cnt > 0:
        gdf.loc[invalid_mask, "geometry"] = gdf.loc[invalid_mask, "geometry"].apply(
            make_valid
        )
        warnings_list.append(
            f"Layer '{path.name}': {invalid_cnt} geometri tidak valid berhasil diperbaiki otomatis dengan make_valid."
        )

    return gdf, warnings_list


def build_reference_grid(
    kecamatan_path: Union[str, Path],
    kecamatan_col: Optional[str] = None,
    pixel_size: float = PIXEL_SIZE,
    target_epsg: int = TARGET_EPSG,
) -> ReferenceGrid:
    """Create the 30 m x 30 m reference grid in EPSG:32647 from the administrative boundary.

    Args:
        kecamatan_path: Path to the kecamatan boundary vector file.
        kecamatan_col: Name of the attribute column holding the kecamatan name.
        pixel_size: Grid cell resolution in meters (default 30.0).
        target_epsg: Target EPSG code (default 32647 - WGS 84 / UTM Zone 47N).

    Returns:
        Configured `ReferenceGrid` instance.
    """
    gdf, warnings_list = read_vector_file(kecamatan_path)
    target_crs = CRS.from_epsg(target_epsg)

    if gdf.crs != target_crs:
        gdf = gdf.to_crs(target_crs)

    # Detect kecamatan name column if not explicitly specified
    non_geom_cols = [c for c in gdf.columns if c != gdf.geometry.name]
    if not non_geom_cols:
        gdf["nama_kecamatan"] = [f"Kecamatan {i+1}" for i in range(len(gdf))]
        kecamatan_col = "nama_kecamatan"
    elif kecamatan_col is None or kecamatan_col not in gdf.columns:
        preferred = [
            "nama_kecamatan",
            "NAMOBJ",
            "WADMKC",
            "KECAMATAN",
            "kecamatan",
            "NAMA_KEC",
            "nama",
            "NAME",
        ]
        selected = next((c for c in preferred if c in gdf.columns), non_geom_cols[0])
        kecamatan_col = selected

    # Dissolve by kecamatan name in case a district is split into multiple rows
    gdf[kecamatan_col] = gdf[kecamatan_col].astype(str).str.strip()
    gdf = gdf.dissolve(by=kecamatan_col, as_index=False)

    if len(gdf) != 15:
        warnings_list.append(
            f"Jumlah kecamatan terdeteksi: {len(gdf)} (standar Kota Pekanbaru adalah 15 kecamatan)."
        )

    city_polygon = unary_union(gdf.geometry).buffer(0)
    if city_polygon.is_empty:
        raise ValueError("Poligon batas administrasi kota kosong setelah penggabungan.")

    minx, miny, maxx, maxy = city_polygon.bounds
    # Snap grid origin cleanly to multiples of pixel_size
    xmin_aligned = math.floor(minx / pixel_size) * pixel_size
    ymin_aligned = math.floor(miny / pixel_size) * pixel_size
    xmax_aligned = math.ceil(maxx / pixel_size) * pixel_size
    ymax_aligned = math.ceil(maxy / pixel_size) * pixel_size

    width = max(1, int(round((xmax_aligned - xmin_aligned) / pixel_size)))
    height = max(1, int(round((ymax_aligned - ymin_aligned) / pixel_size)))

    transform = from_origin(xmin_aligned, ymax_aligned, pixel_size, pixel_size)

    city_mask_uint8 = rasterize(
        [(city_polygon, 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )
    city_mask = city_mask_uint8.astype(bool)
    if not np.any(city_mask):
        # Fallback to all_touched=True for tiny test polygons
        city_mask = rasterize(
            [(city_polygon, 1)],
            out_shape=(height, width),
            transform=transform,
            fill=0,
            all_touched=True,
            dtype=np.uint8,
        ).astype(bool)

    return ReferenceGrid(
        crs=target_crs,
        transform=transform,
        width=width,
        height=height,
        bounds=(xmin_aligned, ymin_aligned, xmax_aligned, ymax_aligned),
        pixel_size=pixel_size,
        city_mask=city_mask,
        city_polygon=city_polygon,
        kecamatan_gdf=gdf,
        kecamatan_column=kecamatan_col,
        warnings=warnings_list,
    )


def preprocess_dem(
    dem_paths: Union[str, Path, Sequence[Union[str, Path]]],
    grid: ReferenceGrid,
) -> Tuple[np.ndarray, List[str]]:
    """Mosaic (if multiple tiles), reproject, bilinear-resample, and clip DEM to `grid`.

    Args:
        dem_paths: Single GeoTIFF path or sequence of GeoTIFF paths.
        grid: ReferenceGrid defining the target CRS, transform, shape, and city mask.

    Returns:
        Tuple of (2D float32 DEM array with `NODATA_FLOAT` outside city, warnings list).

    Raises:
        ValueError: If DEM has no CRS, does not overlap city, or is completely nodata.
    """
    if isinstance(dem_paths, (str, Path)):
        paths = [Path(dem_paths)]
    else:
        paths = [Path(p) for p in dem_paths]

    if not paths:
        raise ValueError("Tidak ada file DEMNAS yang diberikan.")

    warnings_list: List[str] = []
    datasets = []
    try:
        for p in paths:
            if not p.exists():
                raise ValueError(f"File DEM tidak ditemukan: {p.name}")
            ds = rasterio.open(p)
            if ds.crs is None:
                ds.close()
                raise ValueError(
                    f"File DEM '{p.name}' tidak memiliki informasi CRS/proyeksi."
                )
            datasets.append(ds)

        if len(datasets) == 1:
            src_ds = datasets[0]
            src_arr = src_ds.read(1).astype(np.float32)
            src_transform = src_ds.transform
            src_crs = src_ds.crs
            src_nodata = src_ds.nodata
        else:
            warnings_list.append(
                f"Melakukan mosaic otomatis pada {len(datasets)} lembar DEMNAS."
            )
            merged_arr, merged_transform = rio_merge(datasets)
            src_arr = merged_arr[0].astype(np.float32)
            src_transform = merged_transform
            src_crs = datasets[0].crs
            src_nodata = datasets[0].nodata

        # Standardize source nodata values to NODATA_FLOAT
        if src_nodata is not None and not np.isnan(src_nodata):
            src_arr = np.where(
                np.isclose(src_arr, float(src_nodata)) | ~np.isfinite(src_arr),
                NODATA_FLOAT,
                src_arr,
            )
        else:
            src_arr = np.where(~np.isfinite(src_arr) | (src_arr < -1000.0), NODATA_FLOAT, src_arr)

        dst_arr = np.full(grid.shape, NODATA_FLOAT, dtype=np.float32)

        reproject(
            source=src_arr,
            destination=dst_arr,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=NODATA_FLOAT,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            dst_nodata=NODATA_FLOAT,
            resampling=Resampling.bilinear,
        )
    finally:
        for ds in datasets:
            ds.close()

    # Check overlap and nodata within city boundary
    valid_in_city = grid.city_mask & (dst_arr != NODATA_FLOAT) & np.isfinite(dst_arr)
    if not np.any(valid_in_city):
        raise ValueError(
            "DEM tidak memiliki data valid di dalam batas Kota Pekanbaru "
            "(layer tidak overlap dengan batas kota atau DEM penuh nodata)."
        )

    # If small holes exist inside city mask, fill them with nearest neighbor so overlay has full coverage
    missing_in_city = grid.city_mask & ~valid_in_city
    missing_count = int(np.count_nonzero(missing_in_city))
    if missing_count > 0:
        from scipy.ndimage import distance_transform_edt

        pct_missing = 100.0 * missing_count / max(1, grid.valid_pixel_count)
        warnings_list.append(
            f"Terdapat {missing_count} piksel nodata ({pct_missing:.2f}%) di dalam batas kota pada DEM; "
            "diinterpolasi dengan piksel terdekat."
        )
        indices = distance_transform_edt(
            ~valid_in_city, return_distances=False, return_indices=True
        )
        dst_arr[missing_in_city] = dst_arr[tuple(indices[:, missing_in_city])]

    # Enforce nodata outside city boundary
    dst_arr = np.where(grid.city_mask, dst_arr, NODATA_FLOAT).astype(np.float32)
    return dst_arr, warnings_list


def preprocess_rivers(
    river_path: Union[str, Path],
    grid: ReferenceGrid,
    river_col: Optional[str] = None,
    selected_rivers: Optional[Sequence[str]] = None,
) -> Tuple[gpd.GeoDataFrame, List[str]]:
    """Read, reproject, clip river network to city buffer, and convert polygons to boundaries.

    Args:
        river_path: Path to the river SHP (ZIP) or GPKG file.
        grid: ReferenceGrid of the city.
        river_col: Optional column name for river names.
        selected_rivers: Optional list of river names to include.

    Returns:
        Tuple of (reprojected & clipped river GeoDataFrame, warnings list).
    """
    gdf, warnings_list = read_vector_file(river_path)
    if gdf.crs != grid.crs:
        gdf = gdf.to_crs(grid.crs)

    # Filter by selected river names if requested and column exists
    if river_col and river_col in gdf.columns and selected_rivers:
        selected_set = {str(s).strip().lower() for s in selected_rivers}
        filtered = gdf[
            gdf[river_col].astype(str).str.strip().str.lower().isin(selected_set)
        ].copy()
        if not filtered.empty:
            gdf = filtered
        else:
            warnings_list.append(
                "Filter nama sungai tidak menghasilkan fitur; seluruh jaringan sungai digunakan."
            )

    # Convert any Polygon/MultiPolygon geometries to their boundary lines as required
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if bool(poly_mask.any()):
        gdf.loc[poly_mask, "geometry"] = gdf.loc[poly_mask, "geometry"].boundary
        warnings_list.append(
            f"{int(poly_mask.sum())} fitur poligon sungai dikonversi otomatis menjadi garis tepi (boundary)."
        )

    # Clip to city boundary (+1500m buffer so rivers just outside city border still influence edge distance)
    clip_poly = grid.city_polygon.buffer(1500.0)
    gdf["geometry"] = gdf.geometry.intersection(clip_poly)
    gdf = gdf[~(gdf.geometry.isna() | gdf.geometry.is_empty)].copy()

    if gdf.empty or not gdf.geometry.intersects(grid.city_polygon.buffer(1500.0)).any():
        raise ValueError(
            "Layer jaringan sungai tidak berpotongan (overlap) dengan wilayah Kota Pekanbaru."
        )

    return gdf, warnings_list


def preprocess_landuse(
    landuse_path: Union[str, Path],
    grid: ReferenceGrid,
    landuse_col: Optional[str] = None,
) -> Tuple[gpd.GeoDataFrame, str, List[str]]:
    """Read, reproject, and clip land-use polygons to the city boundary.

    Args:
        landuse_path: Path to the land-use SHP (ZIP) or GPKG file.
        grid: ReferenceGrid of the city.
        landuse_col: Column name containing the land-use class names.

    Returns:
        Tuple of (clipped GeoDataFrame, resolved landuse column name, warnings list).
    """
    gdf, warnings_list = read_vector_file(landuse_path)
    if gdf.crs != grid.crs:
        gdf = gdf.to_crs(grid.crs)

    non_geom_cols = [c for c in gdf.columns if c != gdf.geometry.name]
    if not non_geom_cols:
        raise ValueError(
            "Layer penggunaan lahan tidak memiliki kolom atribut kelas lahan."
        )

    if landuse_col is None or landuse_col not in gdf.columns:
        preferred = [
            "kelas_lahan",
            "REMARK",
            "PENUTUP_LA",
            "PL_2022",
            "TUTUPAN",
            "KELAS",
            "landuse",
            "kelas",
        ]
        landuse_col = next((c for c in preferred if c in gdf.columns), non_geom_cols[0])

    gdf[landuse_col] = gdf[landuse_col].astype(str).str.strip()
    gdf["geometry"] = gdf.geometry.intersection(grid.city_polygon)
    gdf = gdf[~(gdf.geometry.isna() | gdf.geometry.is_empty)].copy()

    if gdf.empty:
        raise ValueError(
            "Layer penggunaan lahan tidak overlap dengan batas administrasi Kota Pekanbaru."
        )

    return gdf, landuse_col, warnings_list


def preprocess_rainfall_table(
    rainfall_path: Union[str, Path],
    grid: ReferenceGrid,
) -> Tuple[pd.DataFrame, List[str]]:
    """Read and aggregate rainfall CSV/XLSX into mean annual rainfall (mm/year) per station.

    Supports:
    - Annual format: `stasiun, lat, lon, tahun, hujan_mm`
    - Daily/Monthly format: `stasiun, lat, lon, tanggal, hujan_mm` (summed per year, then averaged)
    - Already-averaged format: `stasiun, lat, lon, hujan_mm`

    Also projects station coordinates (`lon, lat` in WGS84 or UTM) to `grid.crs` (EPSG:32647).

    Args:
        rainfall_path: Path to CSV or XLSX file.
        grid: ReferenceGrid of the city.

    Returns:
        Tuple of (DataFrame with columns `['stasiun', 'lat', 'lon', 'x', 'y', 'hujan_mm', 'n_tahun']`, warnings list).
    """
    path = Path(rainfall_path)
    if not path.exists():
        raise ValueError(f"File curah hujan tidak ditemukan: {path.name}")

    try:
        if path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
    except Exception as exc:
        raise ValueError(f"Gagal membaca tabel curah hujan '{path.name}': {exc}") from exc

    if df.empty:
        raise ValueError("Tabel curah hujan kosong.")

    # Normalize column names to lowercase
    col_map = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=col_map)

    required_base = {"stasiun", "lat", "lon", "hujan_mm"}
    if not required_base.issubset(set(df.columns)):
        missing = required_base - set(df.columns)
        raise ValueError(
            f"Format kolom curah hujan tidak sesuai. Kolom wajib yang belum ada: {sorted(missing)}. "
            "Gunakan kolom: stasiun, lat, lon, tahun (atau tanggal), hujan_mm."
        )

    warnings_list: List[str] = []
    df["stasiun"] = df["stasiun"].astype(str).str.strip()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["hujan_mm"] = pd.to_numeric(df["hujan_mm"], errors="coerce")
    df = df.dropna(subset=["stasiun", "lat", "lon", "hujan_mm"]).copy()

    if df.empty:
        raise ValueError("Tidak ada baris data curah hujan yang valid.")

    # Aggregate daily/monthly -> annual -> multi-year mean per station
    if "tanggal" in df.columns and "tahun" not in df.columns:
        parsed_dates = pd.to_datetime(df["tanggal"], errors="coerce")
        if parsed_dates.isna().all():
            raise ValueError("Kolom 'tanggal' pada data curah hujan tidak dapat dikenali sebagai tanggal.")
        df["tahun"] = parsed_dates.dt.year
        annual_df = (
            df.groupby(["stasiun", "tahun"], as_index=False)
            .agg(
                lat=("lat", "first"),
                lon=("lon", "first"),
                hujan_mm=("hujan_mm", "sum"),
            )
        )
    elif "tahun" in df.columns:
        df["tahun"] = pd.to_numeric(df["tahun"], errors="coerce")
        annual_df = (
            df.groupby(["stasiun", "tahun"], as_index=False)
            .agg(
                lat=("lat", "first"),
                lon=("lon", "first"),
                hujan_mm=("hujan_mm", "sum"),
            )
        )
    else:
        df["tahun"] = 2025
        annual_df = df.copy()

    station_df = (
        annual_df.groupby("stasiun", as_index=False)
        .agg(
            lat=("lat", "mean"),
            lon=("lon", "mean"),
            hujan_mm=("hujan_mm", "mean"),
            n_tahun=("tahun", "nunique"),
        )
    )

    n_stations = len(station_df)
    max_years = int(station_df["n_tahun"].max()) if not station_df.empty else 0

    if n_stations < 3:
        warnings_list.append(
            f"Peringatan: Jumlah stasiun hujan hanya {n_stations} (< 3 stasiun). "
            "Interpolasi spasial IDW kurang representatif."
        )
    if max_years < 10:
        warnings_list.append(
            f"Peringatan: Panjang seri data curah hujan maksimum {max_years} tahun (< 10 tahun standar klimatologi)."
        )

    # Transform geographic coordinates (lon, lat) to target UTM (x, y)
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    xs: List[float] = []
    ys: List[float] = []
    for _, row in station_df.iterrows():
        lat_val = float(row["lat"])
        lon_val = float(row["lon"])
        # If user already supplied UTM coordinates in lon/lat columns, detect automatically
        if abs(lon_val) <= 180.0 and abs(lat_val) <= 90.0:
            x_utm, y_utm = transformer.transform(lon_val, lat_val)
        else:
            x_utm, y_utm = lon_val, lat_val
        xs.append(float(x_utm))
        ys.append(float(y_utm))

    station_df["x"] = xs
    station_df["y"] = ys

    return station_df, warnings_list

