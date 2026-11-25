# yeelight-re untuk iOS

Aplikasi iPhone native (SwiftUI) untuk mengontrol **Yeelight YLDP06YL** langsung
di LAN — tanpa akun, tanpa cloud, tanpa aplikasi resmi Yeelight.

Hasil akhir: **IPA unsigned** yang Anda tanda tangani sendiri dengan Sideloadly
atau AltStore memakai Apple ID biasa (tidak perlu akun developer berbayar).

> Proyek ini adalah port dari toolkit Windows di folder induk. Logika protokol
> (`protocol.py`, `client.py`, `discovery.py`, `miio.py`) diterjemahkan ke Swift,
> GUI tkinter diganti SwiftUI.

---

## Fitur

| Fitur | Status |
|---|:---:|
| Koneksi TCP 55443 persisten + sinkronisasi state tiap 2,5 detik | ✅ |
| **Pindai jaringan** (TCP 55443 + verifikasi `get_prop`) untuk IP DHCP yang berubah | ✅ |
| Pindai otomatis saat app dibuka kalau IP tersimpan mati | ✅ |
| Daya, kecerahan, warna (picker + 10 swatch), HSV, suhu warna 1700–6500 K | ✅ |
| 9 preset scene | ✅ |
| 5 preset flow animasi + stop | ✅ |
| Timer mati otomatis | ✅ |
| Ganti nama lampu | ✅ |
| Raw JSON-RPC untuk reverse engineering | ✅ |
| miIO: cek handshake + buka LAN Control (`set_ps cfg_lan_ctrl=1`) | ✅ |
| SSDP / multicast discovery | ❌ (butuh entitlement multicast; pindai TCP sudah cukup) |
| Music mode (streaming UDP) | ❌ belum diporting |

---

## Yang Anda butuhkan

- **Mac** dengan **Xcode 15+** (gratis dari App Store). Xcode butuh macOS terbaru
  yang didukung; cek kompatibilitas di App Store.
- **XcodeGen** — skrip build memasangnya otomatis lewat Homebrew kalau belum ada.
- **iPhone** iOS 16 atau lebih baru.
- **Sideloadly** (Windows/Mac) *atau* **AltStore** untuk memasang IPA.
- Apple ID biasa. Akun developer berbayar **tidak diperlukan** untuk sideload.

---

## Unduh IPA siap pakai

