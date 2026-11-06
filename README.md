# SIPEKA-Banjir 3D — Sistem Pemetaan Kerawanan Banjir Kota Pekanbaru

**Judul Penelitian / Skripsi:**
> *Analisis Kerawanan Banjir Menggunakan Metode Overlay Berbasis Sistem Informasi Geografis di Kota Pekanbaru*

**Metode:** Multi-Criteria Evaluation (MCE) dengan **Weighted Overlay** pada grid raster **30 m × 30 m** (tanpa ketergantungan pada aplikasi desktop QGIS).

**Wilayah Kajian (15 Kecamatan Kota Pekanbaru):**
Bukit Raya, Lima Puluh, Marpoyan Damai, Payung Sekaki, Pekanbaru Kota, Rumbai, Rumbai Barat, Rumbai Timur, Sail, Senapelan, Sukajadi, Tuah Madani, Bina Widya, Tenayan Raya, dan Kulim.

---

## 1. Fitur Utama

1. **Alur Kerja Terpandu 6 Langkah (Stepper UX):**
   - **Langkah 1 (Upload Data):** Kartu *drag-and-drop* untuk 5 input wajib + 1 input validasi opsional, lengkap dengan validasi CRS, perbaikan geometri otomatis (`shapely.make_valid`), deteksi overlap batas kota, dan mosaic otomatis multi-lembar DEMNAS.
   - **Langkah 2 (Parameter, Bobot & Skoring):** Slider bobot (wajib berjumlah tepat 100%), tabel batas kelas kontinu yang dapat diedit, pemetaan kelas tutupan lahan → skor (1–5) dengan deteksi kelas belum terpetakan, filter sungai, serta panel Daftar Asumsi Metodologis.
   - **Langkah 3 (Hitung Kerawanan):** Tombol eksekusi 1-klik dengan indikator kemajuan bertahap dan *caching* raster 5 parameter untuk *recalculate* bobot super cepat (< 2 detik).
   - **Langkah 4 (Hasil 3D & Dasbor Statistik):**
     - **Peta 3D Interaktif (MapLibre GL JS):** Terrain 3D dari DEMNAS (Terrain-RGB), *hillshade*, slider eksagerasi relief, overlay kelas kerawanan (Hijau/Kuning/Merah) maupun skor masing-masing parameter, batas 15 kecamatan, sungai, titik validasi, pencarian koordinat/kecamatan, **Tur Otomatis**, dan popup inspeksi titik lengkap dengan **Faktor Penyebab Dominan** (`bobot × skor` tertinggi).
     - **Mode Simulasi Banjir 3D & Hujan (Three.js WebGL):** Terrain mesh 3D interaktif dengan **Simulasi Kenaikan Muka Air Sungai (m)**, air 3D semi-transparan reflektif, kalkulasi luas tergenang ($\text{km}^2$), jumlah kecamatan terdampak, persentase genangan di kelas Tinggi, animasi partikel hujan, tombol *Play/Pause* air naik, serta klik sel 3D.
     - **Dasbor Statistik:** Animasi *count-up* angka ringkasan, *Donut Chart* luas kelas (Ha & %), tabel interaktif 15 kecamatan (dapat disortir, difilter, dan diklik untuk *fly-to*), serta grafik batang bertumpuk kontribusi parameter per kecamatan.
   - **Langkah 5 (Validasi & Analisis Sensitivitas):**
     - **Mode A:** *Confusion Matrix* 3×3 (*Rendah, Sedang, Tinggi*), *Overall Accuracy* (Persamaan 3.5 Bab III, valid bila $\ge 80\%$), *Cohen's Kappa*, *Producer's Accuracy*, dan *User's Accuracy*.
     - **Mode B:** Persentase titik banjir historis yang jatuh pada kelas *Sedang/Tinggi* dan *Tinggi* saja, ditambah *Precision, Recall, F1-Score*, dan kurva **AUC-ROC** (jika kolom `label` 1/0 tersedia).
     - **Analisis Sensitivitas OAT ($\pm 5\%$):** Mengubah tiap bobot parameter sebesar $\pm 5$ poin persen (bobot lain disesuaikan proporsional ke 100%) dan melaporkan perubahan persen luas kelas Tinggi ($\Delta\%$) serta perubahan akurasi ($\Delta\%$).
     - **Riwayat Kalibrasi:** Menyimpan log setiap percobaan kombinasi bobot dan akurasinya untuk lampiran skripsi.
   - **Langkah 6 (Ekspor & Laporan):**
     - **GeoTIFF (`EPSG:32647`, kompresi LZW):** Raster Skor $S$, raster Kelas (1/2/3), dan 5 raster skor parameter.
     - **Shapefile (`.zip`) & GeoPackage (`.gpkg`):** Poligon kelas ter-*dissolve* dengan atribut `KELAS` dan `LUAS_HA`, dilengkapi filter luas minimum (default 1 Ha untuk menghilangkan poligon 1 piksel) dan opsi *smoothing*.
     - **Laporan Excel (`.xlsx`):** Multi-sheet berisi ringkasan kota, tabel 15 kecamatan, parameter & bobot, validasi, sensitivitas, dan riwayat kalibrasi.
     - **Layout Peta Kartografis Resmi (`.pdf` & `.png`):** Judul standar skripsi, legenda Hijau/Kuning/Merah, skala batang, panah utara, grid koordinat UTM 47N, peta inset posisi Kota Pekanbaru di Provinsi Riau, sumber data, Tahun 2026.
     - **Tangkapan Layar 3D (`.png`)** & **`metadata.json`** untuk reproduksibilitas penuh.

