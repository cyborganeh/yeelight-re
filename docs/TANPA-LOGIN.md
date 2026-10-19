# Membebaskan YLDP06YL dari akun dan cloud

Dokumen ini menjelaskan apa yang benar-benar mungkin untuk **Yeelight YLDP06YL (`color2`)**, tanpa janji palsu.

---

## Jawaban singkat

| Kondisi awal | Bisa tanpa login? | Yang perlu dilakukan |
|---|---|---|
| LAN Control / Developer Mode **sudah ON** | **Ya, 100%** | Pakai tool ini; tidak perlu app/akun/internet |
| LAN Control **OFF**, bulb sudah terhubung Wi-Fi | **Mungkin** | Coba jalur miIO (`miio --enable`). Kalau token tidak tersedia: app sekali atau hardware |
| Bulb baru, belum pernah di-setup Wi-Fi | **Belum** | Setup Wi-Fi butuh app/AP mode; setelah itu matikan cloud |
| Tidak mau menyentuh app/akun **sama sekali** | **Mungkin** | miIO kalau firmware membocorkan token; kalau tidak, jalur hardware |

Intinya: **tool ini tidak pernah login**. Ada dua penghalang yang berbeda:

1. **Flag LAN Control** di firmware, yang membuka TCP `55443`.
2. **Token miIO**, yang hanya diperlukan kalau kita mencoba menyalakan flag itu lewat UDP `54321`.

Jalur miIO bisa melewati penghalang pertama tanpa app **hanya jika** firmware masih mengirim token di jawaban handshake. Banyak firmware baru mengembalikan token nol, jadi jalur ini tidak bisa dijanjikan untuk semua unit.

---

## Langkah 0 — cek kondisi bulb

```powershell
python -m yeelight_re discover
python -m yeelight_re doctor --ip 192.168.1.20
```

Kalau memakai build EXE (`dist\yeelight-re.exe`), ganti `python -m yeelight_re` dengan `yeelight-re.exe`. Sisanya sama.

Hasil yang mungkin:

- `TCP 55443: OK` dan `LAN API: OK` → lanjut ke **Jalur A**.
- `connection refused` → LAN Control OFF → coba **Jalur B0** (miIO), lalu B1/B2.
- `timed out` → IP/VLAN/firewall → perbaiki jaringan dulu.

Kalau IP tidak diketahui, cek DHCP lease di router (hostname biasanya `yeelink-light-...`) atau:

```powershell
python -m yeelight_re scan --subnet 192.168.1.0/24
```

---

## Jalur A — LAN Control sudah ON (target ideal)

Tidak ada akun, tidak ada cloud, tidak ada internet.

### A1. Reservasi IP

Beri DHCP reservation di router untuk MAC bulb, supaya IP tidak berubah. Kalau tidak, `--ip` bisa basi setelah lease expired.

Cari MAC dari tabel DHCP router, atau dari ARP:

```powershell
arp -a | findstr 192.168.1.20
```

### A2. Blokir akses WAN (opsional, disarankan)

Di router:

- Buat rule firewall: block MAC/IP bulb ke WAN, allow ke LAN.
- Atau taruh bulb di VLAN IoT yang tidak punya route ke internet.
- Atau gunakan DNS sinkhole untuk domain Yeelight/Xiaomi (kurang kuat, karena IP langsung masih bisa).

Setelah diblokir, uji:

```powershell
python -m yeelight_re on --ip 192.168.1.20
python -m yeelight_re color "#00aaff" --ip 192.168.1.20
```

Kalau tetap jalan, bulb sudah sepenuhnya lokal.

### A3. Hapus ketergantungan app

- Logout dari app Yeelight/Mi Home (opsional).
- Uninstall app (opsional).
- Jangan factory reset bulb, karena reset biasanya mengembalikan LAN Control ke default (OFF) dan memutus Wi-Fi.
- Catat nama, IP, dan MAC bulb.

### A4. Integrasi

- Dashboard: `python -m yeelight_re web --ip 192.168.1.20`
- Home Assistant: integrasi Yeelight memakai protokol yang sama. Cukup isi IP/manual, tanpa cloud.
- MQTT/otomasi lain: panggil CLI atau import `YeelightClient` di Python.

---

## Jalur B — LAN Control masih OFF

Firmware menolak TCP `55443`. Ada empat opsi, dicoba dari yang paling ringan.

### B0. Unlock lewat miIO (tanpa app)

Yeelight memakai protokol Xiaomi **miIO** di UDP `54321`, terpisah dari API LAN. Untuk sebagian firmware, perintah ini bisa menyalakan LAN Control:

```text
set_ps ["cfg_lan_ctrl", "1"]
```

Cek dulu apakah perangkat menjawab dan apakah tokennya tersedia:

```powershell
python -m yeelight_re miio --ip 192.168.1.20
```

Kalau muncul `Token: ... (bocor lewat handshake)`, coba:

```powershell
python -m yeelight_re miio --ip 192.168.1.20 --enable
```

Kalau berhasil, output berakhir dengan `TCP 55443: OK` dan kamu bisa langsung memakai seluruh command lain tanpa app.

