# Tahap 6 — Portable Windows dan Release Gate

Status: **implementasi dan gate otomatis selesai pada `main`**. Acceptance manual pada laptop fisik Windows 11 non-admin belum dijalankan dan tidak diklaim selesai.

## Ruang lingkup

Tahap 6 menutup F18 dan memperkeras jalur rilis portable Windows tanpa mengubah engine matching, downloader, Spotify resolver, antrean, atau Gemini dari Tahap 1–5.

Perubahan utama:

- dependency runtime utama memakai exact pin;
- dependency transitif dikunci melalui `constraints.lock.txt`;
- Python CI/build dipin ke 3.11.9 dan pip ke 26.2.1;
- PyInstaller dipin ke 6.22.3 dan pyinstaller-hooks-contrib ke 2026.7;
- FFmpeg Essentials dipin ke 9.0 dari asset GitHub release GyanD dan diverifikasi SHA-256;
- Deno dipin ke 2.9.7 dan diverifikasi checksum upstream + SHA-256 pin;
- `ffprobe.exe` menjadi runtime wajib;
- `yt-dlp-ejs` dan metadata distribusinya ikut frozen build;
- frozen `--self-test` menjalankan tool nyata, membuat fixture audio lokal, mengonversinya ke M4A/AAC, lalu memverifikasi stream dengan ffprobe;
- build menghasilkan `VERSION_MANIFEST.json`, `THIRD_PARTY_NOTICES.txt`, `release-info/`, ZIP, dan sidecar `.sha256`;
- ZIP diuji setelah extract ke path Unicode + spasi, seluruh folder dipindahkan, data sentinel harus tetap ada, lalu EXE dijalankan dari cwd berbeda dengan PATH sistem yang dipersempit;
- README portable mendokumentasikan update versi dengan mempertahankan `data/`, `downloads/`, dan `config.json` pengguna.

## Pin rilis

| Komponen | Versi / SHA |
| --- | --- |
| Python | 3.11.9 |
| pip | 26.2.1 |
| PyInstaller | 6.22.3 |
| pyinstaller-hooks-contrib | 2026.7 |
| PySide6 | 6.11.2 |
| yt-dlp | 2026.8.19 |
| yt-dlp-ejs | 0.8.0 |
| spotdl | 4.5.2 |
| mutagen | 1.48.1 |
| FFmpeg Essentials | 9.0 |
| FFmpeg archive SHA-256 | `e6b54767a6065919048f1a098eb27211ca4e12b4348a05d88777a5855d0b6e71` |
| Deno | 2.9.7 |
| Deno archive SHA-256 | `a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238` |

Catatan: sumber FFmpeg awal dari URL package Gyan menghasilkan 404 pada gate Windows. PR tidak di-merge. Sumber diperbaiki ke asset rilis GitHub GyanD tag `9.0`, asset ID `501165133`, dengan digest upstream yang sama dengan pin SHA-256 di atas.

## Regression gate PR

CI PR terakhir sebelum merge membuktikan:

- Python 3.11.9;
- compile berhasil;
- UI DPI smoke 100%, 125%, 150% berhasil;
- production facade 1.000 item berhasil dan urutan `job_id` tetap stabil;
- **83 passed, 0 failed**.

Windows portable gate PR juga lulus sebelum merge, sehingga perubahan tidak masuk `main` dalam keadaan build Windows rusak.

## Bukti otoritatif setelah merge ke `main`

PR #7 di-merge ke `main` sebagai commit:

`39ee188f50a7bf7066521cade5f3666ede48bf68`

Dua workflow dijalankan ulang pada commit `main` tersebut, bukan synthetic merge ref PR.

### CI `main`

Workflow run: `36519823728`

Hasil:

- dependency pinned install: PASS;
- compile Python: PASS;
- UI DPI smoke 100/125/150%: PASS;
- production UI + 1.000 item: PASS;
- pytest: **83 passed in 0.73s**;
- conclusion: **success**.

### Build Windows Portable `main`

Workflow run: `36519823780`

Runner: GitHub-hosted **Windows Server 2025**.

Hasil:

