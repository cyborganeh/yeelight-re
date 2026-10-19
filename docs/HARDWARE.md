# Jalur hardware: teardown, UART, dump, dan firmware alternatif

Dokumen ini untuk kamu yang ingin **benar-benar melepas YLDP06YL dari cloud**, termasuk melewati flag LAN Control yang dimatikan firmware. Ini bukan proyek soldering pemula.

> **Peringatan tegangan listrik.** Bulb berjalan di 110–240 V AC. Kapasitor di board bisa menyimpan tegangan setelah dicabut. Bekerja di perangkat yang masih tersambung listrik bisa mematikan. Gunakan isolation transformer, alat berinsulasi, dan jangan menyentuh sisi AC. Kalau ragu, berhenti.

> **Risiko.** Membuka bulb membatalkan garansi. Salah pinout bisa merusak MCU, driver LED, atau power supply. Firmware alternatif bisa membuat bulb tidak bisa kembali. Selalu **dump penuh dan backup** sebelum menulis apa pun.

---

## 1. Apakah perlu jalur ini?

Ya, kalau:

- LAN Control tidak bisa diaktifkan lewat app (opsi hilang, firmware mengunci, atau bulb tidak bisa di-bind).
- Kamu tidak mau app/akun sama sekali.
- Kamu ingin firmware yang 100% lokal, misalnya ESPHome/OpenBeken.
- Kamu ingin memahami hardware dan firmware-nya.

Tidak perlu, kalau:

- LAN Control sudah ON dan tool ini sudah bisa kontrol. Cukup blokir WAN.
- Kamu hanya butuh kontrol lokal dan tidak masalah login sekali ke app.

Baca [TANPA-LOGIN.md](TANPA-LOGIN.md) dulu.

---

## 2. Identifikasi varian hardware

YLDP06YL punya beberapa revisi produksi. **Jangan menganggap semua unit memakai chip yang sama.** Langkah pertama adalah melihat marking di PCB/modul.

Sumber foto:

- FCC ID `2ABEU-YLDP06YL`, exhibit **Internal Photos**: <https://fccid.io/2ABEU-YLDP06YL>
- Cari juga foto teardown komunitas untuk batch yang sama.
- Catat marking modul: misalnya `ESP-12`, `ESP8285`, `RTL8710`, `BK7231`, `MXCHIP`, atau modul custom Yeelight.

Kandidat yang sering muncul di perangkat Wi-Fi sezaman:

| Chip/keluarga | Tool dump/flash | Catatan |
|---|---|---|
| ESP8266 / ESP8285 | `esptool.py` | Paling mudah; UART + GPIO0 ke GND saat boot |
| ESP32 | `esptool.py` | Perlu konfirmasi pin flash; biasanya 3.3 V |
| Beken BK7231T/N | `ltchiptool`, OpenBeken | Umum di perangkat Tuya; boot pin khusus |
| Realtek RTL8710/8711 | tool Realtek/ltchiptool (tergantung varian) | Lebih sulit; dokumentasi terbatas |
| Modul custom | tergantung chip di dalamnya | Buka shield, cari marking IC |

Kalau modul tertutup shield, jangan langsung congkel; cari foto FCC/teardown yang menunjukkan isi shield. Shield bisa disolder, bukan hanya dijepit.

---

## 3. Buka bulb

1. Cabut dari listrik. Tunggu minimal 5 menit.
2. Lepas diffuser plastik. Biasanya direkatkan/klip; gunakan heat gun pelan di tepi, spudger plastik. Jangan memutar/menekan PCB.
3. Catat posisi LED, reflektor, dan kabel. Foto dari beberapa sudut.
4. Cari board RF dan board LED/driver. Pada banyak bulb, board RF berdiri vertikal di slot.
5. Cari pad UART: biasanya 4 pad (`GND`, `3V3`, `TX`, `RX`), kadang tanpa label.
6. Cari tombol/TP untuk reset atau boot mode.

Jangan melepas heatsink LED tanpa keperluan; thermal paste bisa rusak.

---

## 4. Cari UART dengan aman

