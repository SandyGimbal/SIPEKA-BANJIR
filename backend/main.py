"""FastAPI application and REST API endpoints for SIPEKA-Banjir 3D."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel, Field
from pyproj import Transformer
from rasterio.features import rasterize

from backend.core.config import (
    APP_NAME,
    APP_VERSION,
    BASE_DIR,
    CLASS_DEFINITIONS,
    DEFAULT_LANDUSE_SCORES,
    DEFAULT_SCORING_RULES,
    DEFAULT_WEIGHTS,
    NODATA_FLOAT,
    PARAMETER_LABELS,
    PIXEL_SIZE,
    TARGET_EPSG,
    WORKSPACE_DIR,
    get_default_config,
)
from backend.core.demo import DEMO_DISCLAIMER, generate_demo_dataset
from backend.core.export import (
    build_threejs_mesh_payload,
    export_all_geotiffs,
    export_cartographic_map,
    export_excel_report,
    export_metadata_json,
    export_vector_polygons,
    render_maplibre_layer_overlays,
)
from backend.core.overlay import (
    PARAMETER_ORDER,
    classify_score_label,
    compute_weighted_overlay,
    get_dominant_factor_for_point,
    normalize_weights,
)
from backend.core.parameters import (
    compute_elevation_parameter,
    compute_landuse_parameter,
    compute_rainfall_parameter,
    compute_river_distance_parameter,
    compute_slope_parameter,
    validate_and_map_landuse_classes,
)
from backend.core.preprocess import (
    ReferenceGrid,
    build_reference_grid,
    preprocess_dem,
    preprocess_landuse,
    preprocess_rainfall_table,
    preprocess_rivers,
    read_vector_file,
)
from backend.core.validation import run_sensitivity_analysis, validate_with_points
from backend.core.zonal import compute_zonal_statistics

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "API Sistem Pemetaan Kerawanan Banjir Kota Pekanbaru 3D "
        "(Multi-Criteria Evaluation & Weighted Overlay)"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ComputeRequest(BaseModel):
    """Payload for triggering or recalculating the MCE Weighted Overlay analysis."""

    weights: Dict[str, float] = Field(default_factory=lambda: copy.deepcopy(DEFAULT_WEIGHTS))
    scoring_rules: Optional[Dict[str, List[Dict[str, Any]]]] = None
    landuse_scores: Optional[Dict[str, int]] = None
    kecamatan_col: Optional[str] = None
    landuse_col: Optional[str] = None
    river_col: Optional[str] = None
    selected_rivers: Optional[List[str]] = None
    recalculate_only: bool = False


class InspectColumnRequest(BaseModel):
    """Payload for inspecting unique values of a selected vector attribute column."""

    input_type: str
    column_name: str


class SessionState:
    """Holds active workspace paths, preprocessed grids, cached rasters, and calibration history."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.is_demo: bool = False
        self.disclaimer: Optional[str] = None
        self.upload_dir: Path = WORKSPACE_DIR / "uploads"
        self.export_dir: Path = WORKSPACE_DIR / "exports"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

        self.paths: Dict[str, Any] = {
            "dem": [],
            "kecamatan": None,
            "sungai": None,
            "curah_hujan": None,
            "penggunaan_lahan": None,
            "titik_banjir": None,
        }
        self.columns: Dict[str, Optional[str]] = {
            "kecamatan_col": None,
            "landuse_col": None,
            "river_col": None,
        }
        self.layer_meta: Dict[str, Any] = {}
        self.warnings: List[str] = []

        # Cached spatial objects
        self.param_cache_key: Optional[str] = None
        self.grid: Optional[ReferenceGrid] = None
        self.dem_raster: Optional[np.ndarray] = None
        self.slope_raster: Optional[np.ndarray] = None
        self.rain_raster: Optional[np.ndarray] = None
        self.dist_river_raster: Optional[np.ndarray] = None
        self.landuse_class_grid: Optional[np.ndarray] = None
        self.landuse_id_to_name: Dict[int, str] = {}
        self.rivers_gdf: Any = None
        self.landuse_gdf: Any = None
        self.rain_df: Any = None

        # Cached score rasters & results
        self.score_rasters: Dict[str, np.ndarray] = {}
        self.score_s_raster: Optional[np.ndarray] = None
        self.class_raster: Optional[np.ndarray] = None
        self.weights_used: Dict[str, float] = copy.deepcopy(DEFAULT_WEIGHTS)
        self.scoring_rules_used: Dict[str, Any] = copy.deepcopy(DEFAULT_SCORING_RULES)
        self.landuse_scores_used: Dict[str, int] = copy.deepcopy(DEFAULT_LANDUSE_SCORES)

        self.zonal_result: Optional[Dict[str, Any]] = None
        self.validation_result: Optional[Dict[str, Any]] = None
        self.sensitivity_result: Optional[Dict[str, Any]] = None
        self.maplibre_overlays: Optional[Dict[str, Any]] = None
        self.geojson_layers: Dict[str, Any] = {}
        self.threejs_mesh: Optional[Dict[str, Any]] = None
        self.calibration_history: List[Dict[str, Any]] = []
        self.last_timing_ms: Dict[str, float] = {}


