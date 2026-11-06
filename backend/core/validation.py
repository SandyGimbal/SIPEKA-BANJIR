"""Model validation and sensitivity analysis module for SIPEKA-Banjir 3D.

Implements:
1. Bab III (Equation 3.5) Overall Accuracy:
   OA (%) = (sum(matching_points) / total_points) * 100%
   Valid criterion: OA >= 80.0%.
2. Mode A (Multi-class field validation with `kelas_lapangan` = Rendah/Sedang/Tinggi):
   - 3x3 Confusion Matrix
   - Overall Accuracy, Cohen's Kappa
   - Producer's Accuracy & User's Accuracy per class
3. Mode B (Historical flood occurrence points):
   - Matching criterion: point falls in Sedang (2) or Tinggi (3)
   - Also reports % falling in Tinggi (3) only + methodological note
   - When binary `label` (1=banjir, 0=tidak banjir) is present: Precision, Recall, F1, and AUC-ROC using continuous score S.
4. One-at-a-time (OAT) Sensitivity Analysis (±5 percentage points per parameter weight,
   with remaining weights adjusted proportionally to 100%).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from rasterio.transform import Affine
from sklearn.metrics import cohen_kappa_score, confusion_matrix, roc_auc_score, roc_curve

from backend.core.config import (
    CLASS_DEFINITIONS,
    DEFAULT_WEIGHTS,
    NODATA_FLOAT,
    PARAMETER_LABELS,
    TARGET_EPSG,
)
from backend.core.overlay import (
    PARAMETER_ORDER,
    classify_score,
    compute_weighted_overlay,
    normalize_weights,
)

CLASS_NAMES_ORDER = ["Rendah", "Sedang", "Tinggi"]
CLASS_NAME_TO_CODE = {"rendah": 1, "sedang": 2, "tinggi": 3, "1": 1, "2": 2, "3": 3}
CODE_TO_CLASS_NAME = {1: "Rendah", 2: "Sedang", 3: "Tinggi"}


def compute_confusion_matrix_metrics(
    y_true_classes: Sequence[Union[str, int]],
    y_pred_classes: Sequence[Union[str, int]],
) -> Dict[str, Any]:
    """Compute 3x3 confusion matrix, Overall Accuracy, Cohen's Kappa, Producer's & User's Accuracy.

    Args:
        y_true_classes: Sequence of ground-truth classes ('Rendah'/'Sedang'/'Tinggi' or 1/2/3).
        y_pred_classes: Sequence of model-predicted classes ('Rendah'/'Sedang'/'Tinggi' or 1/2/3).

    Returns:
        Dictionary with 3x3 matrix, overall_accuracy_pct, kappa, producer_accuracy, user_accuracy,
        matching_count, total_count, and is_valid (OA >= 80%).
    """
    if len(y_true_classes) == 0 or len(y_true_classes) != len(y_pred_classes):
        raise ValueError("Jumlah titik referensi dan prediksi harus sama dan tidak boleh kosong.")

    def _to_code(val: Union[str, int]) -> int:
        key = str(val).strip().lower()
        if key not in CLASS_NAME_TO_CODE:
            raise ValueError(f"Kelas kerawanan tidak dikenali: '{val}'. Gunakan Rendah, Sedang, atau Tinggi.")
        return CLASS_NAME_TO_CODE[key]

    y_true = np.array([_to_code(v) for v in y_true_classes], dtype=int)
    y_pred = np.array([_to_code(v) for v in y_pred_classes], dtype=int)

    labels = [1, 2, 3]
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    total = int(cm.sum())
    correct = int(np.trace(cm))
    oa_pct = (100.0 * correct / total) if total > 0 else 0.0

    # Cohen's Kappa (handle edge case where all points are in a single class)
    if len(np.unique(y_true)) == 1 and len(np.unique(y_pred)) == 1 and y_true[0] == y_pred[0]:
        kappa = 1.0
    else:
        try:
            kappa_val = float(cohen_kappa_score(y_true, y_pred, labels=labels))
            kappa = 0.0 if np.isnan(kappa_val) else kappa_val
        except Exception:
            kappa = 0.0

    producer_acc: Dict[str, float] = {}
    user_acc: Dict[str, float] = {}
    for idx, code in enumerate(labels):
        cls_name = CODE_TO_CLASS_NAME[code]
        row_sum = int(cm[idx, :].sum())  # Reference total for class
        col_sum = int(cm[:, idx].sum())  # Predicted total for class
        diag_val = int(cm[idx, idx])
        producer_acc[cls_name] = round((100.0 * diag_val / row_sum) if row_sum > 0 else 0.0, 2)
        user_acc[cls_name] = round((100.0 * diag_val / col_sum) if col_sum > 0 else 0.0, 2)

    return {
        "labels": CLASS_NAMES_ORDER,
        "matrix": cm.tolist(),  # rows = Lapangan (True), cols = Model (Predicted)
        "total_points": total,
        "matching_points": correct,
        "overall_accuracy_pct": round(oa_pct, 2),
        "is_valid": bool(oa_pct >= 80.0),
        "kappa": round(kappa, 4),
        "producer_accuracy_pct": producer_acc,
        "user_accuracy_pct": user_acc,
    }


def validate_with_points(
    points_source: Union[str, Path, pd.DataFrame],
    score_s_raster: np.ndarray,
    class_raster: np.ndarray,
    transform: Affine,
    valid_mask: np.ndarray,
    target_epsg: int = TARGET_EPSG,
) -> Dict[str, Any]:
    """Validate the flood vulnerability model against field/historical flood points.

    Supports both Mode A (when `kelas_lapangan` column is present) and Mode B
    (occurrence-only points, plus binary `label` metrics including AUC-ROC when `label` is present).

    Args:
        points_source: Path to CSV/XLSX or DataFrame with `lat, lon` (and optional `kelas_lapangan`, `label`).
        score_s_raster: 2D float32 array of composite score S.
        class_raster: 2D uint8 array of classes (1/2/3).
        transform: Reference grid Affine transform.
        valid_mask: Boolean mask of valid city pixels.
        target_epsg: Grid EPSG code (default 32647).

    Returns:
        Comprehensive validation report dictionary including point-level GeoJSON/table records.
    """
    if isinstance(points_source, (str, Path)):
        path = Path(points_source)
        if not path.exists():
            raise ValueError(f"File titik validasi tidak ditemukan: {path.name}")
        if path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
    else:
        df = points_source.copy()

    if df.empty:
        raise ValueError("Data titik banjir historis/validasi kosong.")

    col_map = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=col_map)

    if "lat" not in df.columns or "lon" not in df.columns:
        raise ValueError(
            "File validasi wajib memiliki kolom 'lat' dan 'lon'."
        )

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"]).copy()

    transformer = Transformer.from_crs("EPSG:4326", CRS.from_epsg(target_epsg), always_xy=True)
    rows_cnt, cols_cnt = class_raster.shape

    has_field_class = bool(
        "kelas_lapangan" in df.columns
        and df["kelas_lapangan"].dropna().astype(str).str.strip().ne("").any()
    )
    has_binary_label = bool(
        "label" in df.columns and df["label"].dropna().nunique() >= 2
    )

    warnings_list: List[str] = []
    point_records: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        lat_val = float(row["lat"])
        lon_val = float(row["lon"])
        if abs(lon_val) <= 180.0 and abs(lat_val) <= 90.0:
            x_utm, y_utm = transformer.transform(lon_val, lat_val)
        else:
            x_utm, y_utm = lon_val, lat_val

        col_px = int((x_utm - transform.c) / transform.a)
        row_px = int((y_utm - transform.f) / transform.e)
        if not (0 <= row_px < rows_cnt and 0 <= col_px < cols_cnt):
            continue
        if not bool(valid_mask[row_px, col_px]):
            continue

        s_val = float(score_s_raster[row_px, col_px])
        cls_code = int(class_raster[row_px, col_px])
        if cls_code not in (1, 2, 3) or s_val == NODATA_FLOAT:
            continue

        cls_model = CODE_TO_CLASS_NAME[cls_code]
        lokasi_str = str(row.get("lokasi", f"Titik #{len(point_records) + 1}"))
        kec_str = str(row.get("kecamatan", "-"))

        rec: Dict[str, Any] = {
            "id": len(point_records) + 1,
            "lokasi": lokasi_str,
            "kecamatan": kec_str,
            "lat": round(lat_val, 6),
            "lon": round(lon_val, 6),
            "x_utm": round(float(x_utm), 2),
            "y_utm": round(float(y_utm), 2),
            "score_s": round(s_val, 3),
            "kelas_model": cls_model,
            "kode_model": cls_code,
        }

        if has_field_class:
            raw_fc = str(row.get("kelas_lapangan", "")).strip()
            fc_code = CLASS_NAME_TO_CODE.get(raw_fc.lower(), cls_code)
            fc_name = CODE_TO_CLASS_NAME[fc_code]
            rec["kelas_lapangan"] = fc_name
            rec["kode_lapangan"] = fc_code
            rec["sesuai_mode_a"] = bool(fc_code == cls_code)
        else:
            rec["kelas_lapangan"] = None
            rec["kode_lapangan"] = None
            rec["sesuai_mode_a"] = None

        # Mode B matching: for flood occurrence points (label == 1 or no label column),
        # point matches if model predicts Sedang (2) or Tinggi (3).
        if has_binary_label:
            raw_lbl = row.get("label", 1)
            lbl_int = 1 if str(raw_lbl).strip().lower() in ("1", "true", "banjir", "ya", "1.0") else 0
            rec["label"] = lbl_int
            rec["sesuai_mode_b"] = bool(
                (lbl_int == 1 and cls_code in (2, 3))
                or (lbl_int == 0 and cls_code == 1)
            )
        else:
            rec["label"] = 1
            rec["sesuai_mode_b"] = bool(cls_code in (2, 3))

        rec["sesuai"] = (
            rec["sesuai_mode_a"] if has_field_class else rec["sesuai_mode_b"]
        )
        rec["warna_hex"] = "#22c55e" if rec["sesuai"] else "#ef4444"
        point_records.append(rec)

    if not point_records:
        raise ValueError(
            "Tidak ada titik validasi yang berada di dalam batas wilayah Kota Pekanbaru."
        )

    total_pts = len(point_records)
    if total_pts < 50:
        warnings_list.append(
            f"Jumlah titik validasi di dalam batas kota adalah {total_pts} titik "
            "(Bab III Persamaan 3.5 mensyaratkan minimal 50 titik sampel)."
        )

    # Mode A metrics (if kelas_lapangan available)
    mode_a_result: Optional[Dict[str, Any]] = None
    if has_field_class:
        y_true_a = [r["kode_lapangan"] for r in point_records]
        y_pred_a = [r["kode_model"] for r in point_records]
        mode_a_result = compute_confusion_matrix_metrics(y_true_a, y_pred_a)

    # Mode B metrics (always computed so user can inspect occurrence validation & ROC)
    flood_pts = [r for r in point_records if r["label"] == 1]
    n_flood = len(flood_pts)
    n_sedang_tinggi = sum(1 for r in flood_pts if r["kode_model"] in (2, 3))
    n_tinggi_only = sum(1 for r in flood_pts if r["kode_model"] == 3)

    pct_sedang_tinggi = (100.0 * n_sedang_tinggi / n_flood) if n_flood > 0 else 0.0
    pct_tinggi_only = (100.0 * n_tinggi_only / n_flood) if n_flood > 0 else 0.0

    mode_b_result: Dict[str, Any] = {
        "total_flood_points": n_flood,
        "matching_sedang_tinggi": n_sedang_tinggi,
        "matching_tinggi_only": n_tinggi_only,
        "accuracy_sedang_tinggi_pct": round(pct_sedang_tinggi, 2),
        "accuracy_tinggi_only_pct": round(pct_tinggi_only, 2),
        "is_valid": bool(pct_sedang_tinggi >= 80.0),
        "note": (
            "Catatan Metodologis Mode B: Validasi titik kejadian banjir menganggap titik sesuai "
            "apabila jatuh pada kelas Sedang atau Tinggi. Mode tanpa titik non-banjir tidak menguji "
            "spesifisitas kelas Rendah."
        ),
        "binary_metrics": None,
    }

    if has_binary_label:
        y_bin_true = np.array([int(r["label"]) for r in point_records], dtype=int)
        y_bin_pred = np.array(
            [1 if int(r["kode_model"]) in (2, 3) else 0 for r in point_records],
            dtype=int,
        )
        y_scores = np.array([float(r["score_s"]) for r in point_records], dtype=float)

        tp = int(np.sum((y_bin_true == 1) & (y_bin_pred == 1)))
        tn = int(np.sum((y_bin_true == 0) & (y_bin_pred == 0)))
        fp = int(np.sum((y_bin_true == 0) & (y_bin_pred == 1)))
        fn = int(np.sum((y_bin_true == 1) & (y_bin_pred == 0)))

        precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1 = (
            (2.0 * precision * recall / (precision + recall))
            if (precision + recall) > 0
            else 0.0
        )
        bin_acc = 100.0 * (tp + tn) / len(y_bin_true)

        try:
            auc_val = float(roc_auc_score(y_bin_true, y_scores))
            fpr, tpr, _ = roc_curve(y_bin_true, y_scores)
            roc_pts = [
                {"fpr": round(float(x), 4), "tpr": round(float(y), 4)}
                for x, y in zip(fpr, tpr)
            ]
        except Exception:
            auc_val = 0.0
            roc_pts = []

        mode_b_result["binary_metrics"] = {
            "tp": tp,
            "tn": tn,
            "fp": fp,
            "fn": fn,
            "binary_accuracy_pct": round(bin_acc, 2),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "auc_roc": round(auc_val, 4),
            "roc_curve": roc_pts,
        }

    primary_mode = "A" if has_field_class else "B"
    primary_accuracy = (
        mode_a_result["overall_accuracy_pct"]
        if mode_a_result is not None
        else mode_b_result["accuracy_sedang_tinggi_pct"]
    )
    primary_matching = (
        mode_a_result["matching_points"]
        if mode_a_result is not None
        else mode_b_result["matching_sedang_tinggi"]
    )

    return {
        "primary_mode": primary_mode,
        "has_field_class": has_field_class,
        "has_binary_label": has_binary_label,
        "total_points": total_pts,
        "matching_points": primary_matching,
        "overall_accuracy_pct": round(float(primary_accuracy), 2),
        "is_valid": bool(primary_accuracy >= 80.0),
        "threshold_valid_pct": 80.0,
        "warnings": warnings_list,
        "mode_a": mode_a_result,
        "mode_b": mode_b_result,
        "points": point_records,
    }


def adjust_weights_proportionally(
    base_weights: Dict[str, float],
    target_key: str,
    delta: float,
) -> Dict[str, float]:
    """Adjust `target_key` weight by `delta` (e.g. ±0.05) and scale remaining weights proportionally to sum to 1.0."""
    norm_w = normalize_weights(base_weights)
    old_val = norm_w[target_key]
    new_val = float(np.clip(old_val + delta, 0.0, 1.0))
    rem_budget = 1.0 - new_val
    other_keys = [k for k in PARAMETER_ORDER if k != target_key]
    other_sum = sum(norm_w[k] for k in other_keys)

    adjusted: Dict[str, float] = {}
    for k in PARAMETER_ORDER:
        if k == target_key:
            adjusted[k] = new_val
        elif other_sum > 0:
            adjusted[k] = norm_w[k] * (rem_budget / other_sum)
        else:
            adjusted[k] = rem_budget / len(other_keys)
    return adjusted


def run_sensitivity_analysis(
    score_rasters: Dict[str, np.ndarray],
    valid_mask: np.ndarray,
    base_weights: Optional[Dict[str, float]] = None,
    points_source: Optional[Union[str, Path, pd.DataFrame]] = None,
    transform: Optional[Affine] = None,
    delta_pct_points: float = 5.0,
) -> Dict[str, Any]:
    """Perform ±5 percentage-point One-At-a-Time (OAT) sensitivity analysis on all 5 parameters.

    For each parameter and each perturbation (-5% and +5%), adjusts the remaining 4 weights
    proportionally so the sum equals 100%, and reports:
    - Percentage of city area in class Tinggi (%) and its change (Δ%)
    - Validation Overall Accuracy (%) and its change (Δ%) if validation points are provided.
    """
    norm_base = normalize_weights(base_weights if base_weights is not None else DEFAULT_WEIGHTS)
    delta = float(delta_pct_points) / 100.0

    mask = np.asarray(valid_mask, dtype=bool)
    total_px = max(1, int(np.count_nonzero(mask)))

    base_s, base_cls = compute_weighted_overlay(
        score_rasters, weights=norm_base, valid_mask=mask
    )
    base_high_pct = 100.0 * float(np.count_nonzero(mask & (base_cls == 3))) / total_px

    base_acc_pct: Optional[float] = None
    if points_source is not None and transform is not None:
        try:
            base_val = validate_with_points(
                points_source, base_s, base_cls, transform, mask
            )
            base_acc_pct = float(base_val["overall_accuracy_pct"])
        except Exception:
            base_acc_pct = None

    scenarios: List[Dict[str, Any]] = []
    for param_key in PARAMETER_ORDER:
        for sign, label_dir in ((-1.0, f"-{int(delta_pct_points)}%"), (+1.0, f"+{int(delta_pct_points)}%")):
            perturbed_w = adjust_weights_proportionally(
                norm_base, param_key, sign * delta
            )
            s_pert, cls_pert = compute_weighted_overlay(
                score_rasters, weights=perturbed_w, valid_mask=mask
            )
            high_pct = 100.0 * float(np.count_nonzero(mask & (cls_pert == 3))) / total_px
            diff_high = high_pct - base_high_pct

            acc_pct: Optional[float] = None
            diff_acc: Optional[float] = None
            if points_source is not None and transform is not None and base_acc_pct is not None:
                try:
                    val_res = validate_with_points(
                        points_source, s_pert, cls_pert, transform, mask
                    )
                    acc_pct = float(val_res["overall_accuracy_pct"])
                    diff_acc = round(acc_pct - base_acc_pct, 2)
                except Exception:
                    pass

            scenarios.append(
                {
                    "parameter_key": param_key,
                    "parameter_label": PARAMETER_LABELS.get(param_key, param_key),
                    "perubahan": label_dir,
                    "bobot_awal_pct": round(norm_base[param_key] * 100.0, 2),
                    "bobot_baru_pct": round(perturbed_w[param_key] * 100.0, 2),
                    "weights_pct": {k: round(v * 100.0, 2) for k, v in perturbed_w.items()},
                    "luas_tinggi_pct": round(high_pct, 2),
                    "delta_luas_tinggi_pct": round(diff_high, 2),
                    "akurasi_pct": round(acc_pct, 2) if acc_pct is not None else None,
                    "delta_akurasi_pct": diff_acc,
                }
            )

    return {
        "delta_points": delta_pct_points,
        "base_luas_tinggi_pct": round(base_high_pct, 2),
        "base_akurasi_pct": round(base_acc_pct, 2) if base_acc_pct is not None else None,
        "scenarios": scenarios,
    }
