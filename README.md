# yeelight-re

Toolkit reverse engineering dan kontrol **lokal** untuk **Yeelight Smart LED Bulb (Color) generasi 2 — model `YLDP06YL`** (dikenal di Home Assistant sebagai `color2`).

Tool ini **tidak pernah login** ke akun Yeelight, Mi Home, atau cloud mana pun. Semua komunikasi berjalan di LAN: discovery SSDP di UDP `1982`, kontrol JSON di TCP `55443`.

> **Ringkas soal "tanpa login":** kalau opsi **LAN Control / Developer Mode** di bulb sudah pernah diaktifkan, bulb bisa dipakai 100% offline dengan tool ini. Kalau opsi itu masih mati, firmware bulb menolak koneksi ke port `55443`; tool ini bisa mencoba membukanya lewat jalur **miIO** (`miio --enable`) tanpa app, tetapi hasilnya tergantung firmware. Kalau miIO buntu, perlu sekali app resmi atau jalur hardware. Detailnya di [docs/TANPA-LOGIN.md](docs/TANPA-LOGIN.md).

---

## Download / langsung pakai (Windows)

Build siap pakai sudah tersedia di folder `dist\`:

| File | Keterangan |
|---|---|
| `dist\yeelight-re.exe` | Satu file, ±6,5 MB, tidak butuh Python |
| `dist\yeelight-re-0.2.0-win64.zip` | EXE + `CARA-PAKAI.txt` untuk dibagikan |

```powershell
cd "C:\Users\RIZAL\Documents\Default Project\yeelight-re"

.\dist\yeelight-re.exe discover
.\dist\yeelight-re.exe doctor --ip 192.168.1.20
.\dist\yeelight-re.exe miio --ip 192.168.1.20 --enable
.\dist\yeelight-re.exe web --ip 192.168.1.20 --open
```

EXE ini **tidak butuh instalasi, Python, akun, atau internet**. Karena belum ditandatangani, Windows SmartScreen bisa menampilkan peringatan; itu normal untuk build PyInstaller lokal. Source lengkapnya ada di repo ini kalau ingin diverifikasi atau di-build ulang.

Semua contoh di bawah memakai `python -m yeelight_re`. Kalau memakai EXE, ganti dengan `yeelight-re.exe`.

---

## Status

| Bagian | Status |
|---|---|
| Discovery SSDP + fallback scan subnet | jalan |
| Client TCP persisten + notifikasi | jalan |
| Kontrol power, brightness, RGB, HSV, CT, scene, flow | jalan |
| Music mode (UDP, low-latency) | jalan |
| CLI + interactive REPL | jalan |
| Web dashboard lokal (tanpa cloud) | jalan |
| Emulator bulb untuk uji tanpa hardware | jalan |
| Windows EXE satu file (tanpa Python) | jalan — `dist\yeelight-re.exe` & `dist\yeelight-re-gui.exe` |
| Provisioning Wi-Fi via miIO (tanpa app) | jalan — `wifi-setup` & tombol Pairing di GUI |
| Unlock LAN Control via miIO (tanpa app) | jalan — `set_ps cfg_lan_ctrl=1` otomatis |
| Unit/integration test | 32 test, semua lulus |
| Dokumentasi protokol | [docs/PROTOCOL.md](docs/PROTOCOL.md) |
| Jalur hardware / ganti firmware | [docs/HARDWARE.md](docs/HARDWARE.md) (panduan, belum otomatis) |

Yang **belum** ada: firmware replacement otomatis (butuh riset hardware tambahan).

---

## Kenapa bisa tanpa login?

Protokol LAN Yeelight adalah protokol terbuka: JSON polos di TCP `55443`. Tidak ada token, akun, atau enkripsi di level aplikasi. Yang membatasi hanyalah flag **LAN Control** di firmware.

| Kondisi bulb | Yang terjadi | Solusi |
|---|---|---|
| LAN Control **ON** | Port `55443` terbuka, semua perintah lokal jalan | Langsung pakai tool ini; tidak perlu internet/akun |
| LAN Control **OFF** | Port `55443` menolak koneksi | Coba unlock miIO tanpa app; kalau token tidak tersedia, nyalakan sekali lewat app resmi atau ganti firmware |
| Bulb baru / bekas, belum di-setup | Belum punya kredensial Wi-Fi | Setup Wi-Fi butuh app/AP mode; setelah itu matikan cloud |

Setelah LAN Control ON, bulb **tidak butuh internet** untuk menyala, berubah warna, atau dijadwalkan. Kamu bisa memblokir akses WAN-nya di router dan tetap kontrol penuh dari LAN.

---

## Instalasi

Tanpa dependency eksternal. Cukup Python 3.9+.

```powershell
cd "C:\Users\RIZAL\Documents\Default Project\yeelight-re"

