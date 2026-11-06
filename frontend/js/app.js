/* ==========================================================================
   SIPEKA-Banjir 3D — Main Application Controller
   ========================================================================== */

window.SIPEKAApp = (function () {
  let configData = null;
  let resultsData = null;
  let mesh3dData = null;

  let currentStep = 1;
  let activeView3D = "maplibre"; // "maplibre" | "threejs"
  let kecSortField = "peringkat";
  let kecSortAsc = true;

  // Editable state
  let weightsPct = {
    curah_hujan: 25,
    kemiringan_lereng: 25,
    elevasi: 20,
    penggunaan_lahan: 15,
    jarak_sungai: 15,
  };
  let scoringRules = {};
  let landuseScores = {};
  let detectedLanduseClasses = [
    "Hutan/Rawa",
    "Perkebunan/Semak",
    "Lahan Terbuka/Tegalan",
    "Permukiman Jarang/Industri",
    "Permukiman Padat/Lahan Terbangun Komersial",
  ];
  let selectedRivers = [];

  const UPLOAD_INPUT_TYPES = [
    "dem",
    "kecamatan",
    "sungai",
    "curah_hujan",
    "penggunaan_lahan",
    "titik_banjir",
  ];

  async function init() {
    _setupUploadDropzones();
    await fetchConfig();
    renderWeightSliders();
    renderScoringTables();
    renderLanduseMappingTable();
    renderAssumptionsList();
  }

  async function fetchConfig() {
    try {
      const res = await fetch("/api/config");
      if (!res.ok) return;
      configData = await res.json();

      if (configData.weights) {
        Object.keys(configData.weights).forEach((k) => {
          weightsPct[k] = Math.round(configData.weights[k] * 100);
        });
      }
      if (configData.scoring_rules) {
        scoringRules = JSON.parse(JSON.stringify(configData.scoring_rules));
      }
      if (configData.landuse_scores) {
        landuseScores = Object.assign({}, configData.landuse_scores);
      }
      if (configData.default_rivers) {
        selectedRivers = [...configData.default_rivers];
      }
      renderRiverFilterCheckboxes(configData.default_rivers || []);
    } catch (err) {
      console.error("Gagal memuat konfigurasi awal:", err);
    }
  }

  function goToStep(stepNumber) {
    currentStep = Number(stepNumber);
    for (let i = 1; i <= 6; i++) {
      const panel = document.getElementById(`step-panel-${i}`);
      const btn = document.getElementById(`stepper-btn-${i}`);
      if (panel) {
        panel.classList.toggle("hidden", i !== currentStep);
      }
      if (btn) {
        btn.classList.toggle("active", i === currentStep);
      }
    }

    if (currentStep === 4 && resultsData) {
      setTimeout(function () {
        if (activeView3D === "maplibre") {
          window.SIPEKAMap3D.initMap("maplibre-container", resultsData);
          window.SIPEKAMap3D.resize();
        } else if (mesh3dData) {
          window.SIPEKASim3D.initSim3D("threejs-container", mesh3dData);
        }
      }, 80);
    }

    if (currentStep === 6 && resultsData) {
      const mapPreviewImg = document.getElementById("carto-map-preview");
      if (mapPreviewImg) {
        mapPreviewImg.src = `/api/export/map_png?t=${Date.now()}`;
      }
    }

    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function toggleTheme() {
    const root = document.documentElement;
    const current = root.getAttribute("data-theme");
    const next = current === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    const btn = document.getElementById("btn-theme-toggle");
    if (btn) {
      btn.textContent = next === "light" ? "🌙 Mode Gelap" : "☀️ Mode Terang";
    }
  }

  // ------------------------------------------------------------------------
  // Step 1: Upload & Demo Data
  // ------------------------------------------------------------------------
  function _setupUploadDropzones() {
    UPLOAD_INPUT_TYPES.forEach((typeKey) => {
      const card = document.getElementById(`upload-card-${typeKey}`);
      const fileInput = document.getElementById(`file-input-${typeKey}`);
      if (!card || !fileInput) return;

      card.addEventListener("dragover", function (e) {
        e.preventDefault();
        card.classList.add("dragover");
      });
      card.addEventListener("dragleave", function () {
        card.classList.remove("dragover");
      });
      card.addEventListener("drop", function (e) {
        e.preventDefault();
        card.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          handleFileUpload(typeKey, e.dataTransfer.files);
        }
      });
      fileInput.addEventListener("change", function () {
        if (fileInput.files && fileInput.files.length > 0) {
          handleFileUpload(typeKey, fileInput.files);
        }
      });
    });
  }

  async function handleFileUpload(inputType, fileList) {
    const badge = document.getElementById(`status-badge-${inputType}`);
    const infoBox = document.getElementById(`upload-info-${inputType}`);
    const card = document.getElementById(`upload-card-${inputType}`);

    if (badge) {
      badge.className = "status-pill pending";
      badge.textContent = "⏳ Memvalidasi...";
    }

    const formData = new FormData();
    for (let i = 0; i < fileList.length; i++) {
      formData.append("files", fileList[i]);
    }

    try {
      const res = await fetch(`/api/upload/${inputType}`, {
        method: "POST",
        body: formData,
      });
      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload.detail || "Gagal memvalidasi file.");
      }

      if (card) card.classList.add("uploaded");
      if (badge) {
        badge.className = "status-pill success";
        badge.textContent = "✓ Tervalidasi";
      }

      _updateUploadCardMeta(inputType, payload.meta);
      document.getElementById("demo-banner")?.classList.add("hidden");
    } catch (err) {
      if (card) card.classList.remove("uploaded");
      if (badge) {
        badge.className = "status-pill error";
        badge.textContent = "✕ Error";
      }
      if (infoBox) {
        infoBox.innerHTML = `<span style="color:#f87171;">${err.message}</span>`;
      }
    }
  }

  function _updateUploadCardMeta(inputType, meta) {
    const infoBox = document.getElementById(`upload-info-${inputType}`);
    if (!infoBox || !meta) return;

    const warningsHtml = (meta.warnings || [])
      .map((w) => `<div style="color:#fbbf24;margin-top:3px;">⚠️ ${w}</div>`)
      .join("");

    if (inputType === "dem") {
      infoBox.innerHTML = `<div>Grid DEM: <b>${(meta.shape || []).join(" × ")} piksel</b> (${meta.files?.length || 1} file)</div>${warningsHtml}`;
    } else if (inputType === "curah_hujan") {
      infoBox.innerHTML = `<div><b>${meta.stations} stasiun</b> | Rentang <b>${meta.years} tahun</b></div>${warningsHtml}`;
    } else if (inputType === "titik_banjir") {
      infoBox.innerHTML = `<div><b>${meta.points_count} titik</b> validasi banjir historis</div>${warningsHtml}`;
    } else {
      infoBox.innerHTML = `<div><b>${meta.feature_count} fitur</b> | CRS: ${meta.crs}</div>${warningsHtml}`;
      // Populate column dropdown if present
      const sel = document.getElementById(`col-select-${inputType}`);
      if (sel && meta.columns) {
        sel.innerHTML = meta.columns
          .map(
            (c) =>
              `<option value="${c}" ${c === meta.selected_column ? "selected" : ""}>${c}</option>`
          )
          .join("");
        sel.parentElement?.classList.remove("hidden");
      }

      if (inputType === "penggunaan_lahan" && meta.unique_values) {
        detectedLanduseClasses = meta.unique_values;
        renderLanduseMappingTable();
      }
      if (inputType === "sungai" && meta.unique_values) {
        selectedRivers = [...meta.unique_values];
        renderRiverFilterCheckboxes(meta.unique_values);
      }
    }
  }

  async function onColumnChange(inputType, columnName) {
    try {
      const res = await fetch("/api/inspect-column", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_type: inputType,
          column_name: columnName,
        }),
      });
      if (!res.ok) return;
      const data = await res.json();
      if (inputType === "penggunaan_lahan" && data.unique_values) {
        detectedLanduseClasses = data.unique_values;
        renderLanduseMappingTable();
      } else if (inputType === "sungai" && data.unique_values) {
        selectedRivers = [...data.unique_values];
        renderRiverFilterCheckboxes(data.unique_values);
      }
    } catch (err) {
      console.error("Gagal memeriksa kolom:", err);
    }
  }

  async function loadDemoData(autoRunCompute = false) {
    const btnHero = document.getElementById("btn-hero-demo");
    if (btnHero) {
      btnHero.disabled = true;
      btnHero.textContent = "⏳ Menyiapkan Data Demo Pekanbaru...";
    }

    try {
      const res = await fetch("/api/demo", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal membuat data demo.");

      // Show Demo Banner
      const banner = document.getElementById("demo-banner");
      if (banner) {
        banner.textContent = `⚠️ ${data.disclaimer}`;
        banner.classList.remove("hidden");
      }

      // Mark all 6 upload cards as validated
      UPLOAD_INPUT_TYPES.forEach((t) => {
        const card = document.getElementById(`upload-card-${t}`);
        const badge = document.getElementById(`status-badge-${t}`);
        if (card) card.classList.add("uploaded");
        if (badge) {
          badge.className = "status-pill success";
          badge.textContent = "✓ Demo Siap";
        }
        if (data.layer_meta && data.layer_meta[t]) {
          _updateUploadCardMeta(t, data.layer_meta[t]);
        }
      });

      document.getElementById("stepper-btn-1")?.classList.add("completed");

      if (autoRunCompute) {
        goToStep(3);
        await runFullComputation();
      } else {
        goToStep(1);
      }
    } catch (err) {
      alert("Gagal memuat data demo: " + err.message);
    } finally {
      if (btnHero) {
        btnHero.disabled = false;
        btnHero.textContent = "⚡ Coba Data Demo (1-Klik 3D)";
      }
    }
  }

  // ------------------------------------------------------------------------
  // Step 2: Weights, Scoring Rules, Landuse Mapping & Assumptions
  // ------------------------------------------------------------------------
  function renderWeightSliders() {
    const container = document.getElementById("weights-sliders-container");
    if (!container) return;

    const params = [
      { key: "curah_hujan", label: "A. Curah Hujan (CH)", def: 25 },
      { key: "kemiringan_lereng", label: "B. Kemiringan Lereng (Slope)", def: 25 },
      { key: "elevasi", label: "C. Elevasi / Ketinggian (Elev)", def: 20 },
      { key: "penggunaan_lahan", label: "D. Penggunaan Lahan (LU)", def: 15 },
      { key: "jarak_sungai", label: "E. Jarak terhadap Sungai (Riv)", def: 15 },
    ];

    container.innerHTML = params
      .map(
        (p) => `
      <div class="weight-row">
        <div class="weight-row-header">
          <span>${p.label} <small style="color:var(--text-muted);">(Skripsi: ${p.def}%)</small></span>
          <span id="weight-val-label-${p.key}" style="color:var(--accent-cyan);font-family:var(--font-mono);">${weightsPct[p.key]}% (${(weightsPct[p.key] / 100).toFixed(2)})</span>
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem;">
          <input type="range" min="0" max="100" step="1" value="${weightsPct[p.key]}"
            id="weight-slider-${p.key}"
            oninput="SIPEKAApp.onWeightChange('${p.key}', this.value)" />
          <input type="number" min="0" max="100" step="1" value="${weightsPct[p.key]}"
            id="weight-num-${p.key}" style="width:72px;text-align:center;"
            onchange="SIPEKAApp.onWeightChange('${p.key}', this.value)" />
        </div>
      </div>
    `
      )
      .join("");

    _updateWeightTotalBanner();
  }

  function onWeightChange(paramKey, newVal) {
    const val = Math.max(0, Math.min(100, Number(newVal) || 0));
    weightsPct[paramKey] = val;

    const slider = document.getElementById(`weight-slider-${paramKey}`);
    if (slider) slider.value = val;
    const numInput = document.getElementById(`weight-num-${paramKey}`);
    if (numInput) numInput.value = val;
    const lbl = document.getElementById(`weight-val-label-${paramKey}`);
    if (lbl) lbl.textContent = `${val}% (${(val / 100).toFixed(2)})`;

    _updateWeightTotalBanner();
  }

  function _updateWeightTotalBanner() {
    const total = Object.values(weightsPct).reduce((a, b) => a + Number(b), 0);
    const diff = total - 100;
    const banner = document.getElementById("weight-total-banner");
    const formulaBox = document.getElementById("live-formula-preview");
    const btnCompute = document.getElementById("btn-run-compute");
    const btnQuickRecalc = document.getElementById("btn-quick-recalc");

    if (formulaBox) {
      formulaBox.textContent = `S = ${(weightsPct.curah_hujan / 100).toFixed(2)}·CH + ${(weightsPct.kemiringan_lereng / 100).toFixed(2)}·Slope + ${(weightsPct.elevasi / 100).toFixed(2)}·Elev + ${(weightsPct.penggunaan_lahan / 100).toFixed(2)}·LU + ${(weightsPct.jarak_sungai / 100).toFixed(2)}·Riv`;
    }

    const isValid = Math.abs(diff) < 0.01;
    if (banner) {
      if (isValid) {
        banner.className = "weight-total-banner valid";
        banner.innerHTML = `<span>✓ Total Bobot Valid: <b>100% (1,00)</b></span><span>Siap Dihitung</span>`;
      } else {
        const sign = diff > 0 ? "+" : "";
        banner.className = "weight-total-banner invalid";
        banner.innerHTML = `<span>✕ Total Bobot: <b>${total.toFixed(1)}%</b> (Wajib tepat 100%)</span><span>Selisih: <b>${sign}${diff.toFixed(1)}%</b></span>`;
      }
    }

    if (btnCompute) btnCompute.disabled = !isValid;
    if (btnQuickRecalc) btnQuickRecalc.disabled = !isValid;
  }

  function resetDefaultWeights() {
    weightsPct = {
      curah_hujan: 25,
      kemiringan_lereng: 25,
      elevasi: 20,
      penggunaan_lahan: 15,
      jarak_sungai: 15,
    };
    renderWeightSliders();
  }

  function normalizeWeightsTo100() {
    const sum = Object.values(weightsPct).reduce((a, b) => a + Number(b), 0);
    if (sum <= 0) {
      resetDefaultWeights();
      return;
    }
    const keys = Object.keys(weightsPct);
    let running = 0;
    keys.forEach((k, idx) => {
      if (idx === keys.length - 1) {
        weightsPct[k] = 100 - running;
      } else {
        const scaled = Math.round((weightsPct[k] / sum) * 100);
        weightsPct[k] = scaled;
        running += scaled;
      }
    });
    renderWeightSliders();
  }

  function renderScoringTables() {
    const container = document.getElementById("scoring-tables-container");
    if (!container || !scoringRules) return;

    const paramTitles = {
      curah_hujan: "A. Tabel Skor Curah Hujan (mm/tahun — Interpolasi IDW p=2)",
      kemiringan_lereng: "B. Tabel Skor Kemiringan Lereng (% — Metode Horn 3×3)",
      elevasi: "C. Tabel Skor Elevasi / Ketinggian (mdpl — DEMNAS)",
      jarak_sungai: "E. Tabel Skor Jarak terhadap Sungai (meter — Euclidean Distance)",
    };

    container.innerHTML = Object.keys(paramTitles)
      .map((paramKey) => {
        const rules = scoringRules[paramKey] || [];
        const rowsHtml = rules
          .map(
            (r, idx) => `
          <tr>
            <td>
              <input type="number" step="any" placeholder="-∞"
                value="${r.min !== null && r.min !== undefined ? r.min : ""}"
                onchange="SIPEKAApp.onRuleBoundChange('${paramKey}', ${idx}, 'min', this.value)" />
            </td>
            <td>
              <input type="number" step="any" placeholder="+∞"
                value="${r.max !== null && r.max !== undefined ? r.max : ""}"
                onchange="SIPEKAApp.onRuleBoundChange('${paramKey}', ${idx}, 'max', this.value)" />
            </td>
            <td>${r.label}</td>
            <td>
              <select onchange="SIPEKAApp.onRuleBoundChange('${paramKey}', ${idx}, 'score', this.value)">
                ${[1, 2, 3, 4, 5]
                  .map(
                    (sc) =>
                      `<option value="${sc}" ${Number(r.score) === sc ? "selected" : ""}>Skor ${sc}</option>`
                  )
                  .join("")}
              </select>
            </td>
          </tr>
        `
          )
          .join("");

        return `
        <div style="margin-bottom:1.1rem;">
          <h4 style="font-size:0.9rem;color:var(--accent-cyan);margin-bottom:0.45rem;">${paramTitles[paramKey]}</h4>
          <div class="table-scroll-wrap">
            <table class="data-table" style="min-width:460px;">
              <thead>
                <tr>
                  <th style="width:22%;">Batas Bawah (≥)</th>
                  <th style="width:22%;">Batas Atas (&lt;)</th>
                  <th>Keterangan Kelas</th>
                  <th style="width:18%;">Skor (1–5)</th>
                </tr>
              </thead>
              <tbody>${rowsHtml}</tbody>
            </table>
          </div>
        </div>
      `;
      })
      .join("");
  }

  function onRuleBoundChange(paramKey, ruleIdx, field, rawVal) {
    if (!scoringRules[paramKey] || !scoringRules[paramKey][ruleIdx]) return;
    if (field === "score") {
      scoringRules[paramKey][ruleIdx].score = parseInt(rawVal, 10) || 1;
    } else {
      scoringRules[paramKey][ruleIdx][field] =
        rawVal === "" || rawVal === null ? null : parseFloat(rawVal);
    }
  }

  function renderLanduseMappingTable() {
    const tbody = document.getElementById("landuse-mapping-tbody");
    const warningEl = document.getElementById("landuse-unmapped-warning");
    if (!tbody) return;

    let unmappedCount = 0;
    tbody.innerHTML = detectedLanduseClasses
      .map((clsName) => {
        const currentScore = landuseScores[clsName];
        if (!currentScore) unmappedCount++;

        return `
        <tr>
          <td><b>${clsName}</b></td>
          <td>
            <select onchange="SIPEKAApp.onLanduseScoreChange('${clsName.replace(/'/g, "\\'")}', this.value)">
              <option value="" ${!currentScore ? "selected" : ""}>-- Pilih Skor (Wajib) --</option>
              <option value="1" ${currentScore === 1 ? "selected" : ""}>1 — Sangat Aman (Hutan/Rawa, C &lt; 0,20)</option>
              <option value="2" ${currentScore === 2 ? "selected" : ""}>2 — Aman (Perkebunan/Semak, C 0,20–0,35)</option>
              <option value="3" ${currentScore === 3 ? "selected" : ""}>3 — Sedang (Lahan Terbuka/Tegalan, C 0,35–0,50)</option>
              <option value="4" ${currentScore === 4 ? "selected" : ""}>4 — Rawan (Permukiman Jarang/Industri, C 0,50–0,70)</option>
              <option value="5" ${currentScore === 5 ? "selected" : ""}>5 — Sangat Rawan (Permukiman Padat/Komersial, C 0,70–0,90)</option>
            </select>
          </td>
        </tr>
      `;
      })
      .join("");

    if (warningEl) {
      warningEl.classList.toggle("hidden", unmappedCount === 0);
    }
  }

  function onLanduseScoreChange(clsName, val) {
    if (!val) {
      delete landuseScores[clsName];
    } else {
      landuseScores[clsName] = parseInt(val, 10);
    }
    renderLanduseMappingTable();
  }

  function renderRiverFilterCheckboxes(riversList) {
    const container = document.getElementById("river-filter-container");
    if (!container) return;
    container.innerHTML = (riversList || [])
      .map(
        (rName) => `
      <label style="display:inline-flex;align-items:center;gap:0.35rem;padding:0.3rem 0.65rem;border-radius:999px;background:var(--bg-card);border:1px solid var(--border-glass);font-size:0.78rem;cursor:pointer;">
        <input type="checkbox" value="${rName}" ${selectedRivers.includes(rName) ? "checked" : ""}
          onchange="SIPEKAApp.onRiverFilterToggle(this.value, this.checked)" />
        Sungai ${rName}
      </label>
    `
      )
      .join("");
  }

  function onRiverFilterToggle(riverName, isChecked) {
    if (isChecked) {
      if (!selectedRivers.includes(riverName)) selectedRivers.push(riverName);
    } else {
      selectedRivers = selectedRivers.filter((r) => r !== riverName);
    }
  }

  function renderAssumptionsList() {
    const ul = document.getElementById("assumptions-list");
    if (!ul || !configData?.assumptions) return;
    ul.innerHTML = configData.assumptions
      .map((item, idx) => `<li style="margin-bottom:0.45rem;"><b>Asumsi ${idx + 1}:</b> ${item}</li>`)
      .join("");
  }

  // ------------------------------------------------------------------------
  // Step 3: Execute MCE Weighted Overlay Computation
  // ------------------------------------------------------------------------
  async function runFullComputation(recalculateOnly = false) {
    const btn = document.getElementById("btn-run-compute");
    const errBox = document.getElementById("compute-error-box");
    if (errBox) errBox.classList.add("hidden");
    if (btn) btn.disabled = true;

    // Animate progress stages
    const stages = [1, 2, 3, 4, 5];
    stages.forEach((s) => {
      const el = document.getElementById(`prog-stage-${s}`);
      if (el) {
        el.classList.remove("active", "done");
      }
    });

    function markStage(idx) {
      for (let i = 1; i < idx; i++) {
        const prev = document.getElementById(`prog-stage-${i}`);
        if (prev) {
          prev.classList.remove("active");
          prev.classList.add("done");
        }
      }
      const cur = document.getElementById(`prog-stage-${idx}`);
      if (cur) cur.classList.add("active");
    }

    markStage(1);
    const stageTimer1 = setTimeout(() => markStage(2), 250);
    const stageTimer2 = setTimeout(() => markStage(3), 550);
    const stageTimer3 = setTimeout(() => markStage(4), 850);

    try {
      const weightsDecimal = {};
      Object.keys(weightsPct).forEach((k) => {
        weightsDecimal[k] = Number(weightsPct[k]) / 100.0;
      });

      const res = await fetch("/api/compute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          weights: weightsDecimal,
          scoring_rules: scoringRules,
          landuse_scores: landuseScores,
          selected_rivers: selectedRivers,
          recalculate_only: Boolean(recalculateOnly),
        }),
      });

      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload.detail || "Gagal melakukan perhitungan spasial.");
      }

      resultsData = payload;
      markStage(5);

      // Also fetch 3D mesh payload for Three.js simulator
      const meshRes = await fetch("/api/mesh3d");
      if (meshRes.ok) {
        mesh3dData = await meshRes.json();
      }

      // Mark stepper steps completed
      [2, 3, 4, 5, 6].forEach((s) => {
        document.getElementById(`stepper-btn-${s}`)?.classList.add("completed");
      });

      _populateDashboardAndValidation(resultsData);
      goToStep(4);
    } catch (err) {
      if (errBox) {
        errBox.textContent = `✕ Kesalahan: ${err.message}`;
        errBox.classList.remove("hidden");
      }
    } finally {
      clearTimeout(stageTimer1);
      clearTimeout(stageTimer2);
      clearTimeout(stageTimer3);
      if (btn) btn.disabled = false;
    }
  }

  async function recalculateWeightsQuick() {
    await runFullComputation(true);
  }

  // ------------------------------------------------------------------------
  // Step 4 & Step 5: Populate Dashboard, 15 Kecamatan Table & Validation
  // ------------------------------------------------------------------------
  function _populateDashboardAndValidation(data) {
    if (!data || !data.zonal) return;

    const citySum = data.zonal.city_summary;
    const tinggiInfo = citySum.classes?.Tinggi || { luas_ha: 0, persen: 0 };
    const topKec = data.zonal.kecamatan_stats?.[0];

    // Count-up KPIs
    window.SIPEKACharts.animateCountUp(
      "kpi-total-ha",
      citySum.luas_total_ha,
      1,
      " Ha"
    );
    window.SIPEKACharts.animateCountUp(
      "kpi-high-ha",
      tinggiInfo.luas_ha,
      1,
      ` Ha (${tinggiInfo.persen.toFixed(1)}%)`
    );
    window.SIPEKACharts.animateCountUp(
      "kpi-mean-s",
      citySum.mean_s,
      2,
      " / 5,00"
    );
    const elTopKec = document.getElementById("kpi-top-kec");
    if (elTopKec && topKec) {
      elTopKec.textContent = `#1 ${topKec.kecamatan} (${topKec.tinggi_persen.toFixed(1)}%)`;
    }

    // Timing badge
    const timingEl = document.getElementById("compute-timing-badge");
    if (timingEl && data.timing) {
      timingEl.textContent = `⚡ Selesai dalam ${(data.timing.total_ms / 1000).toFixed(2)} dtk ${data.timing.used_cached_parameters ? "(Cache Parameter Aktif)" : ""}`;
    }

    // Warnings list
    const warnBox = document.getElementById("results-warnings-box");
    if (warnBox) {
      const warns = data.warnings || [];
      if (warns.length > 0) {
        warnBox.classList.remove("hidden");
        warnBox.innerHTML = warns.map((w) => `<div>ℹ️ ${w}</div>`).join("");
      } else {
        warnBox.classList.add("hidden");
      }
    }

    // Charts
    window.SIPEKACharts.renderCityDonutChart(
      "chart-city-donut",
      citySum.classes
    );
    window.SIPEKACharts.renderKecamatanContributionChart(
      "chart-kecamatan-contrib",
      data.zonal.kecamatan_stats
    );

    // 15 Kecamatan Table
    renderKecamatanTable();

    // Validation & Sensitivity (Step 5)
    _renderValidationPanel(data.validation);
    _renderSensitivityPanel(data.sensitivity);
    _renderCalibrationHistory(data.calibration_history);
  }

  function renderKecamatanTable() {
    const tbody = document.getElementById("kecamatan-table-tbody");
    if (!tbody || !resultsData?.zonal?.kecamatan_stats) return;

    const filterText = (
      document.getElementById("kecamatan-filter-input")?.value || ""
    )
      .trim()
      .toLowerCase();

    let rows = [...resultsData.zonal.kecamatan_stats];
    if (filterText) {
      rows = rows.filter(
        (r) =>
          r.kecamatan.toLowerCase().includes(filterText) ||
          r.kelas_dominan.toLowerCase().includes(filterText)
      );
    }

    rows.sort((a, b) => {
      const va = a[kecSortField];
      const vb = b[kecSortField];
      if (typeof va === "string") {
        return kecSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      return kecSortAsc ? va - vb : vb - va;
    });

    tbody.innerHTML = rows
      .map(
        (r) => `
      <tr style="cursor:pointer;" onclick="SIPEKAMap3D.flyToKecamatan('${r.kecamatan.replace(/'/g, "\\'")}')" title="Klik untuk terbang (Fly-To) ke Kecamatan ${r.kecamatan}">
        <td><b>#${r.peringkat}</b></td>
        <td><strong style="color:var(--accent-cyan);">${r.kecamatan}</strong></td>
        <td>${r.rendah_ha.toFixed(1)} Ha <small style="color:var(--text-muted);">(${r.rendah_persen.toFixed(1)}%)</small></td>
        <td>${r.sedang_ha.toFixed(1)} Ha <small style="color:var(--text-muted);">(${r.sedang_persen.toFixed(1)}%)</small></td>
        <td><b style="color:#f87171;">${r.tinggi_ha.toFixed(1)} Ha (${r.tinggi_persen.toFixed(1)}%)</b></td>
        <td><b>${r.mean_s.toFixed(2)}</b> <small style="color:var(--text-muted);">(Max ${r.max_s.toFixed(2)})</small></td>
        <td><span class="class-badge ${r.kelas_dominan}">${r.kelas_dominan}</span></td>
        <td><small>${r.faktor_dominan_label}</small></td>
      </tr>
    `
      )
      .join("");
  }

  function sortKecamatanTable(field) {
    if (kecSortField === field) {
      kecSortAsc = !kecSortAsc;
    } else {
      kecSortField = field;
      kecSortAsc = field === "peringkat" || field === "kecamatan";
    }
    renderKecamatanTable();
  }

  function switch3DMode(mode) {
    activeView3D = mode;
    const mapWrap = document.getElementById("maplibre-wrapper");
    const simWrap = document.getElementById("threejs-wrapper");
    const btnMap = document.getElementById("btn-mode-maplibre");
    const btnSim = document.getElementById("btn-mode-threejs");

    if (mode === "maplibre") {
      mapWrap?.classList.remove("hidden");
      simWrap?.classList.add("hidden");
      btnMap?.classList.add("btn-primary");
      btnMap?.classList.remove("btn-secondary");
      btnSim?.classList.add("btn-secondary");
      btnSim?.classList.remove("btn-primary");
      window.SIPEKAMap3D.resize();
    } else {
      mapWrap?.classList.add("hidden");
      simWrap?.classList.remove("hidden");
      btnSim?.classList.add("btn-primary");
      btnSim?.classList.remove("btn-secondary");
      btnMap?.classList.add("btn-secondary");
      btnMap?.classList.remove("btn-primary");
      if (mesh3dData) {
        window.SIPEKASim3D.initSim3D("threejs-container", mesh3dData);
      }
    }
  }

  function _renderValidationPanel(val) {
    const emptyBox = document.getElementById("validation-empty-box");
    const contentBox = document.getElementById("validation-content-box");
    if (!val) {
      emptyBox?.classList.remove("hidden");
      contentBox?.classList.add("hidden");
      return;
    }
    emptyBox?.classList.add("hidden");
    contentBox?.classList.remove("hidden");

    const badge = document.getElementById("val-status-badge");
    if (badge) {
      if (val.is_valid) {
        badge.className = "status-pill success";
        badge.style.fontSize = "0.95rem";
        badge.textContent = `✓ MODEL VALID (Akurasi ${val.overall_accuracy_pct.toFixed(2)}% ≥ 80%)`;
      } else {
        badge.className = "status-pill error";
        badge.style.fontSize = "0.95rem";
        badge.textContent = `✕ BELUM VALID (Akurasi ${val.overall_accuracy_pct.toFixed(2)}% < 80%) — Silakan Kalibrasi Ulang`;
      }
    }

    document.getElementById("val-oa-value").textContent =
      `${val.overall_accuracy_pct.toFixed(2)}%`;
    document.getElementById("val-points-summary").textContent =
      `${val.matching_points} sesuai dari ${val.total_points} titik uji (Persamaan 3.5)`;

    // Mode A: 3x3 Confusion Matrix
    const modeABox = document.getElementById("val-mode-a-box");
    if (val.mode_a && modeABox) {
      const m = val.mode_a.matrix;
      const prod = val.mode_a.producer_accuracy_pct;
      const usr = val.mode_a.user_accuracy_pct;
      document.getElementById("val-kappa-value").textContent =
        val.mode_a.kappa.toFixed(4);

      const cmHtml = `
        <table class="cm-table">
          <thead>
            <tr>
              <th>Kelas Lapangan \\ Model</th>
              <th>Prediksi: Rendah</th>
              <th>Prediksi: Sedang</th>
              <th>Prediksi: Tinggi</th>
              <th>Producer's Acc.</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>Lapangan: Rendah</th>
              <td class="cm-cell-diag">${m[0][0]}</td>
              <td class="cm-cell-off">${m[0][1]}</td>
              <td class="cm-cell-off">${m[0][2]}</td>
              <td><b>${prod.Rendah.toFixed(1)}%</b></td>
            </tr>
            <tr>
              <th>Lapangan: Sedang</th>
              <td class="cm-cell-off">${m[1][0]}</td>
              <td class="cm-cell-diag">${m[1][1]}</td>
              <td class="cm-cell-off">${m[1][2]}</td>
              <td><b>${prod.Sedang.toFixed(1)}%</b></td>
            </tr>
            <tr>
              <th>Lapangan: Tinggi</th>
              <td class="cm-cell-off">${m[2][0]}</td>
              <td class="cm-cell-off">${m[2][1]}</td>
              <td class="cm-cell-diag">${m[2][2]}</td>
              <td><b>${prod.Tinggi.toFixed(1)}%</b></td>
            </tr>
            <tr>
              <th>User's Accuracy</th>
              <td><b>${usr.Rendah.toFixed(1)}%</b></td>
              <td><b>${usr.Sedang.toFixed(1)}%</b></td>
              <td><b>${usr.Tinggi.toFixed(1)}%</b></td>
              <td class="cm-cell-diag">OA: ${val.mode_a.overall_accuracy_pct.toFixed(1)}%</td>
            </tr>
          </tbody>
        </table>
      `;
      document.getElementById("confusion-matrix-container").innerHTML = cmHtml;
    }

    // Mode B: Historical Flood Occurrence & Binary ROC-AUC
    if (val.mode_b) {
      const mb = val.mode_b;
      document.getElementById("val-modeb-sedang-tinggi").textContent =
        `${mb.accuracy_sedang_tinggi_pct.toFixed(2)}% (${mb.matching_sedang_tinggi}/${mb.total_flood_points} titik)`;
      document.getElementById("val-modeb-tinggi-only").textContent =
        `${mb.accuracy_tinggi_only_pct.toFixed(2)}% (${mb.matching_tinggi_only}/${mb.total_flood_points} titik)`;
      document.getElementById("val-modeb-note").textContent = mb.note || "";

      if (mb.binary_metrics) {
        const bm = mb.binary_metrics;
        document.getElementById("val-auc-value").textContent =
          bm.auc_roc.toFixed(4);
        document.getElementById("val-f1-value").textContent =
          `${bm.f1_score.toFixed(3)} (Precision ${bm.precision.toFixed(2)}, Recall ${bm.recall.toFixed(2)})`;
        window.SIPEKACharts.renderRocCurveChart(
          "chart-roc-curve",
          bm.roc_curve,
          bm.auc_roc
        );
      }
    }

    // Points table
    const ptsTbody = document.getElementById("val-points-tbody");
    if (ptsTbody && val.points) {
      ptsTbody.innerHTML = val.points
        .map(
          (p) => `
        <tr style="cursor:pointer;" onclick="SIPEKAApp.goToStep(4); setTimeout(() => SIPEKAMap3D.searchLocation('${p.lat}, ${p.lon}'), 200);">
          <td>#${p.id}</td>
          <td>${p.lokasi}</td>
          <td>${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</td>
          <td><b>${p.score_s.toFixed(2)}</b></td>
          <td><span class="class-badge ${p.kelas_model}">${p.kelas_model}</span></td>
          <td>${p.kelas_lapangan ? `<span class="class-badge ${p.kelas_lapangan}">${p.kelas_lapangan}</span>` : `Label: ${p.label}`}</td>
          <td>
            <span class="status-pill ${p.sesuai ? "success" : "error"}">
              ${p.sesuai ? "✓ Sesuai" : "✕ Tidak Sesuai"}
            </span>
          </td>
        </tr>
      `
        )
        .join("");
    }
  }

  function _renderSensitivityPanel(sens) {
    const tbody = document.getElementById("sensitivity-tbody");
    if (!tbody || !sens?.scenarios) return;

    tbody.innerHTML = sens.scenarios
      .map((s) => {
        const dHigh = s.delta_luas_tinggi_pct;
        const dAcc = s.delta_akurasi_pct;
        return `
        <tr>
          <td><b>${s.parameter_label}</b></td>
          <td><span class="status-pill pending">${s.perubahan}</span></td>
          <td>${s.bobot_awal_pct.toFixed(1)}% → <b>${s.bobot_baru_pct.toFixed(1)}%</b></td>
          <td>${s.luas_tinggi_pct.toFixed(2)}%</td>
          <td style="color:${dHigh >= 0 ? "#f87171" : "#4ade80"};font-weight:700;">
            ${dHigh >= 0 ? "+" : ""}${dHigh.toFixed(2)}%
          </td>
          <td>${s.akurasi_pct !== null ? `${s.akurasi_pct.toFixed(2)}%` : "-"}</td>
          <td style="color:${dAcc !== null && dAcc >= 0 ? "#4ade80" : "#f87171"};font-weight:700;">
            ${dAcc !== null ? `${dAcc >= 0 ? "+" : ""}${dAcc.toFixed(2)}%` : "-"}
          </td>
        </tr>
      `;
      })
      .join("");
  }

  function _renderCalibrationHistory(historyList) {
    const tbody = document.getElementById("calibration-history-tbody");
    if (!tbody || !historyList) return;

    tbody.innerHTML = historyList
      .map(
        (h) => `
      <tr>
        <td><b>#${h.percobaan_ke}</b></td>
        <td><small>${h.waktu}</small></td>
        <td>CH:${h.bobot_ch_pct}% | Slope:${h.bobot_slope_pct}% | Elev:${h.bobot_elev_pct}% | LU:${h.bobot_lu_pct}% | Riv:${h.bobot_riv_pct}%</td>
        <td>${h.luas_tinggi_ha.toFixed(1)} Ha (${h.luas_tinggi_persen.toFixed(1)}%)</td>
        <td><b>${h.akurasi_validasi_pct !== null ? `${h.akurasi_validasi_pct.toFixed(2)}%` : "-"}</b></td>
        <td><span class="status-pill ${h.status_valid === "VALID" ? "success" : "error"}">${h.status_valid}</span></td>
      </tr>
    `
      )
      .join("");
  }

  // ------------------------------------------------------------------------
  // Step 6: Exports & Screenshot 3D
  // ------------------------------------------------------------------------
  function downloadExport(exportType) {
    const minArea =
      document.getElementById("export-min-area-ha")?.value || "1.0";
    const smooth =
      document.getElementById("export-smooth-poly")?.checked || false;
    const url = `/api/export/${exportType}?min_area_ha=${encodeURIComponent(minArea)}&smooth=${encodeURIComponent(smooth)}`;
    window.open(url, "_blank");
  }

  function download3DScreenshot() {
    let dataUrl = null;
    if (activeView3D === "threejs") {
      dataUrl = window.SIPEKASim3D.captureScreenshot();
    } else {
      dataUrl = window.SIPEKAMap3D.captureScreenshot();
    }
    if (!dataUrl) {
      alert(
        "Silakan buka Langkah 4 (Peta 3D / Simulasi 3D) terlebih dahulu untuk mengambil tangkapan layar 3D."
      );
      return;
    }
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = `SIPEKA_Banjir_3D_Pekanbaru_${activeView3D}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  async function openMobileAccessModal() {
    const modal = document.getElementById("mobile-access-modal");
    if (!modal) return;
    modal.classList.remove("hidden");

    try {
      const res = await fetch("/api/network-info");
      if (!res.ok) return;
      const info = await res.json();
      const url = info.primary_url || "http://10.61.71.203:8000";

      const urlInput = document.getElementById("mobile-lan-url-input");
      if (urlInput) urlInput.value = url;

      const qrImg = document.getElementById("mobile-qr-img");
      if (qrImg) {
        qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&margin=8&data=${encodeURIComponent(url)}`;
      }
    } catch (e) {
      console.error("Gagal memuat info jaringan:", e);
    }
  }

  function closeMobileAccessModal() {
    const modal = document.getElementById("mobile-access-modal");
    if (modal) modal.classList.add("hidden");
  }

  function copyMobileUrl() {
    const urlInput = document.getElementById("mobile-lan-url-input");
    if (!urlInput) return;
    navigator.clipboard?.writeText(urlInput.value);
    const btn = document.getElementById("btn-copy-mobile-url");
    if (btn) {
      const old = btn.textContent;
      btn.textContent = "✓ Tersalin!";
      setTimeout(() => {
        btn.textContent = old;
      }, 1500);
    }
  }

  function toggleLegendCollapse() {
    const body = document.getElementById("map-legend-body");
    const btn = document.getElementById("btn-toggle-legend");
    if (!body) return;
    const isHidden = body.classList.toggle("hidden");
    if (btn) {
      btn.textContent = isHidden ? "▲ Tampilkan" : "▼ Sembunyikan";
    }
  }

  return {
    init,
    goToStep,
    toggleTheme,
    loadDemoData,
    onColumnChange,
    onWeightChange,
    resetDefaultWeights,
    normalizeWeightsTo100,
    onRuleBoundChange,
    onLanduseScoreChange,
    onRiverFilterToggle,
    runFullComputation,
    recalculateWeightsQuick,
    sortKecamatanTable,
    renderKecamatanTable,
    switch3DMode,
    downloadExport,
    download3DScreenshot,
    openMobileAccessModal,
    closeMobileAccessModal,
    copyMobileUrl,
    toggleLegendCollapse,
  };
})();

document.addEventListener("DOMContentLoaded", function () {
  window.SIPEKAApp.init();
});