Alat:

- USB-TTL **3.3 V** (jangan 5 V).
- Multimeter.
- Logic analyzer 8-channel (sangat membantu) atau scope.
- Kabel dupont/jumper halus, solder jika perlu.
- Adaptor 3.3 V terpisah atau power bulb via fixture yang aman.

Langkah:

1. **Dengan bulb mati**, ukur kontinuitas untuk menemukan `GND` (biasanya terhubung ke ground plane/large trace).
2. Cari `3V3` (rail 3.3 V) — ukur saat hidup, hati-hati.
3. Cari `TX`: saat boot, pad ini mengeluarkan data. Logic analyzer paling aman; jangan tusuk sembarang pad dengan probe.
4. Cari `RX`: sering berpasangan dengan TX dan punya pull-up.
5. Hubungkan `GND` tool ke `GND` board. **Jangan hubungkan VCC tool ke board jika board sudah diberi daya.**
6. Coba baud umum: `115200` (ESP8266/ESP32), `74880` (boot log ESP8266), `57600`, `38400`.
7. Simpan log boot. Log sering menyebut chip, firmware, dan partisi.

Kalau tidak yakin pinout: berhenti. Salah memasukkan 3.3 V ke pin data bisa merusak SoC.

---

## 5. Dump firmware (wajib sebelum flash)

Tujuan: punya backup yang bisa dikembalikan.

### ESP8266/ESP32

```powershell
# Cari port
python -m esptool --port COM5 chip_id
python -m esptool --port COM5 flash_id

# Baca seluruh flash (sesuaikan ukuran; 4 MB = 0x400000)
python -m esptool --port COM5 read_flash 0 0x400000 backup-yldp06yl.bin

# Verifikasi
python -m esptool --port COM5 verify_flash 0 backup-yldp06yl.bin
```

Simpan minimal dua salinan di disk berbeda. Catat ukuran flash dan MAC.

### BK7231

Gunakan `ltchiptool` (GUI/CLI) atau OpenBeken flasher. Pilih chip yang benar (BK7231T vs BK7231N), baca full flash, dan simpan. Jangan menulis firmware sebelum dump berhasil dan bisa dibuka kembali.

### RTL8710/8711

Tool tergantung varian. Cari dokumentasi chip dari marking IC; jangan pakai tool ESP. Kalau tidak ada tool yang jelas, jalur ini bukan untuk pemula.

### Hal yang harus disimpan

- Full flash dump (bukan hanya app partition).
- MAC address, RF calibration, dan area NVS/settings.
- Foto pinout dan posisi kabel.
- Log boot asli.
- Versi firmware asli.

---

## 6. Pilihan firmware alternatif

### ESPHome (ESP8266/ESP32)

Keunggulan: native Home Assistant API, OTA, log, PWM/color control.

Tapi: **pinout LED driver harus diketahui**. YLDP06YL memakai driver LED khusus; output MCU bisa berupa PWM ke driver, bukan langsung ke LED. Jangan menganggap pin GPIO standar.

Contoh kerangka (placeholder, bukan pinout final):

```yaml
esphome:
  name: yldp06yl
  friendly_name: YLDP06YL

esp8266:
  board: esp01_1m   # sesuaikan dengan chip/flash sebenarnya

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:
    ssid: "yldp06yl-fallback"

logger:
  baud_rate: 0

api:
ota:

output:
  - platform: esp8266_pwm
    id: out_red
    pin: GPIO12     # GANTI setelah tracing
    frequency: 1000 Hz
  - platform: esp8266_pwm
    id: out_green
    pin: GPIO13
    frequency: 1000 Hz
  - platform: esp8266_pwm
    id: out_blue
    pin: GPIO14
    frequency: 1000 Hz
  - platform: esp8266_pwm
    id: out_white
    pin: GPIO15
    frequency: 1000 Hz

light:
  - platform: rgbw
    name: "YLDP06YL"
    red: out_red
    green: out_green
    blue: out_blue
    white: out_white
```

Catatan:

