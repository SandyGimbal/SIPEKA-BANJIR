"""Comprehensive unit tests for `backend/core/` (Requirements #1 to #10)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from rasterio.transform import from_origin

from backend.core.config import (
    DEFAULT_SCORING_RULES,
    DEFAULT_WEIGHTS,
    PIXEL_SIZE,
    THRESHOLD_LOW_MED,
    THRESHOLD_MED_HIGH,
    validate_weights,
)
from backend.core.demo import generate_demo_dataset
from backend.core.overlay import (
    classify_score,
    classify_score_label,
    compute_weighted_overlay,
    get_dominant_factor_for_point,
)
from backend.core.parameters import (
    compute_elevation_parameter,
    compute_landuse_parameter,
    compute_rainfall_parameter,
    compute_river_distance_from_mask,
    compute_river_distance_parameter,
    compute_slope_horn,
    compute_slope_parameter,
    interpolate_idw,
    reclassify_continuous,
    validate_and_map_landuse_classes,
)
from backend.core.preprocess import (
    build_reference_grid,
    preprocess_dem,
    preprocess_landuse,
    preprocess_rainfall_table,
    preprocess_rivers,
)
from backend.core.validation import (
    compute_confusion_matrix_metrics,
    run_sensitivity_analysis,
)
from backend.core.zonal import compute_zonal_statistics


# ---------------------------------------------------------------------------
# 1. Semua skor 5 -> S = 5.00 (Tinggi); semua 1 -> 1.00 (Rendah); semua 3 -> 3.00 (Sedang)
# ---------------------------------------------------------------------------
def test_uniform_scores_extremes_and_middle() -> None:
    """Test #1: Uniform scores 5 -> 5.00 (Tinggi), 1 -> 1.00 (Rendah), 3 -> 3.00 (Sedang)."""
    scores_all_5 = {k: 5 for k in DEFAULT_WEIGHTS}
    s5, cls5 = compute_weighted_overlay(scores_all_5, DEFAULT_WEIGHTS)
    assert math.isclose(s5, 5.00, rel_tol=1e-6)
    assert cls5 == 3
    assert classify_score_label(s5) == "Tinggi"

    scores_all_1 = {k: 1 for k in DEFAULT_WEIGHTS}
    s1, cls1 = compute_weighted_overlay(scores_all_1, DEFAULT_WEIGHTS)
    assert math.isclose(s1, 1.00, rel_tol=1e-6)
    assert cls1 == 1
    assert classify_score_label(s1) == "Rendah"

    scores_all_3 = {k: 3 for k in DEFAULT_WEIGHTS}
    s3, cls3 = compute_weighted_overlay(scores_all_3, DEFAULT_WEIGHTS)
    assert math.isclose(s3, 3.00, rel_tol=1e-6)
    assert cls3 == 2
    assert classify_score_label(s3) == "Sedang"