STATE = SessionState()


def _inspect_vector_metadata(
    file_path: Path, preferred_cols: List[str]
) -> Dict[str, Any]:
    """Read vector file, validate CRS/geometries, and return column names + sample unique values."""
    gdf, warn_list = read_vector_file(file_path)
    non_geom_cols = [c for c in gdf.columns if c != gdf.geometry.name]
    selected_col = next((c for c in preferred_cols if c in non_geom_cols), non_geom_cols[0] if non_geom_cols else None)
    unique_vals: List[str] = []
    if selected_col:
        unique_vals = sorted(
            gdf[selected_col].dropna().astype(str).str.strip().unique().tolist()
        )
    return {
        "feature_count": len(gdf),
        "crs": str(gdf.crs),
        "columns": non_geom_cols,
        "selected_column": selected_col,
        "unique_values": unique_vals,
        "warnings": warn_list,
    }


@app.get("/api/network-info")
def api_get_network_info() -> Dict[str, Any]:
    """Return local LAN/Wi-Fi IPv4 addresses so the user can open the app on their mobile phone."""
    import socket

    ips: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127."):
            ips.append(primary_ip)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for addr in socket.gethostbyname_ex(hostname)[2]:
            if not addr.startswith("127.") and addr not in ips:
                ips.append(addr)
    except Exception:
        pass

    if not ips:
        ips.append("127.0.0.1")

    urls = [f"http://{ip}:8000" for ip in ips]
    return {
        "primary_ip": ips[0],
        "primary_url": urls[0],
        "all_urls": urls,
        "port": 8000,
    }


@app.get("/api/config")
def api_get_config() -> Dict[str, Any]:
    """Return default parameters, weights, scoring rules, assumptions, and current session status."""
    cfg = get_default_config()
    cfg["session"] = {
        "is_demo": STATE.is_demo,
        "disclaimer": STATE.disclaimer,
        "uploaded": {
            k: bool(v) for k, v in STATE.paths.items()
        },
        "columns": STATE.columns,
        "layer_meta": STATE.layer_meta,
        "has_results": STATE.score_s_raster is not None,
    }
    return cfg


@app.post("/api/demo")
def api_load_demo() -> Dict[str, Any]:
    """Generate synthetic Pekanbaru dataset and load it into the active session."""
    STATE.reset()
    demo_info = generate_demo_dataset()
    STATE.is_demo = True
    STATE.disclaimer = DEMO_DISCLAIMER

    p = demo_info["paths"]
    STATE.paths["dem"] = [p["dem"]]
    STATE.paths["kecamatan"] = p["kecamatan"]
    STATE.paths["sungai"] = p["sungai"]
    STATE.paths["curah_hujan"] = p["curah_hujan"]
    STATE.paths["penggunaan_lahan"] = p["penggunaan_lahan"]
    STATE.paths["titik_banjir"] = p["titik_banjir"]

    STATE.columns["kecamatan_col"] = "nama_kecamatan"
    STATE.columns["landuse_col"] = "kelas_lahan"
    STATE.columns["river_col"] = "nama_sungai"

    STATE.layer_meta = {
        "dem": {"files": ["demnas_pekanbaru_demo.tif"], "shape": demo_info["summary"]["grid_shape"], "status": "ok"},
        "kecamatan": _inspect_vector_metadata(Path(p["kecamatan"]), ["nama_kecamatan"]),
        "sungai": _inspect_vector_metadata(Path(p["sungai"]), ["nama_sungai"]),
        "penggunaan_lahan": _inspect_vector_metadata(Path(p["penggunaan_lahan"]), ["kelas_lahan"]),
        "curah_hujan": {
            "stations": demo_info["summary"]["rainfall_stations"],
            "years": demo_info["summary"]["rainfall_years"],
            "status": "ok",
        },
        "titik_banjir": {
            "points_count": demo_info["summary"]["validation_points"],
            "status": "ok",
        },
    }

    return {
        "status": "ok",
        "is_demo": True,
        "disclaimer": DEMO_DISCLAIMER,
        "summary": demo_info["summary"],
        "columns": STATE.columns,
        "layer_meta": STATE.layer_meta,
    }