Kalau token **tidak** dibocorkan (firmware mengembalikan `0x00`), jalur ini buntu kecuali kamu sudah punya token perangkat:

```powershell
python -m yeelight_re miio --ip 192.168.1.20 --enable --token 0123456789abcdef0123456789abcdef
```

Catatan penting:

- `set_ps` + `cfg_lan_ctrl` **bukan API resmi**. Ini berhasil di beberapa model/firmware Xiaomi, tetapi **belum diverifikasi pada YLDP06YL**. Kalau perangkat menjawab error atau tetap menutup port, jangan mengulang terus-menerus.
- Token adalah kunci perangkat. Jangan kirim ke siapa pun; jangan tempel di issue publik.
- Tool ini tidak menghubungi cloud untuk mendapatkan token. `--token` hanya menerima nilai yang sudah kamu miliki.
- Kalau handshake tidak menjawab sama sekali, kemungkinan firmware tidak membuka miIO, UDP diblokir, atau bulb sedang sibuk reconnect ke cloud.

### B1. Sekali lewat app resmi (paling praktis kalau B0 gagal)

Ini **bukan** "tanpa login selamanya"; ini "login sekali, lalu lepas".

1. Install **Yeelight** (bukan Mi Home) versi terbaru.
2. Login dengan akun apa pun (boleh akun sekali pakai).
3. Pastikan bulb sudah terhubung ke Wi-Fi 2.4 GHz.
4. Buka bulb → ikon settings → cari **LAN Control** atau **Developer Mode**.
5. Aktifkan. Di beberapa firmware, opsi ini muncul setelah update firmware; di region tertentu namanya berbeda.
6. Tutup app. Uji dengan `doctor`.
7. Logout/uninstall app. Blokir WAN bulb.

Catatan:

- Beberapa firmware lama menyembunyikan opsi ini; update firmware dulu.
- Beberapa firmware mematikan LAN Control setelah reset/daya putus. Kalau tiba-tiba `refused` lagi, cek app.
- Versi app lama (APK) kadang masih punya toggle ini saat versi baru menyembunyikannya. Risikonya: APK tidak resmi, kredensial bisa bocor. Kalau memakai cara ini, pakai akun sekali pakai, verifikasi checksum, dan install ulang app resmi setelah selesai.
- Metode "Mi Home token" / cloud API **tetap butuh login** dan tidak dipakai project ini.

#### Kalau app resminya yang bermasalah

App Yeelight memang sering bermasalah: device terdaftar tapi tampil offline, menu LAN Control hilang, atau app crash saat membuka detail bulb. Beberapa hal yang biasanya membantu:

- **Sama-sama online saat mengubah setelan.** Beberapa firmware hanya menampilkan toggle LAN Control kalau bulb dianggap online oleh cloud. Jadi jangan blokir WAN dulu; aktifkan LAN Control, baru blokir.
- **Region akun harus cocok** dengan region perangkat. Ganti region di pengaturan app, lalu login ulang.
- **Clear cache, bukan clear data.** Clear data menghapus daftar perangkat dan memaksa pairing ulang.
- **Coba dari HP lain** atau instal ulang app. Kalau app crash di daftar perangkat, buka lewat ikon share → pilih bulb → menu settings.
- **Mi Home tidak bisa menggantikan Yeelight** untuk menyalakan LAN Control pada produk berlabel Yeelight. Untuk produk Xiaomi/yeelink, opsinya justru sebaliknya.
- **APK versi lama** kadang masih punya toggle yang disembunyikan versi baru. Risikonya nyata (APK tidak resmi, kredensial bisa bocor). Kalau terpaksa: pakai akun sekali pakai, verifikasi sumber, lalu uninstall.

Kalau semua itu gagal dan `miio --enable` juga buntu, jalur yang tersisa adalah hardware (B2).

### B2. Ganti firmware (benar-benar tanpa akun)

Buka bulb, identifikasi chip, dump flash, lalu flash firmware alternatif (ESPHome/OpenBeken/Tasmota bila kompatibel). Ini menghilangkan cloud sepenuhnya, tetapi:

- Berisiko merusak bulb.
- Butuh alat: obeng, heat gun/spudger, USB-TTL 3.3 V, logic analyzer (idealnya), solder.
- Berhadapan dengan **tegangan listrik 110–240 V AC**. Jangan lakukan jika tidak paham keselamatan.
- Pinout dan chipset bisa berbeda antar revisi; jangan menebak.
- Firmware alternatif harus bisa mengemulasi driver LED bulb (PWM/SPI), yang tidak selalu trivial.

Panduan lengkap: [HARDWARE.md](HARDWARE.md).

### B3. Provisioning tanpa app (riset)

Secara teori, bulb bisa dikonfigurasi Wi-Fi lewat AP mode/SmartConfig tanpa app. Namun:

- Protokol provisioning tidak didokumentasikan resmi.
- Setelah terhubung Wi-Fi, flag LAN Control tetap ditentukan firmware; provisioning saja tidak otomatis membukanya.
- Belum ada tool publik yang matang untuk YLDP06YL.

