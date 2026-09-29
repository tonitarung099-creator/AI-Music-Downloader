# Tahap 9 — Release Gate Fisik

Tanggal: 29 September 2026

Tahap ini tidak mengubah engine download, matching, persistence, Gemini, atau layout UI. Tujuannya menutup gap antara artifact CI yang lulus dan klaim rilis stabil pada laptop Windows 11 fisik.

## Masalah yang ditutup

Sebelumnya `UJI_WINDOWS_11.bat` menjalankan acceptance otomatis dan dapat keluar dengan kode 0 setelah tes otomatis lulus, sementara tiga pemeriksaan manual (GUI nyata, satu download nyata, dan persistensi setelah restart) hanya ditampilkan sebagai instruksi. Artinya exit code 0 belum membuktikan seluruh gate rilis stabil selesai.

## Perubahan

- `ACCEPTANCE_WINDOWS_11.ps1` memakai schema laporan versi 2.
- Laporan menyimpan `app_version`, Git SHA manifest, SHA-256 manifest, SHA-256 executable, hasil otomatis, dan hasil manual.
- Mode fisik non-CI meminta tiga konfirmasi eksplisit:
  1. GUI tampil normal.
  2. Satu download nyata yang sah berhasil sampai file audio valid.
  3. Setelah aplikasi ditutup dan dibuka lagi, data/riwayat/pengaturan tetap terbaca.
- `release_ready=true` hanya bila acceptance otomatis lulus, Windows 11 fisik terdeteksi, proses tidak elevated/admin, dan ketiga konfirmasi manual lulus.
- Mode CI selalu menghasilkan `release_ready=false`; CI tidak boleh mengisi `manual_checks` atau menyamar sebagai uji fisik.
- Exit code fisik:
  - `0`: acceptance penuh lulus dan `release_ready=true`.
  - `2`: otomatis lulus tetapi gate manual belum lengkap/lulus.
  - `1`: acceptance otomatis gagal.
- `UJI_WINDOWS_11.bat` menjelaskan tiga gate dan status akhirnya dalam Bahasa Indonesia.
- Workflow Windows memverifikasi bahwa mode CI tidak pernah mempromosikan artifact menjadi release-ready.

## Bukti yang harus dikirim setelah uji laptop

File:

`data/acceptance-windows11.json`

Promosi `v1.0.0-rc1` menjadi `v1.0.0` stabil hanya boleh dilakukan bila laporan dari mesin Windows 11 fisik menunjukkan:

- `ci_mode: false`
- `automated_passed: true`
- tiga `manual_checks[].passed: true`
- `release_ready: true`

Konfirmasi manual adalah attestasi pengguna pada mesin fisik, bukan sesuatu yang dapat dipalsukan atau digantikan oleh runner CI.
