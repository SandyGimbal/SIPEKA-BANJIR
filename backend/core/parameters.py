"""Parameter calculation and reclassification module for SIPEKA-Banjir 3D.

Implements the 5 flood vulnerability parameters:
A. Curah Hujan (IDW power=2 interpolation -> reclassification)
B. Kemiringan Lereng (Horn 3x3 slope in percent -> reclassification)
C. Elevasi (DEM mdpl -> reclassification)
D. Penggunaan Lahan (Polygon to 30m raster via explicit class-to-score mapping)
E. Jarak terhadap Sungai (Rasterization + Euclidean Distance Transform -> reclassification)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import distance_transform_edt

from backend.core.config import (
    DEFAULT_LANDUSE_SCORES,
    DEFAULT_SCORING_RULES,
    NODATA_FLOAT,
    NODATA_UINT8,
    PIXEL_SIZE,
)


def reclassify_continuous(
    array: np.ndarray,
    rules: Sequence[Dict[str, Any]],
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Reclassify a continuous 2D array into integer scores (1..5) using boundary rules.

    Boundary rule convention:
    - Lower bound (`min`) is inclusive (`value >= min`) when `min` is not None.
    - Upper bound (`max`) is exclusive (`value < max`) when `max` is not None.
    - Top class has `max = None` (or `inf`), meaning all values `>= min`.

    Args:
        array: 2D numpy array of continuous parameter values.
        rules: Sequence of dicts with keys `'min'`, `'max'`, `'score'`.
        valid_mask: Boolean mask of valid pixels (True = inside city). If None, inferred from array.

    Returns:
        2D uint8 array of scores (1..5) inside `valid_mask`, and `NODATA_UINT8` (0) outside.
    """
    arr = np.asarray(array, dtype=np.float64)
    if valid_mask is None:
        valid = np.isfinite(arr) & (arr != NODATA_FLOAT)
    else:
        valid = np.asarray(valid_mask, dtype=bool) & np.isfinite(arr) & (arr != NODATA_FLOAT)

    scores = np.full(arr.shape, NODATA_UINT8, dtype=np.uint8)

    for rule in rules:
        r_min = rule.get("min", None)
        r_max = rule.get("max", None)
        score_val = int(rule["score"])

        cond = valid.copy()
        if r_min is not None and not (isinstance(r_min, float) and np.isinf(r_min) and r_min < 0):
            cond &= arr >= float(r_min)
        if r_max is not None and not (isinstance(r_max, float) and np.isinf(r_max) and r_max > 0):
            cond &= arr < float(r_max)

        scores[cond] = score_val

    return scores