Project ini menyediakan tempat untuk riset tersebut (lihat roadmap), tetapi **belum** menjanjikan provisioning tanpa app.

---

## Bulb bekas / sudah terikat akun lain

YLDP06YL menyimpan konfigurasi Wi-Fi dan binding akun di firmware. Beberapa hal yang perlu diketahui:

- Kalau bulb masih terhubung ke Wi-Fi lama, kamu mungkin bisa mengontrolnya via LAN jika LAN Control ON, walau akun lamanya tidak dikenal.
- Factory reset biasanya menghapus Wi-Fi dan bisa mematikan LAN Control. Setelah reset, kamu butuh app lagi untuk setup.
- Binding akun tidak selalu menghalangi kontrol LAN; yang menentukan adalah flag LAN Control dan akses jaringan.
- Kalau bulb belum pernah di-reset dan masih memakai Wi-Fi lama, sambungkan dulu ke jaringan yang sama atau reset.

Prosedur reset umum untuk bulb Yeelight: nyalakan, lalu matikan/nyalakan cepat beberapa kali (biasanya 5×) sampai bulb berkedip. Ikuti manual unit masing-masing; jangan reset kalau LAN Control sudah ON dan kamu tidak punya cara mengaktifkannya lagi.

---

## Mitos yang perlu diluruskan

| Mitos | Kenyataan |
|---|---|
| "Harus login Yeelight selamanya" | Setelah LAN Control ON, tidak. Tool ini tidak menyimpan akun. |
| "Home Assistant butuh cloud" | Integrasi Yeelight memakai LAN protocol yang sama; cloud hanya untuk setup awal. |
| "Cukup blokir internet, LAN Control otomatis ON" | Tidak. Flag-nya di firmware, bukan ditentukan internet. |
| "Developer Mode = LAN Control" | Di beberapa firmware, nama menunya berbeda tapi fungsinya sama: membuka port 55443. |
| "Port 55443 terbuka = aman" | Justru sebaliknya: siapa pun di LAN bisa kontrol. Isolasi jaringan. |
| "Ganti firmware = pasti bisa" | Tergantung chipset, driver LED, dan ketersediaan pinout. Selalu dump dan backup dulu. |
| "miIO pasti bisa membuka LAN Control tanpa app" | Tidak. Butuh token; banyak firmware baru mengembalikan token nol. |

---

## Checklist "sudah benar-benar lepas cloud"

- [ ] `doctor` menunjukkan `TCP 55443: OK` dan `LAN API: OK`.
- [ ] Bulb dapat dikontrol dengan WAN diblokir.
- [ ] IP bulb di-reservasi di DHCP.
- [ ] `cron`/flow tetap jalan setelah koneksi tool ditutup (flow disimpan firmware).
- [ ] Tidak ada app/akun yang diperlukan untuk menyalakan/mengubah warna.
- [ ] Dashboard hanya bind ke localhost atau VLAN tepercaya.
- [ ] Catatan: nama, model `color2`, MAC, IP, versi firmware, isi `support`.

Simpan hasilnya:

```powershell
python -m yeelight_re dump --ip 192.168.1.20 -o bulb.json
```

---

## Keamanan

Protokol ini **tanpa autentikasi**. Konsekuensinya:

- Siapa pun di LAN bisa mengontrol bulb, termasuk mematikan atau mengubah warna.
- Jangan pernah expose `55443` ke internet.
- Pisahkan IoT dari perangkat utama jika bisa.
- Dashboard web tidak punya login; bind default `127.0.0.1` sudah aman untuk satu komputer.

---

## FAQ

**Apakah tool ini mengirim data ke cloud?**
Tidak. Hanya socket LAN ke IP bulb dan (untuk music mode) UDP balik dari bulb.

**App-nya bug terus. Apakah saya wajib memakainya?**
Tidak, kalau LAN Control sudah ON. Kalau masih OFF, coba `python -m yeelight_re miio --ip <IP> --enable` lebih dulu; itu tidak membuka app sama sekali. Kalau firmware tidak membocorkan token, app hanya dipakai sekali untuk menyalakan flag, lalu boleh di-uninstall.

**Apakah perlu internet untuk discovery?**
Tidak. SSDP bekerja di LAN. Internet hanya mengganggu jika bulb sibuk retry cloud.

**Kenapa `refused` padahal app bisa kontrol?**
App mungkin memakai cloud, bukan LAN. Cek toggle LAN Control.

**Apakah bisa dijadwalkan tanpa cloud?**
Bisa, tapi jadwal disimpan di firmware via `cron_add` dan formatnya firmware-dependent. Alternatif yang lebih mudah: scheduler di Home Assistant/script lokal yang memanggil CLI.

**Apakah `set_music` aman?**
Aman untuk kontrol cepat, tetapi bukan untuk penggunaan 24/7. Setelah selesai, keluar dari music mode agar `music_on` kembali 0.

**Kalau firmware update mematikan LAN Control?**
Ulangi Jalur B1. Jangan update firmware jika semuanya sudah stabil dan kamu tidak butuh fitur baru.
