# Protokol LAN Yeelight (YLDP06YL / color2)

Catatan ini menggabungkan spesifikasi publik Yeelight, observasi komunitas, dan pengujian dengan emulator. Firmware berbeda bisa berperilaku sedikit berbeda; gunakan `yeelight-re doctor`, `dump`, dan `raw` untuk memverifikasi perangkatmu.

Referensi resmi: [Yeelight WiFi Light Inter-Operation Specification (PDF)](https://www.yeelight.com/download/Yeelight_Inter-Operation_Spec.pdf).

---

## 1. Ringkasan

| Lapisan | Detail |
|---|---|
| Discovery | SSDP-like, UDP port `1982`, multicast `239.255.255.250` |
| Kontrol | TCP port `55443`, JSON per baris, diakhiri `\r\n` |
| Autentikasi | Tidak ada |
| Enkripsi | Tidak ada |
| Koneksi simultan | Maksimal 4 TCP |
| Quota normal | 60 command/menit per koneksi, 144/menit total |
| Music mode | UDP balik ke client, quota normal dilepas (firmware-dependent) |

Semua pesan kontrol adalah JSON object. Tidak ada header biner, token, atau handshake.

---

## 2. Discovery (SSDP)

Kirim UDP ke `239.255.255.250:1982`:

```http
M-SEARCH * HTTP/1.1
HOST: 239.255.255.250:1982
MAN: "ssdp:discover"
ST: wifi_bulb

```

(`\r\n` di setiap baris, diakhiri baris kosong.)

Balasan datang unicast ke port pengirim:

```http
HTTP/1.1 200 OK
Cache-Control: max-age=3600
Location: yeelight://192.168.1.20:55443
Server: POSIX UPnP/1.0 YGLC/1
id: 0x0000000012345678
model: color2
fw_ver: 18
support: get_prop set_default set_power toggle set_bright start_cf stop_cf set_scene cron_add cron_get cron_del set_ct_abx set_rgb set_hsv set_adjust adjust_bright adjust_ct adjust_color set_music set_name
power: on
bright: 40
color_mode: 2
ct: 3200
rgb: 16737792
hue: 30
sat: 100
name: Kamar
```

Header penting:

| Header | Arti |
|---|---|
| `Location` | `yeelight://IP:PORT` untuk kontrol TCP |
| `id` | ID unik perangkat (dipakai untuk deduplikasi) |
| `model` | `color2` untuk YLDP06YL; model lain: `color1`, `color4`, `mono1`, `strip1`, dll. |
| `fw_ver` | Versi firmware (angka internal, bukan versi app) |
| `support` | Daftar method yang didukung firmware |
| `power` / `bright` / `color_mode` / `ct` / `rgb` / `hue` / `sat` / `name` | Snapshot state awal |

Catatan:

- Sebagian firmware hanya menjawab multicast; sebagian menjawab broadcast. Tool mengirim ke keduanya.
- Multicast sering diblokir di Wi-Fi guest, VLAN, atau Windows Firewall. Fallback: scan TCP `55443` per subnet.
- Respons bisa datang lebih dari sekali; deduplikasi berdasarkan `id`.

---

## 3. Kanal kontrol

Buka TCP ke `Location` (biasanya port `55443`), lalu kirim satu JSON object per baris:

```json
{"id":1,"method":"get_prop","params":["power","bright","rgb","ct","name"]}\r\n
```

Balasan sukses:

```json
{"id":1,"result":["on","40","16737792","3200","Kamar"]}\r\n
```

Balasan error:

```json
{"id":1,"error":{"code":-1,"message":"general error"}}\r\n
```

Aturan:

- `id` adalah integer dan harus dicocokkan dengan balasan. Boleh naik terus; tidak harus mulai dari 1.
- Satu request → satu response. Notifikasi `props` bisa muncul di antara response.
- Koneksi bersifat persisten; jangan buka koneksi baru untuk setiap perintah (batas 4 koneksi).
- Kirim `\r\n` setelah JSON. Tanpa itu, firmware menunggu dan perintah tidak diproses.
- Encoding UTF-8; nama bisa berisi karakter non-ASCII.

### Notifikasi state

Setelah koneksi terbuka, bulb mengirim perubahan state:

```json
{"method":"props","params":{"power":"on","bright":"60"}}
```

`params` hanya berisi properti yang berubah. Notifikasi tidak punya `id`. Kalau koneksi ditutup, notifikasi berhenti.

---

## 4. Properti (`get_prop`)

`get_prop` menerima array nama properti dan mengembalikan array string dengan urutan sama. Properti yang tidak dikenal umumnya menghasilkan `""`.

| Properti | Nilai | Catatan |
|---|---|---|
| `power` | `"on"` / `"off"` | |
| `bright` | `"1"`–`"100"` | persen |
| `ct` | `"1700"`–`"6500"` | Kelvin |
| `rgb` | `"0"`–`"16777215"` | 24-bit |
| `hue` | `"0"`–`"359"` | |
| `sat` | `"0"`–`"100"` | |
| `color_mode` | `"0"`–`"3"` | 0 normal, 1 CT, 2 RGB, 3 HSV |
| `flowing` | `"0"` / `"1"` | flow sedang berjalan |
| `delayoff` | menit | auto-off |
| `music_on` | `"0"` / `"1"` | music mode aktif |
| `name` | string | nama perangkat |
| `bg_power`, `bg_bright`, ... | | hanya model dengan background light (ceiling/strip); color2 tidak |

Contoh:

```json
{"id":2,"method":"get_prop","params":["power","bright","ct","rgb","hue","sat","color_mode","flowing","music_on","name"]}
```

---

## 5. Command umum

Semua `params` adalah array. `effect` biasanya `"smooth"` atau `"sudden"`, `duration` dalam milidetik.

| Method | Params | Fungsi |
|---|---|---|
| `set_power` | `[on/off, effect, duration]` atau `[on/off, effect, duration, mode]` | Power; `mode` opsional langsung memilih mode warna |
| `toggle` | `[]` | Balik power |
| `set_bright` | `[1-100, effect, duration]` | Brightness |
| `set_ct_abx` | `[1700-6500, effect, duration]` | White temperature |
| `set_rgb` | `[0-16777215, effect, duration]` | Warna RGB |
| `set_hsv` | `[0-359, 0-100, effect, duration]` | Warna HSV |
| `set_scene` | lihat bawah | Scene langsung |
| `start_cf` | `[count, action, expression]` | Mulai flow |
| `stop_cf` | `[]` | Hentikan flow |
| `set_adjust` | `["increase"/"decrease", "bright"/"ct"/"color"]` | Adjust relatif |
| `adjust_bright` | `[percentage, duration]` | Adjust brightness relatif |
| `adjust_ct` | `[percentage, duration]` | Adjust CT relatif |
| `adjust_color` | `[percentage, duration]` | Adjust warna relatif |
| `set_name` | `[string]` | Rename |
| `set_music` | `[1, host, port]` / `[0]` | Music mode |
| `cron_add` | `[type, value, ...]` | Jadwal; detail firmware-dependent |
| `cron_get` | `[type]` | Baca jadwal |
| `cron_del` | `[type]` | Hapus jadwal |
| `set_default` | `[]` | Set state saat power-on |

Contoh:

```json
{"id":3,"method":"set_power","params":["on","smooth",500]}
{"id":4,"method":"set_bright","params":[40,"smooth",300]}
{"id":5,"method":"set_rgb","params":[16737792,"smooth",300]}
{"id":6,"method":"set_ct_abx","params":[3200,"smooth",300]}
{"id":7,"method":"set_hsv","params":[200,80,"smooth",300]}
```

### `set_scene`

| Bentuk | Contoh | Arti |
|---|---|---|
| `["color", rgb, bright]` | `["color",16711680,100]` | Warna + brightness |
| `["hsv", hue, sat, bright]` | `["hsv",200,80,60]` | HSV + brightness |
| `["ct", kelvin, bright]` | `["ct",3200,50]` | CT + brightness |
| `["cf", count, action, expression]` | `["cf",0,1,"500,1,16711680,100"]` | Flow |
| `["auto_delay_off", bright, minutes]` | `["auto_delay_off",30,10]` | Nyalakan lalu mati setelah N menit |

---

## 6. Flow

Flow adalah rangkaian langkah yang dijalankan firmware secara lokal, jadi tetap berjalan walau koneksi TCP ditutup.

Format `expression`:

```text
duration_ms,mode,value,brightness,duration_ms,mode,value,brightness,...
```

| Mode | Arti | `value` |
|---|---|---|
| `1` | RGB | 0–16777215 |
| `2` | Color temperature | 1700–6500 |
| `7` | Sleep | diabaikan |

`count`: jumlah pengulangan; `0` = infinite.
`action`: `0` = recover state sebelumnya, `1` = stay di state terakhir, `2` = matikan setelah selesai.

Contoh flow merah → hijau → biru, 700 ms per langkah, infinite:

```json
{"id":8,"method":"start_cf","params":[0,1,"700,1,16711680,100,700,1,65280,100,700,1,255,100"]}
```

Catatan:

- Duration minimum yang aman: 50 ms.
- Beberapa firmware membatasi jumlah langkah/panjang string. Untuk kompatibilitas, gunakan ≤ 9 langkah.
- Saat flow berjalan, `flowing` = `1`. `stop_cf` menghentikannya.
- Flow bisa bertabrakan dengan `set_rgb`/`set_ct`; hentikan dulu kalau ingin kontrol manual.

---

## 7. Music mode

Tujuan: mengurangi latency dan melepas quota command, sehingga animasi/audio visualizer bisa halus.

Alur:

1. Buka koneksi TCP persisten.
2. Buat socket UDP lokal, bind ke `0.0.0.0:0` (port acak).
3. Tentukan IP lokal yang bisa dijangkau bulb (biasanya IP interface yang sama).
4. Kirim:

   ```json
   {"id":9,"method":"set_music","params":[1,"192.168.1.10",54321]}
   ```

5. Bulb membalas `{"id":9,"result":["ok"]}` dan mulai mengirim notifikasi `props` ke `192.168.1.10:54321`.
6. Kirim perintah warna seperti biasa lewat TCP. Command tidak lagi dibatasi 60/menit.
7. Untuk berhenti: `{"id":10,"method":"set_music","params":[0]}`, atau tutup koneksi TCP.

Contoh datagram UDP dari bulb:

```json
{"method":"props","params":{"rgb":"16711680"}}
```

Catatan:

- Host/port di `set_music` harus bisa dijangkau bulb. Jangan pakai `127.0.0.1` kecuali bulb dan client di mesin yang sama.
- Bulb umumnya hanya mendukung satu sesi music mode.
- Kalau client putus, `music_on` kembali `0` (bisa sedikit tertunda).
- Music mode bukan pengganti flow; ini untuk stream command berkecepatan tinggi.

---

## 8. Batas dan quota

Spesifikasi Yeelight menyebut:

- Maksimal **4 koneksi TCP** simultan. Koneksi kelima ditolak.
- **60 command/menit per koneksi**.
- **144 command/menit total** untuk semua koneksi.

Konsekuensi:

- Jangan membuka client baru untuk setiap perintah. Reuse satu koneksi.
- Dashboard web memakai satu client dan lock, jadi aman.
- Kalau quota terlampaui, balasan bisa berupa error `-2` (client quota exceeded) atau koneksi ditutup.
- Music mode melepas batas ini pada firmware yang mendukung.

---

## 9. Error code

Format:

```json
{"id":1,"error":{"code":-4,"message":"method not supported"}}
```

| Code | Arti |
|---|---|
| `-1` | General error |
| `-2` | Client quota exceeded |
| `-3` | Invalid params |
| `-4` | Method not supported |
| `-5` | Device offline / internal error (tergantung firmware) |

Penyebab umum:

- `-3`: tipe param salah (string vs number), nilai di luar range, atau jumlah param kurang.
- `-4`: method tidak ada di `support`, atau model tidak mendukung fitur tersebut.
- `-1`: state tidak valid, misalnya `start_cf` saat mode lain sedang sibuk.

---

## 10. Spesifik `color2` / YLDP06YL

YLDP06YL terdaftar di Home Assistant sebagai model `color2`.

| Fitur | Nilai |
|---|---|
| Model string | `color2` |
| CT range | 1700–6500 K |
| RGB | 24-bit, 0–16777215 |
| Brightness | 1–100 |
| Background light | tidak ada (`bg_*` tidak relevan) |
| Music mode | didukung pada firmware yang mendukung `set_music` |
| Flow | didukung |

Contoh `support` yang umum:

```text
get_prop set_default set_power toggle set_bright start_cf stop_cf set_scene
cron_add cron_get cron_del set_ct_abx set_rgb set_hsv set_adjust adjust_bright
adjust_ct adjust_color set_music set_name
```

Quirk yang perlu diingat:

- `get_prop` mengembalikan **string**, bukan angka. Parse sebelum membandingkan.
- `color_mode` bisa berubah otomatis: `set_ct_abx` → 1, `set_rgb` → 2, `set_hsv` → 3.
- `set_rgb` dengan nilai `0xFFFFFF` (putih) tetap masuk mode RGB; untuk white murni gunakan `set_ct_abx`.
- Firmware lama mungkin tidak punya `set_music`; cek `support`.
- Nama perangkat disimpan di firmware dan ikut di respons SSDP.
- Beberapa unit melaporkan `fw_ver` berbeda; jangan mengandalkan nomor itu untuk fitur.

---

## 11. Metode reverse engineering

### Capture traffic

Wireshark/tshark:

```text
tcp.port == 55443 || udp.port == 1982
```

Langkah:

1. Pastikan HP dan bulb di jaringan yang sama.
2. Mulai capture di interface Wi-Fi/Ethernet yang benar.
3. Ubah warna/brightness dari app.
4. Filter `tcp.port == 55443`.
5. Lihat JSON request/response dan notifikasi.

### Kirim perintah manual

```powershell
python -m yeelight_re raw get_prop --params-json '["power","bright","name"]' --ip 192.168.1.20
python -m yeelight_re raw set_scene --params-json '["color",16711680,100]' --ip 192.168.1.20
```

Gunakan `--json` untuk output terstruktur.

### Fuzzing yang aman

- Mulai dari `get_prop` (read-only).
- Hindari `cron_add`, `cron_del`, `set_default` sampai kamu paham efeknya.
- `set_name` mengubah state persisten; catat nama awal.
- `start_cf` bisa meninggalkan flow berjalan; siapkan `stop_cf`.
- Jangan mengirim perintah ke bulb yang sedang dipakai orang lain tanpa izin.

### Analisa firmware

Lihat [HARDWARE.md](HARDWARE.md). Ringkasnya: buka diffuser, identifikasi chip, cari UART, dump flash penuh, simpan backup, baru eksperimen.

---

## 12. Contoh sesi lengkap

```text
$ telnet 192.168.1.20 55443

{"id":1,"method":"get_prop","params":["power","bright","ct","rgb","name"]}
{"id":1,"result":["on","40","3200","16737792","Kamar"]}

{"id":2,"method":"set_bright","params":[70,"smooth",300]}
{"id":2,"result":["ok"]}
{"method":"props","params":{"bright":"70"}}

{"id":3,"method":"set_rgb","params":[65280,"smooth",300]}
{"id":3,"result":["ok"]}
{"method":"props","params":{"rgb":"65280","color_mode":"2"}}

{"id":4,"method":"start_cf","params":[0,1,"500,1,16711680,100,500,1,255,100"]}
{"id":4,"result":["ok"]}
{"method":"props","params":{"flowing":"1"}}

{"id":5,"method":"stop_cf","params":[]}
{"id":5,"result":["ok"]}
{"method":"props","params":{"flowing":"0"}}
```

---

## 13. Kanal miIO (eksperimental)

Selain TCP `55443`, banyak perangkat Yeelight/Xiaomi membuka **miIO** di UDP `54321`. Project ini memakainya hanya untuk satu tujuan: mencoba menyalakan LAN Control tanpa app.

### 13.1 Handshake

Kirim 32 byte:

```text
21 31 00 20  ff ff ff ff ff ff ff ff ff ff ff ff
ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
```

Balasan juga 32 byte:

| Offset | Isi |
|---|---|
| 0–1 | magic `0x2131` |
| 2–3 | panjang paket (32) |
| 4–7 | unknown |
| 8–11 | device ID |
| 12–15 | timestamp perangkat |
| 16–31 | checksum **atau** token |

Firmware lama mengisi 16 byte terakhir dengan **token perangkat**. Firmware baru mengisinya `00…00` atau `ff…ff`. Inilah sebabnya jalur ini tidak selalu bisa dipakai.

### 13.2 Paket perintah

Header 16 byte: magic, total length, unknown, device ID, timestamp. Lalu 16 byte checksum, lalu payload terenkripsi.

- `key = MD5(token)`
- `iv = MD5(key + token)`
- plaintext = JSON + `\x00`, di-pad PKCS#7, dienkripsi AES-128-CBC
- `checksum = MD5(header + token + ciphertext)`

Timestamp perintah harus lebih baru dari timestamp handshake (biasanya `+1`). Implementasi ada di [`yeelight_re/miio.py`](../yeelight_re/miio.py), AES murni-Python di [`yeelight_re/_aes.py`](../yeelight_re/_aes.py).

### 13.3 Perintah unlock

```json
{"id": 1, "method": "set_ps", "params": ["cfg_lan_ctrl", "1"]}
```

Ini **bukan** API resmi Yeelight. Di beberapa model Xiaomi perintah ini berhasil membuka LAN Control; pada YLDP06YL belum diverifikasi. Kalau perangkat menjawab error atau port tetap tertutup, hentikan percobaan.

### 13.4 Batasan

- Tanpa token yang benar, perangkat tidak membalas (atau balasan gagal checksum).
- Token tidak dikirim ke cloud oleh tool ini; `--token` hanya menerima nilai yang sudah dimiliki pengguna.
- miIO dan API LAN adalah dua kanal terpisah: membuka `55443` tidak otomatis mengubah state lampu.
- Jangan flood UDP; satu handshake dan satu `set_ps` sudah cukup.

---

## 14. Pertanyaan terbuka

- Apakah semua varian YLDP06YL memakai MCU yang sama? FCC internal photos menunjukkan modul Wi-Fi, tetapi revisi produksi bisa berbeda.
- Berapa panjang maksimum flow expression yang diterima tiap firmware?
- Apakah `set_ps ["cfg_lan_ctrl","1"]` bekerja di semua revisi YLDP06YL? Belum diuji pada hardware asli.
- Apakah ada cara mengaktifkan LAN Control tanpa app/cloud pada firmware yang tidak membocorkan token? Belum ada tool publik yang matang.
- Apakah quota music mode benar-benar tanpa batas di semua firmware, atau hanya dinaikkan?

Kalau kamu punya capture dari unit sendiri, simpan di `captures/` dan tambahkan catatan firmware/model.
