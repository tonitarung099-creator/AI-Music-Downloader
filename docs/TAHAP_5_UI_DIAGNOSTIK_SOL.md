# Tahap 5 — UI, Diagnostik, dan Penyimpanan API Key

Implementasi Sol untuk `MASTER_PLAN_ASTRA_UNTUK_SOL_AI_MUSIC_DOWNLOADER`.

## Ringkasan

Tahap ini menangani F19 dan sisa F20. Tujuan utamanya adalah membuat fungsi Tahap 1–4 dapat digunakan dari UI tanpa bergantung pada log teknis, menjaga operasi antrean tetap berbasis `job_id`, serta mencegah API key bocor melalui config, log, laporan, atau diagnostic bundle.

## MainWindow produksi

Entry point `main.py` sekarang memakai `app.ui.production_window.MainWindow` sebagai facade produksi tunggal. Behavior Tahap 1–4 tetap diwarisi, sementara lapisan Tahap 5 menambahkan UI dan diagnostik tanpa mengubah engine download, matcher, Spotify importer, atau queue worker.

Layout tiga area lama dibungkus `QSplitter`:

- kiri: input dan pengaturan,
- tengah: antrean utama,
- kanan: Gemini dan log.

Panel Gemini dapat disembunyikan sehingga antrean memperoleh ruang tambahan. Minimum window diturunkan menjadi 960×640 dan target default 1366×768.

## Alur pengguna

UI sekarang menyediakan:

- tombol Indonesia: **Mulai**, **Jeda/Lanjutkan**, **Hentikan**, **Coba Lagi yang Gagal**, dan **Coba Lagi Terpilih**,
- pencarian antrean,
- filter status,
- hapus item terpilih,
- retry hanya item gagal/dibatalkan yang dipilih,
- detail lagu,
- buka file hasil,
- riwayat event SQLite,
- ringkasan batch,
- empty state / hasil filter kosong,
- drag/drop TXT, CSV, URL, atau teks ke kotak input.

Pencarian/filter hanya menyembunyikan baris tampilan. Urutan `self.tracks` tidak diubah. Semua aksi terpilih memetakan baris kembali ke `job_id`, bukan mengandalkan nomor baris sebagai identitas job.

## Detail dan riwayat

Dialog **Detail Lagu** menampilkan permintaan awal, sumber, status, kandidat yang dipilih, URL hasil, container nyata, codec audio, durasi, ukuran file, output path, alasan matching/error, serta preferensi versi `avoid/prefer` bila ada.

Dialog **Riwayat** membaca tabel `job_history` SQLite. Jika tepat satu job dipilih, riwayat difilter ke job tersebut; tanpa satu pilihan tunggal, riwayat terbaru seluruh antrean ditampilkan.

## Laporan batch

Laporan dapat diekspor sebagai CSV atau JSON. Record mencakup:

- job ID dan urutan,
- permintaan, judul, artis, sumber,
- status dan progress,
- hasil judul/URL/file,
- container, codec, durasi, dan ukuran hasil terverifikasi,
- alasan pemilihan,
- error code dan detail error.

Semua field teks melewati redaction dan metadata sensitif disanitasi sebelum ekspor.

## Diagnostik dan redaction

`DiagnosticLog` menyimpan log terstruktur dengan timestamp, level, dan pesan yang telah dibersihkan. Redaction mencakup:

- pola Google API key `AIza...`,
- Bearer token,
- query parameter seperti `key`, `api_key`, `token`, `access_token`, dan authorization,
- field bernama key/token/cookie/secret/password/authorization dalam mapping.

**Ekspor Diagnostik** menghasilkan ZIP berisi `diagnostics.json` dan `log.txt`. Bundle hanya menyertakan jumlah API key, bukan isi API key.

## Penyimpanan Gemini API key

`config.json` tidak lagi menyimpan API key plaintext. Dua mode tersedia:

1. **Windows DPAPI** — key dienkripsi dengan profil akun Windows saat ini dan disimpan di `data/gemini_keys.dpapi`.
2. **Hanya sesi** — key aktif selama aplikasi berjalan dan tidak dipersistenkan.

Dialog key tetap masked secara default, dapat reveal eksplisit, mendukung impor TXT dengan dedup sampai 100 key, dan ekspor hanya daftar key yang sudah dimasking. Jika blob DPAPI dipindahkan ke akun/komputer Windows yang tidak dapat mendekripsinya, aplikasi menampilkan warning dan meminta pengguna memasukkan ulang key.

Environment variable `GEMINI_API_KEY(S)` tetap diperlakukan sebagai session-only.

## Regression dan gate

CI PR Tahap 5 memverifikasi:

- compile seluruh Python,
- facade `production_window` dapat dibuat,
- panel Gemini dapat hide/show,
- resolusi 1366×768 pada `QT_SCALE_FACTOR` 1.0, 1.25, dan 1.5,
- antrean 1.000 item dapat dimasukkan dan difilter sambil mempertahankan urutan job ID,
- redaction API key/token/Bearer,
- laporan CSV/JSON tidak membocorkan rahasia,
- diagnostic ZIP tidak membocorkan rahasia,
- mode DPAPI tidak menulis key ke `config.json` (unit test dengan secure-store fixture),
- mode session-only tidak menulis key ke `config.json`,
- drag/drop TXT/CSV mempertahankan urutan,
- status filter mempertahankan scope dan urutan stabil.

Gate CI terakhir sebelum dokumentasi menghasilkan **78 passed, 0 xfail**. Workflow Windows juga memiliki smoke DPAPI nyata sebelum build portable; validasi tersebut dijalankan pada workflow Windows setelah perubahan masuk `main`.