def interpolate_idw(
    station_coords_xy: np.ndarray,
    station_values: np.ndarray,
    grid_shape: Tuple[int, int],
    transform: Affine,
    valid_mask: Optional[np.ndarray] = None,
    power: float = 2.0,
) -> np.ndarray:
    """Interpolate point station values onto a 2D raster grid using Inverse Distance Weighting (IDW).

    Formula:
        Z(x, y) = sum(w_i * z_i) / sum(w_i), where w_i = 1 / d_i^power.
    If a grid cell center coincides with a station (d_i == 0), its value is exactly z_i.
    If only one station is provided, the entire valid grid receives that station's value.

    Args:
        station_coords_xy: Array of shape (N, 2) with (x, y) coordinates in grid CRS.
        station_values: Array of shape (N,) with station values.
        grid_shape: Tuple of (rows, cols).
        transform: Affine transform of the target grid.
        valid_mask: Optional boolean mask (True = valid pixels to interpolate).
        power: IDW distance exponent (default 2.0).

    Returns:
        2D float32 array of interpolated values (`NODATA_FLOAT` outside `valid_mask`).
    """
    coords = np.asarray(station_coords_xy, dtype=np.float64)
    values = np.asarray(station_values, dtype=np.float64)
    if coords.ndim != 2 or coords.shape[1] != 2 or len(coords) == 0:
        raise ValueError("Koordinat stasiun hujan tidak valid atau kosong.")
    if len(coords) != len(values):
        raise ValueError("Jumlah koordinat stasiun dan nilai curah hujan tidak sama.")

    rows, cols = grid_shape
    if valid_mask is None:
        mask = np.ones((rows, cols), dtype=bool)
    else:
        mask = np.asarray(valid_mask, dtype=bool)

    result = np.full((rows, cols), NODATA_FLOAT, dtype=np.float32)
    if not np.any(mask):
        return result

    # Special fast-path for single station: entire valid grid equals the station value
    if len(values) == 1:
        result[mask] = float(values[0])
        return result

    # Compute cell center coordinates (cx, cy)
    col_indices = np.arange(cols, dtype=np.float64) + 0.5
    row_indices = np.arange(rows, dtype=np.float64) + 0.5
    cx_1d = transform.c + col_indices * transform.a
    cy_1d = transform.f + row_indices * transform.e
    cx_grid, cy_grid = np.meshgrid(cx_1d, cy_1d)

    vx = cx_grid[mask]  # shape (M,)
    vy = cy_grid[mask]  # shape (M,)

    # Distances from M valid pixels to N stations -> shape (M, N)
    dx = vx[:, None] - coords[None, :, 0]
    dy = vy[:, None] - coords[None, :, 1]
    dist_sq = dx * dx + dy * dy

    # Handle exact coincidence with station coordinates (dist == 0)
    zero_mask = dist_sq < 1e-12
    # Avoid division by zero
    safe_dist_sq = np.where(zero_mask, 1.0, dist_sq)
    if power == 2.0:
        weights = 1.0 / safe_dist_sq
    else:
        weights = 1.0 / (np.sqrt(safe_dist_sq) ** power)

    interp_vals = np.sum(weights * values[None, :], axis=1) / np.sum(weights, axis=1)

    # Where a pixel coincides with a station, set exact station value
    if np.any(zero_mask):
        exact_rows, exact_station_idx = np.where(zero_mask)
        interp_vals[exact_rows] = values[exact_station_idx]

    result[mask] = interp_vals.astype(np.float32)

    # Also ensure that if a station falls inside any valid pixel (row, col) and was given
    # at exact pixel center or within pixel, let's check if station is at exact cell center
    return result


