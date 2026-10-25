yeelight-re 0.3.0 - Windows x64
===============================

Toolkit lokal untuk Yeelight YLDP06YL (color2). Tidak butuh Python,
tidak butuh instalasi, tidak butuh akun/cloud.

Isi paket:
  yeelight-re-gui.exe   aplikasi GUI (klik dua kali, tanpa console)
  yeelight-re.exe       versi command line
  CARA-PAKAI.txt        berkas ini


GUI (paling mudah)
------------------
1. Klik dua kali yeelight-re-gui.exe
2. Klik "Cari bulb" atau isi IP bulb (mis. 192.168.1.20)
3. Klik "Hubungkan"

IP LAMPU BERUBAH-UBAH (DHCP)?
------------------------------
Klik tombol "Pindai subnet". GUI menyapu seluruh jaringan lokal lewat
TCP 55443, lalu mengenali lampu (nama/model/daya/kecerahan) dan langsung
menyambung kalau hanya ada satu lampu.

Kalau jaringan Anda bukan /24 standar, isi kolom "Subnet", misalnya
192.168.0.0/24. Kosongkan untuk memindai semua antarmuka jaringan PC
(Wi-Fi, Ethernet, dsb.) — masing-masing /24.

GUI juga otomatis memindai subnet ketika dibuka dan IP tersimpan sudah
tidak menjawab — jadi setelah lampu dapat IP baru, cukup buka aplikasi.

Cara permanen: atur DHCP Reservation / Static Lease untuk MAC lampu di
router supaya IP-nya tetap.

Kalau port 55443 menolak, GUI otomatis menawarkan unlock lewat miIO.
Tombol "Unlock LAN (miIO)" juga tersedia di bar koneksi.
Jika lampu ter-reset / baru (hotspot yeelink-light-..._miap aktif):
Sambungkan PC ke hotspot lampu, lalu klik "Pairing Wi-Fi (Reset)" untuk
mengirim nama & password Wi-Fi rumah tanpa app!

Fitur GUI: daya, kecerahan, warna (color picker + swatch), HSV, suhu warna,
scene, flow, music mode, timer mati, ganti nama, raw command, diagnosa,
pindai subnet, dan log aktivitas.

Jalankan dengan IP langsung:
  yeelight-re-gui.exe --ip 192.168.1.20

Atau lewat CLI (otomatis membuka yeelight-re-gui.exe):
  yeelight-re.exe gui --ip 192.168.1.20


Command line (opsional)
-----------------------
Buka Command Prompt / PowerShell di folder ini:

  yeelight-re.exe discover
  yeelight-re.exe scan                     <- cari lampu saat IP berubah
  yeelight-re.exe scan --subnet 192.168.1.0/24
  yeelight-re.exe scan --json
  yeelight-re.exe doctor --ip 192.168.1.20
  yeelight-re.exe wifi-setup --ssid "MyWiFi" --password "pass123"
  yeelight-re.exe miio --ip 192.168.1.20 --enable
  yeelight-re.exe on --ip 192.168.1.20
  yeelight-re.exe bright 40 --ip 192.168.1.20
  yeelight-re.exe color "#ff6600" --ip 192.168.1.20
  yeelight-re.exe ct 3200 --ip 192.168.1.20
  yeelight-re.exe web --ip 192.168.1.20 --open

  yeelight-re.exe --help
  yeelight-re.exe scan --help
  yeelight-re.exe miio --help


Catatan
-------
- Tidak ada koneksi cloud. Semua trafik hanya ke IP bulb di LAN.
- Windows SmartScreen / antivirus bisa memberi peringatan karena EXE
  hasil PyInstaller belum ditandatangani. Itu normal untuk build lokal.
- Kalau `miio` menjawab tetapi token 0x00, jalur tanpa app buntu.
  Lihat docs/TANPA-LOGIN.md untuk opsi app-sekali atau hardware.
- Music mode membuka UDP lokal sementara; setelah demo selesai, mode
  dimatikan otomatis.
