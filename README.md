# AI Music Downloader

Aplikasi desktop Windows berbahasa Indonesia untuk mengelola antrean unduh audio dari sumber yang didukung `yt-dlp`, dengan pencarian lagu, pencocokan kandidat, metadata Spotify melalui `spotDL`, dan Gemini opsional untuk memahami perintah manusia atau membantu kandidat yang ambigu.

> Gunakan hanya untuk audio yang memang Anda berhak atau diizinkan untuk unduh. Aplikasi ini tidak membongkar DRM Spotify. Untuk input Spotify, metadata lagu dibaca lalu audio dicari dari sumber yang didukung downloader.

## Status

Implementasi master plan Astra Tahap 0–6 sudah masuk `main`.

Status rilis saat ini:

- CI regression: 83 test lulus;
- build portable Windows: lulus pada GitHub-hosted Windows Server 2025;
- paket memakai format **portable folder multi-file ZIP**, bukan installer dan bukan single-file EXE;
- Python, FFmpeg, ffprobe, dan Deno tidak perlu dipasang terpisah pada paket portable;
- acceptance manual pada laptop fisik clean Windows 11 non-admin masih perlu dilakukan sebelum menyebut kompatibilitas mesin nyata selesai sepenuhnya.

Bukti implementasi tiap tahap tersedia di folder [`docs/`](docs/).

## Fitur utama

- Input judul lagu, URL YouTube/YouTube Music, playlist YouTube, atau URL Spotify.
- Antrean persisten berbasis SQLite dengan `job_id` stabil, history, restore setelah restart/interupsi, dedup, retry terarah, dan output manifest.
- Matching lokal dengan keputusan `MATCHED`, `NEEDS_REVIEW`, dan `NO_MATCH` agar kandidat lemah tidak diunduh diam-diam.
- Dukungan review kandidat tanpa memblokir item antrean lain.
- Verifikasi file hasil dengan ffprobe sebelum status **Selesai** diberikan.
- Mode audio:
  - **Original / Best Audio** — tidak melakukan lossy transcode tambahan;
  - **Utamakan M4A** — memprioritaskan source M4A dan dapat fallback ke format audio lain;
  - **MP3** — konversi eksplisit dengan FFmpeg portable.
- Gemini opsional dengan CommandPlan tervalidasi, budget/cooldown/retry terbatas, dukungan sampai 100 key, model picker, tes koneksi, dan preferensi versi seperti `avoid live/remix`.
- UI tiga area yang dapat dipakai pada target 1366×768 dan diuji pada DPI 100%, 125%, dan 150%.
- Pencarian/filter antrean, detail lagu, riwayat, retry terpilih, ekspor CSV/JSON, dan diagnostic bundle teredaksi.
- API key Gemini tidak disimpan plaintext di `config.json`.

## Menjalankan paket portable Windows

1. Ambil artifact **AI-Music-Downloader-Portable** dari workflow **Build Windows Portable** pada commit `main` yang berhasil.
2. Extract seluruh ZIP ke satu folder.
3. Jalankan `AI Music Downloader.exe`.
4. Jangan memindahkan EXE sendirian. Folder `_internal`, `tools`, `data`, dan file pendamping harus tetap bersama folder portable.

Paket portable berisi antara lain:

```text
AI-Music-Downloader-Portable/
├─ AI Music Downloader.exe
├─ _internal/
├─ tools/
│  ├─ ffmpeg.exe
│  ├─ ffprobe.exe
│  └─ deno.exe
├─ data/
├─ downloads/
├─ release-info/
├─ VERSION_MANIFEST.json
├─ THIRD_PARTY_NOTICES.txt
├─ README_PORTABLE.txt
└─ config.example.json
```

`VERSION_MANIFEST.json` mencatat Git SHA, versi dependency, dan hash tool yang dibundel. Build juga menghasilkan sidecar `.sha256` untuk memverifikasi ZIP rilis.

## Gemini dan API key

Gemini **tidak wajib**. Tanpa API key, jalur manual/downloader lokal tetap dapat digunakan.

Mode penyimpanan key:

1. **Windows DPAPI** — key dienkripsi dengan profil akun Windows saat ini dan disimpan di `data/gemini_keys.dpapi`.
2. **Hanya sesi** — key hanya aktif selama aplikasi berjalan dan tidak dipersistenkan.

`config.json` tidak menyimpan API key plaintext. Jika folder portable dipindah ke komputer atau akun Windows lain, blob DPAPI lama mungkin tidak dapat didekripsi dan pengguna perlu memasukkan ulang key.

Banyak key tidak berarti kuota menjadi tanpa batas. Scheduler tetap menghormati error/cooldown dan membatasi percobaan agar tidak menyapu seluruh pool saat masalah dasarnya sama.

## Kualitas audio

- **Original / Best Audio**: mengambil stream audio terbaik yang dipilih yt-dlp tanpa transcoding lossy tambahan.
- **Utamakan M4A**: memprioritaskan source M4A bila tersedia; fallback dapat menghasilkan container lain.
- **MP3**: melakukan transcoding eksplisit menggunakan FFmpeg portable.

Mengubah sumber lossy menjadi MP3 bitrate tinggi tidak menambah detail audio yang tidak ada pada sumber.

## Menjalankan versi pengembangan

Lingkungan build/release yang diuji memakai Python 3.11.9 dan dependency yang dipin di repository.

```bash
python -m pip install -r requirements.txt -c constraints.lock.txt
python main.py
```

Pada Windows juga tersedia `run_dev.bat`.

Untuk build portable gunakan PowerShell:

```powershell
./build_portable.ps1
```

Build script mengunduh versi FFmpeg dan Deno yang sudah dipin, memverifikasi SHA-256, membuat frozen EXE, menjalankan self-test runtime/audio lokal, membuat ZIP + checksum, lalu menguji paket setelah extract/relocate pada path Unicode dan spasi.

## Struktur kode utama

```text
AI-Music-Downloader/
├─ main.py
├─ app/
│  ├─ config.py
│  ├─ models.py
│  ├─ storage.py
│  ├─ controllers/
│  ├─ services/
│  └─ ui/
│     └─ production_window.py
├─ tests/
├─ docs/
├─ release-tools.json
├─ constraints.lock.txt
├─ requirements.txt
├─ requirements-build.txt
├─ requirements-test.txt
└─ build_portable.ps1
```

## Verifikasi dan batas klaim

CI dan Windows portable gate menguji jalur deterministik, UI smoke, SQLite, matching, Gemini fixtures, DPAPI Windows, frozen runtime, FFmpeg/ffprobe/Deno, audio fixture lokal, checksum, dan relocation portable.

Hal yang belum diklaim otomatis adalah acceptance end-to-end pada laptop fisik clean Windows 11 non-admin dengan jaringan dan akun pengguna nyata. Checklist acceptance akhir tersedia di `docs/FINAL_RELEASE_READINESS_SOL.md`.
