# PROMPT ANTIGRAVITY (VERSI LENGKAP, HTML 3D): SIPEKA-Banjir 3D

Salin semua isi di bawah garis ini ke Antigravity.

---

## PERAN
Kamu adalah senior GIS developer, Python backend engineer, dan frontend creative developer. Bangun aplikasi web lengkap bernama **"SIPEKA-Banjir 3D"** (Sistem Pemetaan Kerawanan Banjir Kota Pekanbaru) dengan tampilan **HTML modern, interaktif, dan 3D yang "wow"**. Pengguna cukup meng-upload data, menekan satu tombol, lalu sistem menghitung dan menampilkan daerah rawan banjir dalam peta 3D, lengkap dengan simulasi kenaikan muka air. Seluruh logika harus mengikuti metodologi skripsi di bawah secara literal. Jangan mengganti bobot, skor, atau rumus tanpa diminta.

## JUDUL & METODE (JANGAN DIUBAH)
Judul: *Analisis Kerawanan Banjir Menggunakan Metode Overlay Berbasis Sistem Informasi Geografis di Kota Pekanbaru*.
Metode: Multi-Criteria Evaluation (MCE) dengan **Weighted Overlay** pada raster. Wilayah: 15 kecamatan Kota Pekanbaru (Bukit Raya, Lima Puluh, Marpoyan Damai, Payung Sekaki, Pekanbaru Kota, Rumbai, Rumbai Barat, Rumbai Timur, Sail, Senapelan, Sukajadi, Tuah Madani, Bina Widya, Tenayan Raya, Kulim).

## ARSITEKTUR & TECH STACK
- **Backend:** Python 3.11 + **FastAPI** + Uvicorn. Library: `rasterio`, `geopandas`, `shapely`, `pyproj`, `numpy`, `scipy`, `pandas`, `scikit-learn`, `openpyxl`, `matplotlib`, `pytest`. Tidak bergantung pada QGIS.
- **Frontend:** satu aplikasi HTML/CSS/JavaScript (tanpa framework berat, boleh Vanilla JS modular). Library via npm atau CDN dengan versi dipin:
  - **MapLibre GL JS** untuk peta 3D (terrain, hillshade, fill-extrusion, atau layer raster kelas di atas terrain).
  - **Three.js** untuk mode "Simulasi 3D" (terrain mesh dari DEM, air 3D, hujan partikel).
  - **Chart.js** atau D3 untuk grafik statistik.
- Backend menyajikan frontend sebagai static files. Jalankan dengan satu perintah: `python run.py` lalu buka `http://localhost:8000`.
- Struktur proyek: `run.py`, `backend/` (main.py, core/{config,preprocess,parameters,overlay,zonal,validation,export,demo}.py), `frontend/` (index.html, css/, js/), `tests/`, `sample_data/`, `requirements.txt`, `README.md`.

## ALUR PENGGUNA (UX)
1. **Halaman awal (hero):** judul animasi, tombol **"Mulai Analisis"** dan **"Coba Data Demo"**.
2. **Langkah 1, Upload Data** (stepper di atas): kartu drag-and-drop untuk tiap input dengan status centang hijau atau pesan error.
3. **Langkah 2, Parameter & Bobot:** slider bobot, tabel skor yang bisa diedit, dan tabel pemetaan kelas lahan → skor.
4. **Langkah 3, Hitung:** tombol besar **"HITUNG KERAWANAN BANJIR"** dengan progress per tahap (pra-pengolahan, 5 parameter, overlay, klasifikasi, statistik).
5. **Langkah 4, Hasil 3D:** peta 3D interaktif, panel statistik, simulasi banjir.
6. **Langkah 5, Validasi** dan **Langkah 6, Ekspor.**

## INPUT (Langkah 1)
| No | Input | Format | Wajib | Catatan |
|---|---|---|---|---|
| 1 | DEMNAS | GeoTIFF, boleh banyak lembar (mosaic otomatis) | Ya | Elevasi mdpl |
| 2 | Batas administrasi 15 kecamatan | SHP (ZIP) atau GPKG | Ya | Dropdown untuk memilih kolom nama kecamatan |
| 3 | Jaringan sungai | SHP (ZIP) atau GPKG | Ya | Siak + anak sungai. Jika poligon, ambil garis tepinya |
| 4 | Curah hujan | CSV/XLSX | Ya | Kolom `stasiun, lat, lon, tahun, hujan_mm` (total tahunan), atau data harian/bulanan dengan kolom `tanggal` yang dijumlahkan per tahun |
| 5 | Tutupan/penggunaan lahan | SHP (ZIP) atau GPKG (poligon) | Ya | Pilih kolom kelas lahan |
| 6 | Titik banjir historis | CSV (lat, lon, opsional `kelas_lapangan`, opsional `label`) | Tidak | Untuk validasi |

