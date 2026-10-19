# yeelight-re

Toolkit reverse engineering dan kontrol **lokal 100% offline** untuk **Yeelight Smart LED Bulb (Color) Generasi 2 — model `YLDP06YL`** (dikenal di ekosistem smart home sebagai `color2`).

Tool ini **tidak pernah login** ke akun Yeelight, Mi Home, atau cloud mana pun. Semua komunikasi berjalan langsung di LAN Anda: discovery SSDP di UDP `1982`, kontrol JSON-RPC di TCP `55443`, dan protokol darurat miIO di UDP `54321`.

> [!NOTE]
> **Karakteristik Utama:**
> - **Zero-dependency**: Murni menggunakan pustaka bawaan Python (Python 3.9+). Bahkan modul AES-128-CBC ditulis murni tanpa `cryptography` / `pycryptodome`.
> - **Siap Pakai**: Tersedia versi aplikasi mandiri Windows (`.exe`) baik untuk Desktop GUI maupun CLI.
> - **Mandiri (No Cloud)**: Mendukung provisioning Wi-Fi tanpa aplikasi HP dan pembukaan port kontrol LAN secara lokal.

---

## Daftar Isi
- [Download & Langsung Pakai (Windows)](#download--langsung-pakai-windows)
- [Status Fitur](#status-fitur)
- [Panduan Penggunaan](#panduan-penggunaan)
  - [1. Desktop GUI (Paling Mudah)](#1-desktop-gui-paling-mudah)
  - [2. Command Line (CLI)](#2-command-line-cli)
  - [3. Pairing Lampu Baru / Ter-reset (Tanpa App HP)](#3-pairing-lampu-baru--ter-reset-tanpa-app-hp)
  - [4. Dashboard Web Lokal](#4-dashboard-web-lokal)
  - [5. Interactive REPL](#5-interactive-repl)
- [Penggunaan sebagai Library Python](#penggunaan-sebagai-library-python)
- [Emulator (Uji Tanpa Hardware)](#emulator-uji-tanpa-hardware)
- [Troubleshooting](#troubleshooting)
- [Struktur Repositori](#struktur-repositori)
- [Build Sendiri (PyInstaller)](#build-sendiri-pyinstaller)
- [Dokumentasi Lanjutan](#dokumentasi-lanjutan)

---

## Download & Langsung Pakai (Windows)

Build portabel siap pakai sudah tersedia di folder `dist\`:

| File | Keterangan |
|---|---|
| [`dist\yeelight-re-gui.exe`](dist/yeelight-re-gui.exe) | **Aplikasi GUI Desktop** (klik dua kali, bertema modern dark, tanpa konsol) |
| [`dist\yeelight-re.exe`](dist/yeelight-re.exe) | **CLI Tool** satu berkas (±6,5 MB, langsung jalan di CMD/PowerShell) |
| [`dist\yeelight-re-0.3.0-win64.zip`](dist/yeelight-re-0.3.0-win64.zip) | Paket zip lengkap berisi GUI, CLI, dan petunjuk pemakaian |

Executable ini **tidak membutuhkan instalasi Python, akun, atau koneksi internet**.

> [!TIP]
> Karena executable dibuat lokal dan belum ditandatangani sertifikat berbayar, Windows SmartScreen mungkin menampilkan peringatan saat pertama kali dijalankan. Klik **More info** → **Run anyway**.

---

## Status Fitur

| Bagian | Status | Deskripsi |
|---|:---:|---|
| **Desktop GUI** | ✅ Jalan | Antarmuka visual lengkap (Power, Brightness, Color Picker, Scenes, Flow, Music) |
| **Discovery SSDP & Subnet Scan** | ✅ Jalan | Deteksi multicast UDP 1982 & scanner port TCP 55443 |
| **Kontrol Lokal Persisten** | ✅ Jalan | JSON-RPC di TCP 55443 dengan penanganan event asinkron |
| **Music Mode** | ✅ Jalan | Mode streaming low-latency via UDP (melewati kuota 60 cmd/menit) |
| **Provisioning Wi-Fi (Tanpa App)** | ✅ Jalan | Hubungkan lampu baru/ter-reset ke Wi-Fi rumah via miIO (`wifi-setup`) |
| **Unlock LAN Control (miIO)** | ✅ Jalan | Membuka TCP 55443 via `set_ps cfg_lan_ctrl=1` tanpa aplikasi resmi |
| **Local Web Dashboard** | ✅ Jalan | Dashboard browser mandiri di `http://127.0.0.1:8765/` |
| **Bulb In-Process Emulator** | ✅ Jalan | Mensimulasikan bulb lengkap untuk pengembangan tanpa lampu fisik |
| **Unit & Integration Tests** | ✅ Lulus | 32 skenario pengujian dengan cakupan AES, protocol, client, dan miIO |

---

## Panduan Penggunaan

### 1. Desktop GUI (Paling Mudah)

Cukup klik dua kali [`dist\yeelight-re-gui.exe`](dist/yeelight-re-gui.exe).

```text
+------------------------------------------------------------------------+
|  yeelight-re                 YLDP06YL · kontrol lokal       [Terhubung] |
+------------------------------------------------------------------------+
| IP: [192.168.1.8     ] Port: [55443]  [Cari bulb] [Hubungkan]           |
|                                        [Unlock LAN] [Pairing Wi-Fi]     |
+------------------------------------------------------------------------+
| [ Kontrol ]  [ Efek & Preset ]  [ miIO & Diagnosa ]  [ Info & Raw ]    |
|                                                                        |
|  * Power Toggle & Slider Kecerahan 1-100%                              |
|  * Color Picker Interaktif, Swatch Palet, & Slider Suhu Warna (CT)     |
|  * Preset Scene (Reading, Movie, Candle, Night Mode)                   |
|  * Preset Animasi Flow Warna Berputar                                  |
|  * Live Activity Event Log                                             |
+------------------------------------------------------------------------+
```

1. Klik tombol **Cari bulb** untuk mendeteksi IP lampu secara otomatis, atau masukkan IP manual.
2. Klik **Hubungkan**.
3. Jika port kontrol lampu masih terkunci, klik **Unlock LAN (miIO)**.

---

### 2. Command Line (CLI)

Semua perintah dapat dijalankan menggunakan executable `.\dist\yeelight-re.exe` atau lewat Python:

```powershell
# Jalankan dari source:
python -m yeelight_re [command]

# Atau install ke environment lokal:
pip install -e .
yeelight-re [command]
```

#### A. Menemukan Lampu
```powershell
# Pencarian cepat via multicast SSDP
yeelight-re discover

# Pencarian alternatif dengan pemindaian subnet
yeelight-re scan --subnet 192.168.1.0/24
```

#### B. Diagnosa Kondisi Jaringan & Lampu
```powershell
yeelight-re doctor --ip 192.168.1.8
```

#### C. Kontrol Dasar
```powershell
# Cek status
yeelight-re status --ip 192.168.1.8

# Power
yeelight-re on --ip 192.168.1.8
yeelight-re off --ip 192.168.1.8
yeelight-re toggle --ip 192.168.1.8

# Kecerahan (1-100%)
yeelight-re bright 60 --ip 192.168.1.8

# Warna RGB (#HEX, r,g,b, atau desimal)
yeelight-re color "#ff6600" --ip 192.168.1.8
yeelight-re color "0,200,255" --bright 80 --ip 192.168.1.8

# Suhu Warna Putih (1700 K - 6500 K)
yeelight-re ct 3200 --ip 192.168.1.8

# Hue & Saturation (HSV)
yeelight-re hsv 200 80 --ip 192.168.1.8
```

#### D. Preset Scene & Animasi (Flow)
```powershell
# Lihat daftar preset
yeelight-re scene --list
yeelight-re flow --list

# Terapkan scene
yeelight-re scene movie --ip 192.168.1.8

# Jalankan animasi flow
yeelight-re flow party --ip 192.168.1.8
yeelight-re flow candle --ip 192.168.1.8
```

---

### 3. Pairing Lampu Baru / Ter-reset (Tanpa App HP)

Jika saklar lampu dimatikan-nyalakan 5 kali berturut-turut, lampu akan ter-reset ke setelan pabrik dan memancarkan hotspot Wi-Fi sendiri (misalnya `yeelink-light-color2_miapXXXX`).

**Anda tidak perlu menginstal aplikasi resmi Yeelight / Mi Home di HP!**

1. Sambungkan Wi-Fi laptop/PC Anda ke hotspot lampu tersebut (`yeelink-light-...`).
2. Jalankan salah satu cara di bawah:

**Lewat GUI:**
- Buka `yeelight-re-gui.exe`.
- Klik tombol **`Pairing Wi-Fi (Reset)`**.
- Masukkan nama Wi-Fi rumah (2.4 GHz) dan password-nya.

**Lewat CLI:**
```powershell
yeelight-re wifi-setup --ssid "NamaWiFiRumah" --password "PasswordWiFi"
```

3. Lampu otomatis menerima konfigurasi, mengaktifkan fitur LAN Control, mematikan hotspotnya, dan bergabung ke router Wi-Fi rumah Anda.
4. Sambungkan kembali laptop Anda ke Wi-Fi rumah, lalu jalankan `yeelight-re scan`.

---

### 4. Dashboard Web Lokal

Buka kontrol lampu berbasis browser yang ringan tanpa internet:

```powershell
yeelight-re web --ip 192.168.1.8 --open
```

Akses melalui browser di `http://127.0.0.1:8765/`.

---

### 5. Interactive REPL

Untuk sesi kontrol cepat interaktif:

```powershell
yeelight-re repl --ip 192.168.1.8
```
```text
yeelight> on
yeelight> bright 80
yeelight> color #00e5ff
yeelight> ct 4000
yeelight> status
yeelight> quit
```

---

## Penggunaan sebagai Library Python

Pustaka ini dapat diintegrasikan langsung ke dalam skrip Python atau automasi Anda sendiri:

```python
from yeelight_re import YeelightClient, discover

# Temukan perangkat pertama di LAN
devices = discover()
if not devices:
    raise SystemExit("Lampu tidak ditemukan!")

bulb_ip = devices[0].ip

with YeelightClient(bulb_ip) as bulb:
    print("Status:", bulb.status())
    bulb.set_power(True)
    bulb.set_bright(75)
    bulb.set_rgb(0x00FF99)
```

Contoh lebih lengkap tersedia di [examples/control.py](examples/control.py).

---

## Emulator (Uji Tanpa Hardware)

Anda dapat menguji seluruh fungsi tanpa memiliki lampu fisik:

**Jalankan Emulator di Terminal 1:**
```powershell
python -m yeelight_re.fake_bulb --port 55443 --ssdp --miio
```

**Jalankan Perintah di Terminal 2:**
```powershell
yeelight-re status --ip 127.0.0.1
yeelight-re color "#ff0055" --ip 127.0.0.1
yeelight-re gui --ip 127.0.0.1
```

---

## Troubleshooting

| Gejala | Kemungkinan Penyebab | Solusi |
|---|---|---|
| `TCP 55443: connection refused` | Lampu dalam mode hotspot (AP) atau LAN Control belum ON | Jika lampu memancarkan Wi-Fi `_miap`, lakukan [Pairing Wi-Fi](#3-pairing-lampu-baru--ter-reset-tanpa-app-hp). Jika sudah terhubung router, jalankan `yeelight-re miio --ip IP --enable`. |
| `timed out` saat koneksi | IP berubah karena DHCP atau beda subnet | Jalankan `yeelight-re scan` untuk menemukan IP terbaru lampu, atau atur *DHCP Reservation* di router. |
| SSDP tidak menemukan lampu | Router memblokir multicast UDP | Gunakan perintah scan subnet: `yeelight-re scan --subnet 192.168.1.0/24`. |
| Perintah ditolak / lampu tidak merespons | Batas koneksi maksimal tercapai | Firmware Yeelight membatasi maksimal 4 koneksi TCP aktif simultan. Tutup instance GUI atau skrip yang menggantung. |
| SmartScreen memblokir `.exe` | Binary belum ditandatangani digital | Klik **More info** → **Run anyway**. Source code lengkap tersedia di repositori ini untuk diverifikasi. |

Detail arsitektur dan penanganan lebih mendalam tersedia di:
- [docs/TANPA-LOGIN.md](docs/TANPA-LOGIN.md) — Panduan bypass akun dan skenario pembebasan cloud.
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — Rincian spesifikasi protokol LAN Yeelight & miIO.
- [docs/HARDWARE.md](docs/HARDWARE.md) — Panduan teardown, pinout UART, dump, dan firmware pihak ketiga.

---

## Struktur Repositori

```text
yeelight-re/
├── yeelight_re/             # Pustaka utama
│   ├── protocol.py          # Definisi protokol LAN & parser JSON-RPC
│   ├── client.py            # Client koneksi persistent TCP & music mode
│   ├── discovery.py         # SSDP multicast discovery & subnet scanner
│   ├── miio.py              # Protokol miIO (handshake, unlock, & wifi-setup)
│   ├── _aes.py              # Implementasi AES-128 murni Python (zero-dependency)
│   ├── fake_bulb.py         # Emulator lampu in-process
│   ├── presets.py           # Preset scene & animasi flow
│   ├── cli.py               # Antarmuka Command Line & REPL
│   ├── web.py               # Dashboard web lokal
│   └── gui.py               # Aplikasi Desktop GUI (Tkinter murni)
├── tests/                   # 32 skenario pengujian unit & integrasi
├── docs/                    # Dokumentasi riset mendalam
│   ├── PROTOCOL.md          # Spesifikasi teknis protokol
│   ├── TANPA-LOGIN.md       # Analisis bebas akun & cloud
│   └── HARDWARE.md          # Teardown, UART, & modifikasi hardware
├── packaging/               # Asset PyInstaller, icon, dan launcher
├── dist/                    # Executable siap pakai (.exe & .zip)
└── build_exe.ps1            # Skrip otomatisasi build Windows
```

---

## Build Sendiri (PyInstaller)

Jika ingin mem-build ulang berkas `.exe` dari source:

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

Skrip ini akan secara otomatis:
1. Mempersiapkan virtual environment di `%TEMP%`.
2. Menghasilkan ikon aplikasi (`tools/make_icon.py`).
3. Mengompilasi `yeelight-re.exe` (CLI) dan `yeelight-re-gui.exe` (GUI).
4. Mengemas seluruh berkas ke dalam zip siap pakai di folder `dist\`.

---

## Lisensi & Disclaimer

- Berlisensi **MIT**.
- Proyek ini adalah proyek independen dan tidak berafiliasi dengan Yeelight atau Xiaomi. Reverse engineering dilakukan semata-mata untuk interoperabilitas dan kontrol perangkat pribadi secara lokal.