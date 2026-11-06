"""End-to-end API tests for `backend/main.py` using FastAPI TestClient (Requirement #11)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_api_config_demo_compute_results_and_export() -> None:
    """Test #11: Full API lifecycle (config -> demo -> compute -> results -> mesh3d -> query-point -> exports)."""
    # 1. GET /api/config
    res_cfg = client.get("/api/config")
    assert res_cfg.status_code == 200
    cfg_data = res_cfg.json()
    assert cfg_data["target_epsg"] == 32647
    assert len(cfg_data["kecamatan_list"]) == 15
    assert len(cfg_data["assumptions"]) == 6

    # 2. POST /api/demo (load synthetic Pekanbaru dataset)
    res_demo = client.post("/api/demo")
    assert res_demo.status_code == 200
    demo_data = res_demo.json()
    assert demo_data["is_demo"] is True
    assert "DATA DEMO" in demo_data["disclaimer"]
    assert demo_data["summary"]["kecamatan_count"] == 15
    assert demo_data["summary"]["validation_points"] >= 50

    # 3. POST /api/compute with invalid weights (total != 100%) must fail with 400
    res_bad = client.post(
        "/api/compute",
        json={
            "weights": {
                "curah_hujan": 0.50,
                "kemiringan_lereng": 0.25,
                "elevasi": 0.20,
                "penggunaan_lahan": 0.15,
                "jarak_sungai": 0.15,
            }
        },
    )
    assert res_bad.status_code == 400

    # 4. POST /api/compute with default thesis weights
    res_comp = client.post(
        "/api/compute",
        json={
            "weights": {
                "curah_hujan": 0.25,
                "kemiringan_lereng": 0.25,
                "elevasi": 0.20,
                "penggunaan_lahan": 0.15,
                "jarak_sungai": 0.15,
            }
        },
    )
    assert res_comp.status_code == 200
    comp_data = res_comp.json()
    assert comp_data["status"] == "ok"
    assert comp_data["is_demo"] is True
    assert len(comp_data["zonal"]["kecamatan_stats"]) == 15
    assert comp_data["validation"] is not None
    assert comp_data["validation"]["total_points"] >= 50
    assert comp_data["validation"]["overall_accuracy_pct"] >= 80.0
    assert comp_data["validation"]["is_valid"] is True
    assert len(comp_data["sensitivity"]["scenarios"]) == 10

    # 5. Fast recalculate using cached 5 parameter rasters
    res_recalc = client.post(
        "/api/compute",
        json={
            "weights": {
                "curah_hujan": 0.20,
                "kemiringan_lereng": 0.30,
                "elevasi": 0.20,
                "penggunaan_lahan": 0.15,
                "jarak_sungai": 0.15,
            },
            "recalculate_only": True,
        },
    )
    assert res_recalc.status_code == 200
    recalc_data = res_recalc.json()
    assert recalc_data["timing"]["used_cached_parameters"] is True
    assert recalc_data["timing"]["total_ms"] < 2000.0
    assert len(recalc_data["calibration_history"]) == 2

    # 6. GET /api/results & GET /api/mesh3d
    res_results = client.get("/api/results")
    assert res_results.status_code == 200

    res_mesh = client.get("/api/mesh3d")
    assert res_mesh.status_code == 200
    mesh_data = res_mesh.json()["mesh"]
    assert mesh_data["rows"] <= 250 and mesh_data["cols"] <= 250

    # 7. GET /api/query-point at Pekanbaru center
    centroid = comp_data["zonal"]["kecamatan_stats"][0]["centroid_wgs84"]
    res_qp = client.get(f"/api/query-point?lon={centroid[0]}&lat={centroid[1]}")
    assert res_qp.status_code == 200
    qp_data = res_qp.json()
    assert qp_data["inside_city"] is True
    assert "dominant_factor" in qp_data
    assert qp_data["class_name"] in ("Rendah", "Sedang", "Tinggi")

    # 8. Test File Upload endpoint (/api/upload/curah_hujan) with the generated demo CSV
    demo_csv = Path("sample_data/demo/curah_hujan_bmkg_demo.csv")
    with demo_csv.open("rb") as f:
        res_up = client.post(
            "/api/upload/curah_hujan",
            files=[("files", ("curah_hujan_bmkg_demo.csv", f, "text/csv"))],
        )
    assert res_up.status_code == 200
    assert res_up.json()["meta"]["stations"] >= 3

    # 9. Test Export endpoints (metadata, excel, gpkg, geotiff_s, map_png)
    for exp_type in ("metadata", "excel", "gpkg", "geotiff_s", "map_png"):
        res_exp = client.get(f"/api/export/{exp_type}")
        assert res_exp.status_code == 200
        assert len(res_exp.content) > 100