- Kalau driver memakai dua channel putih (warm/cool), gunakan `rgbww` dan tambahkan output kedua.
- Kalau driver memakai SPI/I2C, ESPHome butuh komponen khusus; bukan PWM biasa.
- Mulai dengan brightness rendah dan ukur arus; jangan langsung 100%.
- Pastikan GPIO yang dipakai tidak bentrok dengan flash (GPIO6–11 pada ESP8266).
- Cek suhu driver setelah 10 menit.

### OpenBeken (BK7231)

OpenBeken bisa menggantikan firmware Tuya/Beken dan menyediakan MQTT/Home Assistant. Kamu perlu:

- Identifikasi chip (BK7231T/N).
- Dump flash.
- Flash OpenBeken.
- Konfigurasi pin role untuk channel LED dan tombol.
- Simpan backup untuk rollback.

Pin mapping tetap harus ditelusuri; jangan menebak.

### Tasmota

Mungkin untuk ESP8266, tetapi driver LED bulb tidak selalu didukung. ESPHome/OpenBeken biasanya lebih fleksibel untuk RGBW custom.

---

## 7. Rollback

Sebelum flash, pastikan:

- Backup full flash bisa dibaca ulang.
- Kamu tahu perintah restore untuk chip tersebut.
- Kamu punya sumber daya stabil (jangan via USB port lemah).
- Kamu bisa membuka bulb lagi kalau OTA gagal.

Restore ESP:

```powershell
python -m esptool --port COM5 write_flash 0x0 backup-yldp06yl.bin
```

Setelah restore, verifikasi boot log dan koneksi Wi-Fi.

---

## 8. Setelah firmware alternatif

- Tidak ada cloud, tidak ada akun, tidak ada flag LAN Control.
- Kontrol via Home Assistant API/MQTT/Web UI lokal.
- Update via OTA.
- Catat konfigurasi pin dan kalibrasi warna (setiap bulb bisa beda).
- Simpan backup firmware asli selamanya.

Konsekuensi:

- Fitur asli (scene Yeelight, music sync app, update resmi) hilang.
- Garansi hilang.
- Kalau driver LED tidak dipahami, warna bisa tidak akurat atau LED rusak.

---

## 9. Alternatif tanpa membuka bulb

Kalau tujuanmu hanya "tidak mau login":

1. Nyalakan LAN Control sekali lewat app, lalu blokir WAN. Ini jauh lebih aman.
2. Gunakan Home Assistant dengan integrasi Yeelight lokal.
3. Kalau app benar-benar tidak bisa, pertimbangkan bulb lain yang mendukung Tasmota/ESPHome dari pabrik.

Jalur hardware adalah pilihan terakhir, bukan langkah pertama.

---

## 10. Checklist

- [ ] Sudah baca [TANPA-LOGIN.md](TANPA-LOGIN.md) dan yakin jalur app tidak bisa.
- [ ] Punya alat keselamatan listrik.
- [ ] Sudah foto dan catat pinout.
- [ ] Sudah identifikasi chip dengan marking/foto FCC.
- [ ] Sudah dump full flash dan verifikasi.
- [ ] Sudah simpan backup di dua tempat.
- [ ] Sudah paham driver LED dan pin mapping.
- [ ] Sudah siap rollback.
- [ ] Sudah izin pemilik perangkat (kalau bukan milik sendiri).

---

## Referensi

- FCC internal photos: <https://fccid.io/2ABEU-YLDP06YL>
- Yeelight LAN spec: <https://www.yeelight.com/download/Yeelight_Inter-Operation_Spec.pdf>
- ESPHome light components: <https://esphome.io/components/light/>
- OpenBeken: <https://github.com/openshwprojects/OpenBK7231T_App>
- `ltchiptool`: <https://github.com/libretiny-eu/ltchiptool>
- `esptool`: <https://docs.espressif.com/projects/esptool/>

Project ini tidak menyediakan pinout final karena revisi hardware bisa berbeda. Kalau kamu berhasil menelusuri unit sendiri, tambahkan catatan model/firmware/foto ke `captures/` atau buka issue.