Kalau tidak ingin memasang Xcode, IPA hasil build otomatis sudah tersedia di
halaman [**Releases**](https://github.com/cyborganeh/yeelight-re/releases/tag/v0.4.0)
repo ini. Unduh `yeelight-ios-0.1.0.ipa` (501.390 byte) lalu langsung ke bagian
[sideload](#memasang-di-iphone-sideload).

```
sha256  dbddbfe8cbdd6815362a917ed64145574aff0a4e49671329fed3d85a5aa13f4c
```

Cek di Mac/Linux dengan `shasum -a 256 yeelight-ios-0.1.0.ipa`, di Windows
dengan `Get-FileHash .\yeelight-ios-0.1.0.ipa -Algorithm SHA256`.

---

## Membangun IPA

Di Mac:

```bash
cd yeelight-re/ios
bash build.sh
```

Skrip akan:

1. memeriksa Xcode,
2. memasang `xcodegen` bila perlu,
3. membuat `Yeelight.xcodeproj` dari `project.yml`,
4. build `Release` untuk `iphoneos` **tanpa code signing**,
5. mengemas hasilnya menjadi IPA.

Keluaran:

```
yeelight-re/dist/yeelight-ios-0.1.0.ipa
```

### Tanpa Mac (GitHub Actions)

Repo ini punya workflow `.github/workflows/ios.yml`. Setiap push yang menyentuh
folder `ios/` (atau lewat **Actions → iOS IPA → Run workflow**) akan:

1. checkout di runner macOS milik GitHub,
2. memasang XcodeGen,
3. menjalankan `ios/build.sh`,
4. mengunggah IPA sebagai artifact `yeelight-ios-ipa` (tersimpan 30 hari).

Unduh artifact dari tab **Actions** → pilih run terbaru → **Artifacts**.
Cocok kalau Mac sedang tidak tersedia; runner ini juga yang memverifikasi kode
Swift benar-benar bisa dikompilasi.

### Kalau ingin membuka di Xcode

```bash
cd yeelight-re/ios
xcodegen generate
open Yeelight.xcodeproj
```

Lalu pilih target **Yeelight** → Signing & Capabilities → pilih tim Apple ID Anda,
dan Run ke iPhone. Cara ini juga menghasilkan app 7 hari (gratis) atau 1 tahun
(berbayar).

---

## Memasang di iPhone (sideload)

### Sideloadly (paling mudah, ada versi Windows)

1. Unduh <https://sideloadly.io>, pasang di Mac/PC.
2. Sambungkan iPhone dengan kabel, percayai komputer.
3. Seret `yeelight-ios-0.1.0.ipa` ke jendela Sideloadly.
4. Isi **Apple ID** Anda (dipakai hanya untuk menandatangani app di perangkat).
5. Klik **Start**. Masukkan password / kode 2FA bila diminta.
6. Setelah selesai, buka app di iPhone. Kalau muncul "Untrusted Developer":
   **Settings → General → VPN & Device Management → pilih Apple ID → Trust**.

### AltStore

1. Pasang AltServer di Mac, lalu AltStore ke iPhone.
2. Buka AltStore → **+** → pilih file IPA.
3. Masuk dengan Apple ID saat diminta.

### Catatan penting soal gratis

- Tanda tangan dengan Apple ID gratis **berlaku 7 hari**, lalu app tidak mau
  dibuka sampai ditandatangani ulang (Sideloadly/AltStore bisa memperbarui).
- Maksimal **3 app** per Apple ID.
- Kalau muncul error "bundle identifier already in use", ganti dulu:
  `project.yml` → `PRODUCT_BUNDLE_IDENTIFIER`, misalnya
  `com.rizal.yeelight2`, lalu build ulang.

---

## Izin Local Network (wajib)

iOS memblokir akses ke perangkat LAN sampai Anda menyetujuinya.

Saat pertama kali menekan **Pindai lampu**, akan muncul dialog
*"Yeelight would like to find and connect to devices on your local network"* →
pilih **Allow**.

Kalau tidak sengaja menolak:

**Settings → Privacy & Security → Local Network → Yeelight = ON**

Tanpa izin ini pemindaian akan selesai tanpa hasil dan log menampilkan
"Tidak ada host dengan TCP 55443".

---

## Pemakaian

1. Pastikan iPhone dan lampu ada di **Wi-Fi 2.4 GHz yang sama**
   (bukan Guest Network yang memisahkan klien).
2. Buka app. Kalau ada IP tersimpan, app langsung mencoba; bila gagal, ia
   memindai jaringan otomatis.
3. Atau tekan **Pindai lampu**:
   - satu lampu → IP diisi dan langsung tersambung,
   - beberapa lampu → pilih chip IP, lalu **Hubungkan**.
4. Kolom **Subnet** boleh dikosongkan (memindai semua antarmuka `/24`).
   Isi manual kalau jaringan Anda bukan `/24`, misalnya `192.168.0.0/24`.

### Kalau port 55443 menolak

Artinya **LAN Control** mati. Buka tab **miIO**:

- **Cek miIO** — memastikan UDP 54321 menjawab dan apakah token dibocorkan.
- **Buka LAN Control** — mengirim `set_ps ["cfg_lan_ctrl","1"]`.

Banyak firmware YLDP06YL **tidak membocorkan token** saat handshake. Kalau
demikian, nyalakan LAN Control **sekali** lewat aplikasi resmi (butuh internet
saat itu saja). Setelah aktif, app ini bekerja 100% lokal.

---

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| Pindai tidak menemukan apa pun | Izin Local Network ditolak | Settings → Privacy & Security → Local Network → Yeelight = ON |
| | iPhone di Wi-Fi 5 GHz / beda subnet | Pakai Wi-Fi yang sama dengan lampu, atau isi kolom Subnet |
| | Guest network memisahkan klien | Matikan isolation / pakai SSID utama |
| Chip IP muncul tetapi "bukan Yeelight" | Bukan lampu, atau LAN Control mati | Coba tombol miIO |
| `connection refused` | LAN Control OFF | Tab miIO → Buka LAN Control |
| App langsung tertutup setelah sideload | Tanda tangan 7 hari habis | Tandatangani ulang dengan Sideloadly/AltStore |
| Build gagal: "xcodegen not found" | Homebrew belum ada | Install <https://brew.sh> lalu `brew install xcodegen` |
| Build gagal: SDK tidak ditemukan | Xcode belum diarahkan | `sudo xcode-select -s /Applications/Xcode.app` |

---

## Struktur

```text
ios/
├── build.sh                    # build + kemas IPA
├── project.yml                 # definisi proyek untuk XcodeGen
└── YeelightApp/
    ├── YeelightApp.swift       # entry point
    ├── Info.plist              # izin Local Network, versi
    ├── Assets.xcassets/        # ikon & warna aksen
    ├── Core/
    │   ├── Protocol.swift      # konstanta, state, preset scene/flow
    │   ├── BulbClient.swift    # TCP 55443 + JSON-RPC + timeout
    │   ├── Discovery.swift     # enumerasi NIC, probe TCP, scan, identify
    │   ├── Miio.swift          # UDP 54321: handshake, set_ps, verifikasi
    │   ├── Crypto.swift        # MD5 + AES-128-CBC (CommonCrypto)
    │   ├── BulbError.swift     # error + BulbHit
    │   └── Theme.swift         # palet & komponen tampilan
    ├── Store/
    │   └── AppStore.swift      # state aplikasi, scan, polling, perintah
    └── Views/
        ├── RootView.swift      # header + kartu koneksi + tab
        ├── ControlView.swift   # daya, kecerahan, warna, CT
        ├── EffectsView.swift   # scene, flow, timer
        ├── DiagnosticsView.swift # miIO + log
        └── InfoView.swift      # info perangkat, rename, raw
```

---

## Catatan teknis

- **Tanpa dependency eksternal.** Hanya `Network`, `CommonCrypto`, dan SwiftUI.
- **Tanpa entitlement multicast.** Karena itu SSDP tidak dipakai; pemindaian
  selalu lewat TCP 55443. Ini justru lebih andal di jaringan yang memblokir
  multicast — masalah yang sama yang membuat fitur "Pindai subnet" dibuat di
  versi Windows.
- **Satu koneksi TCP** dipakai ulang, karena firmware hanya mengizinkan empat
  koneksi simultan.
- **Quota 60 perintah/menit** dihormati: slider mengirim perintah saat jari
  dilepas, bukan setiap piksel.
- Semua data sensitif (IP, port, subnet, token miIO) disimpan di `UserDefaults`
  perangkat. Tidak ada telemetri.
