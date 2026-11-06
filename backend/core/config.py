"""Configuration, default weights, scoring tables, and constants for SIPEKA-Banjir 3D.

Judul Skripsi:
    Analisis Kerawanan Banjir Menggunakan Metode Overlay Berbasis Sistem Informasi
    Geografis di Kota Pekanbaru.

Metode:
    Multi-Criteria Evaluation (MCE) dengan Weighted Overlay pada raster 30m x 30m.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Metadata & Paths
# ---------------------------------------------------------------------------
APP_NAME: str = "SIPEKA-Banjir 3D"
APP_VERSION: str = "1.0.0"
THESIS_TITLE: str = (
    "Analisis Kerawanan Banjir Menggunakan Metode Overlay Berbasis Sistem "
    "Informasi Geografis di Kota Pekanbaru"
)
METHOD_NAME: str = "Multi-Criteria Evaluation (MCE) dengan Weighted Overlay"

BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
SAMPLE_DATA_DIR: Path = BASE_DIR / "sample_data"
WORKSPACE_DIR: Path = BASE_DIR / "workspace_data"

# ---------------------------------------------------------------------------
# Coordinate Reference System & Grid Reference
# ---------------------------------------------------------------------------
# Catatan: Proposal menyebut UTM Zona 48N, tetapi Kota Pekanbaru (101°14'–101°34' BT)
# secara geografis berada pada rentang 96°–102° BT yaitu WGS 84 / UTM Zone 47N (EPSG:32647).
TARGET_EPSG: int = 32647
TARGET_CRS_STR: str = f"EPSG:{TARGET_EPSG}"
CRS_EXPLANATION: str = (
    "WGS 84 / UTM Zone 47N (EPSG:32647). Catatan: Dokumen proposal menyebut "
    "UTM Zona 48N, namun secara geografis Kota Pekanbaru (101°14'–101°34' BT) "
    "terletak di Zona 47N (96°–102° BT). Sistem menggunakan EPSG:32647 agar "
    "perhitungan jarak (meter) dan luas (hektar) memiliki distorsi minimal."
)

PIXEL_SIZE: float = 30.0  # Resolusi grid acuan 30 m x 30 m
PIXEL_AREA_M2: float = PIXEL_SIZE * PIXEL_SIZE  # 900 m²
PIXEL_AREA_HA: float = PIXEL_AREA_M2 / 10_000.0  # 0.09 ha

NODATA_FLOAT: float = -9999.0
NODATA_UINT8: int = 0

# ---------------------------------------------------------------------------
# Wilayah Administrasi (15 Kecamatan Kota Pekanbaru)
# ---------------------------------------------------------------------------
KECAMATAN_LIST: List[str] = [
    "Bukit Raya",
    "Lima Puluh",
    "Marpoyan Damai",
    "Payung Sekaki",
    "Pekanbaru Kota",
    "Rumbai",
    "Rumbai Barat",
    "Rumbai Timur",
    "Sail",
    "Senapelan",
    "Sukajadi",
    "Tuah Madani",
    "Bina Widya",
    "Tenayan Raya",
    "Kulim",
]

DEFAULT_RIVERS: List[str] = [
    "Siak",
    "Sail",
    "Air Hitam",
    "Senapelan",
    "Sago",
    "Sibam",
    "Tenayan",
    "Umban Sari",
]

# ---------------------------------------------------------------------------
# Bobot Parameter Default (Total = 1.00 atau 100%)
# S = 0,25·CH + 0,25·Slope + 0,20·Elev + 0,15·LU + 0,15·Riv
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS: Dict[str, float] = {
    "curah_hujan": 0.25,
    "kemiringan_lereng": 0.25,
    "elevasi": 0.20,
    "penggunaan_lahan": 0.15,
    "jarak_sungai": 0.15,
}

PARAMETER_LABELS: Dict[str, str] = {
    "curah_hujan": "Curah Hujan (CH)",
    "kemiringan_lereng": "Kemiringan Lereng (Slope)",
    "elevasi": "Elevasi / Ketinggian (Elev)",
    "penggunaan_lahan": "Penggunaan Lahan (LU)",
    "jarak_sungai": "Jarak terhadap Sungai (Riv)",
}

# ---------------------------------------------------------------------------
# Tabel Skor Parameter Default
# Aturan batas kelas: batas bawah inklusif (min <= x), batas atas eksklusif (x < max)
# kecuali kelas teratas (max = None / inf).
# Skor 5 = Sangat Rawan (Paling Rawan), Skor 1 = Sangat Aman (Paling Aman)
# ---------------------------------------------------------------------------
DEFAULT_SCORING_RULES: Dict[str, List[Dict[str, Any]]] = {
    # A. Curah Hujan (mm/tahun) - IDW power 2
    "curah_hujan": [
        {"min": None, "max": 2000.0, "score": 1, "label": "< 2.000 mm/tahun (Sangat Rendah)"},
        {"min": 2000.0, "max": 2500.0, "score": 2, "label": "2.000 – 2.500 mm/tahun (Rendah)"},
        {"min": 2500.0, "max": 3000.0, "score": 3, "label": "2.500 – 3.000 mm/tahun (Sedang)"},
        {"min": 3000.0, "max": 3500.0, "score": 4, "label": "3.000 – 3.500 mm/tahun (Tinggi)"},
        {"min": 3500.0, "max": None, "score": 5, "label": ">= 3.500 mm/tahun (Sangat Tinggi)"},
    ],
    # B. Kemiringan Lereng (%) - Van Zuidam (1985) / Permenhut P.32/2009
    "kemiringan_lereng": [
        {"min": None, "max": 8.0, "score": 5, "label": "0 – 8% (Datar)"},
        {"min": 8.0, "max": 15.0, "score": 4, "label": "8 – 15% (Landai)"},
        {"min": 15.0, "max": 25.0, "score": 3, "label": "15 – 25% (Agak Curam)"},
        {"min": 25.0, "max": 40.0, "score": 2, "label": "25 – 40% (Curam)"},
        {"min": 40.0, "max": None, "score": 1, "label": ">= 40% (Sangat Curam)"},
    ],
    # C. Elevasi (mdpl)
    "elevasi": [
        {"min": None, "max": 10.0, "score": 5, "label": "< 10 mdpl (Sangat Rendah)"},
        {"min": 10.0, "max": 20.0, "score": 4, "label": "10 – 20 mdpl (Rendah)"},
        {"min": 20.0, "max": 35.0, "score": 3, "label": "20 – 35 mdpl (Sedang)"},
        {"min": 35.0, "max": 50.0, "score": 2, "label": "35 – 50 mdpl (Tinggi)"},
        {"min": 50.0, "max": None, "score": 1, "label": ">= 50 mdpl (Sangat Tinggi)"},
    ],
    # E. Jarak terhadap Sungai (meter) - Euclidean Distance
    "jarak_sungai": [
        {"min": None, "max": 250.0, "score": 5, "label": "0 – 250 m (Sangat Dekat)"},
        {"min": 250.0, "max": 500.0, "score": 4, "label": "250 – 500 m (Dekat)"},
        {"min": 500.0, "max": 750.0, "score": 3, "label": "500 – 750 m (Sedang)"},
        {"min": 750.0, "max": 1000.0, "score": 2, "label": "750 – 1.000 m (Jauh)"},
        {"min": 1000.0, "max": None, "score": 1, "label": ">= 1.000 m (Sangat Jauh)"},
    ],
}

# D. Penggunaan Lahan (pemetaan kelas -> skor 1..5)
DEFAULT_LANDUSE_SCORES: Dict[str, int] = {
    "Hutan/Rawa": 1,
    "Hutan": 1,
    "Rawa": 1,
    "Badan Air": 1,
    "Perkebunan/Semak": 2,
    "Perkebunan": 2,
    "Semak Belukar": 2,
    "Lahan Terbuka/Tegalan": 3,
    "Lahan Terbuka": 3,
    "Tegalan/Ladang": 3,
    "Pertanian Lahan Kering": 3,
    "Permukiman Jarang/Industri": 4,
    "Permukiman Jarang": 4,
    "Industri": 4,
    "Permukiman Padat/Lahan Terbangun Komersial": 5,
    "Permukiman Padat": 5,
    "Lahan Terbangun Komersial": 5,
    "Kawasan Perdagangan dan Jasa": 5,
}

LANDUSE_CLASS_DESCRIPTIONS: List[Dict[str, Any]] = [
    {"score": 1, "category": "Hutan / Rawa", "runoff_coeff": "C < 0,20", "vulnerability": "Sangat Rendah"},
    {"score": 2, "category": "Perkebunan / Semak", "runoff_coeff": "C 0,20 – 0,35", "vulnerability": "Rendah"},
    {"score": 3, "category": "Lahan Terbuka / Tegalan", "runoff_coeff": "C 0,35 – 0,50", "vulnerability": "Sedang"},
    {"score": 4, "category": "Permukiman Jarang / Industri", "runoff_coeff": "C 0,50 – 0,70", "vulnerability": "Tinggi"},
    {"score": 5, "category": "Permukiman Padat / Lahan Terbangun Komersial", "runoff_coeff": "C 0,70 – 0,90", "vulnerability": "Sangat Tinggi"},
]

# ---------------------------------------------------------------------------
# Klasifikasi Equal Interval (Weighted Overlay)
# I = (5 - 1) / 3 = 4 / 3 = 1,333333...
# Ambang eksak: 7/3 (2,333333...) dan 11/3 (3,666666...)
# ---------------------------------------------------------------------------
INTERVAL_WIDTH: float = 4.0 / 3.0
THRESHOLD_LOW_MED: float = 7.0 / 3.0   # 2.3333333333333335
THRESHOLD_MED_HIGH: float = 11.0 / 3.0  # 3.6666666666666665

CLASS_DEFINITIONS: Dict[int, Dict[str, Any]] = {
    1: {
        "code": 1,
        "name": "Rendah",
        "range_str": "1,00 ≤ S < 2,33",
        "min": 1.0,
        "max": THRESHOLD_LOW_MED,
        "color_hex": "#22c55e",
        "color_rgb": (34, 197, 94),
    },
    2: {
        "code": 2,
        "name": "Sedang",
        "range_str": "2,33 ≤ S < 3,67",
        "min": THRESHOLD_LOW_MED,
        "max": THRESHOLD_MED_HIGH,
        "color_hex": "#eab308",
        "color_rgb": (234, 179, 8),
    },
    3: {
        "code": 3,
        "name": "Tinggi",
        "range_str": "3,67 ≤ S ≤ 5,00",
        "min": THRESHOLD_MED_HIGH,
        "max": 5.0,
        "color_hex": "#ef4444",
        "color_rgb": (239, 68, 68),
    },
}

# ---------------------------------------------------------------------------
# Daftar Asumsi Metodologis (ditampilkan di UI Langkah 2 & README)
# ---------------------------------------------------------------------------
ASSUMPTIONS: List[str] = [
    "Interval kelas curah hujan tengah (2.500, 3.000, 3.500 mm/tahun) diasumsikan berinterval 500 mm karena proposal hanya mencantumkan batas ekstrem kelas 1 (< 2.000 mm) dan kelas 5 (> 3.500 mm).",
    "Aturan batas kelas menggunakan batas bawah inklusif dan batas atas eksklusif [min, max), kecuali pada kelas teratas.",
    "Interpolasi spasial curah hujan menggunakan metode Inverse Distance Weighting (IDW) dengan pangkat (power) = 2.",
    "Validasi Mode B (hanya titik kejadian banjir historis tanpa kelas lapangan) menganggap titik terprediksi sesuai apabila jatuh pada kelas Sedang atau Tinggi, disertai pelaporan persentase yang jatuh di kelas Tinggi saja.",
    "Kelas tutupan/penggunaan lahan yang belum ada dalam kamus pemetaan wajib ditentukan skornya (1–5) oleh pengguna dan tidak diberi skor secara diam-diam.",
    "Simulasi kenaikan muka air 3D merupakan model genangan berbasis elevasi relatif (bathtub/planar relative model), bukan pemodelan hidrodinamika 1D/2D (seperti HEC-RAS).",
]


def get_default_config() -> Dict[str, Any]:
    """Return a deep copy of the default configuration dictionary for UI/API consumption."""
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "thesis_title": THESIS_TITLE,
        "method_name": METHOD_NAME,
        "target_epsg": TARGET_EPSG,
        "crs_explanation": CRS_EXPLANATION,
        "pixel_size": PIXEL_SIZE,
        "kecamatan_list": list(KECAMATAN_LIST),
        "default_rivers": list(DEFAULT_RIVERS),
        "weights": copy.deepcopy(DEFAULT_WEIGHTS),
        "parameter_labels": copy.deepcopy(PARAMETER_LABELS),
        "scoring_rules": copy.deepcopy(DEFAULT_SCORING_RULES),
        "landuse_scores": copy.deepcopy(DEFAULT_LANDUSE_SCORES),
        "landuse_class_descriptions": copy.deepcopy(LANDUSE_CLASS_DESCRIPTIONS),
        "thresholds": {
            "low_med": THRESHOLD_LOW_MED,
            "med_high": THRESHOLD_MED_HIGH,
            "interval": INTERVAL_WIDTH,
        },
        "classes": copy.deepcopy(CLASS_DEFINITIONS),
        "assumptions": list(ASSUMPTIONS),
    }


def validate_weights(weights: Dict[str, float], tolerance: float = 1e-4) -> float:
    """Validate that all 5 parameter weights exist, are non-negative, and sum to 1.0 (100%).

    Args:
        weights: Dictionary mapping parameter keys to float weights (either 0..1 or 0..100).
        tolerance: Allowed floating-point tolerance around 1.0.

    Returns:
        Normalized sum of weights (around 1.0).

    Raises:
        ValueError: If keys are missing, weights are negative, or total is not 100%.
    """
    required_keys = set(DEFAULT_WEIGHTS.keys())
    provided_keys = set(weights.keys())
    if required_keys != provided_keys:
        missing = required_keys - provided_keys
        extra = provided_keys - required_keys
        raise ValueError(
            f"Parameter bobot tidak sesuai. Kurang: {missing}, Tambahan: {extra}."
        )

    values = [float(weights[k]) for k in DEFAULT_WEIGHTS.keys()]
    if any(v < 0 for v in values):
        raise ValueError("Bobot parameter tidak boleh bernilai negatif.")

    total = sum(values)
    # Support weights passed as percentages (e.g. 25, 25, 20, 15, 15 -> sum = 100)
    if abs(total - 100.0) <= tolerance * 100.0:
        total = total / 100.0

    if abs(total - 1.0) > tolerance:
        diff_pct = (total - 1.0) * 100.0
        raise ValueError(
            f"Total bobot harus tepat 100% (1.00). Saat ini: {total * 100:.2f}% "
            f"(selisih {diff_pct:+.2f}%)."
        )
    return total