---

## 2. Cara Instalasi dan Menjalankan Aplikasi

### Prasyarat
- Python 3.11+ (kompatibel hingga Python 3.14)
- Browser modern dengan dukungan WebGL (Chrome, Edge, Firefox)

### Langkah Instalasi
```bash
# 1. Masuk ke direktori proyek
cd d:\SIPEKA-BANJIR

# 2. Instal seluruh dependensi Python
pip install -r requirements.txt
```

### Menjalankan Aplikasi (Satu Perintah)
```bash
python run.py
```
Setelah server berjalan, buka browser dan akses:
👉 **`http://localhost:8000`**

### Menjalankan Pengujian Otomatis (`pytest`)
```bash
pytest tests/ -v
```

---

## 3. Catatan Penting Sistem Koordinat: UTM Zona 47N (`EPSG:32647`) vs Zona 48N

Dokumen proposal awal menyebutkan proyeksi UTM Zona 48N. Namun secara geografis:
- **Kota Pekanbaru** terletak pada koordinat **$101^\circ 14' \text{ BT} - 101^\circ 34' \text{ BT}$** dan **$0^\circ 25' \text{ LU} - 0^\circ 45' \text{ LU}$**.
- Dalam pembagian zona Universal Transverse Mercator (UTM), **Zona 47N mencakup rentang bujur $96^\circ \text{ BT} - 102^\circ \text{ BT}$**, sedangkan Zona 48N baru dimulai dari $102^\circ \text{ BT} - 108^\circ \text{ BT}$.
- Oleh sebab itu, aplikasi ini menetapkan **`TARGET_EPSG = 32647` (WGS 84 / UTM Zone 47N)** di `backend/core/config.py` sebagai sistem koordinat referensi utama agar perhitungan jarak Euclidean sungai (meter), kemiringan lereng Horn 3×3 (%), dan luas wilayah (hektar) bebas dari distorsi batas zona.

---

## 4. Sumber Data & Format Kolom Input

| No | Layer Input | Sumber Instansi Resmi | Format File | Ketentuan Atribut / Kolom |
|---|---|---|---|---|
| 1 | **DEMNAS** (Elevasi) | Badan Informasi Geospasial (BIG) | GeoTIFF (`.tif`) | Elevasi dalam meter di atas permukaan laut (mdpl). Mendukung upload banyak *tile* (mosaic otomatis). |
| 2 | **Batas Administrasi 15 Kecamatan** | Bappeda Kota Pekanbaru / BIG (RBI) | `.zip` (SHP) / `.gpkg` | Poligon 15 kecamatan. Pilih kolom nama kecamatan pada dropdown UI. |
| 3 | **Jaringan Sungai** | BIG (Peta RBI) / BWS Sumatera III | `.zip` (SHP) / `.gpkg` | Garis Sungai Siak & anak sungai. Jika berupa poligon, sistem otomatis mengekstrak garis tepinya (`boundary`). |
| 4 | **Data Curah Hujan** | BMKG Provinsi Riau | `.csv` / `.xlsx` | Wajib memuat kolom: `stasiun, lat, lon, tahun, hujan_mm` (atau kolom `tanggal` untuk data harian/bulanan yang akan dijumlahkan otomatis per tahun). |
| 5 | **Tutupan / Penggunaan Lahan** | Bappeda / KLHK | `.zip` (SHP) / `.gpkg` | Poligon tutupan lahan. Pilih kolom kelas lahan pada dropdown UI. |
| 6 | **Titik Banjir Historis** | BPBD Kota Pekanbaru / Survei Lapangan | `.csv` / `.xlsx` | Kolom wajib: `lat, lon`. Kolom opsional: `kelas_lapangan` (`Rendah`/`Sedang`/`Tinggi` untuk Mode A) dan `label` (`1`/`0` untuk evaluasi biner & AUC-ROC Mode B). |

