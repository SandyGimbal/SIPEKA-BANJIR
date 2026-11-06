/* ==========================================================================
   SIPEKA-Banjir 3D — Statistical Charts & Count-Up Animations (Chart.js)
   ========================================================================== */

window.SIPEKACharts = (function () {
  let donutChartInstance = null;
  let paramBarChartInstance = null;
  let rocChartInstance = null;

  function animateCountUp(elementId, targetValue, decimals = 1, suffix = "") {
    const el = document.getElementById(elementId);
    if (!el) return;
    const duration = 850;
    const startTime = performance.now();
    const startVal = 0;
    const endVal = Number(targetValue) || 0;

    function tick(now) {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = startVal + (endVal - startVal) * eased;
      el.textContent =
        current.toLocaleString("id-ID", {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        }) + suffix;
      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }
    requestAnimationFrame(tick);
  }

  function renderCityDonutChart(canvasId, classesSummary) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === "undefined") return;

    const rendah = classesSummary?.Rendah || { luas_ha: 0, persen: 0 };
    const sedang = classesSummary?.Sedang || { luas_ha: 0, persen: 0 };
    const tinggi = classesSummary?.Tinggi || { luas_ha: 0, persen: 0 };

    if (donutChartInstance) {
      donutChartInstance.destroy();
    }

    donutChartInstance = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: [
          `Rendah (${rendah.persen.toFixed(1)}%)`,
          `Sedang (${sedang.persen.toFixed(1)}%)`,
          `Tinggi (${tinggi.persen.toFixed(1)}%)`,
        ],
        datasets: [
          {
            data: [rendah.luas_ha, sedang.luas_ha, tinggi.luas_ha],
            backgroundColor: ["#22c55e", "#eab308", "#ef4444"],
            borderColor: "rgba(15, 23, 42, 0.8)",
            borderWidth: 2,
            hoverOffset: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "64%",
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              color: "#cbd5e1",
              font: { size: 11, weight: "600" },
              padding: 12,
            },
          },
          tooltip: {
            callbacks: {
              label: function (context) {
                const valHa = Number(context.raw || 0).toLocaleString("id-ID", {
                  maximumFractionDigits: 2,
                });
                return ` ${context.label}: ${valHa} Ha`;
              },
            },
          },
        },
      },
    });
  }

  function renderKecamatanContributionChart(canvasId, kecamatanStats) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === "undefined") return;

    if (paramBarChartInstance) {
      paramBarChartInstance.destroy();
    }

    const labels = kecamatanStats.map((k) => k.kecamatan);
    const paramConfigs = [
      { key: "curah_hujan", label: "Curah Hujan (CH)", color: "#38bdf8" },
      { key: "kemiringan_lereng", label: "Kemiringan Lereng", color: "#818cf8" },
      { key: "elevasi", label: "Elevasi (DEM)", color: "#2dd4bf" },
      { key: "penggunaan_lahan", label: "Penggunaan Lahan", color: "#f59e0b" },
      { key: "jarak_sungai", label: "Jarak Sungai", color: "#f43f5e" },
    ];

    const datasets = paramConfigs.map((cfg) => ({
      label: cfg.label,
      data: kecamatanStats.map((k) =>
        Number(k.param_contributions?.[cfg.key] || 0)
      ),
      backgroundColor: cfg.color,
      borderRadius: 3,
    }));

    paramBarChartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            ticks: {
              color: "#94a3b8",
              font: { size: 10 },
              maxRotation: 45,
              minRotation: 30,
            },
            grid: { color: "rgba(148,163,184,0.08)" },
          },
          y: {
            stacked: true,
            min: 0,
            max: 5.0,
            title: {
              display: true,
              text: "Rata-rata Skor S (Σ Bobot × Skor)",
              color: "#cbd5e1",
              font: { size: 11 },
            },
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(148,163,184,0.12)" },
          },
        },
        plugins: {
          legend: {
            position: "top",
            labels: {
              color: "#cbd5e1",
              font: { size: 10 },
              boxWidth: 12,
            },
          },
        },
      },
    });
  }

  function renderRocCurveChart(canvasId, rocPoints, aucValue) {
    const ctx = document.getElementById(canvasId);
    if (!ctx || typeof Chart === "undefined") return;

    if (rocChartInstance) {
      rocChartInstance.destroy();
    }

    const dataPts = (rocPoints || []).map((pt) => ({ x: pt.fpr, y: pt.tpr }));

    rocChartInstance = new Chart(ctx, {
      type: "scatter",
      data: {
        datasets: [
          {
            label: `Kurva ROC Model S (AUC = ${Number(aucValue || 0).toFixed(3)})`,
            data: dataPts,
            showLine: true,
            borderColor: "#38bdf8",
            backgroundColor: "rgba(56, 189, 248, 0.2)",
            fill: true,
            tension: 0.15,
            pointRadius: 3,
          },
          {
            label: "Garis Acak (AUC = 0.500)",
            data: [
              { x: 0, y: 0 },
              { x: 1, y: 1 },
            ],
            showLine: true,
            borderColor: "#64748b",
            borderDash: [5, 5],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: 1,
            title: {
              display: true,
              text: "False Positive Rate (1 - Specificity)",
              color: "#cbd5e1",
            },
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(148,163,184,0.12)" },
          },
          y: {
            type: "linear",
            min: 0,
            max: 1,
            title: {
              display: true,
              text: "True Positive Rate (Sensitivity / Recall)",
              color: "#cbd5e1",
            },
            ticks: { color: "#94a3b8" },
            grid: { color: "rgba(148,163,184,0.12)" },
          },
        },
        plugins: {
          legend: {
            labels: { color: "#cbd5e1", font: { size: 11 } },
          },
        },
      },
    });
  }

  return {
    animateCountUp,
    renderCityDonutChart,
    renderKecamatanContributionChart,
    renderRocCurveChart,
  };
})();

