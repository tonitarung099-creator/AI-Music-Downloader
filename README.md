# AI Music Downloader

Aplikasi desktop Windows berbahasa Indonesia untuk mengelola antrean unduh audio dari sumber yang didukung `yt-dlp`, dengan pencarian lagu, pencocokan kandidat, metadata Spotify melalui `spotDL`, dan Gemini opsional untuk memahami perintah manusia atau membantu kandidat yang ambigu.

> Gunakan hanya untuk audio yang memang Anda berhak atau diizinkan untuk unduh. Aplikasi ini tidak membongkar DRM Spotify. Untuk input Spotify, metadata lagu dibaca lalu audio dicari dari sumber yang didukung downloader.

## Status

Implementasi master plan Astra Tahap 0–6 dan hardening acceptance Windows Tahap 7 sudah masuk `main`.

Status rilis saat ini:

- CI regression: **87 test lulus**;
- build portable Windows: lulus pada GitHub-hosted Windows Server 2025;
- acceptance harness dari ZIP hasil build: lulus di CI mode;
- paket memakai format **portable folder multi-file ZIP**, bukan installer dan bukan single-file EXE;
- Python, FFmpeg, ffprobe, dan Deno tidak perlu dipasang terpisah pada paket portable;
- paket membawa `UJI_WINDOWS_11.bat` untuk menjalankan acceptance otomatis pada laptop Windows 11 fisik sebagai user non-admin;
- tiga langkah manual terakhir tetap diperlukan sebelum menyebut mesin pengguna tertentu tervalidasi penuh: buka GUI, lakukan satu download yang memang berhak diunduh, lalu tutup/buka ulang dan cek state pengguna.

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
├─ UJI_WINDOWS_11.bat
├─ ACCEPTANCE_WINDOWS_11.ps1
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

## Uji Windows 11 fisik

Untuk menguji paket pada laptop Windows 11 nyata:

1. Extract seluruh ZIP.
2. Double-click **`UJI_WINDOWS_11.bat`** sebagai user biasa. **Jangan** pilih *Run as administrator*.
3. Tes otomatis memeriksa:
   - Windows 11 fisik;
   - proses tidak elevated/admin;
   - hash FFmpeg, ffprobe, dan Deno terhadap manifest;
   - folder `data/` dapat ditulis;
   - frozen `--self-test` tetap bekerja tanpa tool global di PATH;
   - seluruh paket dapat disalin dan dipindahkan ke path Unicode + spasi;
   - data sentinel tetap ada setelah relocation;
   - EXE tetap lulus self-test setelah relocation.
4. Laporan otomatis tersimpan di `data/acceptance-windows11.json`.
5. Setelah tes otomatis lulus, lakukan tiga langkah manual yang ditampilkan script: buka GUI, selesaikan satu download yang memang Anda berhak unduh, lalu tutup/buka ulang untuk memastikan antrean/riwayat/pengaturan tetap terbaca.

Workflow CI menjalankan harness yang sama dari ZIP hasil ekstraksi memakai `-CiMode`, tetapi **tidak** mengklaim Windows Server CI sebagai Windows 11 fisik.

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

Build script mengunduh versi FFmpeg dan Deno yang sudah dipin, memverifikasi SHA-256, membuat frozen EXE, menjalankan self-test runtime/audio lokal, membuat ZIP + checksum, menguji paket setelah extract/relocate pada path Unicode dan spasi, lalu workflow Windows mengeksekusi acceptance harness dari ZIP yang benar-benar akan didistribusikan.

## Struktur kode utama

```text
AI-Music-Downloader/
├─ main.py
├─ ACCEPTANCE_WINDOWS_11.ps1
├─ UJI_WINDOWS_11.bat
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

CI dan Windows portable gate menguji jalur deterministik, UI smoke, SQLite, matching, Gemini fixtures, DPAPI Windows, frozen runtime, FFmpeg/ffprobe/Deno, audio fixture lokal, checksum, relocation portable, dan acceptance harness dari ZIP hasil build.

Artifact acceptance-ready dari commit kode `6604662ce1f54dc32e6a6efa9cb957f675ab0b3d` memiliki ZIP SHA-256:

`4bb27ade79bc1e51322d462ba3d7e69e00d8bfc7e668b74788be5e993b02a00b`

Hal yang belum diklaim otomatis adalah tiga langkah manual end-to-end pada laptop fisik Windows 11 non-admin dengan jaringan dan akun pengguna nyata. Checklist akhir tersedia di `docs/TAHAP_7_ACCEPTANCE_WINDOWS_SOL.md` dan `docs/FINAL_RELEASE_READINESS_SOL.md`.
