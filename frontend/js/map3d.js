/* ==========================================================================
   SIPEKA-Banjir 3D — MapLibre GL JS 3D Map Controller
   Supports Google Maps Hybrid/Satellite, Dashed Kecamatan Boundaries & Labels
   ========================================================================== */

window.SIPEKAMap3D = (function () {
  let map = null;
  let currentData = null;
  let activeLayerKey = "kelas";
  let activeOpacity = 0.62;
  let tourInterval = null;
  let tourIndex = 0;
  let activePopup = null;
  let kecamatanMarkers = [];
  let isKecamatanVisible = true;

  function initMap(containerId, resultsPayload) {
    currentData = resultsPayload;
    const container = document.getElementById(containerId);
    if (!container || typeof maplibregl === "undefined") return;

    const boundsWgs = resultsPayload?.maplibre?.bounds_wgs84 || [
      101.365, 0.435, 101.535, 0.60,
    ];
    const centerLon = (boundsWgs[0] + boundsWgs[2]) / 2;
    const centerLat = (boundsWgs[1] + boundsWgs[3]) / 2;

    if (map) {
      updateMapData(resultsPayload);
      return;
    }

    map = new maplibregl.Map({
      container: containerId,
      preserveDrawingBuffer: true,
      center: [centerLon, centerLat],
      zoom: 11.7,
      pitch: 52,
      bearing: -12,
      maxPitch: 82,
      style: {
        version: 8,
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
        sources: {
          google_hybrid: {
            type: "raster",
            tiles: [
              "https://mt0.google.com/vt/lyrs=y&hl=id&x={x}&y={y}&z={z}",
              "https://mt1.google.com/vt/lyrs=y&hl=id&x={x}&y={y}&z={z}",
              "https://mt2.google.com/vt/lyrs=y&hl=id&x={x}&y={y}&z={z}",
              "https://mt3.google.com/vt/lyrs=y&hl=id&x={x}&y={y}&z={z}",
            ],
            tileSize: 256,
            maxzoom: 20,
            attribution: "© Google Maps Hybrid (Satelit & Jalan Pekanbaru)",
          },
          google_satellite: {
            type: "raster",
            tiles: [
              "https://mt0.google.com/vt/lyrs=s&hl=id&x={x}&y={y}&z={z}",
              "https://mt1.google.com/vt/lyrs=s&hl=id&x={x}&y={y}&z={z}",
              "https://mt2.google.com/vt/lyrs=s&hl=id&x={x}&y={y}&z={z}",
              "https://mt3.google.com/vt/lyrs=s&hl=id&x={x}&y={y}&z={z}",
            ],
            tileSize: 256,
            maxzoom: 20,
            attribution: "© Google Maps Satellite",
          },
          google_terrain: {
            type: "raster",
            tiles: [
              "https://mt0.google.com/vt/lyrs=p&hl=id&x={x}&y={y}&z={z}",
              "https://mt1.google.com/vt/lyrs=p&hl=id&x={x}&y={y}&z={z}",
            ],
            tileSize: 256,
            maxzoom: 20,
            attribution: "© Google Maps Terrain & Streets",
          },
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
          esri_satellite: {
            type: "raster",
            tiles: [
              "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
            attribution: "© Esri World Imagery",
          },
          terrainSource: {
            type: "raster-dem",
            tiles: [
              "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
            ],
            encoding: "terrarium",
            tileSize: 256,
            maxzoom: 14,
          },
          hillshadeSource: {
            type: "raster-dem",
            tiles: [
              "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
            ],
            encoding: "terrarium",
            tileSize: 256,
            maxzoom: 14,
          },
        },
        layers: [
          {
            id: "basemap-google_hybrid",
            type: "raster",
            source: "google_hybrid",
            layout: { visibility: "visible" },
          },
          {
            id: "basemap-google_satellite",
            type: "raster",
            source: "google_satellite",
            layout: { visibility: "none" },
          },
          {
            id: "basemap-google_terrain",
            type: "raster",
            source: "google_terrain",
            layout: { visibility: "none" },
          },
          {
            id: "basemap-osm",
            type: "raster",
            source: "osm",
            layout: { visibility: "none" },
          },
          {
            id: "basemap-esri_satellite",
            type: "raster",
            source: "esri_satellite",
            layout: { visibility: "none" },
          },
          {
            id: "terrain-hillshade",
            type: "hillshade",
            source: "hillshadeSource",
            paint: {
              "hillshade-exaggeration": 0.45,
              "hillshade-shadow-color": "#020617",
              "hillshade-highlight-color": "#f8fafc",
              "hillshade-accent-color": "#38bdf8",
            },
          },
        ],
        terrain: {
          source: "terrainSource",
          exaggeration: 2.5,
        },
      },
    });

    map.addControl(
      new maplibregl.NavigationControl({ visualizePitch: true }),
      "bottom-right"
    );
    map.addControl(
      new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }),
      "bottom-left"
    );

    // Render 15 Kecamatan HTML markers immediately (DOM markers don't wait for tile network requests)
    _renderKecamatanMarkers(resultsPayload);

    map.on("style.load", function () {
      _setupOverlayLayers(resultsPayload);
      fitToCity();
    });

    map.on("load", function () {
      _setupOverlayLayers(resultsPayload);
    });

    map.on("click", function (e) {
      queryAndShowPopup(e.lngLat.lat, e.lngLat.lng);
    });
  }

  function _buildValidationPointsGeoJSON(validationObj) {
    const pts = validationObj?.points || [];
    return {
      type: "FeatureCollection",
      features: pts.map((p) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [p.lon, p.lat],
        },
        properties: p,
      })),
    };
  }

  function _renderKecamatanMarkers(resultsPayload) {
    kecamatanMarkers.forEach((m) => m.remove());
    kecamatanMarkers = [];

    const stats = resultsPayload?.zonal?.kecamatan_stats || [];
    if (!map || !stats.length) return;

    stats.forEach((k) => {
      if (!k.centroid_wgs84) return;
      const [lon, lat] = k.centroid_wgs84;

      const el = document.createElement("div");
      el.className = "kec-map-marker";
      if (!isKecamatanVisible) {
        el.style.display = "none";
      }

      const dotColor =
        k.kelas_dominan === "Tinggi"
          ? "#ef4444"
          : k.kelas_dominan === "Sedang"
            ? "#eab308"
            : "#22c55e";

      el.innerHTML = `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${dotColor};margin-right:4px;"></span>${k.kecamatan}`;
      el.title = `Kec. ${k.kecamatan} (Rank #${k.peringkat}, Rata-rata S = ${k.mean_s.toFixed(2)})`;
      el.addEventListener("click", function (ev) {
        ev.stopPropagation();
        flyToKecamatan(k.kecamatan);
      });

      const marker = new maplibregl.Marker({ element: el, anchor: "center" })
        .setLngLat([lon, lat])
        .addTo(map);
      kecamatanMarkers.push(marker);
    });
  }

  function _setupOverlayLayers(resultsPayload) {
    if (!map || !resultsPayload?.maplibre) return;

    const quad = resultsPayload.maplibre.coordinates_quad;
    const imgUrl =
      resultsPayload.maplibre.layers[activeLayerKey] ||
      resultsPayload.maplibre.layers.kelas;

    // 1. Raster MCE Overlay
    if (map.getSource("mce-overlay")) {
      map.getSource("mce-overlay").updateImage({
        url: imgUrl,
        coordinates: quad,
      });
    } else {
      map.addSource("mce-overlay", {
        type: "image",
        url: imgUrl,
        coordinates: quad,
      });
      map.addLayer({
        id: "mce-overlay-layer",
        type: "raster",
        source: "mce-overlay",
        paint: {
          "raster-opacity": activeOpacity,
          "raster-resampling": "nearest",
        },
      });
    }

    // 2. Sungai GeoJSON
    const sungaiGeo = resultsPayload.geojson?.sungai || {
      type: "FeatureCollection",
      features: [],
    };
    if (map.getSource("sungai-src")) {
      map.getSource("sungai-src").setData(sungaiGeo);
    } else {
      map.addSource("sungai-src", { type: "geojson", data: sungaiGeo });
      map.addLayer({
        id: "sungai-glow",
        type: "line",
        source: "sungai-src",
        paint: {
          "line-color": "#38bdf8",
          "line-width": 6,
          "line-opacity": 0.45,
          "line-blur": 2,
        },
      });
      map.addLayer({
        id: "sungai-line",
        type: "line",
        source: "sungai-src",
        paint: {
          "line-color": "#0284c7",
          "line-width": 2.6,
          "line-opacity": 0.98,
        },
      });
    }

    // 3. Batas 15 Kecamatan GeoJSON (Garis Putus-putus dengan Casing Kontras Tinggi)
    const kecGeo = resultsPayload.geojson?.kecamatan || {
      type: "FeatureCollection",
      features: [],
    };
    if (map.getSource("kecamatan-src")) {
      map.getSource("kecamatan-src").setData(kecGeo);
    } else {
      map.addSource("kecamatan-src", { type: "geojson", data: kecGeo });
      // Dark background casing for visibility over bright yellow/red & satellite
      map.addLayer({
        id: "kecamatan-casing",
        type: "line",
        source: "kecamatan-src",
        paint: {
          "line-color": "#020617",
          "line-width": 3.8,
          "line-opacity": 0.85,
        },
      });
      // Dashed administrative boundary line (garis putus-putus)
      map.addLayer({
        id: "kecamatan-outline",
        type: "line",
        source: "kecamatan-src",
        paint: {
          "line-color": "#fef08a",
          "line-width": 2.2,
          "line-dasharray": [4, 2.5],
          "line-opacity": 0.98,
        },
      });
    }

    // 4. Batas Administrasi Luar Kota Pekanbaru (Dash-Dot)
    const kotaGeo = resultsPayload.geojson?.batas_kota || {
      type: "FeatureCollection",
      features: [],
    };
    if (map.getSource("batas-kota-src")) {
      map.getSource("batas-kota-src").setData(kotaGeo);
    } else {
      map.addSource("batas-kota-src", { type: "geojson", data: kotaGeo });
      map.addLayer({
        id: "batas-kota-casing",
        type: "line",
        source: "batas-kota-src",
        paint: {
          "line-color": "#020617",
          "line-width": 5.2,
          "line-opacity": 0.9,
        },
      });
      map.addLayer({
        id: "batas-kota-outline",
        type: "line",
        source: "batas-kota-src",
        paint: {
          "line-color": "#38bdf8",
          "line-width": 2.8,
          "line-dasharray": [6, 2.5, 1.5, 2.5],
          "line-opacity": 1.0,
        },
      });
    }

    // 5. Validation Points GeoJSON
    const valGeo = _buildValidationPointsGeoJSON(resultsPayload.validation);
    if (map.getSource("val-points-src")) {
      map.getSource("val-points-src").setData(valGeo);
    } else {
      map.addSource("val-points-src", { type: "geojson", data: valGeo });
      map.addLayer({
        id: "val-points-layer",
        type: "circle",
        source: "val-points-src",
        paint: {
          "circle-radius": 6,
          "circle-color": ["get", "warna_hex"],
          "circle-stroke-color": "#0f172a",
          "circle-stroke-width": 1.8,
        },
      });
    }

    // 6. Render 15 Kecamatan Name Labels as HTML Markers
    _renderKecamatanMarkers(resultsPayload);
  }

  function updateMapData(resultsPayload) {
    currentData = resultsPayload;
    if (!map) return;
    _renderKecamatanMarkers(resultsPayload);
    try {
      _setupOverlayLayers(resultsPayload);
    } catch (e) {
      map.once("load", function () {
        _setupOverlayLayers(resultsPayload);
      });
    }
  }

  function setOverlayLayer(layerKey) {
    activeLayerKey = layerKey;
    if (!map || !currentData?.maplibre) return;
    const src = map.getSource("mce-overlay");
    const imgUrl = currentData.maplibre.layers[layerKey];
    if (src && imgUrl) {
      src.updateImage({
        url: imgUrl,
        coordinates: currentData.maplibre.coordinates_quad,
      });
    }
  }

  function setOverlayOpacity(opacityVal) {
    activeOpacity = Number(opacityVal);
    if (!map || !map.getLayer("mce-overlay-layer")) return;
    map.setPaintProperty("mce-overlay-layer", "raster-opacity", activeOpacity);
  }

  function setTerrainExaggeration(exagVal) {
    if (!map) return;
    const num = Number(exagVal);
    map.setTerrain({ source: "terrainSource", exaggeration: num });
  }

  function setBasemap(mode) {
    if (!map) return;
    const allBasemaps = [
      "google_hybrid",
      "google_satellite",
      "google_terrain",
      "osm",
      "esri_satellite",
    ];
    allBasemaps.forEach((bm) => {
      const layerId = `basemap-${bm}`;
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(
          layerId,
          "visibility",
          bm === mode ? "visible" : "none"
        );
      }
    });
  }

  function toggleVectorLayer(layerGroup, visible) {
    if (!map) return;
    const vis = visible ? "visible" : "none";
    if (layerGroup === "kecamatan") {
      isKecamatanVisible = Boolean(visible);
      [
        "kecamatan-casing",
        "kecamatan-outline",
        "batas-kota-casing",
        "batas-kota-outline",
      ].forEach((id) => {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
      });
      kecamatanMarkers.forEach((m) => {
        const el = m.getElement();
        if (el) el.style.display = visible ? "" : "none";
      });
    } else if (layerGroup === "sungai") {
      ["sungai-glow", "sungai-line"].forEach((id) => {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis);
      });
    } else if (layerGroup === "validasi") {
      if (map.getLayer("val-points-layer")) {
        map.setLayoutProperty("val-points-layer", "visibility", vis);
      }
    }
  }

  function fitToCity() {
    stopAutoTour();
    if (!map || !currentData?.maplibre?.bounds_wgs84) return;
    const [west, south, east, north] = currentData.maplibre.bounds_wgs84;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      {
        padding: 45,
        pitch: 52,
        bearing: -12,
        duration: 1400,
      }
    );
  }

  function flyToKecamatan(kecName) {
    stopAutoTour();
    if (!map || !currentData?.zonal?.kecamatan_stats) return;
    const target = currentData.zonal.kecamatan_stats.find(
      (k) => k.kecamatan.toLowerCase() === String(kecName).trim().toLowerCase()
    );
    if (!target) return;
    const [lon, lat] = target.centroid_wgs84;
    map.flyTo({
      center: [lon, lat],
      zoom: 13.4,
      pitch: 62,
      bearing: (target.peringkat * 28) % 360 - 180,
      duration: 1800,
      essential: true,
    });
    queryAndShowPopup(lat, lon);
  }

  function toggleAutoTour(btnElement) {
    if (tourInterval) {
      stopAutoTour(btnElement);
      return;
    }
    const stats = currentData?.zonal?.kecamatan_stats || [];
    if (!stats.length || !map) return;

    tourIndex = 0;
    if (btnElement) {
      btnElement.textContent = "⏹ Hentikan Tur";
      btnElement.classList.add("btn-success");
    }

    function stepTour() {
      const k = stats[tourIndex % Math.min(8, stats.length)];
      const [lon, lat] = k.centroid_wgs84;
      map.flyTo({
        center: [lon, lat],
        zoom: 13.3,
        pitch: 64,
        bearing: -35 + (tourIndex * 45) % 180,
        duration: 2600,
        essential: true,
      });
      queryAndShowPopup(lat, lon);
      tourIndex++;
    }

    stepTour();
    tourInterval = setInterval(stepTour, 4500);
  }

  function stopAutoTour(btnElement) {
    if (tourInterval) {
      clearInterval(tourInterval);
      tourInterval = null;
    }
    const tourBtn = btnElement || document.getElementById("btn-auto-tour");
    if (tourBtn) {
      tourBtn.textContent = "✈️ Tur Otomatis";
      tourBtn.classList.remove("btn-success");
    }
  }

  async function queryAndShowPopup(lat, lon) {
    if (!map) return;
    try {
      const res = await fetch(
        `/api/query-point?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`
      );
      if (!res.ok) return;
      const info = await res.json();
      if (!info.inside_city) return;

      if (activePopup) {
        activePopup.remove();
      }

      const dom = info.dominant_factor || {};
      const rv = info.raw_values || {};
      const sc = info.scores || {};

      const html = `
        <div style="font-size:0.8rem;line-height:1.45;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;margin-bottom:0.45rem;border-bottom:1px solid rgba(148,163,184,0.2);padding-bottom:0.35rem;">
            <strong style="font-size:0.92rem;color:#38bdf8;">Kec. ${info.kecamatan}</strong>
            <span class="class-badge ${info.class_name}">${info.class_name} (S = ${info.score_s.toFixed(2)})</span>
          </div>
          <div style="color:#94a3b8;font-size:0.72rem;margin-bottom:0.45rem;">
            Koordinat: ${info.lat.toFixed(5)}°, ${info.lon.toFixed(5)}° | UTM 47N: ${info.x_utm} mT, ${info.y_utm} mU
          </div>
          <table style="width:100%;font-size:0.76rem;border-collapse:collapse;margin-bottom:0.5rem;">
            <tr><td style="padding:2px 0;color:#cbd5e1;">Curah Hujan:</td><td style="text-align:right;"><b>${rv.curah_hujan_mm} mm/thn</b> (Skor ${sc.curah_hujan})</td></tr>
            <tr><td style="padding:2px 0;color:#cbd5e1;">Kemiringan Lereng:</td><td style="text-align:right;"><b>${rv.lereng_persen}%</b> (Skor ${sc.kemiringan_lereng})</td></tr>
            <tr><td style="padding:2px 0;color:#cbd5e1;">Elevasi (DEMNAS):</td><td style="text-align:right;"><b>${rv.elevasi_mdpl} mdpl</b> (Skor ${sc.elevasi})</td></tr>
            <tr><td style="padding:2px 0;color:#cbd5e1;">Penggunaan Lahan:</td><td style="text-align:right;"><b>${rv.kelas_lahan}</b> (Skor ${sc.penggunaan_lahan})</td></tr>
            <tr><td style="padding:2px 0;color:#cbd5e1;">Jarak ke Sungai:</td><td style="text-align:right;"><b>${rv.jarak_sungai_m} m</b> (Skor ${sc.jarak_sungai})</td></tr>
          </table>
          <div style="background:rgba(56,189,248,0.14);border:1px solid rgba(56,189,248,0.4);border-radius:8px;padding:0.4rem 0.55rem;font-size:0.74rem;">
            <span style="color:#38bdf8;font-weight:700;">⚡ Faktor Penyebab Dominan:</span><br/>
            <b>${dom.parameter_label || "-"}</b> (Kontribusi ${dom.contribution?.toFixed(2) || 0} atau <b>${dom.contribution_pct || 0}%</b> dari S)
          </div>
        </div>
      `;

      activePopup = new maplibregl.Popup({ closeOnClick: false, maxWidth: "330px" })
        .setLngLat([lon, lat])
        .setHTML(html)
        .addTo(map);
    } catch (err) {
      console.error("Gagal mengambil informasi titik:", err);
    }
  }

  function searchLocation(queryStr) {
    if (!queryStr || !map) return;
    const clean = String(queryStr).trim();

    // Check if query is "lat, lon"
    const coordMatch = clean.match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/);
    if (coordMatch) {
      let a = parseFloat(coordMatch[1]);
      let b = parseFloat(coordMatch[2]);
      const lat = Math.abs(a) < 10 ? a : b;
      const lon = Math.abs(a) < 10 ? b : a;
      map.flyTo({ center: [lon, lat], zoom: 14, pitch: 60, duration: 1500 });
      queryAndShowPopup(lat, lon);
      return;
    }

    // Otherwise match Kecamatan name
    const stats = currentData?.zonal?.kecamatan_stats || [];
    const found = stats.find((k) =>
      k.kecamatan.toLowerCase().includes(clean.toLowerCase())
    );
    if (found) {
      flyToKecamatan(found.kecamatan);
    }
  }

  function captureScreenshot() {
    if (!map) return null;
    return map.getCanvas().toDataURL("image/png");
  }

  function resize() {
    if (map) map.resize();
  }

  return {
    initMap,
    updateMapData,
    setOverlayLayer,
    setOverlayOpacity,
    setTerrainExaggeration,
    setBasemap,
    toggleVectorLayer,
    fitToCity,
    flyToKecamatan,
    toggleAutoTour,
    stopAutoTour,
    queryAndShowPopup,
    searchLocation,
    captureScreenshot,
    resize,
  };
})();