@app.post("/api/upload/{input_type}")
async def api_upload_input(
    input_type: str,
    files: List[UploadFile] = File(...),
) -> Dict[str, Any]:
    """Upload and validate one of the 6 spatial/tabular inputs."""
    valid_types = {
        "dem",
        "kecamatan",
        "sungai",
        "curah_hujan",
        "penggunaan_lahan",
        "titik_banjir",
    }
    if input_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Tipe input tidak dikenal: {input_type}")

    if not files:
        raise HTTPException(status_code=400, detail="Tidak ada file yang diunggah.")

    target_subdir = STATE.upload_dir / input_type
    if target_subdir.exists():
        shutil.rmtree(target_subdir)
    target_subdir.mkdir(parents=True, exist_ok=True)

    saved_paths: List[Path] = []
    for uf in files:
        fname = Path(uf.filename or f"{input_type}_file").name
        dest = target_subdir / fname
        content = await uf.read()
        dest.write_bytes(content)
        saved_paths.append(dest)

    # Clear demo flag when user uploads real files
    STATE.is_demo = False
    STATE.disclaimer = None
    STATE.param_cache_key = None

    try:
        if input_type == "dem":
            import rasterio

            shapes_list = []
            for sp in saved_paths:
                with rasterio.open(sp) as ds:
                    if ds.crs is None:
                        raise ValueError(f"File DEM '{sp.name}' tidak memiliki CRS/proyeksi.")
                    shapes_list.append([ds.height, ds.width])
            STATE.paths["dem"] = [str(sp) for sp in saved_paths]
            meta = {
                "files": [sp.name for sp in saved_paths],
                "tile_count": len(saved_paths),
                "shape": shapes_list[0],
                "warnings": (
                    [f"{len(saved_paths)} lembar DEMNAS akan di-mosaic otomatis."]
                    if len(saved_paths) > 1
                    else []
                ),
            }
            STATE.layer_meta["dem"] = meta
            return {"status": "ok", "input_type": input_type, "meta": meta}

        if input_type == "kecamatan":
            meta = _inspect_vector_metadata(
                saved_paths[0],
                ["nama_kecamatan", "NAMOBJ", "WADMKC", "KECAMATAN", "kecamatan", "NAME"],
            )
            STATE.paths["kecamatan"] = str(saved_paths[0])
            STATE.columns["kecamatan_col"] = meta["selected_column"]
            STATE.layer_meta["kecamatan"] = meta
            return {"status": "ok", "input_type": input_type, "meta": meta}

        if input_type == "sungai":
            meta = _inspect_vector_metadata(
                saved_paths[0],
                ["nama_sungai", "NAMOBJ", "REMARK", "NAMA", "sungai", "NAME"],
            )
            STATE.paths["sungai"] = str(saved_paths[0])
            STATE.columns["river_col"] = meta["selected_column"]
            STATE.layer_meta["sungai"] = meta
            return {"status": "ok", "input_type": input_type, "meta": meta}

        if input_type == "penggunaan_lahan":
            meta = _inspect_vector_metadata(
                saved_paths[0],
                ["kelas_lahan", "REMARK", "PENUTUP_LA", "TUTUPAN", "KELAS", "landuse"],
            )
            STATE.paths["penggunaan_lahan"] = str(saved_paths[0])
            STATE.columns["landuse_col"] = meta["selected_column"]
            STATE.layer_meta["penggunaan_lahan"] = meta
            return {"status": "ok", "input_type": input_type, "meta": meta}

        if input_type == "curah_hujan":
            import pandas as pd

            sp = saved_paths[0]
            df = pd.read_excel(sp) if sp.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(sp)
            cols_lower = {str(c).strip().lower() for c in df.columns}
            req = {"stasiun", "lat", "lon", "hujan_mm"}
            if not req.issubset(cols_lower):
                raise ValueError(
                    f"Kolom wajib curah hujan belum lengkap ({sorted(req - cols_lower)}). "
                    "Wajib ada: stasiun, lat, lon, tahun (atau tanggal), hujan_mm."
                )
            df.columns = [str(c).strip().lower() for c in df.columns]
            n_st = int(df["stasiun"].nunique())
            n_yr = int(df["tahun"].nunique()) if "tahun" in df.columns else 1
            warn_rain = []
            if n_st < 3:
                warn_rain.append(f"Jumlah stasiun hujan hanya {n_st} (< 3 stasiun).")
            if n_yr < 10:
                warn_rain.append(f"Data curah hujan tercatat {n_yr} tahun (< 10 tahun).")
            STATE.paths["curah_hujan"] = str(sp)
            meta = {
                "file": sp.name,
                "stations": n_st,
                "years": n_yr,
                "rows": len(df),
                "warnings": warn_rain,
            }
            STATE.layer_meta["curah_hujan"] = meta
            return {"status": "ok", "input_type": input_type, "meta": meta}

        if input_type == "titik_banjir":
            import pandas as pd

            sp = saved_paths[0]
            df = pd.read_excel(sp) if sp.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(sp)
            cols_lower = {str(c).strip().lower() for c in df.columns}
            if not {"lat", "lon"}.issubset(cols_lower):
                raise ValueError("File titik banjir historis wajib memiliki kolom 'lat' dan 'lon'.")
            STATE.paths["titik_banjir"] = str(sp)
            warn_val = []
            if len(df) < 50:
                warn_val.append(
                    f"Jumlah titik ({len(df)}) kurang dari 50 titik standar Bab III Persamaan 3.5."
                )
            meta = {
                "file": sp.name,
                "points_count": len(df),
                "has_kelas_lapangan": "kelas_lapangan" in cols_lower,
                "has_label": "label" in cols_lower,
                "warnings": warn_val,
            }
            STATE.layer_meta["titik_banjir"] = meta
            return {"status": "ok", "input_type": input_type, "meta": meta}

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Gagal memvalidasi file '{input_type}': {exc}"
        ) from exc

    raise HTTPException(status_code=400, detail="Tipe input tidak didukung.")


