# Captures

Contoh transaksi di folder ini adalah **contoh sintetis** yang mengikuti protokol, bukan rekaman dari unit fisik. Gunakan sebagai referensi format.

Untuk merekam unit sendiri:

1. Pasang Wireshark/tshark.
2. Filter: `tcp.port == 55443 || udp.port == 1982`.
3. Jalankan `yeelight-re` atau app, lalu simpan `.pcapng`.
4. Jangan commit file pcap berisi data pribadi (IP/MAC/nama).
5. Tambahkan catatan model, `fw_ver`, dan isi `support` di filename/README.

File contoh:

- `ssdp-color2.txt` — respons discovery.
- `session-color2.txt` — sesi TCP: get_prop, power, brightness, RGB, CT, flow, notifikasi.
- `music-mode.txt` — alur music mode via TCP + UDP.