# Langsung dari source:
python -m yeelight_re discover

# Atau install sebagai command:
pip install -e .
yeelight-re discover
```

Semua contoh di bawah memakai `python -m yeelight_re`. Kalau sudah `pip install -e .`, ganti dengan `yeelight-re`.

---

## Quick start

### 1. Cari bulb

```powershell
python -m yeelight_re discover
python -m yeelight_re discover --scan --subnet 192.168.1.0/24
```

Contoh output:

```text
Found 1 Yeelight device(s):

[1] 192.168.1.20:55443
     model   : color2
     firmware: 18
     name    : Kamar
     support : 21 methods
```

### 2. Diagnosa

```powershell
python -m yeelight_re doctor --ip 192.168.1.20
```

`doctor` mengecek SSDP, port TCP, LAN API, model, dan daftar method yang didukung. Kalau port ditolak, tool juga mencoba handshake **miIO** di UDP `54321` dan memberi tahu apakah jalur tanpa-app masih mungkin.

### 2b. Kalau LAN Control masih OFF

```powershell
# Baca-only: cek apakah miIO menjawab dan tokennya tersedia
python -m yeelight_re miio --ip 192.168.1.20

# Coba nyalakan LAN Control tanpa membuka app
python -m yeelight_re miio --ip 192.168.1.20 --enable

# Kalau handshake tidak membocorkan token, pakai token perangkat sendiri
python -m yeelight_re miio --ip 192.168.1.20 --enable --token 0123456789abcdef0123456789abcdef
```

Perintah `miio` memakai protokol Xiaomi di UDP `54321`, bukan cloud. Ini **eksperimental**: sebagian firmware membocorkan token lewat handshake, sebagian mengembalikan nol. Kalau tidak ada token, jalur ini tidak bisa dipakai. Bacaan lengkap: [docs/TANPA-LOGIN.md](docs/TANPA-LOGIN.md).

### 3. Kontrol

```powershell
# Status
python -m yeelight_re status --ip 192.168.1.20

# Power
python -m yeelight_re on --ip 192.168.1.20
python -m yeelight_re off --ip 192.168.1.20
python -m yeelight_re toggle --ip 192.168.1.20

# Brightness 1-100
python -m yeelight_re bright 40 --ip 192.168.1.20

# Warna: #RRGGBB, r,g,b, 0xRRGGBB, atau integer
python -m yeelight_re color "#ff6600" --ip 192.168.1.20
python -m yeelight_re color "0,128,255" --bright 60 --ip 192.168.1.20

# White temperature 1700-6500 K
python -m yeelight_re ct 3200 --ip 192.168.1.20

# HSV
python -m yeelight_re hsv 200 80 --ip 192.168.1.20

# Scene siap pakai
python -m yeelight_re scene --list
python -m yeelight_re scene movie --ip 192.168.1.20

# Flow / animasi
python -m yeelight_re flow --list
python -m yeelight_re flow party --ip 192.168.1.20
python -m yeelight_re flow --expression "500,1,16711680,100,500,1,65280,100" --count 0 --action 1 --ip 192.168.1.20

