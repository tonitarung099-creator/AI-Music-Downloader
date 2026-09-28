# Tahap 3 — Akurasi Lagu dan Kualitas Output

Implementasi Sol untuk `MASTER_PLAN_ASTRA_UNTUK_SOL_AI_MUSIC_DOWNLOADER`.

## Ringkasan

Tahap ini menangani F03, F11, F12, dan F13. Sasaran utamanya adalah mencegah aplikasi memilih lagu yang salah ketika bukti lemah, mencegah status **Selesai** palsu, dan memperjelas kontrak kualitas audio.

## Matching dan keputusan kandidat

Matcher sekarang mempertahankan huruf Unicode, memisahkan bukti judul/artis, membandingkan durasi, serta memperlakukan kata versi seperti `live`, `remix`, `cover`, `karaoke`, `instrumental`, `slowed`, `sped up`, dan variasi lain sebagai frasa/token, bukan substring mentah.

Keputusan matching memiliki tiga state:

- `MATCHED`: bukti kandidat dan margin cukup untuk dipilih otomatis.
- `NEEDS_REVIEW`: kandidat masuk akal tetapi terlalu ambigu untuk auto-download.
- `NO_MATCH`: bukti terlalu lemah dan download tidak dijalankan.

Gemini hanya boleh membantu memecahkan `NEEDS_REVIEW`. Pilihan Gemini tetap harus melewati hard floor skor lokal dan confidence minimum sehingga model tidak dapat memaksa kandidat yang bukti lokalnya sangat buruk.

## Review kandidat

Item ambigu disimpan sebagai **Perlu Ditinjau** dan tidak memblokir lagu berikutnya. Kandidat review berisi judul, channel, durasi, skor, versi, dan URL. Pengguna dapat membuka sumber lalu memilih kandidat yang benar. Pilihan tersebut disimpan sebagai `resolved_url`/`resolved_title` dan dipersistenkan ke SQLite sehingga restart tidak mengulang ambiguity yang sama.

State `NEEDS_REVIEW` dan daftar kandidat juga bertahan setelah restart.

## Verifikasi output

`DownloadEngine.download()` sekarang mengembalikan `DownloadResult` terstruktur. Status **Selesai** hanya diberikan bila:

1. yt-dlp mengembalikan identitas media,
2. file final benar-benar ada dan ukurannya lebih dari nol,
3. FFprobe dapat membaca file,
4. sedikitnya satu audio stream ditemukan,
5. durasi tidak invalid.

`QueueWorker` menolak hasil lama berbentuk dict atau `DownloadResult` yang belum terverifikasi. Kegagalan verifikasi memakai taxonomy `VERIFICATION` dan tidak dianggap sukses.

Item yang sudah selesai dapat dibuka dari tabel antrean dengan double-click selama file final masih valid.

## Kontrak format audio

- **Original / Best Audio**: `bestaudio`; tidak melakukan lossy transcode tambahan.
- **Utamakan M4A**: memilih M4A jika tersedia, lalu fallback ke best audio asli. Fallback dapat menghasilkan container selain M4A dan UI menyatakan hal itu secara eksplisit.
- **MP3**: konversi eksplisit dengan FFmpeg untuk kompatibilitas. Ini satu-satunya mode yang melakukan lossy transcode terencana.

FFmpeg dan FFprobe portable tetap digunakan dari folder `tools/` pada paket Windows.

## Metadata

Metadata Spotify yang tersedia dipertahankan: title, artist, album, track number, year, source URL, dan track ID. Setelah file audio lolos verifikasi, Mutagen mencoba menulis title/artist/album/track/year secara best-effort. Kegagalan tagging hanya menghasilkan warning dan tidak menghapus file audio yang sudah valid.

Cover art belum menjadi syarat karena dalam master plan bersifat opsional.

## Fixture dan regression gate

Dataset `tests/fixtures/stage3_match_cases.json` berisi **32 kasus beranotasi**, mencakup:

- judul sama dengan artis berbeda,
- versi live/remix diminta dan tidak diminta,
- karaoke/cover/instrumental/slowed/sped-up/nightcore/8D/acoustic,
- kedekatan durasi,
- channel Topic dan channel yang menyesatkan,
- aksen Latin,
- Unicode Jepang, Korea, Arab, Cyrillic, Thai, dan Tionghoa,
- kandidat ambigu,
- kandidat yang memang harus `NO_MATCH`.

Pada CI PR #4 gate awal menghasilkan **54 passed, 1 expected XFAIL**. Fixture Stage 3 lulus dengan **0 false-positive auto-match pada 32 kasus anotasi**. Angka ini hanya berlaku untuk fixture terkontrol tersebut dan **bukan klaim akurasi 100% terhadap seluruh internet**.

Satu expected XFAIL tersisa adalah F10 (`CommandPlan` Gemini), yang memang dialokasikan untuk Tahap 4.