### Contoh Format CSV Curah Hujan (`curah_hujan.csv`)
```csv
stasiun,lat,lon,tahun,hujan_mm
Stasiun Meteo SSK II Pekanbaru,0.460785,101.445120,2024,3180.5
Stasiun Klimatologi Senapelan,0.531420,101.438910,2024,3540.0
Pos Hujan Payung Sekaki,0.521100,101.401200,2024,3390.2
```

### Contoh Format CSV Titik Banjir Historis (`titik_banjir.csv`)
```csv
id,lokasi,kecamatan,lat,lon,kelas_lapangan,label
1,Jl. Sudirman Ujung,Pekanbaru Kota,0.531240,101.446120,Tinggi,1
2,Kel. Tirta Siak,Payung Sekaki,0.528910,101.412340,Sedang,1
3,Bukit Rumbai Utara,Rumbai,0.581200,101.441100,Rendah,0
```

---

## 5. Penjelasan Rumus & Metodologi Skoring

### A. Parameter & Bobot Skripsi
Setiap parameter direklasifikasi ke dalam skor kerawanan **1 (Paling Aman)** hingga **5 (Paling Rawan)**:

1. **Curah Hujan Tahunan ($\text{CH}$, Bobot $0,25$):**
   - Rata-rata curah hujan tahunan per stasiun diinterpolasi ke grid 30 m menggunakan **Inverse Distance Weighting (IDW)** berpangkat $p = 2$:
     $$Z(x, y) = \frac{\sum_{i=1}^{N} d_i^{-2} z_i}{\sum_{i=1}^{N} d_i^{-2}}$$
   - Kelas Skor: $< 2.000 \rightarrow 1$; $2.000–2.500 \rightarrow 2$; $2.500–3.000 \rightarrow 3$; $3.000–3.500 \rightarrow 4$; $\ge 3.500 \text{ mm/thn} \rightarrow 5$.
2. **Kemiringan Lereng ($\text{Slope}$, Bobot $0,25$):**
   - Dihitung dalam satuan **persen (%)** dari DEMNAS 30 m menggunakan operator **Horn 3×3** dengan ukuran sel nyata ($\Delta x = \Delta y = 30\text{ m}$).
   - Kelas Skor (Van Zuidam 1985 / Permenhut P.32/2009): $0–8\% \rightarrow 5$; $8–15\% \rightarrow 4$; $15–25\% \rightarrow 3$; $25–40\% \rightarrow 2$; $\ge 40\% \rightarrow 1$.
3. **Elevasi ($\text{Elev}$, Bobot $0,20$):**
   - Kelas Skor: $< 10\text{ mdpl} \rightarrow 5$; $10–20 \rightarrow 4$; $20–35 \rightarrow 3$; $35–50 \rightarrow 2$; $\ge 50\text{ mdpl} \rightarrow 1$.
4. **Penggunaan Lahan ($\text{LU}$, Bobot $0,15$):**
   - Hutan/Rawa ($C < 0,20$) $\rightarrow 1$; Perkebunan/Semak ($C\ 0,20–0,35$) $\rightarrow 2$; Lahan Terbuka/Tegalan ($C\ 0,35–0,50$) $\rightarrow 3$; Permukiman Jarang/Industri ($C\ 0,50–0,70$) $\rightarrow 4$; Permukiman Padat/Lahan Terbangun Komersial ($C\ 0,70–0,90$) $\rightarrow 5$.
5. **Jarak terhadap Sungai ($\text{Riv}$, Bobot $0,15$):**
   - Dihitung menggunakan transformasi jarak Euclidean (`scipy.ndimage.distance_transform_edt(sampling=30)`).
   - Kelas Skor: $0–250\text{ m} \rightarrow 5$; $250–500\text{ m} \rightarrow 4$; $500–750\text{ m} \rightarrow 3$; $750–1.000\text{ m} \rightarrow 2$; $\ge 1.000\text{ m} \rightarrow 1$.

### B. Rumus Weighted Overlay & Ambang Klasifikasi Eksak
$$S = 0,25 \cdot \text{CH} + 0,25 \cdot \text{Slope} + 0,20 \cdot \text{Elev} + 0,15 \cdot \text{LU} + 0,15 \cdot \text{Riv}$$

Lebar kelas *Equal Interval* untuk 3 tingkat kerawanan:
$$I = \frac{5 - 1}{3} = \frac{4}{3} \approx 1,3333$$