def compute_rainfall_parameter(
    station_df: pd.DataFrame,
    grid_shape: Tuple[int, int],
    transform: Affine,
    valid_mask: np.ndarray,
    rules: Optional[Sequence[Dict[str, Any]]] = None,
    power: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Compute interpolated annual rainfall raster (mm/yr) and its score raster (1..5).

    Args:
        station_df: DataFrame with columns `'x'`, `'y'`, `'hujan_mm'`.
        grid_shape: Target raster shape `(rows, cols)`.
        transform: Target raster Affine transform.
        valid_mask: Boolean mask of valid city pixels.
        rules: Scoring rules for rainfall (defaults to `DEFAULT_SCORING_RULES['curah_hujan']`).
        power: IDW exponent (default 2.0).

    Returns:
        Tuple of (continuous rainfall raster float32, score raster uint8, warnings list).
    """
    scoring_rules = rules if rules is not None else DEFAULT_SCORING_RULES["curah_hujan"]
    warnings_list: List[str] = []

    coords = station_df[["x", "y"]].to_numpy(dtype=np.float64)
    vals = station_df["hujan_mm"].to_numpy(dtype=np.float64)

    rain_raster = interpolate_idw(
        station_coords_xy=coords,
        station_values=vals,
        grid_shape=grid_shape,
        transform=transform,
        valid_mask=valid_mask,
        power=power,
    )

    score_raster = reclassify_continuous(rain_raster, scoring_rules, valid_mask=valid_mask)

    # Check spatial differentiation of rainfall
    unique_scores = np.unique(score_raster[valid_mask])
    val_range = float(np.ptp(vals)) if len(vals) > 1 else 0.0
    if len(vals) < 4 or val_range < 250.0 or len(unique_scores) <= 1:
        warnings_list.append(
            f"Catatan Parameter Curah Hujan: Jumlah stasiun ({len(vals)}) atau rentang variasi "
            f"antar-stasiun ({val_range:.1f} mm/thn) relatif kecil sehingga parameter curah hujan "
            f"kurang membedakan wilayah ({len(unique_scores)} kelas skor terbentuk)."
        )

    return rain_raster, score_raster, warnings_list


def compute_slope_horn(
    dem: np.ndarray,
    pixel_size: float = PIXEL_SIZE,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Compute slope in percent (%) from a DEM using Horn's (1981) 3x3 finite-difference method.

    Horn's 3x3 formulas:
        dz/dx = ((z3 + 2*z6 + z9) - (z1 + 2*z4 + z7)) / (8 * cell_size_x)
        dz/dy = ((z7 + 2*z8 + z9) - (z1 + 2*z2 + z3)) / (8 * cell_size_y)
        slope_pct = 100 * sqrt((dz/dx)^2 + (dz/dy)^2)

    Args:
        dem: 2D array of elevation values in meters (mdpl).
        pixel_size: Real cell size in meters (default 30.0).
        valid_mask: Optional boolean mask of valid pixels.

    Returns:
        2D float32 array of slope in percent (%), with `NODATA_FLOAT` outside `valid_mask`.
    """
    arr = np.asarray(dem, dtype=np.float64)
    if valid_mask is None:
        mask = np.isfinite(arr) & (arr != NODATA_FLOAT)
    else:
        mask = np.asarray(valid_mask, dtype=bool) & np.isfinite(arr) & (arr != NODATA_FLOAT)

    slope_out = np.full(arr.shape, NODATA_FLOAT, dtype=np.float32)
    if not np.any(mask):
        return slope_out

    # Fill any nodata cells prior to 3x3 window so nodata values (-9999) don't corrupt edge gradients
    filled = arr.copy()
    if not np.all(mask):
        indices = distance_transform_edt(~mask, return_distances=False, return_indices=True)
        filled[~mask] = filled[tuple(indices[:, ~mask])]

    # Pad array by 1 pixel using linear extrapolation at the outer border so planar slopes stay exact at edges
    padded = np.pad(filled, pad_width=1, mode="edge")
    if filled.shape[0] >= 2:
        padded[0, 1:-1] = 2.0 * filled[0, :] - filled[1, :]
        padded[-1, 1:-1] = 2.0 * filled[-1, :] - filled[-2, :]
    if filled.shape[1] >= 2:
        padded[1:-1, 0] = 2.0 * filled[:, 0] - filled[:, 1]
        padded[1:-1, -1] = 2.0 * filled[:, -1] - filled[:, -2]
    if filled.shape[0] >= 2 and filled.shape[1] >= 2:
        padded[0, 0] = padded[0, 1] + (padded[0, 1] - padded[0, 2])
        padded[0, -1] = padded[0, -2] + (padded[0, -2] - padded[0, -3])
        padded[-1, 0] = padded[-1, 1] + (padded[-1, 1] - padded[-1, 2])
        padded[-1, -1] = padded[-1, -2] + (padded[-1, -2] - padded[-1, -3])

    z1 = padded[:-2, :-2]
    z2 = padded[:-2, 1:-1]
    z3 = padded[:-2, 2:]
    z4 = padded[1:-1, :-2]
    z6 = padded[1:-1, 2:]
    z7 = padded[2:, :-2]
    z8 = padded[2:, 1:-1]
    z9 = padded[2:, 2:]

    dz_dx = ((z3 + 2.0 * z6 + z9) - (z1 + 2.0 * z4 + z7)) / (8.0 * float(pixel_size))
    dz_dy = ((z7 + 2.0 * z8 + z9) - (z1 + 2.0 * z2 + z3)) / (8.0 * float(pixel_size))

    slope_pct = 100.0 * np.sqrt(dz_dx * dz_dx + dz_dy * dz_dy)
    slope_out[mask] = slope_pct[mask].astype(np.float32)
    return slope_out


def compute_slope_parameter(
    dem: np.ndarray,
    valid_mask: np.ndarray,
    pixel_size: float = PIXEL_SIZE,
    rules: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute Horn 3x3 slope (%) raster and its reclassified score raster (1..5)."""
    scoring_rules = rules if rules is not None else DEFAULT_SCORING_RULES["kemiringan_lereng"]
    slope_pct = compute_slope_horn(dem, pixel_size=pixel_size, valid_mask=valid_mask)
    score_raster = reclassify_continuous(slope_pct, scoring_rules, valid_mask=valid_mask)
    return slope_pct, score_raster


def compute_elevation_parameter(
    dem: np.ndarray,
    valid_mask: np.ndarray,
    rules: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute elevation raster (mdpl) and its reclassified score raster (1..5)."""
    scoring_rules = rules if rules is not None else DEFAULT_SCORING_RULES["elevasi"]
    elev_raster = np.where(valid_mask, dem, NODATA_FLOAT).astype(np.float32)
    score_raster = reclassify_continuous(elev_raster, scoring_rules, valid_mask=valid_mask)
    return elev_raster, score_raster


def validate_and_map_landuse_classes(
    unique_classes: Sequence[str],
    landuse_scores: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[str, int], List[str]]:
    """Match unique land-use class names to scores (1..5), raising ValueError if any class is unmapped.

    Args:
        unique_classes: Sequence of unique class names found in the land-use dataset.
        landuse_scores: Mapping of class name -> integer score (1..5).

    Returns:
        Tuple of (resolved exact mapping dict, list of unmapped class names).
    """
    mapping_source = (
        landuse_scores if landuse_scores is not None else DEFAULT_LANDUSE_SCORES
    )
    # Build case-insensitive lookup
    lookup_lower: Dict[str, int] = {
        str(k).strip().lower(): int(v)
        for k, v in mapping_source.items()
        if v is not None and 1 <= int(v) <= 5
    }

    resolved: Dict[str, int] = {}
    unmapped: List[str] = []

    for cls_name in unique_classes:
        clean_name = str(cls_name).strip()
        key_lower = clean_name.lower()
        if key_lower in lookup_lower:
            resolved[clean_name] = lookup_lower[key_lower]
        else:
            unmapped.append(clean_name)

    return resolved, unmapped


def compute_landuse_parameter(
    landuse_gdf: gpd.GeoDataFrame,
    landuse_col: str,
    grid_shape: Tuple[int, int],
    transform: Affine,
    valid_mask: np.ndarray,
    landuse_scores: Optional[Dict[str, int]] = None,
) -> Tuple[np.ndarray, List[str]]:
    """Rasterize land-use polygons onto the 30 m grid using explicit class-to-score mapping.

    Raises ValueError if any land-use class present in `landuse_gdf[landuse_col]` is not mapped.

    Args:
        landuse_gdf: Clipped GeoDataFrame of land-use polygons.
        landuse_col: Column name containing class names.
        grid_shape: Target grid `(rows, cols)`.
        transform: Target grid Affine transform.
        valid_mask: Boolean mask of valid city pixels.
        landuse_scores: Mapping of class name -> integer score (1..5).

    Returns:
        Tuple of (uint8 score raster 1..5, warnings list).
    """
    unique_classes = sorted(
        landuse_gdf[landuse_col].dropna().astype(str).str.strip().unique().tolist()
    )
    resolved_map, unmapped = validate_and_map_landuse_classes(
        unique_classes, landuse_scores
    )
    if unmapped:
        raise ValueError(
            f"Terdapat kelas penggunaan lahan yang belum dipetakan skornya (1–5): {unmapped}. "
            "Silakan tentukan skor untuk seluruh kelas lahan pada Langkah 2."
        )

    warnings_list: List[str] = []
    shapes_with_scores = [
        (geom, int(resolved_map[str(cls_val).strip()]))
        for geom, cls_val in zip(landuse_gdf.geometry, landuse_gdf[landuse_col])
        if geom is not None and not geom.is_empty
    ]

    if not shapes_with_scores:
        raise ValueError("Tidak ada poligon penggunaan lahan yang valid untuk dirasterisasi.")

    score_raster = rasterize(
        shapes_with_scores,
        out_shape=grid_shape,
        transform=transform,
        fill=NODATA_UINT8,
        all_touched=False,
        dtype=np.uint8,
    )

    # Check if any valid city pixels were missed by polygon sliver gaps
    valid_scored = valid_mask & (score_raster >= 1) & (score_raster <= 5)
    if not np.any(valid_scored):
        # Retry with all_touched=True
        score_raster = rasterize(
            shapes_with_scores,
            out_shape=grid_shape,
            transform=transform,
            fill=NODATA_UINT8,
            all_touched=True,
            dtype=np.uint8,
        )
        valid_scored = valid_mask & (score_raster >= 1) & (score_raster <= 5)

    missing_in_city = valid_mask & ~valid_scored
    missing_cnt = int(np.count_nonzero(missing_in_city))
    if missing_cnt > 0 and np.any(valid_scored):
        indices = distance_transform_edt(
            ~valid_scored, return_distances=False, return_indices=True
        )
        score_raster[missing_in_city] = score_raster[tuple(indices[:, missing_in_city])]
        warnings_list.append(
            f"Penggunaan lahan: {missing_cnt} piksel celah poligon (sliver) diisi dari poligon terdekat."
        )

    score_raster = np.where(valid_mask, score_raster, NODATA_UINT8).astype(np.uint8)
    return score_raster, warnings_list


def compute_river_distance_from_mask(
    river_binary: np.ndarray,
    pixel_size: float = PIXEL_SIZE,
    valid_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Compute Euclidean distance (in meters) from river pixels (`river_binary > 0`).

    Uses `scipy.ndimage.distance_transform_edt(sampling=pixel_size)` as required.

    Args:
        river_binary: 2D array where river pixels are non-zero (True/1) and background is 0.
        pixel_size: Grid cell size in meters (default 30.0).
        valid_mask: Optional boolean mask of valid city pixels.

    Returns:
        2D float32 array of Euclidean distances in meters (`NODATA_FLOAT` outside `valid_mask`).
    """
    is_river = np.asarray(river_binary, dtype=bool)
    if not np.any(is_river):
        raise ValueError("Raster sungai kosong (tidak ada piksel sungai yang terdeteksi).")

    dist_m = distance_transform_edt(~is_river, sampling=float(pixel_size)).astype(
        np.float32
    )
    if valid_mask is not None:
        dist_m = np.where(valid_mask, dist_m, NODATA_FLOAT).astype(np.float32)
    return dist_m


def compute_river_distance_parameter(
    rivers_gdf: gpd.GeoDataFrame,
    grid_shape: Tuple[int, int],
    transform: Affine,
    valid_mask: np.ndarray,
    pixel_size: float = PIXEL_SIZE,
    rules: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Rasterize river network and compute Euclidean distance raster (m) and score raster (1..5)."""
    scoring_rules = rules if rules is not None else DEFAULT_SCORING_RULES["jarak_sungai"]

    shapes = [
        (geom, 1)
        for geom in rivers_gdf.geometry
        if geom is not None and not geom.is_empty
    ]
    if not shapes:
        raise ValueError("Tidak ada geometri sungai yang valid untuk dirasterisasi.")

    river_binary = rasterize(
        shapes,
        out_shape=grid_shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )

    dist_raster = compute_river_distance_from_mask(
        river_binary, pixel_size=pixel_size, valid_mask=valid_mask
    )
    score_raster = reclassify_continuous(
        dist_raster, scoring_rules, valid_mask=valid_mask
    )
    return dist_raster, score_raster

