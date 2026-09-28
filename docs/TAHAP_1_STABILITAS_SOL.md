# Tahap 1 — Stabilitas proses, Spotify, config, dan impor (Sol)

Tanggal: 28 September 2026  
Repository: `tonitarung099-creator/AI-Music-Downloader`

## 1. Cakupan master plan

Tahap 1 mengerjakan fondasi F01, F02, F05, F06, F07, F08 dan F14 dasar tanpa melakukan rewrite framework atau perubahan UI kosmetik besar.

Tujuan tahap ini:

- Spotify metadata dapat dibootstrap saat benar-benar dibutuhkan tanpa membuat jalur manual/YouTube bergantung pada inisialisasi Spotify.
- Satu item impor gagal tidak membuang item valid lain dalam batch.
- URL diklasifikasikan dari hostname/path/query yang benar, bukan substring.
- Operasi import, queue dan Gemini memiliki identitas sehingga event lama dapat ditolak.
- Config rusak/tipe salah tidak menjatuhkan startup, output path konsisten terhadap app root, dan penyimpanan config atomik.
- Import, Gemini dan download memiliki cancellation/deadline dasar.
- Penutupan jendela tidak menghancurkan QThread aktif secara paksa.

## 2. Perubahan implementasi

### F01 — Spotify bootstrap + lazy import

`app/services/spotify.py` sekarang:

- mengimpor spotDL hanya ketika URL Spotify benar-benar digunakan;
- menggunakan `SpotifyClient` dan `DEFAULT_CONFIG` dari spotDL 4.5.2;
- memastikan client diinisialisasi sekali sebelum `Playlist.get_metadata`, `Album.get_metadata`, atau `Song.from_url`;
- memakai backend default spotDL, tidak menambahkan kredensial baru ke repository;
- memberi batas waktu best-effort pada operasi metadata;
- mengubah kegagalan backend menjadi pesan `SpotifyResolverError` yang terisolasi.

Input manual dan URL non-Spotify tidak memanggil resolver Spotify; ada regression test khusus untuk kontrak ini.

### F02/F07 — lifecycle dan event correlation

Ditambahkan `app/controllers/lifecycle.py` dengan `OperationCoordinator`.

Identitas minimum:

- setiap `TrackRequest` memiliki `job_id` stabil;
- import memiliki `import_id` dan `batch_id`;
- command Gemini memiliki `command_id`;
- queue memiliki `batch_id` aktif.

Progress queue sekarang mengirim `job_id`, bukan bergantung pada nomor row. Hasil import/Gemini yang berasal dari operasi lama tidak diterapkan ke antrean baru.

Aksi yang konflik dibatasi: import baru tidak dimulai ketika queue aktif, queue tidak dimulai ketika import aktif, retry tidak memutasi queue aktif, dan Gemini yang dapat mengubah antrean tidak dijalankan bersamaan dengan import/queue.

### F02/F14 dasar — shutdown dan cancellation

`main_window_v3.py` sekarang menggunakan close terkoordinasi:

1. close event ditunda jika worker masih aktif;
2. import diminta cancel;
3. queue diminta stop;
4. Gemini diminta cancel;
5. Qt melakukan polling non-blocking sampai seluruh worker benar-benar berhenti;
6. jendela baru ditutup setelah worker selesai.

Tidak menggunakan `QThread.terminate()` dan tidak menerima close hanya karena timeout `wait(2500)` habis.

Gemini request timeout dasar diturunkan menjadi 15 detik dan cancellation dicek antar-request. yt-dlp search/import/download mendapatkan `socket_timeout` dasar. Scheduler key/cooldown global tetap pekerjaan Tahap 4.

### F05 — partial import

`ImportWorker` sekarang memproses per baris dan menghasilkan `ImportResult` berisi track valid, daftar `ImportIssue`, status cancelled, `import_id`, dan `batch_id`.

Jika satu URL Spotify/YouTube gagal, item valid sebelum/sesudahnya tetap dipertahankan. Entri playlist `None` atau tanpa URL dilewati dengan error spesifik, bukan menggagalkan seluruh batch.

### F06 — source routing

Routing sekarang menggunakan `urlparse` dan validasi hostname/path/query.

Contoh yang diuji:

- `open.spotify.com/track/...` diterima sebagai Spotify;
- `open.spotify.com.evil.example/...` ditolak;
- URL domain lain yang hanya memiliki Spotify/YouTube di query tidak salah routing;
- `youtube.com/playlist?list=...`, `music.youtube.com/watch?...&list=...`, dan `youtu.be/...?...list=...` dikenali sebagai playlist;
- video YouTube tanpa parameter `list` tidak dianggap playlist.

### F08 — config dan portable path

`AppConfig` sekarang:

- memvalidasi root JSON harus object;
- memvalidasi `audio_mode`, `gemini_model`, `max_retries`, API key list, dan output path;
- menangani `null`, list, JSON rusak, dan tipe field salah dengan default aman;
- memakai resolver output path tunggal terhadap app root;
- membuat snapshot config terpisah untuk batch yang sedang berjalan;
- menyimpan config melalui temp file + `fsync` + `os.replace`;
- menyimpan backup config lama sebagai `config.json.bak`;
- menghapus temp file jika penulisan gagal dan mengangkat `ConfigSaveError` yang dapat ditampilkan UI.

## 3. Pengujian

Regression Tahap 0 yang sekarang sudah menjadi PASS:

- F01 Spotify bootstrap;
- F05 partial import;
- F08 config `null` fallback.

Tes Tahap 1 menutup:

- routing hostname/path/query;
- manual import tidak menyentuh Spotify;
- playlist entry invalid tidak membuang valid entry;
- import cancellation;
- config file dengan tipe salah;
- config yang dimutasi ke tipe salah saat runtime;
- atomic save + backup;
- snapshot API key terpisah;
- stale operation IDs;
- queue event memakai stable `job_id`.

CI run awal PR #2 (`36377998497`) lulus dengan:

- compileall: PASS;
- production UI v3 smoke: `UI_V3_SMOKE_OK`;
- pytest: `24 passed, 4 xfailed`.

Empat expected failure yang sengaja tetap ada bukan target Tahap 1:

- F03 kandidat lokal buruk masih dapat diterima;
- F03 Gemini confidence 0 masih dapat diterima;
- F10 CommandPlan belum typed/validated penuh;
- F12 hasil download kosong masih dapat menjadi DONE.

Perbaikan tersebut diteruskan sesuai urutan master plan pada tahap akurasi/AI/output berikutnya.

## 4. Batas verifikasi

Tes deterministik dan smoke Qt berjalan di CI Linux. Tahap ini belum mengklaim telah menguji live Spotify, live YouTube, API Gemini nyata, atau close saat postprocessor FFmpeg nyata pada Windows bersih. Batas waktu Spotify menggunakan adapter best-effort karena API metadata spotDL 4.5.2 tidak mengekspos cancellation token sendiri.

Windows frozen/package smoke tetap dipertahankan sebagai verifikasi rilis dan akan diperkuat pada Tahap 6.

## 5. Gate Tahap 1

Tahap 1 siap digabung bila CI pada head final tetap hijau dan regression test yang dipromosikan dari xfail menjadi PASS tidak regress. Kriteria utama yang telah ditutup secara deterministik adalah partial import, routing ketat, config recovery, stable IDs/event correlation, cancellation dasar, dan jalur manual tanpa bootstrap Spotify.