- Tombol **"Coba Data Demo"** membuat data sintetis (DEM, sungai berkelok, stasiun hujan, poligon lahan) agar seluruh alur bisa diuji tanpa data asli. Beri label jelas "DATA DEMO, bukan hasil sungguhan".
- Validasi otomatis: CRS hilang, geometri invalid (perbaiki dengan `make_valid`), layer tidak overlap dengan batas kota, DEM penuh nodata, stasiun hujan < 3, data hujan < 10 tahun (peringatan, jangan blokir).

## PRA-PENGOLAHAN (core/preprocess.py)
1. **CRS target: WGS 84 / UTM Zone 47N (EPSG:32647).** Catatan: proposal menyebut zona 48N, tetapi Pekanbaru (101°14'–101°34' BT) berada di zona 47N. Simpan sebagai `TARGET_EPSG = 32647` di `config.py` dan jelaskan di README.
2. Reproject semua layer, lalu clip ke batas kota (union 15 kecamatan).
3. Grid acuan **30 m x 30 m** dengan extent batas kota. Semua raster harus identik shape, transform, dan CRS. DEM di-resample bilinear.
4. Piksel di luar batas kota bernilai nodata dan tidak ikut statistik.

## PARAMETER & SKORING (core/parameters.py)
Semua tabel skor ada di `config.py` dan **dapat diedit di UI**. Nilai default adalah nilai skripsi. Skor 5 = paling rawan, 1 = paling aman. Aturan batas kelas: batas bawah inklusif, batas atas eksklusif (kecuali kelas teratas).

**A. Curah hujan (bobot 0,25):** rata-rata tahunan (mm/tahun) per stasiun → interpolasi **IDW** (pangkat 2) ke grid 30 m → reklasifikasi: `< 2.000 → 1`, `2.000–2.500 → 2`, `2.500–3.000 → 3`, `3.000–3.500 → 4`, `> 3.500 → 5`. (Asumsi: kelas tengah berinterval 500 mm, karena proposal hanya menyebut kelas 1 dan 5.) Jika stasiun < 4 atau variasi antar-stasiun kecil, tampilkan peringatan bahwa parameter ini kurang membedakan wilayah.

**B. Kemiringan lereng (bobot 0,25):** slope **persen** dari DEM dengan metode Horn 3x3 memakai ukuran sel nyata (meter). Reklasifikasi (Van Zuidam 1985 / Permenhut P.32/2009): `> 40% → 1`, `25–40% → 2`, `15–25% → 3`, `8–15% → 4`, `0–8% → 5`.

**C. Elevasi (bobot 0,20):** `> 50 mdpl → 1`, `35–50 → 2`, `20–35 → 3`, `10–20 → 4`, `< 10 → 5`.

**D. Penggunaan lahan (bobot 0,15):** poligon → raster 30 m berdasarkan skor. Pemetaan default (editable): Hutan/Rawa → 1 (C < 0,20); Perkebunan/Semak → 2 (C 0,20–0,35); Lahan terbuka/Tegalan → 3 (C 0,35–0,50); Permukiman jarang/Industri → 4 (C 0,50–0,70); Permukiman padat/Lahan terbangun komersial → 5 (C 0,70–0,90). Setelah upload, tampilkan semua nilai unik kolom lahan dengan dropdown skor 1–5. Kelas yang belum dipetakan harus diberi peringatan, jangan diberi skor diam-diam.

**E. Jarak terhadap sungai (bobot 0,15):** rasterisasi garis sungai, lalu jarak Euclidean (meter) memakai `scipy.ndimage.distance_transform_edt(sampling=30)` (setara multi-ring buffer). Skor: `0–250 m → 5`, `250–500 → 4`, `500–750 → 3`, `750–1.000 → 2`, `> 1.000 → 1`. Opsi memilih sungai yang dipakai (Siak, Sail, Air Hitam, Senapelan, Sago, Sibam, Tenayan, Umban Sari) jika ada kolom nama.

## WEIGHTED OVERLAY (core/overlay.py)
```
S = 0,25·CH + 0,25·Slope + 0,20·Elev + 0,15·LU + 0,15·Riv
```
- Bobot editable via slider. **Total harus tepat 100%**; jika tidak, tombol Hitung nonaktif dan tampilkan selisihnya.
- Klasifikasi equal interval: `I = (5 − 1) / 3 = 1,333`. Gunakan ambang eksak `7/3` dan `11/3` (jangan dibulatkan):
  - Rendah: `1,00 ≤ S < 2,33` → **hijau**
  - Sedang: `2,33 ≤ S < 3,67` → **kuning**
  - Tinggi: `3,67 ≤ S ≤ 5,00` → **merah**
