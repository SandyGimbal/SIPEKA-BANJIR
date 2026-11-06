/* ==========================================================================
   SIPEKA-Banjir 3D — Three.js 3D Terrain Mesh, Rising Water & Rain Simulator
   ========================================================================== */

window.SIPEKASim3D = (function () {
  let scene = null;
  let camera = null;
  let renderer = null;
  let terrainMesh = null;
  let waterMesh = null;
  let rainPoints = null;
  let rainVelocities = null;
  let animFrameId = null;

  let meshPayload = null;
  let currentWeights = null;
  let verticalExaggeration = 2.4;
  let waterRiseM = 0.0;
  let baseRiverLevelM = 5.5;
  let isWaterPlaying = false;
  let isRainActive = true;
  let rainIntensity = 1.0;
  let isAutoRotate = true;

  // Orbit camera spherical state
  let isPointerDown = false;
  let pointerStart = { x: 0, y: 0 };
  let spherical = { theta: 0.45, phi: 1.02, radius: 135 };
  let pointerMovedDistance = 0;

  const WORLD_SIZE = 100;

  function initSim3D(containerId, meshResponse) {
    const container = document.getElementById(containerId);
    if (!container || typeof THREE === "undefined") return;

    meshPayload = meshResponse?.mesh || meshResponse;
    currentWeights = meshResponse?.weights || {
      curah_hujan: 0.25,
      kemiringan_lereng: 0.25,
      elevasi: 0.2,
      penggunaan_lahan: 0.15,
      jarak_sungai: 0.15,
    };

    if (!meshPayload || !meshPayload.rows || !meshPayload.cols) return;
    baseRiverLevelM = Number(meshPayload.min_elev_m || 4.0);

    // Clean up existing renderer if re-initialized
    if (renderer) {
      cancelAnimationFrame(animFrameId);
      container.innerHTML = "";
    }

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 650;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050914);
    scene.fog = new THREE.FogExp2(0x050914, 0.0032);

    camera = new THREE.PerspectiveCamera(45, width / height, 0.5, 1000);
    _updateCameraPosition();

    renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xdbeafe, 0.72);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.15);
    dirLight.position.set(60, 110, 50);
    scene.add(dirLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 0.45);
    rimLight.position.set(-70, 55, -60);
    scene.add(rimLight);

    // Build Terrain Mesh, Water Surface, and Rain Particles
    _buildTerrainGeometry();
    _buildWaterSurface();
    _buildRainSystem();

    // Pointer interaction (Orbit + Raycast cell click + Mobile Pinch-to-Zoom)
    const domEl = renderer.domElement;
    domEl.style.touchAction = "none";
    domEl.addEventListener("pointerdown", _onPointerDown);
    domEl.addEventListener("pointermove", _onPointerMove);
    domEl.addEventListener("pointerup", _onPointerUp);
    domEl.addEventListener("wheel", _onWheel, { passive: false });

    let pinchStartDist = 0;
    domEl.addEventListener(
      "touchstart",
      function (ev) {
        if (ev.touches && ev.touches.length === 2) {
          isPointerDown = false;
          const dx = ev.touches[0].clientX - ev.touches[1].clientX;
          const dy = ev.touches[0].clientY - ev.touches[1].clientY;
          pinchStartDist = Math.hypot(dx, dy);
        }
      },
      { passive: true }
    );
    domEl.addEventListener(
      "touchmove",
      function (ev) {
        if (ev.touches && ev.touches.length === 2 && pinchStartDist > 0) {
          ev.preventDefault();
          const dx = ev.touches[0].clientX - ev.touches[1].clientX;
          const dy = ev.touches[0].clientY - ev.touches[1].clientY;
          const curDist = Math.hypot(dx, dy);
          const delta = pinchStartDist - curDist;
          spherical.radius = Math.max(
            45,
            Math.min(260, spherical.radius + delta * 0.25)
          );
          pinchStartDist = curDist;
          _updateCameraPosition();
        }
      },
      { passive: false }
    );

    window.addEventListener("resize", function () {
      if (!container || !renderer || !camera) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w > 0 && h > 0) {
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }
    });

    updateWaterLevel(waterRiseM);
    _animate();
  }

  function _elevToWorldY(elevM) {
    if (elevM <= -900) return -3.0;
    return (elevM - baseRiverLevelM) * 0.26 * verticalExaggeration;
  }

  function _buildTerrainGeometry() {
    if (terrainMesh) {
      scene.remove(terrainMesh);
      terrainMesh.geometry.dispose();
      terrainMesh.material.dispose();
    }

    const rows = meshPayload.rows;
    const cols = meshPayload.cols;
    const aspect = cols / rows;
    const planeW = WORLD_SIZE * aspect;
    const planeH = WORLD_SIZE;

    const geom = new THREE.PlaneGeometry(planeW, planeH, cols - 1, rows - 1);
    geom.rotateX(-Math.PI / 2);

    const posAttr = geom.attributes.position;
    const colors = new Float32Array(posAttr.count * 3);

    const elevs = meshPayload.elevation_m;
    const classes = meshPayload.class_code;
    const valid = meshPayload.valid_mask;
    const riverDist = meshPayload.river_dist_m;

    for (let i = 0; i < posAttr.count; i++) {
      const isVal = valid[i] === 1;
      const el = isVal ? elevs[i] : baseRiverLevelM - 4;
      posAttr.setY(i, _elevToWorldY(el));

      let r = 0.08,
        g = 0.11,
        b = 0.18;
      if (isVal) {
        const cls = classes[i];
        // Highlight river channel in cyan-blue if distance <= 45m
        if (riverDist && riverDist[i] <= 42) {
          r = 0.05;
          g = 0.65;
          b = 0.95;
        } else if (cls === 1) {
          r = 0.13;
          g = 0.77;
          b = 0.37; // Hijau (#22c55e)
        } else if (cls === 2) {
          r = 0.92;
          g = 0.7;
          b = 0.03; // Kuning (#eab308)
        } else if (cls === 3) {
          r = 0.94;
          g = 0.27;
          b = 0.27; // Merah (#ef4444)
        }
      }
      colors[i * 3] = r;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = b;
    }

    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geom.computeVertexNormals();

    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.62,
      metalness: 0.12,
      flatShading: false,
      side: THREE.DoubleSide,
    });

    terrainMesh = new THREE.Mesh(geom, mat);
    scene.add(terrainMesh);
  }

  function _buildWaterSurface() {
    if (waterMesh) {
      scene.remove(waterMesh);
      waterMesh.geometry.dispose();
      waterMesh.material.dispose();
    }

    const rows = meshPayload.rows;
    const cols = meshPayload.cols;
    const aspect = cols / rows;
    const planeW = WORLD_SIZE * aspect * 0.96;
    const planeH = WORLD_SIZE * 0.96;

    const waterGeom = new THREE.PlaneGeometry(planeW, planeH, 48, 48);
    waterGeom.rotateX(-Math.PI / 2);

    const waterMat = new THREE.MeshPhysicalMaterial({
      color: 0x0ea5e9,
      emissive: 0x0369a1,
      emissiveIntensity: 0.22,
      transparent: true,
      opacity: 0.68,
      roughness: 0.12,
      metalness: 0.35,
      reflectivity: 0.92,
      clearcoat: 1.0,
      clearcoatRoughness: 0.1,
      side: THREE.DoubleSide,
    });

    waterMesh = new THREE.Mesh(waterGeom, waterMat);
    scene.add(waterMesh);
  }

  function _buildRainSystem() {
    if (rainPoints) {
      scene.remove(rainPoints);
      rainPoints.geometry.dispose();
      rainPoints.material.dispose();
    }

    const dropCount = 3200;
    const positions = new Float32Array(dropCount * 3);
    rainVelocities = new Float32Array(dropCount);

    for (let i = 0; i < dropCount; i++) {
      positions[i * 3] = (Math.random() - 0.5) * WORLD_SIZE * 1.25;
      positions[i * 3 + 1] = Math.random() * 65;
      positions[i * 3 + 2] = (Math.random() - 0.5) * WORLD_SIZE * 1.25;
      rainVelocities[i] = 0.65 + Math.random() * 0.55;
    }

    const rainGeom = new THREE.BufferGeometry();
    rainGeom.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const rainMat = new THREE.PointsMaterial({
      color: 0x7dd3fc,
      size: 0.45,
      transparent: true,
      opacity: 0.62,
    });

    rainPoints = new THREE.Points(rainGeom, rainMat);
    rainPoints.visible = isRainActive;
    scene.add(rainPoints);
  }

  function updateWaterLevel(riseMeters) {
    waterRiseM = Math.max(0, Number(riseMeters) || 0);
    if (!meshPayload || !waterMesh) return;

    const absoluteWaterElevM = baseRiverLevelM + waterRiseM;
    const waterWorldY = _elevToWorldY(absoluteWaterElevM);
    waterMesh.position.y = waterWorldY;
    waterMesh.visible = waterRiseM > 0.05;

    // Compute inundated statistics across the city
    const valid = meshPayload.valid_mask;
    const elevs = meshPayload.elevation_m;
    const classes = meshPayload.class_code;
    const kecIds = meshPayload.kecamatan_id;
    const cellAreaKm2 = Number(meshPayload.cell_area_km2 || 0.0036);

    let floodedCells = 0;
    let floodedHighClassCells = 0;
    const impactedKecSet = new Set();

    for (let i = 0; i < valid.length; i++) {
      if (valid[i] !== 1) continue;
      if (waterRiseM > 0.05 && elevs[i] <= absoluteWaterElevM) {
        floodedCells++;
        if (classes[i] === 3) {
          floodedHighClassCells++;
        }
        if (kecIds[i] > 0) {
          impactedKecSet.add(kecIds[i]);
        }
      }
    }

    const floodedKm2 = floodedCells * cellAreaKm2;
    const highSharePct =
      floodedCells > 0 ? (100.0 * floodedHighClassCells) / floodedCells : 0.0;

    // Update UI badges in Step 4 Simulasi 3D panel
    const elRise = document.getElementById("sim-water-val");
    if (elRise) elRise.textContent = `+${waterRiseM.toFixed(1)} m`;

    const elArea = document.getElementById("sim-flooded-area");
    if (elArea) elArea.textContent = `${floodedKm2.toFixed(2)} km²`;

    const elKec = document.getElementById("sim-impacted-kec");
    if (elKec) elKec.textContent = `${impactedKecSet.size} / 15 Kec.`;

    const elHighPct = document.getElementById("sim-high-class-pct");
    if (elHighPct) elHighPct.textContent = `${highSharePct.toFixed(1)}%`;
  }

  function setVerticalExaggeration(exagVal) {
    verticalExaggeration = Math.max(0.5, Number(exagVal) || 2.4);
    if (!terrainMesh || !meshPayload) return;

    const posAttr = terrainMesh.geometry.attributes.position;
    const elevs = meshPayload.elevation_m;
    const valid = meshPayload.valid_mask;

    for (let i = 0; i < posAttr.count; i++) {
      const el = valid[i] === 1 ? elevs[i] : baseRiverLevelM - 4;
      posAttr.setY(i, _elevToWorldY(el));
    }
    posAttr.needsUpdate = true;
    terrainMesh.geometry.computeVertexNormals();
    updateWaterLevel(waterRiseM);
  }

  function toggleWaterAnimation(btnEl) {
    isWaterPlaying = !isWaterPlaying;
    if (btnEl) {
      btnEl.textContent = isWaterPlaying ? "⏸ Pause Air Naik" : "▶ Play Air Naik";
    }
  }

  function toggleRain(enabled) {
    isRainActive = Boolean(enabled);
    if (rainPoints) {
      rainPoints.visible = isRainActive;
    }
  }

  function setRainIntensity(val) {
    rainIntensity = Math.max(0.2, Number(val) || 1.0);
    if (rainPoints && rainPoints.material) {
      rainPoints.material.opacity = Math.min(0.95, 0.35 + rainIntensity * 0.25);
      rainPoints.material.size = 0.3 + rainIntensity * 0.16;
    }
  }

  function toggleAutoRotate(enabled) {
    isAutoRotate = Boolean(enabled);
  }

  function resetCamera() {
    spherical = { theta: 0.45, phi: 1.02, radius: 135 };
    _updateCameraPosition();
  }

  function _updateCameraPosition() {
    if (!camera) return;
    const sinPhi = Math.sin(spherical.phi);
    camera.position.x = spherical.radius * sinPhi * Math.sin(spherical.theta);
    camera.position.y = spherical.radius * Math.cos(spherical.phi);
    camera.position.z = spherical.radius * sinPhi * Math.cos(spherical.theta);
    camera.lookAt(0, 4, 0);
  }

  function _onPointerDown(e) {
    isPointerDown = true;
    pointerMovedDistance = 0;
    pointerStart.x = e.clientX;
    pointerStart.y = e.clientY;
  }

  function _onPointerMove(e) {
    if (!isPointerDown) return;
    const dx = e.clientX - pointerStart.x;
    const dy = e.clientY - pointerStart.y;
    pointerMovedDistance += Math.abs(dx) + Math.abs(dy);
    pointerStart.x = e.clientX;
    pointerStart.y = e.clientY;

    spherical.theta -= dx * 0.0075;
    spherical.phi = Math.max(
      0.22,
      Math.min(1.48, spherical.phi - dy * 0.0065)
    );
    _updateCameraPosition();
  }

  function _onPointerUp(e) {
    if (!isPointerDown) return;
    isPointerDown = false;
    if (pointerMovedDistance < 6) {
      _handleMeshClick(e);
    }
  }

  function _onWheel(e) {
    e.preventDefault();
    spherical.radius = Math.max(
      45,
      Math.min(260, spherical.radius + e.deltaY * 0.08)
    );
    _updateCameraPosition();
  }

  function _handleMeshClick(e) {
    if (!renderer || !camera || !terrainMesh || !meshPayload) return;
    const rect = renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);
    const hits = raycaster.intersectObject(terrainMesh);
    if (!hits.length) return;

    const hit = hits[0];
    const rows = meshPayload.rows;
    const cols = meshPayload.cols;
    const aspect = cols / rows;
    const planeW = WORLD_SIZE * aspect;
    const planeH = WORLD_SIZE;

    const u = (hit.point.x + planeW / 2) / planeW;
    const v = (hit.point.z + planeH / 2) / planeH;
    const c = Math.max(0, Math.min(cols - 1, Math.round(u * (cols - 1))));
    const r = Math.max(0, Math.min(rows - 1, Math.round(v * (rows - 1))));
    const idx = r * cols + c;

    if (meshPayload.valid_mask[idx] !== 1) return;

    const kecId = meshPayload.kecamatan_id[idx];
    const kecName =
      kecId > 0 && meshPayload.kecamatan_names[kecId - 1]
        ? meshPayload.kecamatan_names[kecId - 1]
        : "Kota Pekanbaru";
    const elev = meshPayload.elevation_m[idx];
    const slope = meshPayload.slope_pct[idx];
    const rain = meshPayload.rainfall_mm[idx];
    const rivDist = meshPayload.river_dist_m[idx];
    const scoreS = meshPayload.score_s[idx];
    const clsCode = meshPayload.class_code[idx];
    const clsName =
      clsCode === 3 ? "Tinggi" : clsCode === 2 ? "Sedang" : "Rendah";

    const pScores = {
      curah_hujan: meshPayload.param_scores?.curah_hujan?.[idx] || 0,
      kemiringan_lereng: meshPayload.param_scores?.kemiringan_lereng?.[idx] || 0,
      elevasi: meshPayload.param_scores?.elevasi?.[idx] || 0,
      penggunaan_lahan: meshPayload.param_scores?.penggunaan_lahan?.[idx] || 0,
      jarak_sungai: meshPayload.param_scores?.jarak_sungai?.[idx] || 0,
    };

    const paramLabels = {
      curah_hujan: "Curah Hujan",
      kemiringan_lereng: "Kemiringan Lereng",
      elevasi: "Elevasi",
      penggunaan_lahan: "Penggunaan Lahan",
      jarak_sungai: "Jarak Sungai",
    };

    let bestParam = "elevasi";
    let bestContrib = -1;
    Object.keys(pScores).forEach((k) => {
      const cVal = (currentWeights[k] || 0.2) * pScores[k];
      if (cVal > bestContrib) {
        bestContrib = cVal;
        bestParam = k;
      }
    });

    const box = document.getElementById("sim3d-cell-popup");
    if (box) {
      box.classList.remove("hidden");
      box.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:0.6rem;margin-bottom:0.35rem;">
          <strong style="color:#38bdf8;">📍 Sel 3D — Kec. ${kecName}</strong>
          <span class="class-badge ${clsName}">${clsName} (S = ${scoreS.toFixed(2)})</span>
        </div>
        <div style="font-size:0.75rem;color:#cbd5e1;display:grid;grid-template-columns:1fr 1fr;gap:0.2rem 0.75rem;">
          <span>Elevasi: <b>${elev.toFixed(1)} mdpl</b> (Skor ${pScores.elevasi})</span>
          <span>Lereng: <b>${slope.toFixed(1)}%</b> (Skor ${pScores.kemiringan_lereng})</span>
          <span>Hujan: <b>${rain.toFixed(0)} mm</b> (Skor ${pScores.curah_hujan})</span>
          <span>Jarak Sungai: <b>${rivDist.toFixed(0)} m</b> (Skor ${pScores.jarak_sungai})</span>
          <span>Skor Lahan: <b>${pScores.penggunaan_lahan}</b></span>
          <span style="color:#38bdf8;">Dominan: <b>${paramLabels[bestParam]}</b></span>
        </div>
      `;
    }
  }

  function _animate() {
    animFrameId = requestAnimationFrame(_animate);

    if (isAutoRotate && !isPointerDown) {
      spherical.theta += 0.0022;
      _updateCameraPosition();
    }

    // Rising water animation when Play is active
    if (isWaterPlaying) {
      waterRiseM += 0.035;
      if (waterRiseM > 20.0) {
        waterRiseM = 0.0;
      }
      const slider = document.getElementById("slider-water-rise");
      if (slider) slider.value = waterRiseM.toFixed(1);
      updateWaterLevel(waterRiseM);
    }

    // Rain particle drop animation
    if (rainPoints && isRainActive && rainVelocities) {
      const posAttr = rainPoints.geometry.attributes.position;
      for (let i = 0; i < rainVelocities.length; i++) {
        let y = posAttr.getY(i) - rainVelocities[i] * rainIntensity;
        if (y < 0) {
          y = 62;
        }
        posAttr.setY(i, y);
      }
      posAttr.needsUpdate = true;
    }

    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  function captureScreenshot() {
    if (!renderer) return null;
    renderer.render(scene, camera);
    return renderer.domElement.toDataURL("image/png");
  }

  return {
    initSim3D,
    updateWaterLevel,
    setVerticalExaggeration,
    toggleWaterAnimation,
    toggleRain,
    setRainIntensity,
    toggleAutoRotate,
    resetCamera,
    captureScreenshot,
  };
})();