@app.post("/api/inspect-column")
def api_inspect_column(req: InspectColumnRequest) -> Dict[str, Any]:
    """Return unique values when the user changes a vector attribute column in Step 1/2."""
    path_val = STATE.paths.get(req.input_type)
    if not path_val:
        raise HTTPException(status_code=400, detail=f"Layer '{req.input_type}' belum diunggah.")

    gdf, _ = read_vector_file(Path(path_val))
    if req.column_name not in gdf.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Kolom '{req.column_name}' tidak ditemukan pada layer '{req.input_type}'.",
        )

    unique_vals = sorted(
        gdf[req.column_name].dropna().astype(str).str.strip().unique().tolist()
    )
    if req.input_type == "kecamatan":
        STATE.columns["kecamatan_col"] = req.column_name
    elif req.input_type == "sungai":
        STATE.columns["river_col"] = req.column_name
    elif req.input_type == "penggunaan_lahan":
        STATE.columns["landuse_col"] = req.column_name

    STATE.param_cache_key = None
    return {
        "status": "ok",
        "input_type": req.input_type,
        "column_name": req.column_name,
        "unique_values": unique_vals,
    }


def _build_param_cache_signature(
    scoring_rules: Dict[str, Any],
    landuse_scores: Dict[str, int],
    kec_col: Optional[str],
    lu_col: Optional[str],
    riv_col: Optional[str],
    selected_rivers: Optional[List[str]],
) -> str:
    """Create a deterministic hash of everything that affects the 5 parameter score rasters."""
    payload = {
        "paths": STATE.paths,
        "scoring_rules": scoring_rules,
        "landuse_scores": landuse_scores,
        "kec_col": kec_col,
        "lu_col": lu_col,
        "riv_col": riv_col,
        "selected_rivers": sorted(selected_rivers) if selected_rivers else None,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@app.post("/api/compute")
def api_compute_analysis(req: ComputeRequest) -> Dict[str, Any]:
    """Execute preprocessing, 5 parameter scoring, weighted overlay, zonal stats, and 3D preparation."""
    t_start = time.perf_counter()

    # 1. Validate weights first (must sum to 100% / 1.0)
    try:
        norm_w = normalize_weights(req.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Ensure required 5 spatial inputs exist
    required_inputs = ["dem", "kecamatan", "sungai", "curah_hujan", "penggunaan_lahan"]
    missing_inputs = [k for k in required_inputs if not STATE.paths.get(k)]
    if missing_inputs:
        raise HTTPException(
            status_code=400,
            detail=f"Data input wajib belum lengkap: {missing_inputs}. Silakan unggah data atau klik 'Coba Data Demo'.",
        )

    scoring_rules = (
        copy.deepcopy(req.scoring_rules)
        if req.scoring_rules is not None
        else copy.deepcopy(DEFAULT_SCORING_RULES)
    )
    landuse_scores = (
        copy.deepcopy(req.landuse_scores)
        if req.landuse_scores is not None
        else copy.deepcopy(DEFAULT_LANDUSE_SCORES)
    )

    kec_col = req.kecamatan_col or STATE.columns.get("kecamatan_col")
    lu_col = req.landuse_col or STATE.columns.get("landuse_col")
    riv_col = req.river_col or STATE.columns.get("river_col")

    cache_sig = _build_param_cache_signature(
        scoring_rules, landuse_scores, kec_col, lu_col, riv_col, req.selected_rivers
    )

    can_use_cached_params = (
        STATE.param_cache_key == cache_sig
        and STATE.grid is not None
        and len(STATE.score_rasters) == 5
    )

    all_warnings: List[str] = []

    try:
        if not can_use_cached_params:
            # Stage 1: Preprocessing (CRS EPSG:32647, 30m Reference Grid, Clip & Resample)
            grid = build_reference_grid(
                STATE.paths["kecamatan"],
                kecamatan_col=kec_col,
                pixel_size=PIXEL_SIZE,
                target_epsg=TARGET_EPSG,
            )
            all_warnings.extend(grid.warnings)

            dem_arr, dem_warn = preprocess_dem(STATE.paths["dem"], grid)
            all_warnings.extend(dem_warn)

            rivers_gdf, riv_warn = preprocess_rivers(
                STATE.paths["sungai"],
                grid,
                river_col=riv_col,
                selected_rivers=req.selected_rivers,
            )
            all_warnings.extend(riv_warn)

            landuse_gdf, resolved_lu_col, lu_warn = preprocess_landuse(
                STATE.paths["penggunaan_lahan"],
                grid,
                landuse_col=lu_col,
            )
            all_warnings.extend(lu_warn)

            rain_df, rain_warn = preprocess_rainfall_table(
                STATE.paths["curah_hujan"], grid
            )
            all_warnings.extend(rain_warn)

            # Stage 2: 5 Parameters & Reclassification (1..5)
            rain_raster, ch_score, ch_warn = compute_rainfall_parameter(
                rain_df,
                grid.shape,
                grid.transform,
                grid.city_mask,
                rules=scoring_rules.get("curah_hujan"),
            )
            all_warnings.extend(ch_warn)

            slope_raster, slope_score = compute_slope_parameter(
                dem_arr,
                grid.city_mask,
                pixel_size=grid.pixel_size,
                rules=scoring_rules.get("kemiringan_lereng"),
            )

            elev_raster, elev_score = compute_elevation_parameter(
                dem_arr,
                grid.city_mask,
                rules=scoring_rules.get("elevasi"),
            )

            lu_score, lu_score_warn = compute_landuse_parameter(
                landuse_gdf,
                resolved_lu_col,
                grid.shape,
                grid.transform,
                grid.city_mask,
                landuse_scores=landuse_scores,
            )
            all_warnings.extend(lu_score_warn)

            # Also rasterize landuse class names for point click popup
            unique_lu_names = sorted(
                landuse_gdf[resolved_lu_col].dropna().astype(str).str.strip().unique().tolist()
            )
            lu_id_to_name = {i + 1: name for i, name in enumerate(unique_lu_names)}
            lu_name_to_id = {name: i + 1 for i, name in enumerate(unique_lu_names)}
            lu_id_grid = rasterize(
                [
                    (geom, lu_name_to_id[str(val).strip()])
                    for geom, val in zip(landuse_gdf.geometry, landuse_gdf[resolved_lu_col])
                    if geom is not None and not geom.is_empty
                ],
                out_shape=grid.shape,
                transform=grid.transform,
                fill=0,
                all_touched=True,
                dtype=np.int16,
            )

            dist_river_raster, riv_score = compute_river_distance_parameter(
                rivers_gdf,
                grid.shape,
                grid.transform,
                grid.city_mask,
                pixel_size=grid.pixel_size,
                rules=scoring_rules.get("jarak_sungai"),
            )

            STATE.grid = grid
            STATE.dem_raster = dem_arr
            STATE.slope_raster = slope_raster
            STATE.rain_raster = rain_raster
            STATE.dist_river_raster = dist_river_raster
            STATE.landuse_class_grid = lu_id_grid
            STATE.landuse_id_to_name = lu_id_to_name
            STATE.rivers_gdf = rivers_gdf
            STATE.landuse_gdf = landuse_gdf
            STATE.rain_df = rain_df
            STATE.score_rasters = {
                "curah_hujan": ch_score,
                "kemiringan_lereng": slope_score,
                "elevasi": elev_score,
                "penggunaan_lahan": lu_score,
                "jarak_sungai": riv_score,
            }
            STATE.param_cache_key = cache_sig
            STATE.warnings = all_warnings
        else:
            all_warnings = list(STATE.warnings)

        assert STATE.grid is not None
        assert STATE.dem_raster is not None
        assert STATE.slope_raster is not None
        assert STATE.rain_raster is not None
        assert STATE.dist_river_raster is not None

        # Stage 3: Weighted Overlay & Equal Interval Classification (7/3 and 11/3)
        s_raster, cls_raster = compute_weighted_overlay(
            STATE.score_rasters,
            weights=norm_w,
            valid_mask=STATE.grid.city_mask,
        )
        STATE.score_s_raster = s_raster
        STATE.class_raster = cls_raster
        STATE.weights_used = norm_w
        STATE.scoring_rules_used = scoring_rules
        STATE.landuse_scores_used = landuse_scores

        # Stage 4: Zonal Statistics (City Summary & 15 Kecamatan Ranking)
        zonal_res = compute_zonal_statistics(
            score_s_raster=s_raster,
            class_raster=cls_raster,
            score_rasters=STATE.score_rasters,
            kecamatan_gdf=STATE.grid.kecamatan_gdf,
            kecamatan_col=STATE.grid.kecamatan_column,
            transform=STATE.grid.transform,
            valid_mask=STATE.grid.city_mask,
            weights=norm_w,
            pixel_size=STATE.grid.pixel_size,
        )
        STATE.zonal_result = zonal_res

        # Stage 5: Validation & Sensitivity Analysis
        val_res: Optional[Dict[str, Any]] = None
        if STATE.paths.get("titik_banjir"):
            val_res = validate_with_points(
                STATE.paths["titik_banjir"],
                s_raster,
                cls_raster,
                STATE.grid.transform,
                STATE.grid.city_mask,
                target_epsg=TARGET_EPSG,
            )
            all_warnings.extend(val_res.get("warnings", []))
        STATE.validation_result = val_res

        sens_res = run_sensitivity_analysis(
            score_rasters=STATE.score_rasters,
            valid_mask=STATE.grid.city_mask,
            base_weights=norm_w,
            points_source=STATE.paths.get("titik_banjir"),
            transform=STATE.grid.transform,
            delta_pct_points=5.0,
        )
        STATE.sensitivity_result = sens_res

        # Record in calibration history
        high_cls_info = zonal_res["city_summary"]["classes"].get("Tinggi", {})
        STATE.calibration_history.append(
            {
                "percobaan_ke": len(STATE.calibration_history) + 1,
                "waktu": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "bobot_ch_pct": round(norm_w["curah_hujan"] * 100.0, 1),
                "bobot_slope_pct": round(norm_w["kemiringan_lereng"] * 100.0, 1),
                "bobot_elev_pct": round(norm_w["elevasi"] * 100.0, 1),
                "bobot_lu_pct": round(norm_w["penggunaan_lahan"] * 100.0, 1),
                "bobot_riv_pct": round(norm_w["jarak_sungai"] * 100.0, 1),
                "luas_tinggi_ha": high_cls_info.get("luas_ha", 0.0),
                "luas_tinggi_persen": high_cls_info.get("persen", 0.0),
                "mean_s_kota": zonal_res["city_summary"].get("mean_s", 0.0),
                "akurasi_validasi_pct": val_res["overall_accuracy_pct"] if val_res else None,
                "status_valid": (
                    ("VALID" if val_res["is_valid"] else "BELUM VALID")
                    if val_res
                    else "Tanpa Titik Uji"
                ),
            }
        )

        # Stage 6: Render Web 3D Overlays, GeoJSON vectors, and Three.js Mesh
        STATE.maplibre_overlays = render_maplibre_layer_overlays(
            dem_raster=STATE.dem_raster,
            score_s_raster=s_raster,
            class_raster=cls_raster,
            score_rasters=STATE.score_rasters,
            valid_mask=STATE.grid.city_mask,
            transform=STATE.grid.transform,
            crs=STATE.grid.crs,
        )

        kec_wgs84 = STATE.grid.kecamatan_gdf.to_crs("EPSG:4326")
        riv_wgs84 = STATE.rivers_gdf.to_crs("EPSG:4326")
        import geopandas as gpd

        city_gdf_wgs84 = gpd.GeoDataFrame(
            {"nama_kota": ["Kota Pekanbaru"]},
            geometry=[STATE.grid.city_polygon],
            crs=STATE.grid.crs,
        ).to_crs("EPSG:4326")
        STATE.geojson_layers = {
            "kecamatan": json.loads(kec_wgs84.to_json()),
            "batas_kota": json.loads(city_gdf_wgs84.to_json()),
            "sungai": json.loads(riv_wgs84.to_json()),
        }

        STATE.threejs_mesh = build_threejs_mesh_payload(
            dem_raster=STATE.dem_raster,
            slope_raster=STATE.slope_raster,
            rain_raster=STATE.rain_raster,
            dist_river_raster=STATE.dist_river_raster,
            score_s_raster=s_raster,
            class_raster=cls_raster,
            score_rasters=STATE.score_rasters,
            valid_mask=STATE.grid.city_mask,
            kecamatan_gdf=STATE.grid.kecamatan_gdf,
            kecamatan_col=STATE.grid.kecamatan_column,
            transform=STATE.grid.transform,
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Kesalahan saat pemrosesan spasial: {exc}"
        ) from exc

    elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 1)
    STATE.last_timing_ms = {
        "total_ms": elapsed_ms,
        "used_cached_parameters": can_use_cached_params,
    }

    return _build_full_results_response()


def _build_full_results_response() -> Dict[str, Any]:
    """Assemble the complete analysis payload for the frontend."""
    if STATE.score_s_raster is None or STATE.grid is None or STATE.zonal_result is None:
        raise HTTPException(
            status_code=404,
            detail="Belum ada hasil perhitungan. Silakan jalankan perhitungan terlebih dahulu.",
        )

    return {
        "status": "ok",
        "is_demo": STATE.is_demo,
        "disclaimer": STATE.disclaimer,
        "timing": STATE.last_timing_ms,
        "grid_info": {
            "epsg": TARGET_EPSG,
            "pixel_size_m": STATE.grid.pixel_size,
            "shape": list(STATE.grid.shape),
            "valid_pixels": STATE.grid.valid_pixel_count,
            "bounds_utm": list(STATE.grid.bounds),
        },
        "weights": STATE.weights_used,
        "warnings": STATE.warnings,
        "zonal": STATE.zonal_result,
        "validation": STATE.validation_result,
        "sensitivity": STATE.sensitivity_result,
        "calibration_history": STATE.calibration_history,
        "maplibre": STATE.maplibre_overlays,
        "geojson": STATE.geojson_layers,
    }


@app.get("/api/results")
def api_get_results() -> Dict[str, Any]:
    """Return the latest cached computation result."""
    return _build_full_results_response()


@app.get("/api/mesh3d")
def api_get_mesh3d() -> Dict[str, Any]:
    """Return the downsampled 3D terrain mesh payload for the Three.js simulation mode."""
    if STATE.threejs_mesh is None:
        raise HTTPException(
            status_code=404,
            detail="Mesh 3D belum tersedia. Jalankan perhitungan terlebih dahulu.",
        )
    return {
        "status": "ok",
        "is_demo": STATE.is_demo,
        "disclaimer": STATE.disclaimer,
        "weights": STATE.weights_used,
        "mesh": STATE.threejs_mesh,
    }


@app.get("/api/query-point")
def api_query_point(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
) -> Dict[str, Any]:
    """Query all parameter values, scores, composite S, class, and dominant factor at (lat, lon)."""
    if STATE.grid is None or STATE.score_s_raster is None or STATE.class_raster is None:
        raise HTTPException(status_code=404, detail="Hasil analisis belum tersedia.")

    transformer = Transformer.from_crs("EPSG:4326", STATE.grid.crs, always_xy=True)
    x_utm, y_utm = transformer.transform(lon, lat)

    transform = STATE.grid.transform
    col = int((x_utm - transform.c) / transform.a)
    row = int((y_utm - transform.f) / transform.e)
    rows_cnt, cols_cnt = STATE.grid.shape

    if not (0 <= row < rows_cnt and 0 <= col < cols_cnt) or not bool(STATE.grid.city_mask[row, col]):
        return {
            "inside_city": False,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "message": "Titik berada di luar batas administrasi Kota Pekanbaru.",
        }

    # Find kecamatan name
    from shapely.geometry import Point

    pt_utm = Point(x_utm, y_utm)
    kec_name = "-"
    for _, krow in STATE.grid.kecamatan_gdf.iterrows():
        if krow.geometry.contains(pt_utm):
            kec_name = str(krow[STATE.grid.kecamatan_column])
            break

    point_scores = {
        k: int(STATE.score_rasters[k][row, col]) for k in PARAMETER_ORDER
    }
    s_val = float(STATE.score_s_raster[row, col])
    cls_code = int(STATE.class_raster[row, col])
    cls_info = CLASS_DEFINITIONS.get(cls_code, CLASS_DEFINITIONS[2])

    lu_id = int(STATE.landuse_class_grid[row, col]) if STATE.landuse_class_grid is not None else 0
    lu_name = STATE.landuse_id_to_name.get(lu_id, "Terpetakan")

    dominant = get_dominant_factor_for_point(point_scores, STATE.weights_used)

    return {
        "inside_city": True,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "x_utm": round(float(x_utm), 1),
        "y_utm": round(float(y_utm), 1),
        "kecamatan": kec_name,
        "raw_values": {
            "elevasi_mdpl": round(float(STATE.dem_raster[row, col]), 2) if STATE.dem_raster is not None else 0.0,
            "lereng_persen": round(float(STATE.slope_raster[row, col]), 2) if STATE.slope_raster is not None else 0.0,
            "curah_hujan_mm": round(float(STATE.rain_raster[row, col]), 1) if STATE.rain_raster is not None else 0.0,
            "jarak_sungai_m": round(float(STATE.dist_river_raster[row, col]), 1) if STATE.dist_river_raster is not None else 0.0,
            "kelas_lahan": lu_name,
        },
        "scores": point_scores,
        "score_s": round(s_val, 3),
        "class_code": cls_code,
        "class_name": cls_info["name"],
        "class_color": cls_info["color_hex"],
        "dominant_factor": dominant,
    }


@app.get("/api/export/{export_type}")
def api_export_file(
    export_type: str,
    min_area_ha: float = Query(1.0, ge=0.0, description="Filter luas poligon minimum (Ha)"),
    smooth: bool = Query(False, description="Haluskan batas poligon"),
) -> FileResponse:
    """Generate and download requested export file (GeoTIFF, GPKG, SHP, Excel, PDF/PNG Map, Metadata)."""
    if STATE.grid is None or STATE.score_s_raster is None or STATE.class_raster is None or STATE.zonal_result is None:
        raise HTTPException(
            status_code=400,
            detail="Belum ada hasil analisis untuk diekspor. Jalankan perhitungan terlebih dahulu.",
        )

    out_dir = STATE.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    config_snapshot = {
        "weights": STATE.weights_used,
        "scoring_rules": STATE.scoring_rules_used,
        "landuse_scores": STATE.landuse_scores_used,
    }

    if export_type == "metadata":
        meta_path = export_metadata_json(
            out_dir / "metadata.json",
            config_snapshot,
            STATE.zonal_result["city_summary"],
            STATE.validation_result,
            is_demo=STATE.is_demo,
        )
        return FileResponse(
            meta_path, media_type="application/json", filename="metadata.json"
        )

    if export_type in ("geotiff_s", "geotiff_kelas", "geotiff_zip"):
        tiffs = export_all_geotiffs(
            out_dir / "geotiff",
            STATE.score_s_raster,
            STATE.class_raster,
            STATE.score_rasters,
            STATE.grid.transform,
            STATE.grid.crs,
        )
        meta_path = export_metadata_json(
            out_dir / "geotiff" / "metadata.json",
            config_snapshot,
            STATE.zonal_result["city_summary"],
            STATE.validation_result,
            is_demo=STATE.is_demo,
        )
        if export_type == "geotiff_s":
            return FileResponse(
                tiffs["skor_s"],
                media_type="image/tiff",
                filename="skor_kerawanan_S_EPSG32647.tif",
            )
        if export_type == "geotiff_kelas":
            return FileResponse(
                tiffs["kelas"],
                media_type="image/tiff",
                filename="kelas_kerawanan_banjir_EPSG32647.tif",
            )
        zip_path = out_dir / "raster_geotiff_pekanbaru_EPSG32647.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in tiffs.values():
                zf.write(p, arcname=p.name)
            zf.write(meta_path, arcname="metadata.json")
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="raster_geotiff_pekanbaru_EPSG32647.zip",
        )

    if export_type in ("gpkg", "shp"):
        vec_paths = export_vector_polygons(
            out_dir / "vector",
            STATE.class_raster,
            STATE.grid.city_mask,
            STATE.grid.transform,
            STATE.grid.crs,
            min_area_ha=min_area_ha,
            smooth=smooth,
        )
        if export_type == "gpkg":
            return FileResponse(
                vec_paths["gpkg"],
                media_type="application/geopackage+sqlite3",
                filename="kerawanan_banjir_pekanbaru.gpkg",
            )
        return FileResponse(
            vec_paths["shp_zip"],
            media_type="application/zip",
            filename="kerawanan_banjir_pekanbaru_shp.zip",
        )

    if export_type == "excel":
        xlsx_path = export_excel_report(
            out_dir / "laporan_kerawanan_banjir_pekanbaru.xlsx",
            STATE.zonal_result,
            STATE.weights_used,
            STATE.scoring_rules_used,
            STATE.landuse_scores_used,
            STATE.validation_result,
            STATE.sensitivity_result,
            STATE.calibration_history,
        )
        return FileResponse(
            xlsx_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="laporan_kerawanan_banjir_pekanbaru.xlsx",
        )

    if export_type in ("map_png", "map_pdf"):
        maps = export_cartographic_map(
            out_dir / "layout",
            STATE.class_raster,
            STATE.grid.city_mask,
            STATE.grid.transform,
            STATE.grid.kecamatan_gdf,
            STATE.grid.kecamatan_column,
            STATE.rivers_gdf,
            STATE.zonal_result,
            is_demo=STATE.is_demo,
        )
        if export_type == "map_png":
            return FileResponse(
                maps["png"],
                media_type="image/png",
                filename="PETA_KERAWANAN_BANJIR_PEKANBARU_2026.png",
            )
        return FileResponse(
            maps["pdf"],
            media_type="application/pdf",
            filename="PETA_KERAWANAN_BANJIR_PEKANBARU_2026.pdf",
        )

    if export_type == "all_zip":
        tiffs = export_all_geotiffs(
            out_dir / "geotiff",
            STATE.score_s_raster,
            STATE.class_raster,
            STATE.score_rasters,
            STATE.grid.transform,
            STATE.grid.crs,
        )
        vec_paths = export_vector_polygons(
            out_dir / "vector",
            STATE.class_raster,
            STATE.grid.city_mask,
            STATE.grid.transform,
            STATE.grid.crs,
            min_area_ha=min_area_ha,
            smooth=smooth,
        )
        xlsx_path = export_excel_report(
            out_dir / "laporan_kerawanan_banjir_pekanbaru.xlsx",
            STATE.zonal_result,
            STATE.weights_used,
            STATE.scoring_rules_used,
            STATE.landuse_scores_used,
            STATE.validation_result,
            STATE.sensitivity_result,
            STATE.calibration_history,
        )
        maps = export_cartographic_map(
            out_dir / "layout",
            STATE.class_raster,
            STATE.grid.city_mask,
            STATE.grid.transform,
            STATE.grid.kecamatan_gdf,
            STATE.grid.kecamatan_column,
            STATE.rivers_gdf,
            STATE.zonal_result,
            is_demo=STATE.is_demo,
        )
        meta_path = export_metadata_json(
            out_dir / "metadata.json",
            config_snapshot,
            STATE.zonal_result["city_summary"],
            STATE.validation_result,
            is_demo=STATE.is_demo,
        )
        bundle_path = out_dir / "SIPEKA_Banjir_Pekanbaru_Paket_Lengkap_2026.zip"
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in tiffs.values():
                zf.write(p, arcname=f"GeoTIFF/{p.name}")
            zf.write(vec_paths["gpkg"], arcname=f"Vektor/{vec_paths['gpkg'].name}")
            zf.write(vec_paths["shp_zip"], arcname=f"Vektor/{vec_paths['shp_zip'].name}")
            zf.write(xlsx_path, arcname=xlsx_path.name)
            zf.write(maps["png"], arcname=f"Peta_Layout/{maps['png'].name}")
            zf.write(maps["pdf"], arcname=f"Peta_Layout/{maps['pdf'].name}")
            zf.write(meta_path, arcname="metadata.json")
        return FileResponse(
            bundle_path,
            media_type="application/zip",
            filename="SIPEKA_Banjir_Pekanbaru_Paket_Lengkap_2026.zip",
        )

    raise HTTPException(status_code=400, detail=f"Tipe ekspor tidak dikenal: {export_type}")


# Mount frontend directory as static files if present
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