# ---------------------------------------------------------------------------
# 2. Contoh manual: CH=4, Slope=5, Elev=5, LU=3, Riv=2 -> S = 4.00 (Tinggi)
# ---------------------------------------------------------------------------
def test_manual_calculation_example() -> None:
    """Test #2: S = 0.25*4 + 0.25*5 + 0.20*5 + 0.15*3 + 0.15*2 = 4.00 (Tinggi)."""
    manual_scores = {
        "curah_hujan": 4,
        "kemiringan_lereng": 5,
        "elevasi": 5,
        "penggunaan_lahan": 3,
        "jarak_sungai": 2,
    }
    s_val, cls_val = compute_weighted_overlay(manual_scores, DEFAULT_WEIGHTS)
    expected_s = 0.25 * 4 + 0.25 * 5 + 0.20 * 5 + 0.15 * 3 + 0.15 * 2
    assert math.isclose(expected_s, 4.00, rel_tol=1e-9)
    assert math.isclose(s_val, 4.00, rel_tol=1e-7)
    assert cls_val == 3
    assert classify_score_label(s_val) == "Tinggi"

    dom = get_dominant_factor_for_point(manual_scores, DEFAULT_WEIGHTS)
    assert dom["parameter_key"] == "kemiringan_lereng"
    assert math.isclose(dom["contribution"], 1.25, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 3. Batas kelas: S = 7/3 -> Sedang; S = 11/3 -> Tinggi; S = 5.00 -> Tinggi
# ---------------------------------------------------------------------------
def test_exact_class_boundaries() -> None:
    """Test #3: Exact thresholds 7/3 -> Sedang (2), 11/3 -> Tinggi (3), 5.00 -> Tinggi (3)."""
    assert classify_score(1.0) == 1
    assert classify_score(7.0 / 3.0 - 0.001) == 1

    # Exact 7/3 in both float64 and float32
    assert classify_score(7.0 / 3.0) == 2
    assert classify_score(float(np.float32(7.0 / 3.0))) == 2
    assert classify_score_label(7.0 / 3.0) == "Sedang"

    assert classify_score(11.0 / 3.0 - 0.001) == 2

    # Exact 11/3 in both float64 and float32
    assert classify_score(11.0 / 3.0) == 3
    assert classify_score(float(np.float32(11.0 / 3.0))) == 3
    assert classify_score_label(11.0 / 3.0) == "Tinggi"

    assert classify_score(5.00) == 3
    assert classify_score_label(5.00) == "Tinggi"

    # Array test
    arr_s = np.array([[1.0, 7.0 / 3.0, 11.0 / 3.0, 5.0]], dtype=np.float32)
    cls_arr = classify_score(arr_s)
    assert np.array_equal(cls_arr, np.array([[1, 2, 3, 3]], dtype=np.uint8))


# ---------------------------------------------------------------------------
# 4. Total bobot != 100% ditolak
# ---------------------------------------------------------------------------
def test_invalid_weights_rejected() -> None:
    """Test #4: Total weights not equal to 100% (1.0) must raise ValueError."""
    bad_weights_low = {
        "curah_hujan": 0.20,
        "kemiringan_lereng": 0.20,
        "elevasi": 0.20,
        "penggunaan_lahan": 0.15,
        "jarak_sungai": 0.15,
    }  # Sum = 0.90 (90%)
    with pytest.raises(ValueError, match="100%"):
        validate_weights(bad_weights_low)

    with pytest.raises(ValueError, match="100%"):
        compute_weighted_overlay(
            {k: 3 for k in DEFAULT_WEIGHTS}, weights=bad_weights_low
        )

    bad_weights_high = {
        "curah_hujan": 30.0,
        "kemiringan_lereng": 25.0,
        "elevasi": 20.0,
        "penggunaan_lahan": 15.0,
        "jarak_sungai": 15.0,
    }  # Sum = 105%
    with pytest.raises(ValueError, match="100%"):
        validate_weights(bad_weights_high)


# ---------------------------------------------------------------------------
# 5. Reklasifikasi di nilai batas (slope 8/15/25/40%, elevasi 10/20/35/50m, jarak 250/500/750/1000m)
# ---------------------------------------------------------------------------
def test_reclassification_at_exact_boundaries() -> None:
    """Test #5: Boundary rule [min, max) inclusive lower bound and exclusive upper bound."""
    # Slope boundaries: [0,8)->5, [8,15)->4, [15,25)->3, [25,40)->2, [40,inf)->1
    slope_vals = np.array([[0.0, 7.99, 8.0, 15.0, 25.0, 40.0, 55.0]])
    slope_scores = reclassify_continuous(
        slope_vals, DEFAULT_SCORING_RULES["kemiringan_lereng"]
    )
    assert slope_scores.tolist()[0] == [5, 5, 4, 3, 2, 1, 1]

    # Elevation boundaries: <10->5, [10,20)->4, [20,35)->3, [35,50)->2, >=50->1
    elev_vals = np.array([[5.0, 9.99, 10.0, 20.0, 35.0, 50.0, 75.0]])
    elev_scores = reclassify_continuous(
        elev_vals, DEFAULT_SCORING_RULES["elevasi"]
    )
    assert elev_scores.tolist()[0] == [5, 5, 4, 3, 2, 1, 1]

    # River distance boundaries: [0,250)->5, [250,500)->4, [500,750)->3, [750,1000)->2, >=1000->1
    dist_vals = np.array([[0.0, 249.9, 250.0, 500.0, 750.0, 1000.0, 1500.0]])
    dist_scores = reclassify_continuous(
        dist_vals, DEFAULT_SCORING_RULES["jarak_sungai"]
    )
    assert dist_scores.tolist()[0] == [5, 5, 4, 3, 2, 1, 1]

    # Rainfall boundaries: <2000->1, [2000,2500)->2, [2500,3000)->3, [3000,3500)->4, >=3500->5
    rain_vals = np.array([[1800.0, 2000.0, 2500.0, 3000.0, 3500.0, 4000.0]])
    rain_scores = reclassify_continuous(
        rain_vals, DEFAULT_SCORING_RULES["curah_hujan"]
    )
    assert rain_scores.tolist()[0] == [1, 2, 3, 4, 5, 5]


# ---------------------------------------------------------------------------
# 6. Slope: bidang miring 10% -> ~= 10%
# ---------------------------------------------------------------------------
def test_horn_slope_inclined_plane_10_percent() -> None:
    """Test #6: Inclined plane with 10% gradient yields ~10.0% slope via Horn 3x3."""
    rows, cols = 30, 40
    pixel_size = 30.0
    # z increases by 0.10 * 30m = 3.0m per column -> 10% slope in X direction
    col_idx = np.arange(cols, dtype=np.float64)
    dem_plane = np.tile(col_idx * (0.10 * pixel_size), (rows, 1)).astype(np.float32)

    slope_pct = compute_slope_horn(dem_plane, pixel_size=pixel_size)
    assert np.allclose(slope_pct, 10.0, atol=1e-3)


# ---------------------------------------------------------------------------
# 7. Jarak sungai: garis lurus dibandingkan dengan jarak analitik
# ---------------------------------------------------------------------------
def test_river_distance_straight_line_vs_analytic() -> None:
    """Test #7: Euclidean distance transform from a straight river matches analytical distance."""
    rows, cols = 50, 60
    pixel_size = 30.0
    river_mask = np.zeros((rows, cols), dtype=np.uint8)
    river_row = 20
    river_mask[river_row, :] = 1  # Straight horizontal river across row 20

    dist_raster = compute_river_distance_from_mask(river_mask, pixel_size=pixel_size)

    for r in range(rows):
        analytic_dist = abs(r - river_row) * pixel_size
        assert np.allclose(dist_raster[r, :], analytic_dist, atol=1e-4)


# ---------------------------------------------------------------------------
# 8. IDW: satu stasiun -> seluruh grid sama; di lokasi stasiun nilainya persis nilai stasiun
# ---------------------------------------------------------------------------
def test_idw_single_station_and_exact_at_station_locations() -> None:
    """Test #8: Single station gives uniform grid; multi-station gives exact values at station locations."""
    rows, cols = 20, 25
    pixel_size = 30.0
    transform = from_origin(765000.0, 55000.0, pixel_size, pixel_size)
    valid_mask = np.ones((rows, cols), dtype=bool)

    # Case A: Single station -> entire grid equals that station's rainfall
    single_xy = np.array([[765300.0, 54700.0]])
    single_val = np.array([2845.5])
    grid_single = interpolate_idw(
        single_xy, single_val, (rows, cols), transform, valid_mask=valid_mask, power=2.0
    )
    assert np.allclose(grid_single, 2845.5, atol=1e-4)

    # Case B: Multiple stations placed at exact cell centers -> value at each station cell is exact
    station_cells = [(3, 4, 2100.0), (10, 12, 2950.0), (16, 20, 3650.0)]
    coords_list = []
    vals_list = []
    for r, c, val in station_cells:
        cx = transform.c + (c + 0.5) * transform.a
        cy = transform.f + (r + 0.5) * transform.e
        coords_list.append([cx, cy])
        vals_list.append(val)

    grid_multi = interpolate_idw(
        np.array(coords_list),
        np.array(vals_list),
        (rows, cols),
        transform,
        valid_mask=valid_mask,
        power=2.0,
    )
    for r, c, val in station_cells:
        assert math.isclose(float(grid_multi[r, c]), val, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 9. Total luas tiga kelas = total luas kota (toleransi 1 piksel)
# ---------------------------------------------------------------------------
def test_total_class_area_equals_total_city_area(tmp_path: Path) -> None:
    """Test #9: Sum of pixels/areas across Rendah + Sedang + Tinggi equals total city area (<= 1 px tolerance)."""
    demo_info = generate_demo_dataset(
        output_dir=tmp_path / "demo_test",
        pixel_size=30.0,
        width_m=4500.0,
        height_m=4200.0,
    )
    paths = demo_info["paths"]

    grid = build_reference_grid(paths["kecamatan"], kecamatan_col="nama_kecamatan")
    dem_arr, _ = preprocess_dem(paths["dem"], grid)
    rivers_gdf, _ = preprocess_rivers(paths["sungai"], grid)
    landuse_gdf, lu_col, _ = preprocess_landuse(paths["penggunaan_lahan"], grid, "kelas_lahan")
    rain_df, _ = preprocess_rainfall_table(paths["curah_hujan"], grid)

    _, ch_score, _ = compute_rainfall_parameter(
        rain_df, grid.shape, grid.transform, grid.city_mask
    )
    _, slope_score = compute_slope_parameter(dem_arr, grid.city_mask, grid.pixel_size)
    _, elev_score = compute_elevation_parameter(dem_arr, grid.city_mask)
    lu_score, _ = compute_landuse_parameter(
        landuse_gdf, lu_col, grid.shape, grid.transform, grid.city_mask
    )
    _, riv_score = compute_river_distance_parameter(
        rivers_gdf, grid.shape, grid.transform, grid.city_mask, grid.pixel_size
    )

    score_rasters = {
        "curah_hujan": ch_score,
        "kemiringan_lereng": slope_score,
        "elevasi": elev_score,
        "penggunaan_lahan": lu_score,
        "jarak_sungai": riv_score,
    }

    s_raster, cls_raster = compute_weighted_overlay(
        score_rasters, DEFAULT_WEIGHTS, valid_mask=grid.city_mask
    )
    zonal = compute_zonal_statistics(
        s_raster,
        cls_raster,
        score_rasters,
        grid.kecamatan_gdf,
        grid.kecamatan_column,
        grid.transform,
        grid.city_mask,
    )

    city_sum = zonal["city_summary"]
    classes = city_sum["classes"]
    sum_class_pixels = (
        classes["Rendah"]["pixels"]
        + classes["Sedang"]["pixels"]
        + classes["Tinggi"]["pixels"]
    )
    assert abs(sum_class_pixels - city_sum["total_pixels"]) <= 1
    assert abs(sum_class_pixels - grid.valid_pixel_count) <= 1

    pixel_area_ha = (grid.pixel_size ** 2) / 10_000.0
    sum_class_ha = (
        classes["Rendah"]["luas_ha"]
        + classes["Sedang"]["luas_ha"]
        + classes["Tinggi"]["luas_ha"]
    )
    assert abs(sum_class_ha - city_sum["luas_total_ha"]) <= max(0.05, pixel_area_ha)


# ---------------------------------------------------------------------------
# 10. Confusion matrix kecil dengan hasil yang dihitung manual
# ---------------------------------------------------------------------------
def test_small_confusion_matrix_manual() -> None:
    """Test #10: Small 3x3 confusion matrix verified against manual hand calculation."""
    # 10 points total:
    # True Rendah (3): 2 predicted Rendah, 1 predicted Sedang
    # True Sedang (3): 3 predicted Sedang
    # True Tinggi (4): 1 predicted Sedang, 3 predicted Tinggi
    # Diagonal correct = 2 + 3 + 3 = 8 / 10 -> OA = 80.0% (Valid!)
    y_true = [
        "Rendah", "Rendah", "Rendah",
        "Sedang", "Sedang", "Sedang",
        "Tinggi", "Tinggi", "Tinggi", "Tinggi",
    ]
    y_pred = [
        "Rendah", "Rendah", "Sedang",
        "Sedang", "Sedang", "Sedang",
        "Sedang", "Tinggi", "Tinggi", "Tinggi",
    ]

    metrics = compute_confusion_matrix_metrics(y_true, y_pred)
    assert metrics["matrix"] == [
        [2, 1, 0],
        [0, 3, 0],
        [0, 1, 3],
    ]
    assert metrics["total_points"] == 10
    assert metrics["matching_points"] == 8
    assert math.isclose(metrics["overall_accuracy_pct"], 80.0, rel_tol=1e-6)
    assert metrics["is_valid"] is True

    # Producer's accuracy: Rendah = 2/3 (66.67%), Sedang = 3/3 (100%), Tinggi = 3/4 (75.0%)
    assert math.isclose(metrics["producer_accuracy_pct"]["Rendah"], 66.67, abs_tol=0.02)
    assert math.isclose(metrics["producer_accuracy_pct"]["Sedang"], 100.0, abs_tol=0.01)
    assert math.isclose(metrics["producer_accuracy_pct"]["Tinggi"], 75.0, abs_tol=0.01)

    # User's accuracy: Rendah = 2/2 (100%), Sedang = 3/5 (60.0%), Tinggi = 3/3 (100%)
    assert math.isclose(metrics["user_accuracy_pct"]["Rendah"], 100.0, abs_tol=0.01)
    assert math.isclose(metrics["user_accuracy_pct"]["Sedang"], 60.0, abs_tol=0.01)
    assert math.isclose(metrics["user_accuracy_pct"]["Tinggi"], 100.0, abs_tol=0.01)

    # Manual Cohen's Kappa:
    # p_o = 0.80
    # p_e = (3*2 + 3*5 + 4*3) / 100 = (6 + 15 + 12) / 100 = 0.33
    # kappa = (0.80 - 0.33) / (1 - 0.33) = 0.47 / 0.67 = 0.7014925
    assert math.isclose(metrics["kappa"], 0.47 / 0.67, abs_tol=1e-3)


def test_unmapped_landuse_class_raises_warning_error() -> None:
    """Verify that unmapped land-use classes are never silently scored."""
    _, unmapped = validate_and_map_landuse_classes(
        ["Hutan/Rawa", "Kelas_Misterius_Baru"]
    )
    assert "Kelas_Misterius_Baru" in unmapped

