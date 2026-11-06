"""Zonal statistics module for SIPEKA-Banjir 3D.

Computes:
1. City-wide flood vulnerability area summary (ha, km², %) across Rendah/Sedang/Tinggi.
2. Per-district (15 Kecamatan) statistics: area & percentage per class, mean S, max S,
   dominant class, vulnerability rank (sorted by High % descending, then mean S descending),
   and per-parameter weighted contributions (`weight * mean_score`) for stacked bar charts.
3. Centroid and bounding box in WGS84 (EPSG:4326) for camera fly-to and Auto-Tour.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import distance_transform_edt

from backend.core.config import (
    CLASS_DEFINITIONS,
    DEFAULT_WEIGHTS,
    NODATA_FLOAT,
    PARAMETER_LABELS,
    PIXEL_SIZE,
)
from backend.core.overlay import PARAMETER_ORDER, normalize_weights


def compute_zonal_statistics(
    score_s_raster: np.ndarray,
    class_raster: np.ndarray,
    score_rasters: Dict[str, np.ndarray],
    kecamatan_gdf: gpd.GeoDataFrame,
    kecamatan_col: str,
    transform: Affine,
    valid_mask: np.ndarray,
    weights: Optional[Dict[str, float]] = None,
    pixel_size: float = PIXEL_SIZE,
) -> Dict[str, Any]:
    """Compute city-wide and per-kecamatan zonal statistics.

    Args:
        score_s_raster: 2D float32 array of composite score S.
        class_raster: 2D uint8 array of classes (1=Rendah, 2=Sedang, 3=Tinggi).
        score_rasters: Dict of 5 parameter score rasters (uint8, 1..5).
        kecamatan_gdf: GeoDataFrame of districts in grid CRS (EPSG:32647).
        kecamatan_col: Column name for district names.
        transform: Reference grid Affine transform.
        valid_mask: Boolean mask of valid pixels inside the city boundary.
        weights: Parameter weights dictionary.
        pixel_size: Grid cell size in meters (default 30.0).

    Returns:
        Dictionary containing `'city_summary'` and `'kecamatan_stats'`.
    """
    norm_w = normalize_weights(weights if weights is not None else DEFAULT_WEIGHTS)
    pixel_area_ha = (float(pixel_size) * float(pixel_size)) / 10_000.0
    pixel_area_km2 = pixel_area_ha / 100.0

    mask = np.asarray(valid_mask, dtype=bool) & (class_raster >= 1) & (class_raster <= 3)
    total_pixels = int(np.count_nonzero(mask))
    total_area_ha = total_pixels * pixel_area_ha
    total_area_km2 = total_pixels * pixel_area_km2

    # 1. City-wide class distribution
    classes_summary: Dict[str, Dict[str, Any]] = {}
    for cls_code in (1, 2, 3):
        cls_name = str(CLASS_DEFINITIONS[cls_code]["name"])
        cls_mask = mask & (class_raster == cls_code)
        px_cnt = int(np.count_nonzero(cls_mask))
        area_ha = px_cnt * pixel_area_ha
        area_km2 = px_cnt * pixel_area_km2
        pct = (100.0 * px_cnt / total_pixels) if total_pixels > 0 else 0.0
        classes_summary[cls_name] = {
            "code": cls_code,
            "name": cls_name,
            "color_hex": CLASS_DEFINITIONS[cls_code]["color_hex"],
            "pixels": px_cnt,
            "luas_ha": round(area_ha, 2),
            "luas_km2": round(area_km2, 4),
            "persen": round(pct, 2),
        }

    valid_s = score_s_raster[mask]
    mean_s_city = float(np.mean(valid_s)) if valid_s.size > 0 else 0.0
    max_s_city = float(np.max(valid_s)) if valid_s.size > 0 else 0.0
    min_s_city = float(np.min(valid_s)) if valid_s.size > 0 else 0.0

    city_param_contributions: Dict[str, float] = {}
    for k in PARAMETER_ORDER:
        if k in score_rasters:
            arr_k = score_rasters[k][mask]
            mean_k = float(np.mean(arr_k)) if arr_k.size > 0 else 0.0
            city_param_contributions[k] = round(norm_w[k] * mean_k, 4)

    # 2. Rasterize Kecamatan polygons with integer IDs 1..N
    gdf_proj = kecamatan_gdf.copy().reset_index(drop=True)
    gdf_wgs84 = gdf_proj.to_crs("EPSG:4326")

    shapes = [
        (geom, idx + 1)
        for idx, geom in enumerate(gdf_proj.geometry)
        if geom is not None and not geom.is_empty
    ]
    kec_id_raster = rasterize(
        shapes,
        out_shape=class_raster.shape,
        transform=transform,
        fill=0,
        all_touched=False,
        dtype=np.int32,
    )

    # Ensure every pixel inside `mask` is assigned to a district ID so district totals match city total
    unassigned = mask & (kec_id_raster == 0)
    if np.any(unassigned) and np.any(kec_id_raster > 0):
        indices = distance_transform_edt(
            kec_id_raster == 0, return_distances=False, return_indices=True
        )
        kec_id_raster[unassigned] = kec_id_raster[tuple(indices[:, unassigned])]

    kecamatan_rows: List[Dict[str, Any]] = []
    for idx, row in gdf_proj.iterrows():
        kec_id = idx + 1
        kec_name = str(row[kecamatan_col])
        k_mask = mask & (kec_id_raster == kec_id)
        k_pixels = int(np.count_nonzero(k_mask))
        k_area_ha = k_pixels * pixel_area_ha

        c1_px = int(np.count_nonzero(k_mask & (class_raster == 1)))
        c2_px = int(np.count_nonzero(k_mask & (class_raster == 2)))
        c3_px = int(np.count_nonzero(k_mask & (class_raster == 3)))

        c1_ha = c1_px * pixel_area_ha
        c2_ha = c2_px * pixel_area_ha
        c3_ha = c3_px * pixel_area_ha

        c1_pct = (100.0 * c1_px / k_pixels) if k_pixels > 0 else 0.0
        c2_pct = (100.0 * c2_px / k_pixels) if k_pixels > 0 else 0.0
        c3_pct = (100.0 * c3_px / k_pixels) if k_pixels > 0 else 0.0

        k_s = score_s_raster[k_mask]
        k_mean_s = float(np.mean(k_s)) if k_s.size > 0 else 0.0
        k_max_s = float(np.max(k_s)) if k_s.size > 0 else 0.0
        k_min_s = float(np.min(k_s)) if k_s.size > 0 else 0.0

        # Dominant class by pixel count
        cls_counts = {1: c1_px, 2: c2_px, 3: c3_px}
        dom_cls_code = max(cls_counts, key=lambda c: (cls_counts[c], c))
        dom_cls_name = str(CLASS_DEFINITIONS[dom_cls_code]["name"])

        # Parameter mean scores & weighted contributions
        param_means: Dict[str, float] = {}
        param_contribs: Dict[str, float] = {}
        for k in PARAMETER_ORDER:
            if k in score_rasters and k_pixels > 0:
                m_val = float(np.mean(score_rasters[k][k_mask]))
            else:
                m_val = 0.0
            param_means[k] = round(m_val, 3)
            param_contribs[k] = round(norm_w[k] * m_val, 4)

        dom_param_key = (
            max(PARAMETER_ORDER, key=lambda k: param_contribs.get(k, 0.0))
            if param_contribs
            else "elevasi"
        )

        # WGS84 centroid and bounds for camera fly-to
        geom_wgs = gdf_wgs84.loc[idx, "geometry"]
        rep_pt = geom_wgs.representative_point()
        minx, miny, maxx, maxy = geom_wgs.bounds

        kecamatan_rows.append(
            {
                "id": kec_id,
                "kecamatan": kec_name,
                "total_pixels": k_pixels,
                "luas_total_ha": round(k_area_ha, 2),
                "rendah_ha": round(c1_ha, 2),
                "rendah_persen": round(c1_pct, 2),
                "sedang_ha": round(c2_ha, 2),
                "sedang_persen": round(c2_pct, 2),
                "tinggi_ha": round(c3_ha, 2),
                "tinggi_persen": round(c3_pct, 2),
                "mean_s": round(k_mean_s, 3),
                "max_s": round(k_max_s, 3),
                "min_s": round(k_min_s, 3),
                "kelas_dominan": dom_cls_name,
                "faktor_dominan_key": dom_param_key,
                "faktor_dominan_label": PARAMETER_LABELS.get(dom_param_key, dom_param_key),
                "param_mean_scores": param_means,
                "param_contributions": param_contribs,
                "centroid_wgs84": [round(float(rep_pt.x), 6), round(float(rep_pt.y), 6)],
                "bbox_wgs84": [
                    round(float(minx), 6),
                    round(float(miny), 6),
                    round(float(maxx), 6),
                    round(float(maxy), 6),
                ],
                "_sort_high_pct": c3_pct,
                "_sort_mean_s": k_mean_s,
            }
        )

    # Sort by persen kelas Tinggi descending, then rata-rata S descending
    kecamatan_rows.sort(
        key=lambda r: (r["_sort_high_pct"], r["_sort_mean_s"]), reverse=True
    )
    for rank_idx, r in enumerate(kecamatan_rows, start=1):
        r["peringkat"] = rank_idx
        r.pop("_sort_high_pct", None)
        r.pop("_sort_mean_s", None)

    return {
        "city_summary": {
            "total_pixels": total_pixels,
            "luas_total_ha": round(total_area_ha, 2),
            "luas_total_km2": round(total_area_km2, 4),
            "mean_s": round(mean_s_city, 3),
            "max_s": round(max_s_city, 3),
            "min_s": round(min_s_city, 3),
            "classes": classes_summary,
            "param_contributions": city_param_contributions,
        },
        "kecamatan_stats": kecamatan_rows,
    }

