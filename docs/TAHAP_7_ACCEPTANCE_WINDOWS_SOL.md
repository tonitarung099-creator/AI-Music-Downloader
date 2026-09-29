# Tahap 7 — Acceptance Windows 11 Fisik

Tanggal: 29 September 2026  
Repository: `tonitarung099-creator/AI-Music-Downloader`

## Tujuan

Tahap 7 tidak mengubah engine download/matching/Gemini. Tujuannya adalah mengubah acceptance fisik Windows 11 yang sebelumnya hanya checklist manual menjadi alur satu-klik yang dapat dijalankan pengguna dari paket portable yang sama.

## Implementasi

Dua file baru dibundel ke root ZIP portable:

- `UJI_WINDOWS_11.bat` — launcher satu-klik untuk pengguna;
- `ACCEPTANCE_WINDOWS_11.ps1` — acceptance harness terstruktur.

Harness mode fisik memeriksa:

1. sistem adalah Windows 11, bukan Windows Server CI;
2. proses berjalan sebagai user biasa/non-elevated;
3. `AI Music Downloader.exe` dan `VERSION_MANIFEST.json` tersedia;
4. SHA-256 `ffmpeg.exe`, `ffprobe.exe`, dan `deno.exe` cocok dengan manifest;
5. folder `data/` dapat ditulis tanpa admin;
6. frozen EXE lulus `--self-test` dengan PATH sistem dipersempit;
7. seluruh folder portable dapat disalin dan dipindahkan ke path Unicode + spasi;
8. sentinel dalam `data/` tetap ada setelah relocation;
9. EXE tetap lulus self-test setelah relocation.

Laporan otomatis disimpan sebagai:

`data/acceptance-windows11.json`

Laporan tidak menyertakan API key, cookie, token, username, atau nama komputer. Isinya terbatas pada status check, versi Windows, status elevated, Git SHA manifest, timestamp, dan langkah manual tersisa.

## CI mode

Workflow Windows menjalankan harness yang sama langsung dari ZIP hasil build dengan `-CiMode`.

CI mode sengaja **tidak** menganggap GitHub-hosted Windows Server 2025 sebagai Windows 11 fisik dan tidak menggagalkan run karena runner GitHub memang elevated. Semua check runtime/manifest/hash/relocation tetap dijalankan.

Marker gate:

- `WINDOWS11_PHYSICAL_ACCEPTANCE_AUTOMATED_OK`
- `PACKAGED_WINDOWS_ACCEPTANCE_HARNESS_OK`

## Regression gate

PR #9:

- CI: **87 passed, 0 failed**;
- Build Windows Portable #23: success;
- DPAPI smoke: success;
- frozen runtime self-test: success;
- checksum ZIP: success;
- packaged acceptance harness: success;
- artifact upload: success.

Setelah merge, commit kode `main`:

`6604662ce1f54dc32e6a6efa9cb957f675ab0b3d`

CI `main` run `36521993438`: success.

Build Windows Portable `main` run `36521993353`: success.

## Artifact acceptance-ready dari main

Artifact:

- name: `AI-Music-Downloader-Portable`;
- Artifact ID: `11012788241`;
- outer artifact size: `212915412` byte;
- outer artifact SHA-256: `e2266d5b57b08516aec5f2c1d8f5de1023c831f028cd84ddf783a3539e2523ee`.

Internal portable ZIP:

- ukuran sekitar `203.1 MiB`;
- SHA-256: `4bb27ade79bc1e51322d462ba3d7e69e00d8bfc7e668b74788be5e993b02a00b`;
- sidecar `.sha256`: cocok dengan hash aktual.

Manifest di dalam ZIP menunjuk tepat ke commit kode `6604662ce1f54dc32e6a6efa9cb957f675ab0b3d`.

## Tiga langkah manual yang tetap diperlukan

Tes otomatis tidak dapat menggantikan pengalaman pengguna nyata. Setelah `UJI_WINDOWS_11.bat` lulus pada laptop Windows 11 fisik non-admin, lakukan:

1. buka `AI Music Downloader.exe` dan pastikan GUI tampil normal;
2. selesaikan satu download media yang memang pengguna berhak/diizinkan unduh dan pastikan file hasil dapat dibuka;
3. tutup dan buka kembali aplikasi, lalu pastikan antrean, riwayat, dan pengaturan tetap terbaca.

Jika ketiga langkah itu juga PASS, mesin tersebut dapat dianggap melewati acceptance release candidate.

## Batas klaim

Gate otomatis yang sudah lulus memakai GitHub-hosted **Windows Server 2025**, bukan laptop fisik Windows 11. Karena itu repository tidak mengklaim acceptance fisik selesai sampai `UJI_WINDOWS_11.bat` dan tiga langkah manual di atas benar-benar dijalankan pada mesin pengguna.