# Rename
python -m yeelight_re name "Lampu Kamar" --ip 192.168.1.20
```

Kalau hanya ada satu bulb di LAN, `--ip` boleh dihilangkan (otomatis discovery). Bisa juga set environment variable:

```powershell
$env:YEELIGHT_IP = "192.168.1.20"
python -m yeelight_re status
```

### 4. Web dashboard lokal

```powershell
python -m yeelight_re web --ip 192.168.1.20 --open
```

Buka `http://127.0.0.1:8765/`. Dashboard mendukung power, brightness, color picker, white temperature, scene, dan flow. Semua request diteruskan langsung ke bulb; tidak ada aset eksternal dan tidak ada login.

Default bind hanya `127.0.0.1`. Kalau mau diakses dari HP di LAN:

```powershell
python -m yeelight_re web --ip 192.168.1.20 --bind 0.0.0.0
```

> Dashboard tidak punya autentikasi. Jangan bind ke `0.0.0.0` di jaringan yang tidak dipercaya.

### 5. Notifikasi real-time

```powershell
python -m yeelight_re listen --ip 192.168.1.20
```

Perubahan state dari app/fisik (power, brightness, color) akan tampil sebagai JSON.

### 6. Music mode (low-latency)

```powershell
python -m yeelight_re music --ip 192.168.1.20 --seconds 15 --fps 25 --mode rainbow
```

Music mode membuka UDP lokal dan meminta bulb mengirim notifikasi ke situ. Quota 60 command/menit tidak berlaku, jadi animasi halus bisa mencapai 25–60 fps (tergantung firmware dan Wi-Fi).

### 7. Interactive REPL

```powershell
python -m yeelight_re repl --ip 192.168.1.20
```

```text
yeelight> status
yeelight> bright 25
yeelight> color #00aaff
yeelight> raw set_scene ["color", 16711680, 100]
yeelight> quit
```

---

## Referensi command

| Command | Fungsi |
|---|---|
| `discover [--scan] [--subnet CIDR]` | Cari bulb via SSDP dan/atau scan port |
| `scan [--subnet CIDR]` | Cari host dengan TCP 55443 terbuka |
| `doctor --ip IP` | Diagnosa lengkap (SSDP, port, API, model, miIO) |
| `miio --ip IP [--enable] [--token HEX]` | Cek/unlock LAN Control lewat miIO UDP 54321 (eksperimental) |
| `status --ip IP` | Baca power, bright, RGB, CT, nama |
| `on` / `off` / `toggle` | Kontrol power |
| `bright N` | Brightness 1–100 |
| `color VALUE [--bright N]` | Warna RGB |
| `ct K [--bright N]` | White temperature 1700–6500 K |
| `hsv H S` | Hue 0–359, saturation 0–100 |
| `scene NAME` | Scene preset (`--list` untuk daftar) |
| `flow [PRESET]` | Flow/animasi (`--list`, `--expression`, `--count`, `--action`) |
| `name TEXT` | Rename bulb |
| `listen [--seconds N]` | Cetak notifikasi state |
| `music` | Demo music mode |
| `web` | Dashboard lokal |
| `raw METHOD [PARAMS...]` | Kirim method mentah (untuk reverse engineering) |
| `dump [-o file.json]` | Simpan discovery + status |
| `repl` | Shell interaktif |

Semua command kontrol menerima `--ip`, `--port`, `--timeout`, dan `--json`. Command `miio` memakai `--miio-port` (default `54321`); `--port` di sana adalah port TCP yang diverifikasi setelah unlock.

Contoh `raw` dengan parameter numerik:

```powershell
python -m yeelight_re raw set_scene --params-json '["color", 16711680, 100]' --ip 192.168.1.20
```

---

## Pakai sebagai library

```python
from yeelight_re import YeelightClient, discover

device = discover()[0]
with YeelightClient(device.ip) as bulb:
    print(bulb.status())
    bulb.set_power(True)
    bulb.set_bright(40)
    bulb.set_rgb(0xFF6600)
    bulb.set_ct(3200)
```

Contoh lengkap: [`examples/control.py`](examples/control.py).

