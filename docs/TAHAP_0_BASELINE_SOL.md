# Tahap 0 — Baseline dan Regression Gate (Sol)

Tanggal: 28 September 2026  
Repository: `tonitarung099-creator/AI-Music-Downloader`

## 1. Baseline yang diperiksa

- Baseline audit Astra: `28f35c720733b41a0a4bab66ae10166f9d9265a6`.
- HEAD sebelum implementasi Sol: `632deda00c867d4408e3c0cb2b846dfa6f1d3301`.
- Selisih baseline → HEAD sebelum Sol hanya satu commit dokumentasi master plan Astra. Tidak ada perubahan kode aplikasi setelah baseline audit.
- Entrypoint produksi pada `main.py` memakai `app.ui.main_window_v3.MainWindow`.
- CI lama melakukan smoke terhadap `main_window_v2`, sehingga tidak sama dengan entrypoint produksi.

## 2. Baseline dependency dan tool

Baseline CI yang dicatat Astra menjalankan Python 3.11 dan melaporkan:

- `spotdl==4.5.2`
- `yt-dlp==2026.8.19`
- `PySide6==6.11.2`
- `yt-dlp-ejs==0.8.0`
- hasil: 13 passed, 1 warning

`requirements.txt` saat Tahap 0 masih belum mem-pin versi (`PySide6`, `yt-dlp`, `spotdl`). Tahap 0 tidak mengubah kebijakan dependency; CI sekarang mencetak versi aktual setiap run agar perubahan lingkungan terlihat.

Tool portable saat Tahap 0:

- Python build: 3.11 pada workflow Windows.
- PyInstaller: `>=6.11,<7` pada workflow build Windows.
- FFmpeg: diambil dari URL `ffmpeg-release-essentials.zip`; versi dan checksum belum dipin.
- Deno: diambil dari release `latest`; checksum file unduhan diverifikasi, tetapi versi belum dipin.
- `ffprobe.exe` disalin bila ditemukan, namun belum menjadi required item pada verifikasi package.

Kekurangan reproduksibilitas tool tersebut merupakan pekerjaan Tahap 6/F18, bukan diperbaiki pada Tahap 0.

## 3. Hasil CI Tahap 0

PR Tahap 0 menjalankan workflow CI run `36376891023` dan lulus.

Versi aktual yang direkam pada run tersebut:

- Python `3.11.16`
- pip `26.2.1`
- `PySide6==6.11.2`
- `yt-dlp==2026.8.19`
- `spotdl==4.5.2`
- `yt-dlp-ejs==0.8.0`
- `pytest==9.1.1`

Hasil verifikasi:

- compileall: lulus;
- UI smoke `main_window_v3`: lulus (`UI_V3_SMOKE_OK`);
- pytest: `13 passed, 7 xfailed, 1 warning`;
- tidak ada XPASS dan tidak ada regression fixture yang berubah menjadi setup/import error.

## 4. Regression gate yang ditambahkan

File `tests/test_stage0_regressions.py` menambahkan fixture deterministik untuk temuan berikut:

| Temuan | Perilaku baseline yang direproduksi | Status Tahap 0 |
|---|---|---|
| F01 | Spotify metadata dipanggil tanpa bootstrap client | `xfail(strict=True)` |
| F03 | Kandidat score sangat buruk masih diterima | `xfail(strict=True)` |
| F03 | Gemini confidence `0.0` masih dapat memilih kandidat | `xfail(strict=True)` |
| F05 | Kegagalan satu baris Spotify membuang hasil valid batch | `xfail(strict=True)` |
| F08 | `config.json = null` menyebabkan startup error | `xfail(strict=True)` |
| F10 | Bentuk `CommandPlan` tidak valid belum ditolak | `xfail(strict=True)` |
| F12 | Hasil download `{}` tetap ditandai `DONE` | `xfail(strict=True)` |

Marker `xfail(strict=True)` sengaja dipakai untuk bug baseline yang belum diperbaiki pada Tahap 0. Dengan mode strict, ketika implementasi berikutnya membuat tes tersebut lolos, CI akan menghasilkan XPASS dan memaksa pengembang menghapus marker serta menjadikannya regression test normal.

Tes bukan sekadar memeriksa keberadaan nama fungsi/string; masing-masing mengeksekusi jalur perilaku yang bermasalah dengan fake/mocking deterministik tanpa akses jaringan.

## 5. F17 awal — CI dan smoke produksi

Perubahan CI Tahap 0:

1. Smoke Qt sekarang mengimpor `app.ui.main_window_v3.MainWindow`, sama dengan `main.py` produksi.
2. CI mencetak versi Python, pip, PySide6, yt-dlp, spotDL, yt-dlp-ejs, dan pytest.
3. Pytest dijalankan dengan ringkasan XFAIL/XPASS (`-rxX`) agar regression gate terlihat di log.
4. Compileall tetap dipertahankan, tetapi bukan dianggap bukti Tahap 0 selesai.

## 6. Batas verifikasi Tahap 0

Tahap 0 hanya membangun baseline dan regression gate. Tahap ini **tidak** mengklaim F01/F03/F05/F08/F10/F12 sudah diperbaiki.

Live Spotify, Gemini, YouTube download, dan executable Windows tidak dijadikan syarat regression fixture karena tes deterministik harus dapat berjalan tanpa layanan eksternal. Build/frozen Windows tetap diverifikasi oleh workflow terpisah pada tahapan rilis.

## 7. Gate Tahap 0

Tahap 0 dianggap lolos karena:

- source branch berasal dari HEAD terbaru yang sudah dicocokkan dengan baseline Astra;
- smoke CI memakai UI v3 produksi;
- test suite lama tetap lulus;
- fixture target F01/F03/F05/F08/F10/F12 dieksekusi dan tercatat sebagai expected failure, bukan error setup/import;
- tidak ada XPASS tak disengaja;
- log CI merekam versi dependency aktual.
