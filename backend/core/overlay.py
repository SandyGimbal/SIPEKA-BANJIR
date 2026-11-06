"""Weighted Overlay and Equal-Interval Classification module for SIPEKA-Banjir 3D.

Formula:
    S = 0.25*CH + 0.25*Slope + 0.20*Elev + 0.15*LU + 0.15*Riv

Classification (Equal Interval, I = (5 - 1) / 3 = 4/3):
    Exact thresholds: 7/3 and 11/3
    - Rendah (1): 1.00 <= S < 7/3   (Hijau)
    - Sedang (2): 7/3  <= S < 11/3  (Kuning)
    - Tinggi (3): 11/3 <= S <= 5.00 (Merah)
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

from backend.core.config import (
    CLASS_DEFINITIONS,
    DEFAULT_WEIGHTS,
    NODATA_FLOAT,
    NODATA_UINT8,
    PARAMETER_LABELS,
    THRESHOLD_LOW_MED,
    THRESHOLD_MED_HIGH,
    validate_weights,
)

PARAMETER_ORDER = [
    "curah_hujan",
    "kemiringan_lereng",
    "elevasi",
    "penggunaan_lahan",
    "jarak_sungai",
]


def normalize_weights(weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Validate and normalize parameter weights so they are in [0, 1] and sum to 1.0.

    Args:
        weights: Dictionary of 5 parameter weights (either 0..1 or 0..100).
                 Defaults to `DEFAULT_WEIGHTS`.

    Returns:
        Normalized weight dictionary summing to 1.0.

    Raises:
        ValueError: If total weight is not 100% (1.0) within tolerance.
    """
    if weights is None:
        return dict(DEFAULT_WEIGHTS)

    validate_weights(weights)
    raw_sum = sum(float(weights[k]) for k in PARAMETER_ORDER)
    scale = 100.0 if raw_sum > 2.0 else 1.0
    return {k: float(weights[k]) / scale for k in PARAMETER_ORDER}


def classify_score(
    score_s: Union[float, np.ndarray],
    valid_mask: Optional[np.ndarray] = None,
) -> Union[int, np.ndarray]:
    """Classify continuous vulnerability index S into class 1 (Rendah), 2 (Sedang), or 3 (Tinggi).

    Uses exact thresholds 7/3 and 11/3 with a float32-safe epsilon (1e-6) so that
    `S = 7/3` (both float32 and float64) maps to 2 (Sedang) and `S = 11/3` maps to 3 (Tinggi).

    Args:
        score_s: Scalar float or 2D numpy array of composite score S in [1, 5].
        valid_mask: Optional boolean mask when `score_s` is an array.

    Returns:
        Integer class (1, 2, or 3) if scalar input, or 2D uint8 array (0 = nodata, 1/2/3 = classes).
    """
    eps = 1e-6
    t_low_med = THRESHOLD_LOW_MED - eps
    t_med_high = THRESHOLD_MED_HIGH - eps

    if np.ndim(score_s) == 0:
        val = float(score_s)
        if not np.isfinite(val) or val == NODATA_FLOAT or val < 1.0 - eps:
            return NODATA_UINT8
        if val >= t_med_high:
            return 3
        if val >= t_low_med:
            return 2
        return 1

    arr = np.asarray(score_s, dtype=np.float64)
    if valid_mask is None:
        mask = np.isfinite(arr) & (arr != NODATA_FLOAT) & (arr >= 1.0 - eps)
    else:
        mask = (
            np.asarray(valid_mask, dtype=bool)
            & np.isfinite(arr)
            & (arr != NODATA_FLOAT)
        )

    classes = np.full(arr.shape, NODATA_UINT8, dtype=np.uint8)
    classes[mask & (arr < t_low_med)] = 1
    classes[mask & (arr >= t_low_med) & (arr < t_med_high)] = 2
    classes[mask & (arr >= t_med_high)] = 3
    return classes