---

## Emulator (uji tanpa bulb)

Terminal 1:

```powershell
python -m yeelight_re.fake_bulb --port 55443 --ssdp --miio
```

Terminal 2:

```powershell
python -m yeelight_re discover
python -m yeelight_re status --ip 127.0.0.1
python -m yeelight_re color "#00ff88" --ip 127.0.0.1
python -m yeelight_re web --ip 127.0.0.1 --open

# Uji jalur unlock tanpa app (emulator membocorkan token)
python -m yeelight_re miio --ip 127.0.0.1
python -m yeelight_re miio --ip 127.0.0.1 --enable
```

Emulator mengimplementasikan `get_prop`, power, brightness, RGB/HSV/CT, scene, flow flag, rename, notifikasi, music mode, SSDP, dan handshake miIO. Cocok untuk mengembangkan UI/otomasi sebelum menyentuh bulb asli.

---

## Test

```powershell
python -m unittest discover -s tests -v
```

Test mencakup parser protokol, client, notifikasi, music mode, discovery SSDP, error handling, HTTP dashboard, AES/miIO, dan unlock LAN Control terhadap emulator. Tidak butuh bulb asli.

AES diuji dengan vektor resmi FIPS-197. Protokol miIO diuji terhadap `FakeMiio`, termasuk kasus token bocor, token disembunyikan, token salah, dan `set_ps cfg_lan_ctrl`.

---

## Build EXE sendiri

Butuh Python 3.10 (lewat launcher `py`) dan koneksi internet sekali untuk memasang PyInstaller. Script akan membuat venv sementara di `%TEMP%`, jadi Python utama tidak disentuh.

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

Hasilnya:

```text
dist\yeelight-re.exe
dist\yeelight-re-0.2.0-win64.zip
```

Yang dilakukan script:

1. Generate icon (`tools/make_icon.py`, PNG/ICO murni stdlib).
2. Build `--onefile --console` dengan metadata versi dan icon.
3. Bungkus EXE + `CARA-PAKAI.txt` menjadi ZIP.

Catatan:

- PyInstaller 6.x di Python 3.14 belum tentu stabil; script memakai `py -3.10`.
- EXE hasil PyInstaller sering memicu false positive antivirus. Kalau mau distribusi lebih luas, code-sign EXE-nya.
- `--onefile` mengekstrak ke `%TEMP%` saat dijalankan, jadi startup pertama lebih lambat (±1 detik) dibanding versi source.

---

## Struktur project

```text
yeelight-re/
├─ yeelight_re/
│  ├─ protocol.py      # parser/builder JSON + SSDP, warna, flow
│  ├─ discovery.py     # SSDP multicast + scan subnet
│  ├─ client.py        # TCP client, notifikasi, music mode
│  ├─ miio.py          # handshake miIO + unlock cfg_lan_ctrl (eksperimental)
│  ├─ _aes.py          # AES-128-CBC murni Python untuk miIO
│  ├─ cli.py           # command-line + REPL
│  ├─ web.py           # dashboard lokal
│  ├─ presets.py       # scene & flow preset
│  └─ fake_bulb.py     # emulator YLDP06YL/color2 + miIO
├─ tools/
│  ├─ capture.py       # simpan discovery + status ke JSON
│  └─ make_icon.py     # generator icon EXE (stdlib)
├─ packaging/
│  ├─ launcher.py      # entry point PyInstaller
│  ├─ version_info.txt # metadata versi Windows
│  └─ README-EXE.txt   # petunjuk singkat di dalam ZIP
├─ examples/
│  └─ control.py       # contoh pemakaian library
├─ docs/
│  ├─ PROTOCOL.md      # detail protokol LAN Yeelight + miIO
│  ├─ TANPA-LOGIN.md   # empat jalur bebas akun
│  └─ HARDWARE.md      # teardown, UART, dump, ganti firmware
├─ captures/           # contoh transaksi SSDP/TCP
├─ dist/               # hasil build EXE + ZIP
├─ build_exe.ps1       # build Windows onefile
└─ tests/
```

