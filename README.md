# AI Music Downloader

Aplikasi desktop Windows untuk mengelola antrean download audio dari sumber yang didukung `yt-dlp`, dengan pencarian lagu, pencocokan kandidat, dukungan playlist Spotify melalui `spotDL`, dan Gemini opsional untuk memahami perintah manusia atau membantu pencocokan yang ambigu.

> Gunakan hanya untuk audio yang memang Anda berhak/diizinkan untuk unduh. Aplikasi ini tidak membongkar DRM Spotify. Untuk input Spotify, metadata lagu dibaca lalu audio dicari dari sumber yang didukung downloader.

## Target MVP

- UI desktop PySide6, Bahasa Indonesia.
- Input daftar judul lagu, URL YouTube/YouTube Music, playlist YouTube, atau URL Spotify.
- Antrean 100+ lagu dengan status, progress, pause, stop, retry alami per item.
- Mode **Original / Best Audio** sebagai default supaya tidak ada transcoding tambahan jika tidak diperlukan.
- Mode M4A dan MP3 untuk kompatibilitas.
- Matching lokal: judul, artis, durasi, penalti live/cover/karaoke/remix/sped-up/slowed jika tidak diminta.
- Gemini opsional sebagai fallback saat hasil pencarian ambigu dan untuk parsing perintah natural.
- Banyak Gemini API key dapat disimpan dan diputar otomatis saat sebuah key gagal/limit.
- Folder output dapat dipilih pengguna.

## Menjalankan versi pengembangan

1. Install Python 3.11+.
2. Install dependency:
   ```bash
   pip install -r requirements.txt
   ```
3. Pastikan FFmpeg tersedia di `tools/ffmpeg.exe` + `tools/ffprobe.exe` atau sudah ada di PATH.
4. Jalankan:
   ```bash
   python main.py
   ```

Atau di Windows klik `run_dev.bat`.

## Gemini

Gemini **tidak wajib**. Tanpa API key aplikasi tetap bisa mencari, mencocokkan, dan mengunduh dengan engine lokal.

API key dapat dimasukkan dari UI. Penyimpanan saat ini lokal di `config.json` dan file tersebut diabaikan Git.

## Kualitas audio

- **Original / Best Audio**: mengambil stream audio terbaik yang dipilih yt-dlp tanpa transcoding tambahan.
- **M4A source preferred**: memprioritaskan stream M4A jika tersedia; fallback ke best audio.
- **MP3 high quality**: membutuhkan FFmpeg dan melakukan transcoding ke MP3.

Mengubah sumber lossy menjadi MP3 bitrate tinggi tidak menambah detail audio yang tidak ada pada sumber.

## Struktur

```text
AI-Music-Downloader/
├─ main.py
├─ app/
│  ├─ config.py
│  ├─ models.py
│  ├─ services/
│  │  ├─ downloader.py
│  │  ├─ gemini_agent.py
│  │  ├─ matcher.py
│  │  └─ spotify.py
│  └─ ui/
│     └─ main_window.py
├─ tests/
├─ tools/                 # ffmpeg portable dapat diletakkan di sini
├─ config.example.json
├─ requirements.txt
└─ run_dev.bat
```

## Status

Fondasi MVP sedang dibangun. Target rilis akhir adalah **portable folder multi-file ZIP** untuk Windows, bukan single-file executable.
