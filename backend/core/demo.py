"""Synthetic demo dataset generator for SIPEKA-Banjir 3D.

Generates realistic synthetic GIS datasets representing the 15 districts (kecamatan)
of Kota Pekanbaru so the entire workflow can be tested end-to-end without external files.
Clearly labeled as "DATA DEMO, bukan hasil sungguhan".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.spatial import Voronoi
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union

from backend.core.config import (
    DEFAULT_RIVERS,
    KECAMATAN_LIST,
    NODATA_FLOAT,
    PIXEL_SIZE,
    SAMPLE_DATA_DIR,
    TARGET_CRS_STR,
    TARGET_EPSG,
)

DEMO_DISCLAIMER: str = "DATA DEMO — Data sintetis untuk pengujian sistem, bukan hasil pengukuran sungguhan."

# Approximate UTM Zone 47N (EPSG:32647) bounding box for Kota Pekanbaru
# Aligns directly with real-world Pekanbaru on Google Maps (101.365°E..101.535°E, 0.435°N..0.600°N)
DEMO_XMIN: float = 763_200.0
DEMO_YMIN: float = 48_200.0
DEMO_WIDTH_M: float = 18_000.0
DEMO_HEIGHT_M: float = 18_000.0

# Relative seed centers (normalized 0..1 within bounding box) for the 15 Kecamatan
# matching their real-world coordinates in Kota Pekanbaru on Google Maps
KECAMATAN_SEEDS_NORM: Dict[str, Tuple[float, float]] = {
    # North of Siak River (Rumbai region)
    "Rumbai Barat": (0.18, 0.80),
    "Rumbai": (0.45, 0.76),
    "Rumbai Timur": (0.78, 0.78),
    # Along Siak River corridor (West to East)
    "Payung Sekaki": (0.25, 0.52),
    "Senapelan": (0.41, 0.56),
    "Pekanbaru Kota": (0.48, 0.50),
    "Lima Puluh": (0.56, 0.53),
    "Tenayan Raya": (0.78, 0.48),
    # Central & West-South belt (Panam, Marpoyan, Bukit Raya, Kulim)
    "Bina Widya": (0.16, 0.35),
    "Tuah Madani": (0.22, 0.18),
    "Sukajadi": (0.40, 0.42),
    "Sail": (0.54, 0.41),
    "Marpoyan Damai": (0.40, 0.24),
    "Bukit Raya": (0.54, 0.24),
    "Kulim": (0.76, 0.22),
}


def _build_city_boundary(xmin: float, ymin: float, width: float, height: float) -> Polygon:
    """Create a realistic organic polygon boundary for the Pekanbaru demo area."""
    cx = xmin + width * 0.5
    cy = ymin + height * 0.5
    rx = width * 0.47
    ry = height * 0.47

    angles = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    # Deterministic organic perturbation
    radii_mod = (
        1.0
        + 0.04 * np.sin(3 * angles + 0.5)
        + 0.03 * np.cos(5 * angles - 0.8)
        + 0.02 * np.sin(7 * angles + 1.2)
    )
    coords = [
        (cx + rx * r * np.cos(a), cy + ry * r * np.sin(a))
        for a, r in zip(angles, radii_mod)
    ]
    coords.append(coords[0])
    return Polygon(coords).buffer(0)


def _generate_kecamatan_gdf(
    xmin: float, ymin: float, width: float, height: float
) -> gpd.GeoDataFrame:
    """Generate 15 Kecamatan polygons partitioning the city boundary via clipped Voronoi."""
    city_poly = _build_city_boundary(xmin, ymin, width, height)

    names: List[str] = []
    seed_pts: List[Tuple[float, float]] = []
    for name in KECAMATAN_LIST:
        nx, ny = KECAMATAN_SEEDS_NORM[name]
        names.append(name)
        seed_pts.append((xmin + nx * width, ymin + ny * height))

    # Add far boundary mirror points so all 15 interior Voronoi cells are bounded
    far_pts = [
        (xmin - width * 2, ymin - height * 2),
        (xmin + width * 3, ymin - height * 2),
        (xmin + width * 3, ymin + height * 3),
        (xmin - width * 2, ymin + height * 3),
        (xmin + width * 0.5, ymin - height * 2.5),
        (xmin + width * 0.5, ymin + height * 3.5),
        (xmin - width * 2.5, ymin + height * 0.5),
        (xmin + width * 3.5, ymin + height * 0.5),
    ]
    all_pts = np.array(seed_pts + far_pts)
    vor = Voronoi(all_pts)

    polys: List[Polygon] = []
    for i in range(len(names)):
        region_idx = vor.point_region[i]
        vertices_idx = vor.regions[region_idx]
        cell_poly = Polygon([vor.vertices[v] for v in vertices_idx]).buffer(0)
        clipped = cell_poly.intersection(city_poly).buffer(0)
        polys.append(clipped)

    gdf = gpd.GeoDataFrame(
        {
            "id_kec": list(range(1, len(names) + 1)),
            "nama_kecamatan": names,
            "kota": ["Pekanbaru"] * len(names),
            "provinsi": ["Riau"] * len(names),
            "sumber": [DEMO_DISCLAIMER] * len(names),
        },
        geometry=polys,
        crs=TARGET_CRS_STR,
    )
    return gdf


def _generate_rivers_gdf(
    xmin: float, ymin: float, width: float, height: float, city_poly: Polygon
) -> gpd.GeoDataFrame:
    """Generate 8 named rivers (Siak + 7 tributaries) meandering across the city."""
    t = np.linspace(0.0, 1.0, 120)

    # 1. Sungai Siak (main river flowing West -> East around y = 0.62..0.58)
    siak_x = xmin + t * width
    siak_y = ymin + height * (0.61 + 0.035 * np.sin(2.5 * np.pi * t) - 0.02 * t)
    siak_line = LineString(np.column_stack([siak_x, siak_y]))

    # 2. Sungai Sail (South -> North into Siak around x = 0.52)
    sail_y = ymin + height * (0.18 + t * 0.43)
    sail_x = xmin + width * (0.55 - 0.03 * t + 0.018 * np.sin(3 * np.pi * t))
    sail_line = LineString(np.column_stack([sail_x, sail_y]))

    # 3. Sungai Air Hitam (West/SW -> North into Siak around x = 0.25)
    ah_y = ymin + height * (0.30 + t * 0.33)
    ah_x = xmin + width * (0.12 + 0.14 * t + 0.02 * np.cos(2.5 * np.pi * t))
    ah_line = LineString(np.column_stack([ah_x, ah_y]))

    # 4. Sungai Senapelan (Central-SW -> Siak around x = 0.41)
    sen_y = ymin + height * (0.36 + t * 0.26)
    sen_x = xmin + width * (0.36 + 0.05 * t + 0.012 * np.sin(2 * np.pi * t))
    sen_line = LineString(np.column_stack([sen_x, sen_y]))

    # 5. Sungai Sago (Central -> Siak around x = 0.49)
    sago_y = ymin + height * (0.40 + t * 0.20)
    sago_x = xmin + width * (0.47 + 0.02 * t + 0.01 * np.cos(2 * np.pi * t))
    sago_line = LineString(np.column_stack([sago_x, sago_y]))

    # 6. Sungai Sibam (SW -> Air Hitam / West corridor)
    sibam_y = ymin + height * (0.12 + t * 0.28)
    sibam_x = xmin + width * (0.18 + 0.06 * t + 0.015 * np.sin(2 * np.pi * t))
    sibam_line = LineString(np.column_stack([sibam_x, sibam_y]))

    # 7. Sungai Tenayan (SE -> North into Siak around x = 0.76)
    ten_y = ymin + height * (0.22 + t * 0.37)
    ten_x = xmin + width * (0.80 - 0.04 * t + 0.02 * np.sin(2.5 * np.pi * t))
    ten_line = LineString(np.column_stack([ten_x, ten_y]))

    # 8. Sungai Umban Sari (North Rumbai -> South into Siak around x = 0.38)
    umban_y = ymin + height * (0.88 - t * 0.26)
    umban_x = xmin + width * (0.35 + 0.04 * t + 0.015 * np.cos(2 * np.pi * t))
    umban_line = LineString(np.column_stack([umban_x, umban_y]))

    raw_lines = [
        ("Siak", "Sungai Utama", siak_line),
        ("Sail", "Anak Sungai", sail_line),
        ("Air Hitam", "Anak Sungai", ah_line),
        ("Senapelan", "Anak Sungai", sen_line),
        ("Sago", "Anak Sungai", sago_line),
        ("Sibam", "Anak Sungai", sibam_line),
        ("Tenayan", "Anak Sungai", ten_line),
        ("Umban Sari", "Anak Sungai", umban_line),
    ]

    records = []
    geoms = []
    for idx, (name, jenis, line) in enumerate(raw_lines, start=1):
        clipped = line.intersection(city_poly.buffer(150.0))
        if not clipped.is_empty:
            records.append(
                {
                    "id_sungai": idx,
                    "nama_sungai": name,
                    "jenis": jenis,
                    "sumber": DEMO_DISCLAIMER,
                }
            )
            geoms.append(clipped)

    return gpd.GeoDataFrame(records, geometry=geoms, crs=TARGET_CRS_STR)


def _generate_dem_raster(
    output_path: Path,
    xmin: float,
    ymin: float,
    width: float,
    height: float,
    rivers_gdf: gpd.GeoDataFrame,
    city_poly: Polygon,
    pixel_size: float = PIXEL_SIZE,
) -> Tuple[np.ndarray, rasterio.Affine]:
    """Generate a synthetic DEM GeoTIFF with floodplain valleys and hills."""
    cols = int(round(width / pixel_size))
    rows = int(round(height / pixel_size))
    ymax = ymin + rows * pixel_size
    transform = from_origin(xmin, ymax, pixel_size, pixel_size)

    # Normalized coordinates (0..1)
    xs = np.linspace(0.0, 1.0, cols)
    ys = np.linspace(1.0, 0.0, rows)  # top row is ymax (y=1.0)
    xx, yy = np.meshgrid(xs, ys)

    # Rasterize rivers to compute distance to river for floodplain carving
    from rasterio.features import rasterize

    river_mask = rasterize(
        [(geom, 1) for geom in rivers_gdf.geometry],
        out_shape=(rows, cols),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )
    dist_river_m = distance_transform_edt(river_mask == 0, sampling=pixel_size)

    # Siak main corridor distance (approx y around 0.60)
    siak_geom = rivers_gdf.loc[rivers_gdf["nama_sungai"] == "Siak", "geometry"].values[0]
    siak_mask = rasterize(
        [(siak_geom, 1)],
        out_shape=(rows, cols),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )
    dist_siak_m = distance_transform_edt(siak_mask == 0, sampling=pixel_size)

    # Base elevation:
    # - Very low floodplain along Siak & tributaries (4m - 9.5m)
    # - Gentle terrace in central/south (12m - 26m)
    # - Undulating steep hills in northern Rumbai (yy > 0.64) and SE Kulim/Tenayan (38m - 68m)
    rng = np.random.default_rng(42)
    fine_noise = gaussian_filter(rng.standard_normal((rows, cols)), sigma=2.2) * 14.0
    north_hill_mask = np.clip((yy - 0.62) * 3.0, 0.0, 1.0)
    se_hill_mask = np.clip((xx - 0.58) * 2.5, 0.0, 1.0) * np.clip((0.46 - yy) * 2.5, 0.0, 1.0)
    hill_zone = np.clip(north_hill_mask + se_hill_mask, 0.0, 1.0)

    local_relief = hill_zone * (
        18.0 * np.sin(55.0 * np.pi * xx) * np.cos(55.0 * np.pi * yy)
        + 14.0 * np.cos(40.0 * np.pi * xx + 0.7)
    )
    ridge_hills = (
        42.0 * north_hill_mask
        + 38.0 * se_hill_mask
        + 18.0 * np.exp(-((xx - 0.16) ** 2 + (yy - 0.18) ** 2) / 0.045)
    )

    floodplain_rise = 20.0 * (1.0 - np.exp(-dist_siak_m / 1600.0))
    tributary_carve = -7.5 * np.exp(-dist_river_m / 300.0)

    dem = 5.0 + floodplain_rise + ridge_hills + local_relief + tributary_carve + fine_noise * (0.35 + 0.85 * hill_zone)
    dem = np.clip(dem, 2.5, 72.0).astype(np.float32)

    # Mask outside city boundary with a slight buffer so edge pixels are clean
    city_mask = rasterize(
        [(city_poly.buffer(pixel_size * 2), 1)],
        out_shape=(rows, cols),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )
    dem_out = np.where(city_mask == 1, dem, NODATA_FLOAT).astype(np.float32)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs=TARGET_CRS_STR,
        transform=transform,
        nodata=NODATA_FLOAT,
        compress="lzw",
    ) as dst:
        dst.write(dem_out, 1)

    return dem_out, transform


def _generate_landuse_gdf(
    kecamatan_gdf: gpd.GeoDataFrame,
    rivers_gdf: gpd.GeoDataFrame,
    xmin: float,
    ymin: float,
    width: float,
    height: float,
) -> gpd.GeoDataFrame:
    """Create polygon land-use zones covering the entire city boundary."""
    city_poly = unary_union(kecamatan_gdf.geometry).buffer(0)
    cx = xmin + width * 0.46
    cy = ymin + height * 0.52

    # Concentric/sectoral urban zones + river corridors
    urban_core = Point(cx, cy).buffer(width * 0.22).intersection(city_poly)
    siak_corridor = unary_union(rivers_gdf.geometry).buffer(420.0).intersection(city_poly)
    dense_zone = unary_union([urban_core, siak_corridor.intersection(Point(cx, cy).buffer(width * 0.34))]).intersection(city_poly)

    suburban_ring = (
        Point(cx, cy)
        .buffer(width * 0.36)
        .difference(dense_zone)
        .intersection(city_poly)
    )

    open_land_box = Polygon(
        [
            (xmin, ymin),
            (xmin + width * 0.68, ymin),
            (xmin + width * 0.68, ymin + height * 0.72),
            (xmin, ymin + height * 0.72),
        ]
    )
    open_zone = (
        open_land_box.intersection(city_poly)
        .difference(unary_union([dense_zone, suburban_ring]))
    )

    forest_box = Polygon(
        [
            (xmin, ymin + height * 0.76),
            (xmin + width, ymin + height * 0.76),
            (xmin + width, ymin + height),
            (xmin, ymin + height),
        ]
    )
    forest_zone = (
        forest_box.intersection(city_poly)
        .difference(unary_union([dense_zone, suburban_ring, open_zone]))
    )

    plantation_zone = city_poly.difference(
        unary_union([dense_zone, suburban_ring, open_zone, forest_zone])
    )

    zones = [
        ("Permukiman Padat/Lahan Terbangun Komersial", dense_zone),
        ("Permukiman Jarang/Industri", suburban_ring),
        ("Lahan Terbuka/Tegalan", open_zone),
        ("Perkebunan/Semak", plantation_zone),
        ("Hutan/Rawa", forest_zone),
    ]

    records = []
    geoms = []
    for idx, (kelas, geom) in enumerate(zones, start=1):
        clean_geom = geom.buffer(0)
        if not clean_geom.is_empty:
            records.append(
                {
                    "id_lu": idx,
                    "kelas_lahan": kelas,
                    "sumber": DEMO_DISCLAIMER,
                }
            )
            geoms.append(clean_geom)

    return gpd.GeoDataFrame(records, geometry=geoms, crs=TARGET_CRS_STR)


def _generate_rainfall_df(
    xmin: float, ymin: float, width: float, height: float
) -> pd.DataFrame:
    """Generate 10-year annual rainfall table (2016-2025) across 6 stations in Pekanbaru."""
    transformer = Transformer.from_crs(f"EPSG:{TARGET_EPSG}", "EPSG:4326", always_xy=True)

    stations = [
        ("Stasiun Meteo SSK II Pekanbaru", 0.44, 0.36, 3180.0),
        ("Stasiun Klimatologi Senapelan", 0.42, 0.56, 3560.0),
        ("Pos Hujan Payung Sekaki", 0.22, 0.54, 3380.0),
        ("Pos Hujan Tenayan Raya", 0.76, 0.50, 2720.0),
        ("Pos Hujan Rumbai Utara", 0.48, 0.84, 2280.0),
        ("Pos Hujan Kulim Selatan", 0.78, 0.22, 1940.0),
    ]

    rng = np.random.default_rng(101)
    rows: List[Dict[str, Any]] = []
    for name, nx, ny, base_mm in stations:
        x_utm = xmin + nx * width
        y_utm = ymin + ny * height
        lon, lat = transformer.transform(x_utm, y_utm)
        for year in range(2016, 2026):
            annual_mm = round(float(base_mm + rng.normal(0.0, 65.0)), 1)
            rows.append(
                {
                    "stasiun": name,
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "tahun": year,
                    "hujan_mm": annual_mm,
                }
            )
    return pd.DataFrame(rows)


def _generate_validation_points_df(
    xmin: float,
    ymin: float,
    width: float,
    height: float,
    kecamatan_gdf: gpd.GeoDataFrame,
    rivers_gdf: gpd.GeoDataFrame,
    landuse_gdf: gpd.GeoDataFrame,
    rain_df: pd.DataFrame,
    dem: np.ndarray,
    transform: rasterio.Affine,
) -> pd.DataFrame:
    """Generate 60 historical validation points with coordinates, field class, and binary label."""
    from backend.core.overlay import classify_score_label, compute_weighted_overlay
    from backend.core.parameters import (
        compute_elevation_parameter,
        compute_landuse_parameter,
        compute_rainfall_parameter,
        compute_river_distance_parameter,
        compute_slope_parameter,
    )

    transformer = Transformer.from_crs(f"EPSG:{TARGET_EPSG}", "EPSG:4326", always_xy=True)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{TARGET_EPSG}", always_xy=True)
    rng = np.random.default_rng(2026)

    city_poly = unary_union(kecamatan_gdf.geometry)
    rows_cnt, cols_cnt = dem.shape
    valid_mask = (dem != NODATA_FLOAT) & np.isfinite(dem)
    px_size = float(transform.a)

    # Precompute reference score S raster so ground-truth survey points have realistic ~92% agreement
    st_df = (
        rain_df.groupby("stasiun", as_index=False)
        .agg(lat=("lat", "mean"), lon=("lon", "mean"), hujan_mm=("hujan_mm", "mean"))
    )
    st_xy = [to_utm.transform(float(r["lon"]), float(r["lat"])) for _, r in st_df.iterrows()]
    st_df["x"] = [p[0] for p in st_xy]
    st_df["y"] = [p[1] for p in st_xy]

    _, ch_sc, _ = compute_rainfall_parameter(st_df, (rows_cnt, cols_cnt), transform, valid_mask)
    _, sl_sc = compute_slope_parameter(dem, valid_mask, pixel_size=px_size)
    _, el_sc = compute_elevation_parameter(dem, valid_mask)
    lu_sc, _ = compute_landuse_parameter(landuse_gdf, "kelas_lahan", (rows_cnt, cols_cnt), transform, valid_mask)
    _, rv_sc = compute_river_distance_parameter(rivers_gdf, (rows_cnt, cols_cnt), transform, valid_mask, pixel_size=px_size)

    s_ref, _ = compute_weighted_overlay(
        {
            "curah_hujan": ch_sc,
            "kemiringan_lereng": sl_sc,
            "elevasi": el_sc,
            "penggunaan_lahan": lu_sc,
            "jarak_sungai": rv_sc,
        },
        valid_mask=valid_mask,
    )

    points_data: List[Dict[str, Any]] = []
    attempts = 0
    while len(points_data) < 60 and attempts < 2000:
        attempts += 1
        # Sample across river corridors, central urban area, and northern/SE hills
        if len(points_data) < 28:
            nx = rng.uniform(0.15, 0.82)
            ny = float(np.clip(rng.normal(0.56, 0.10), 0.12, 0.88))
        elif len(points_data) < 45:
            nx = rng.uniform(0.12, 0.88)
            ny = rng.uniform(0.12, 0.88)
        else:
            # Sample northern hills & SE hills so Rendah class is also well-represented
            nx = rng.uniform(0.20, 0.88)
            ny = rng.choice([rng.uniform(0.75, 0.90), rng.uniform(0.12, 0.30)])

        x_utm = xmin + nx * width
        y_utm = ymin + ny * height
        pt = Point(x_utm, y_utm)
        if not city_poly.contains(pt):
            continue

        col = int((x_utm - transform.c) / transform.a)
        row = int((y_utm - transform.f) / transform.e)
        if not (0 <= row < rows_cnt and 0 <= col < cols_cnt):
            continue

        if not valid_mask[row, col]:
            continue

        # Determine district name
        kec_name = "Pekanbaru Kota"
        for _, krow in kecamatan_gdf.iterrows():
            if krow.geometry.contains(pt):
                kec_name = str(krow["nama_kecamatan"])
                break

        s_here = float(s_ref[row, col])
        true_cls = classify_score_label(s_here)
        label_banjir = 1 if true_cls in ("Sedang", "Tinggi") else 0

        # Introduce ~8% realistic field survey variation (5 out of 60 points -> 91.67% accuracy)
        if len(points_data) in (11, 23, 37, 48, 56):
            kelas_lapangan = "Sedang" if true_cls == "Tinggi" else "Tinggi"
        else:
            kelas_lapangan = true_cls

        lon, lat = transformer.transform(x_utm, y_utm)
        points_data.append(
            {
                "id": len(points_data) + 1,
                "lokasi": f"Titik Survey #{len(points_data) + 1:02d} ({kec_name})",
                "kecamatan": kec_name,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "kelas_lapangan": kelas_lapangan,
                "label": label_banjir,
                "catatan": DEMO_DISCLAIMER,
            }
        )

    return pd.DataFrame(points_data)


def generate_demo_dataset(
    output_dir: Path | None = None,
    pixel_size: float = PIXEL_SIZE,
    width_m: float = DEMO_WIDTH_M,
    height_m: float = DEMO_HEIGHT_M,
) -> Dict[str, Any]:
    """Generate all 6 demo input files in `output_dir` and return their paths & metadata.

    Args:
        output_dir: Target directory for demo files (defaults to `sample_data/demo`).
        pixel_size: Grid resolution in meters (default 30.0).
        width_m: Demo extent width in meters.
        height_m: Demo extent height in meters.

    Returns:
        Dictionary containing paths to all generated files and summary metadata.
    """
    target_dir = Path(output_dir) if output_dir is not None else (SAMPLE_DATA_DIR / "demo")
    target_dir.mkdir(parents=True, exist_ok=True)

    xmin, ymin = DEMO_XMIN, DEMO_YMIN

    # 1. Batas Administrasi 15 Kecamatan
    kecamatan_gdf = _generate_kecamatan_gdf(xmin, ymin, width_m, height_m)
    kec_path = target_dir / "batas_kecamatan_pekanbaru_demo.gpkg"
    kecamatan_gdf.to_file(kec_path, driver="GPKG")

    city_poly = unary_union(kecamatan_gdf.geometry).buffer(0)

    # 2. Jaringan Sungai
    rivers_gdf = _generate_rivers_gdf(xmin, ymin, width_m, height_m, city_poly)
    rivers_path = target_dir / "jaringan_sungai_pekanbaru_demo.gpkg"
    rivers_gdf.to_file(rivers_path, driver="GPKG")

    # 3. DEMNAS GeoTIFF
    dem_path = target_dir / "demnas_pekanbaru_demo.tif"
    dem_arr, dem_transform = _generate_dem_raster(
        dem_path, xmin, ymin, width_m, height_m, rivers_gdf, city_poly, pixel_size=pixel_size
    )

    # 4. Penggunaan Lahan
    landuse_gdf = _generate_landuse_gdf(
        kecamatan_gdf, rivers_gdf, xmin, ymin, width_m, height_m
    )
    landuse_path = target_dir / "penggunaan_lahan_pekanbaru_demo.gpkg"
    landuse_gdf.to_file(landuse_path, driver="GPKG")

    # 5. Curah Hujan (CSV & XLSX)
    rain_df = _generate_rainfall_df(xmin, ymin, width_m, height_m)
    rain_csv_path = target_dir / "curah_hujan_bmkg_demo.csv"
    rain_xlsx_path = target_dir / "curah_hujan_bmkg_demo.xlsx"
    rain_df.to_csv(rain_csv_path, index=False)
    rain_df.to_excel(rain_xlsx_path, index=False)

    # 6. Titik Banjir Historis (Validasi)
    val_df = _generate_validation_points_df(
        xmin,
        ymin,
        width_m,
        height_m,
        kecamatan_gdf,
        rivers_gdf,
        landuse_gdf,
        rain_df,
        dem_arr,
        dem_transform,
    )
    val_csv_path = target_dir / "titik_banjir_historis_demo.csv"
    val_df.to_csv(val_csv_path, index=False)

    return {
        "is_demo": True,
        "disclaimer": DEMO_DISCLAIMER,
        "paths": {
            "dem": str(dem_path),
            "kecamatan": str(kec_path),
            "sungai": str(rivers_path),
            "curah_hujan": str(rain_csv_path),
            "curah_hujan_xlsx": str(rain_xlsx_path),
            "penggunaan_lahan": str(landuse_path),
            "titik_banjir": str(val_csv_path),
        },
        "columns": {
            "kecamatan_col": "nama_kecamatan",
            "landuse_col": "kelas_lahan",
            "river_col": "nama_sungai",
        },
        "summary": {
            "kecamatan_count": len(kecamatan_gdf),
            "river_count": len(rivers_gdf),
            "river_names": rivers_gdf["nama_sungai"].tolist(),
            "landuse_classes": sorted(landuse_gdf["kelas_lahan"].unique().tolist()),
            "rainfall_stations": int(rain_df["stasiun"].nunique()),
            "rainfall_years": int(rain_df["tahun"].nunique()),
            "validation_points": len(val_df),
            "grid_shape": list(dem_arr.shape),
        },
    }
