# Tahap 6 — Portable Windows dan Release Gate

Status: **implementasi dan gate otomatis selesai** pada PR #7. Acceptance manual pada laptop fisik Windows 11 non-admin belum dijalankan dan tidak diklaim selesai.

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

## Regression gate

CI PR #63 pada head `552031de681bff1414b74a759093fa3a2d91f7dd`:

- Python 3.11.9;
- compile berhasil;
- UI DPI smoke 100%, 125%, 150% berhasil;
- production facade 1.000 item berhasil dan urutan `job_id` tetap stabil;
- **83 passed, 0 failed**.

## Windows portable gate

Workflow **Build Windows Portable #20** pada head yang sama selesai `success` di GitHub-hosted Windows Server 2025.

Bukti penting:

- clean checkout: PASS;
- pinned dependency install: PASS;
- Windows DPAPI smoke: `WINDOWS_DPAPI_SMOKE_OK`;
- FFmpeg archive checksum: `FFMPEG_ARCHIVE_SHA256_OK`;
- Deno archive checksum: `DENO_ARCHIVE_SHA256_OK`;
- frozen executable runtime/audio test: `FROZEN_RUNTIME_SELF_TEST_OK`;
- extract + relocate pada path Unicode/spasi + restricted PATH: `UNICODE_RELOCATED_PORTABLE_SELF_TEST_OK`;
- portable build: `PORTABLE_BUILD_OK`;
- final ZIP checksum verification: PASS;
- artifact upload: PASS.

Portable ZIP pada PR gate:

- ukuran ZIP internal: sekitar 203.0 MiB;
- SHA-256 ZIP portable: `5d21bfbe57b8bb5826406918311e19a8f98856ca10101696897b91387f8f3e97`;
- artifact GitHub: `AI-Music-Downloader-Portable`;
- artifact ID: `11012168315`;
- ukuran outer artifact GitHub: `212910196` byte;
- outer artifact digest: `sha256:d3174ca91b38efb1f5cbb30cafcc0ba8d0fb335103bd32e100a7c13dd2f01fae`.

`GIT_SHA` yang tercatat dalam artifact PR adalah SHA synthetic merge ref GitHub (`2d131312...`), karena workflow pull request checkout merge ref. Setelah PR di-merge, workflow `main` harus membangun ulang artifact dari commit `main` sebenarnya; SHA manifest dan SHA ZIP final dapat berbeda dan artifact `main` itulah yang menjadi bukti rilis otoritatif.

## Batas verifikasi

Gate otomatis ini menguji Windows melalui **GitHub-hosted Windows Server 2025**, bukan laptop fisik clean Windows 11 yang benar-benar non-admin. Karena itu hasil ini tidak boleh ditulis sebagai “pasti bekerja di setiap laptop Windows”. Acceptance manual Astra yang masih eksternal adalah:

1. extract artifact `main` pada clean Windows 11 fisik;
2. jalankan sebagai user non-admin;
3. verifikasi GUI, import sederhana, dan satu download yang memang pengguna berhak unduh;
4. pindahkan folder portable lalu buka ulang;
5. verifikasi queue/config/history pengguna tetap terbaca.

Implementasi kode dan release pipeline Tahap 6 selesai; acceptance fisik Windows 11 tetap dicatat secara eksplisit sebagai langkah manual di luar CI.