---

## Keamanan

- Protokol LAN Yeelight **tanpa enkripsi dan tanpa autentikasi**. Siapa pun yang bisa menjangkau port `55443` bisa mengontrol bulb.
- Jangan port-forward `55443` ke internet.
- Tempatkan bulb di VLAN/IoT network yang terpisah.
- Dashboard web default hanya localhost dan tidak punya login; jangan expose ke publik.
- Untuk "cukup lokal", blokir WAN bulb di router (MAC filter / firewall) setelah LAN Control aktif. Bulb tetap bisa dikontrol dari LAN.

---

## Troubleshooting

| Gejala | Penyebab umum | Solusi |
|---|---|---|
| `connection refused` di port 55443 | LAN Control / Developer Mode OFF | Coba `miio --enable`; kalau token tidak tersedia, nyalakan sekali di app (lihat [docs/TANPA-LOGIN.md](docs/TANPA-LOGIN.md)) |
| `miio` tidak menjawab | Firmware tanpa miIO, UDP diblokir, atau beda VLAN | Pastikan satu jaringan; cek firewall UDP 54321 |
| `miio` menjawab tapi token `0x00` | Firmware menutup kebocoran token | Tidak bisa unlock tanpa token; pakai app sekali atau jalur hardware |
| `set_ps` error / port tetap tertutup | Firmware memakai parameter berbeda | Jangan spam; lanjut ke app/hardware |
| `timed out` | IP salah, beda VLAN, firewall Windows, atau bulb sleep | Cek IP di DHCP lease; coba `scan --subnet` |
| SSDP tidak menemukan apa pun | Multicast diblokir / beda subnet | Pakai `scan --subnet 192.168.x.0/24` atau `--ip` |
| Ditemukan >1 bulb | Ada beberapa perangkat | Tambahkan `--ip` |
| Perintah timeout setelah beberapa saat | Koneksi TCP putus / quota | Tool reconnect otomatis; hindari >4 koneksi bersamaan |
| `error -4: method not supported` | Firmware/model tidak mendukung method | Cek `doctor` → daftar `support` |
| Warna tidak berubah | Mode sedang CT/flow | `stop_cf` lalu `color ...`; atau `set_power on` |
| Web menampilkan offline | Bulb mati / IP berubah | Reservasi DHCP; refresh halaman |

---

## Roadmap

- [ ] Bridge MQTT / Home Assistant MQTT Discovery.
- [ ] Verifikasi `set_ps ["cfg_lan_ctrl","1"]` pada YLDP06YL asli (butuh unit fisik).
- [ ] Provisioning Wi-Fi tanpa app (riset protokol AP/SmartConfig).
- [ ] Dump/restore firmware otomatis untuk chip yang teridentifikasi.
- [ ] Dukungan beberapa bulb dalam satu dashboard.
- [ ] Capture analyzer: import pcap → ringkasan command/state.
- [ ] Efek audio (FFT) untuk music mode.

---

## Dokumentasi

- [docs/PROTOCOL.md](docs/PROTOCOL.md) — SSDP, framing JSON, daftar command, quota, music mode, error code, quirk `color2`.
- [docs/TANPA-LOGIN.md](docs/TANPA-LOGIN.md) — jalur praktis membebaskan bulb dari akun/cloud.
- [docs/HARDWARE.md](docs/HARDWARE.md) — teardown, identifikasi chip, UART, dump flash, opsi firmware alternatif.
- [captures/](captures/) — contoh respons SSDP dan sesi TCP.

---

## Disclaimer

Project ini tidak berafiliasi dengan Yeelight/Yeelink. Reverse engineering dilakukan untuk interoperabilitas dan kontrol perangkat milik sendiri. Membuka bulb berarti berurusan dengan tegangan listrik 110–240 V AC; jangan lakukan tanpa alat dan pengetahuan keselamatan yang memadai. Garansi bisa hilang. Gunakan dengan risiko sendiri.