Ambang klasifikasi menggunakan pecahan eksak **`7/3`** dan **`11/3`** tanpa pembulatan prematur:
- **Rendah (Kode 1 — Hijau `#22c55e`):** $1,00 \le S < \frac{7}{3}$ ($1,00 \le S < 2,33$)
- **Sedang (Kode 2 — Kuning `#eab308`):** $\frac{7}{3} \le S < \frac{11}{3}$ ($2,33 \le S < 3,67$)
- **Tinggi (Kode 3 — Merah `#ef4444`):** $\frac{11}{3} \le S \le 5,00$ ($3,67 \le S \le 5,00$)

### C. Rumus Validasi Akurasi (Persamaan 3.5 Bab III)
$$\text{Akurasi Keseluruhan (\%)} = \frac{\sum \text{Titik Sesuai}}{\text{Total Titik Sampel}} \times 100\%$$
Model dinyatakan **Valid** apabila nilai akurasi keseluruhan mencapai **$\ge 80\%$** (dengan jumlah sampel minimal 50 titik).

---

## 6. Daftar Asumsi Metodologis

1. **Interval Kelas Curah Hujan Tengah:** Kelas tengah ($2.500$, $3.000$, $3.500\text{ mm/tahun}$) diasumsikan berinterval $500\text{ mm}$ karena dokumen proposal hanya mencantumkan batas ekstrem kelas 1 ($< 2.000\text{ mm}$) dan kelas 5 ($> 3.500\text{ mm}$).
2. **Konvensi Batas Kelas Kontinu:** Seluruh reklasifikasi memakai aturan batas bawah inklusif dan batas atas eksklusif $[\text{min}, \text{max})$, kecuali kelas teratas.
3. **Eksponen Interpolasi IDW:** Interpolasi curah hujan menggunakan pangkat (*power*) $= 2$.
4. **Kriteria Kecocokan Validasi Mode B:** Pada data yang hanya memuat titik kejadian banjir historis tanpa atribut kelas lapangan, titik dianggap sesuai apabila jatuh pada zona kerawanan **Sedang** atau **Tinggi** (disertai pelaporan proporsi yang jatuh di kelas **Tinggi** saja, dengan catatan bahwa mode ini tidak menguji kelas Rendah).
5. **Pemetaan Eksplisit Kelas Lahan:** Kelas tutupan lahan yang belum ada di kamus standar wajib diputuskan skornya (1–5) oleh pengguna di Langkah 2 dan tidak pernah diberi skor secara diam-diam.
6. **Simulasi Muka Air 3D (*Bathtub Model*):** Simulasi kenaikan muka air pada mode Three.js merupakan simulasi genangan berbasis elevasi relatif terhadap muka air sungai, bukan pemodelan hidrodinamika aliran 1D/2D.

---

## 7. Struktur Proyek
```text
SIPEKA-BANJIR/
├── run.py                       # Peluncur aplikasi satu perintah (http://localhost:8000)
├── requirements.txt             # Daftar pustaka Python
├── README.md                    # Dokumentasi lengkap metodologi & penggunaan
├── backend/
│   ├── main.py                  # REST API FastAPI & penyaji static files frontend
│   └── core/
│       ├── config.py            # Konfigurasi EPSG:32647, bobot, tabel skor, & daftar asumsi
│       ├── preprocess.py        # Reproject, make_valid, grid 30m, clip, & bilinear DEM
│       ├── parameters.py        # IDW p=2, Slope Horn 3x3, Elevasi, Lahan, & Euclidean Sungai
│       ├── overlay.py           # Weighted Overlay & klasifikasi eksak 7/3 dan 11/3
│       ├── zonal.py             # Statistik kota & peringkat 15 Kecamatan Kota Pekanbaru
│       ├── validation.py        # Validasi Mode A/B, Kappa, ROC-AUC, & Sensitivitas ±5%
│       ├── export.py            # Ekspor GeoTIFF, GPKG/SHP, Excel, Peta PDF/PNG, & 3D Mesh
│       └── demo.py              # Generator dataset sintetis 15 Kecamatan Kota Pekanbaru
├── frontend/
│   ├── index.html               # Antarmuka utama SPA 6 langkah (Dark/Light Glassmorphism)
│   ├── css/
│   │   └── styles.css           # Desain visual glassmorphism responsif
│   └── js/
│       ├── app.js               # Pengendali state, stepper, upload, bobot, & validasi
│       ├── map3d.js             # Peta 3D MapLibre GL JS, Terrain-RGB, popup, & Tur Otomatis
│       ├── sim3d.js             # Simulasi Banjir 3D & Hujan Partikel Three.js WebGL
│       └── charts.js            # Grafik Donut, Kontribusi Parameter, ROC Curve, & Count-up
├── sample_data/                 # Direktori penyimpanan data demo sintetis
└── tests/
    ├── test_core.py             # Pengujian unit metodologi & matematika GIS (Tes #1 - #10)
    └── test_api.py              # Pengujian integrasi endpoint FastAPI & ekspor (Tes #11)
```