- clean checkout commit `39ee188f...`: PASS;
- pinned dependency install: PASS;
- Windows DPAPI smoke: `WINDOWS_DPAPI_SMOKE_OK`;
- FFmpeg archive checksum: `FFMPEG_ARCHIVE_SHA256_OK`;
- Deno archive checksum: `DENO_ARCHIVE_SHA256_OK`;
- frozen executable runtime/audio test: `FROZEN_RUNTIME_SELF_TEST_OK`;
- extract + relocate pada path Unicode/spasi + restricted PATH: `UNICODE_RELOCATED_PORTABLE_SELF_TEST_OK`;
- portable build: `PORTABLE_BUILD_OK`;
- final ZIP checksum verification: PASS;
- artifact upload: PASS;
- conclusion: **success**.

Artifact otoritatif dari `main`:

- nama artifact: `AI-Music-Downloader-Portable`;
- artifact ID: `11012920039`;
- ukuran outer artifact GitHub: `212910254` byte;
- outer artifact digest: `sha256:183575b4bd3f3a67a306c2bec0e16297cb0d0099147aec43facb8c153e3f283a`;
- internal portable ZIP: sekitar `203.0 MiB`;
- internal ZIP SHA-256: `0526befad586875224926c7add2bc5d337a868c7e13c5c57890078ec3450741b`.

`VERSION_MANIFEST.json` di artifact final mencatat Git SHA `39ee188f50a7bf7066521cade5f3666ede48bf68`, sehingga paket final dapat ditelusuri ke commit `main` yang tepat.

## Audit langsung artifact final

Setelah workflow `main` selesai, artifact ID `11012920039` diunduh kembali dan diperiksa sebagai file, bukan hanya berdasarkan status workflow.

Hasil audit:

- outer artifact SHA-256 cocok dengan digest GitHub: `183575b4...f283a`;
- sidecar `AI-Music-Downloader-Portable.zip.sha256` cocok byte-for-byte dengan ZIP internal;
- ZIP internal SHA-256 terverifikasi: `0526befa...0741b`;
- file wajib benar-benar ada:
  - `AI Music Downloader.exe`;
  - `tools/ffmpeg.exe`;
  - `tools/ffprobe.exe`;
  - `tools/deno.exe`;
  - `VERSION_MANIFEST.json`;
  - `THIRD_PARTY_NOTICES.txt`;
  - `README_PORTABLE.txt`;
  - `release-info/`;
  - `data/`;
  - `downloads/`;
- hash `ffmpeg.exe`, `ffprobe.exe`, dan `deno.exe` cocok dengan nilai di `VERSION_MANIFEST.json`;
- `config.example.json` memiliki `gemini_api_keys: []`;
- scan file teks tidak menemukan pola API key Gemini nyata;
- `data/queue.sqlite3` hanya berisi schema dengan 0 row pada `jobs`, `job_history`, dan `manifest`, sehingga artifact tidak membawa antrean/riwayat proses build.

Hash tool final yang diverifikasi langsung dari artifact:

- `ffmpeg.exe`: `227af0691433b703ffc5725e47f7d06eefc34b4a72e7870e73d30e2cda483ecf`;
- `ffprobe.exe`: `901f0efe4793cbb0f017101e3427f816e8fbf9a407bd585f49df30f4325cfd88`;
- `deno.exe`: `e020f3e232bd16e33768dee528e5983349c962952051ced0a5d58ad42f5d9b33`.

## Batas verifikasi

Gate otomatis ini menguji Windows melalui **GitHub-hosted Windows Server 2025**, bukan laptop fisik clean Windows 11 yang benar-benar non-admin. Karena itu hasil ini tidak boleh ditulis sebagai “pasti bekerja di setiap laptop Windows”.

Acceptance manual eksternal yang masih tersisa:

1. extract artifact final pada clean Windows 11 fisik;
2. jalankan sebagai user non-admin;
3. verifikasi GUI, import sederhana, dan satu download yang memang pengguna berhak unduh;
4. pindahkan folder portable lalu buka ulang;
5. verifikasi queue/config/history pengguna tetap terbaca;
6. bila memakai Gemini, tes satu key milik pengguna melalui tombol **Tes Gemini** dan pastikan mode DPAPI/session-only sesuai pilihan.

Implementasi kode, regression gate, build pipeline, dan artifact integrity Tahap 6 selesai. Acceptance fisik Windows 11 tetap dicatat secara eksplisit sebagai langkah manual di luar CI.