def classify_score_label(score_s: float) -> str:
    """Return the Indonesian class name ('Rendah', 'Sedang', 'Tinggi') for a scalar score S."""
    cls_code = int(classify_score(score_s))
    if cls_code in CLASS_DEFINITIONS:
        return str(CLASS_DEFINITIONS[cls_code]["name"])
    return "Nodata"


def compute_weighted_overlay(
    score_rasters: Dict[str, Union[float, int, np.ndarray]],
    weights: Optional[Dict[str, float]] = None,
    valid_mask: Optional[np.ndarray] = None,
) -> Tuple[Union[float, np.ndarray], Union[int, np.ndarray]]:
    """Compute composite vulnerability score S and class (1/2/3) via Weighted Overlay.

    Formula:
        S = w_CH * CH + w_Slope * Slope + w_Elev * Elev + w_LU * LU + w_Riv * Riv

    Supports both scalar inputs (for point checks/unit tests) and 2D numpy raster arrays.

    Args:
        score_rasters: Dict mapping parameter keys (`curah_hujan`, `kemiringan_lereng`,
                       `elevasi`, `penggunaan_lahan`, `jarak_sungai`) to scores (1..5).
        weights: Optional dict of parameter weights (must sum to 1.0 or 100%).
        valid_mask: Optional boolean mask of valid pixels inside the city boundary.

    Returns:
        Tuple of `(score_s, class_code)` where `score_s` is float/float32 array and
        `class_code` is int/uint8 array (1=Rendah, 2=Sedang, 3=Tinggi).
    """
    norm_w = normalize_weights(weights)

    missing_params = set(PARAMETER_ORDER) - set(score_rasters.keys())
    if missing_params:
        raise ValueError(f"Raster skor parameter belum lengkap: {sorted(missing_params)}")

    first_val = score_rasters[PARAMETER_ORDER[0]]
    if np.ndim(first_val) == 0:
        s_val = sum(
            float(norm_w[k]) * float(score_rasters[k]) for k in PARAMETER_ORDER
        )
        cls_val = int(classify_score(s_val))
        return float(s_val), cls_val

    shapes = {np.asarray(score_rasters[k]).shape for k in PARAMETER_ORDER}
    if len(shapes) != 1:
        raise ValueError(
            f"Seluruh 5 raster skor parameter harus memiliki ukuran grid (shape) yang identik. Ditemukan: {shapes}"
        )

    grid_shape = next(iter(shapes))
    if valid_mask is None:
        mask = np.ones(grid_shape, dtype=bool)
        for k in PARAMETER_ORDER:
            arr_k = np.asarray(score_rasters[k])
            mask &= (arr_k >= 1) & (arr_k <= 5)
    else:
        mask = np.asarray(valid_mask, dtype=bool)

    s_accum = np.zeros(grid_shape, dtype=np.float64)
    for k in PARAMETER_ORDER:
        s_accum += norm_w[k] * np.asarray(score_rasters[k], dtype=np.float64)

    score_s_raster = np.where(mask, s_accum, NODATA_FLOAT).astype(np.float32)
    class_raster = classify_score(s_accum, valid_mask=mask)
    return score_s_raster, class_raster


def get_dominant_factor_for_point(
    point_scores: Dict[str, int],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Identify the dominant contributing parameter (`weight * score`) at a single point."""
    norm_w = normalize_weights(weights)
    contributions: Dict[str, float] = {}
    for k in PARAMETER_ORDER:
        contributions[k] = round(float(norm_w[k]) * float(point_scores.get(k, 0)), 4)

    best_key = max(PARAMETER_ORDER, key=lambda k: contributions[k])
    total_s = sum(contributions.values())
    pct_share = (100.0 * contributions[best_key] / total_s) if total_s > 0 else 0.0

    return {
        "parameter_key": best_key,
        "parameter_label": PARAMETER_LABELS.get(best_key, best_key),
        "score": int(point_scores.get(best_key, 0)),
        "weight": round(norm_w[best_key], 4),
        "contribution": contributions[best_key],
        "contribution_pct": round(pct_share, 1),
        "all_contributions": contributions,
    }