- Simpan raster S (float32) dan raster kelas (1/2/3), serta 5 raster skor parameter.
- Recalculate ringan: cache raster skor 5 parameter. Saat bobot berubah, backend hanya menghitung ulang overlay dan klasifikasi (target < 2 detik).

## HASIL 3D (Langkah 4), BAGIAN "WOW"
Desain visual: **tema gelap bergaya glassmorphism** (panel transparan dengan blur, aksen cyan #38bdf8), tipografi bersih, animasi halus, responsif untuk laptop dan ponsel. Dukung mode terang melalui `prefers-color-scheme`.

**A. Peta 3D (MapLibre):**
- Terrain 3D dari DEMNAS (konversi ke Terrain-RGB/tiles lokal oleh backend), hillshade, dan exaggeration slider.
- Overlay kelas kerawanan (hijau/kuning/merah) di atas terrain dengan opacity yang bisa diatur, batas 15 kecamatan dengan label, dan sungai.
- Kamera: pitch/bearing bebas, tombol **"Tur Otomatis"** (fly-to ke tiap kecamatan paling rawan), tombol reset kamera, basemap OSM dan citra satelit.
- Mode tampilan (dropdown): Kelas, Skor S, dan masing-masing skor 5 parameter.
- **Klik peta**: popup berisi kecamatan, elevasi, lereng, curah hujan, jarak sungai, skor tiap parameter, S, kelas, dan **faktor penyebab dominan** (parameter dengan kontribusi `bobot × skor` tertinggi).
- Kolom pencarian koordinat/kecamatan.

**B. Mode "Simulasi 3D" (Three.js):** tombol untuk berpindah ke tampilan terrain mesh yang bisa diputar:
- Mesh dari DEM (downsample otomatis ke ±250x250 sel untuk performa), vertex diberi warna sesuai kelas.
- **Simulasi kenaikan muka air:** slider "kenaikan muka air sungai (m)". Air 3D semi-transparan dengan reflektansi; sel dengan elevasi di bawah muka air tergenang. Tampilkan luas tergenang (km²), jumlah kecamatan terdampak, dan persentase genangan yang berada di kelas Tinggi.
- **Animasi hujan** (partikel) dengan toggle, intensitas yang bisa diatur, serta animasi air naik bertahap dengan tombol Play/Pause.
- Auto-rotate, tombol ⟳, dan tinggi relief yang bisa diatur.
- Klik sel untuk melihat skor di titik itu (seperti popup peta).

**C. Dasbor statistik (panel samping):**
- Donut chart luas kelas (ha dan %).
- Tabel 15 kecamatan: luas dan persen tiap kelas, rata-rata S, S maksimum, kelas dominan, dan peringkat kerawanan (urut berdasarkan persen kelas Tinggi, lalu rata-rata S). Bisa disortir dan difilter, dan klik baris akan fly-to ke kecamatan.
- Grafik batang kontribusi tiap parameter terhadap skor rata-rata per kecamatan.
- Hitungan angka naik (count-up animation) untuk angka ringkasan.

## VALIDASI (Langkah 5)
Sesuai Bab III (Persamaan 3.5), minimal 50 titik.
- Ambil kelas model di tiap koordinat titik. **Akurasi keseluruhan (%) = (Σ titik sesuai / total titik) × 100%**. Model valid jika **≥ 80%**; tampilkan lencana hijau (valid) atau merah (belum valid).
- **Mode A** (CSV punya `kelas_lapangan` = Rendah/Sedang/Tinggi): confusion matrix 3x3 (heatmap), overall accuracy, kappa Cohen, producer's dan user's accuracy.
- **Mode B** (hanya titik kejadian banjir): titik sesuai jika jatuh di kelas **Sedang atau Tinggi**; tampilkan juga persen yang jatuh di kelas Tinggi saja. Beri catatan bahwa mode ini tidak menguji kelas Rendah. Jika ada kolom `label` banjir/tidak banjir, hitung juga precision, recall, F1, dan **AUC-ROC** dengan skor S kontinu.
- Titik validasi tampil di peta (hijau = sesuai, merah = tidak sesuai).
- Jika akurasi < 80%, tampilkan tombol **"Kalibrasi Ulang"** (ubah bobot/skor, hitung ulang) dan simpan **riwayat percobaan** (bobot, akurasi) dalam tabel yang bisa diekspor untuk laporan skripsi.
- **Analisis sensitivitas**: ubah tiap bobot ±5 poin (bobot lain disesuaikan proporsional ke 100%), tampilkan perubahan persen luas kelas Tinggi dan akurasi.

## EKSPOR (Langkah 6)
- GeoTIFF (EPSG:32647, LZW): raster S, raster kelas, dan 5 raster skor.
- **SHP/GPKG**: poligon kelas (dissolve per kelas) dengan kolom `KELAS`, `LUAS_HA`. Hindari poligon 1 piksel: filter luas minimum (default 1 ha, bisa diatur) dan opsi smoothing.
- Excel: statistik kecamatan, ringkasan kota, parameter dan bobot, hasil validasi, dan riwayat kalibrasi.
- **Layout peta PDF/PNG**: judul "PETA TINGKAT KERAWANAN BANJIR KOTA PEKANBARU PROVINSI RIAU", legenda hijau/kuning/merah, skala batang, panah utara, grid koordinat UTM 47N, peta inset posisi Pekanbaru di Riau (jika batas Riau tersedia), sumber data, tahun 2026.
- Screenshot tampilan 3D (PNG) dan `metadata.json` (semua parameter, bobot, versi, timestamp) agar hasil bisa direproduksi.

## KUALITAS & PENGUJIAN (tests/)
Tulis `pytest` untuk:
1. Semua skor 5 → S = 5,00 (Tinggi); semua 1 → 1,00 (Rendah); semua 3 → 3,00 (Sedang).
2. Contoh manual: CH=4, Slope=5, Elev=5, LU=3, Riv=2 → S = 0,25·4 + 0,25·5 + 0,20·5 + 0,15·3 + 0,15·2 = **4,00** (Tinggi).
3. Batas kelas: S = 7/3 → Sedang; S = 11/3 → Tinggi; S = 5,00 → Tinggi.
4. Total bobot ≠ 100% ditolak.
5. Reklasifikasi di nilai batas (slope 8/15/25/40%, elevasi 10/20/35/50 m, jarak 250/500/750/1000 m).
6. Slope: bidang miring 10% → ≈ 10%.
7. Jarak sungai: garis lurus dibandingkan dengan jarak analitik.
8. IDW: satu stasiun → seluruh grid sama; di lokasi stasiun nilainya persis nilai stasiun.
9. Total luas tiga kelas = total luas kota (toleransi 1 piksel).
10. Confusion matrix kecil dengan hasil yang dihitung manual.
11. Endpoint API (upload, hitung, hasil, ekspor) dengan data demo.

Semua fungsi memakai type hints dan docstring. Jangan hard-code path. Pesan error harus mudah dipahami pengguna. Proses 1 kota (±700.000 piksel pada 30 m) harus selesai < 60 detik di laptop biasa. Frontend tetap lancar (≥ 30 FPS) untuk mesh simulasi.

## README.md
Cara instal dan menjalankan, sumber data (DEMNAS/BIG, RBI sungai/BIG, BMKG, Bappeda/KLHK, BPBD), format kolom CSV, penjelasan rumus, daftar asumsi, serta catatan CRS 47N vs 48N.

## DAFTAR ASUMSI (tampilkan juga di UI Langkah 2)
1. Interval kelas hujan tengah (2.500, 3.000, 3.500 mm) diasumsikan 500 mm.
2. Batas kelas: bawah inklusif, atas eksklusif (kecuali kelas teratas).
3. IDW pangkat 2.
4. Validasi Mode B menganggap titik banjir sesuai bila jatuh di kelas Sedang/Tinggi.
5. Kelas lahan yang belum dipetakan harus diputuskan pengguna.
6. Simulasi muka air adalah simulasi sederhana berbasis elevasi (bathtub), bukan model hidrodinamika, dan harus diberi catatan itu di UI.

## URUTAN KERJA
1. Buat kerangka proyek, `config.py`, dan modul `demo.py`.
2. Implementasikan `core/` beserta tes. Jalankan `pytest` sampai lulus dan **tunjukkan hasilnya**.
3. Buat API FastAPI dan tes endpoint dengan data demo.
4. Bangun frontend: hero, stepper, upload, bobot, hasil peta 3D MapLibre, mode simulasi Three.js, dasbor, validasi, dan ekspor.
5. Jalankan seluruh alur dengan data demo di browser, perbaiki bug, lalu tulis README.
6. Tampilkan ringkasan: file yang dibuat, cara menjalankan, dan hasil tes.

Kerjakan bertahap dan jangan lanjut ke tahap berikutnya sebelum tahap sebelumnya lulus tes.
