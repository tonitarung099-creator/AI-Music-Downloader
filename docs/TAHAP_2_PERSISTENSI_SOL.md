# Tahap 2 — Antrean tahan restart, history, retry, dan dedup (Sol)

Tanggal: 28 September 2026  
Repository: `tonitarung099-creator/AI-Music-Downloader`

## 1. Cakupan master plan

Tahap 2 mengerjakan F04, F15, F16 dan memperkuat F07.

Gate master plan:

- batch besar tidak hilang setelah aplikasi terinterupsi/restart;
- retry hanya menjalankan job yang memang ditargetkan;
- file/item yang sudah selesai tidak diunduh ulang tanpa alasan;
- identitas job/media tidak berubah hanya karena urutan antrean berubah.

## 2. SQLite sebagai source of truth antrean

Ditambahkan `app/storage.py` dengan `QueueRepository` berbasis SQLite standar Python.

Lokasi runtime default:

`data/queue.sqlite3`

Database memakai:

- schema version melalui `PRAGMA user_version`;
- WAL journal mode;
- foreign keys + busy timeout;
- transaksi SQLite untuk perubahan antrean;
- tabel `jobs`, `job_history`, dan `manifest`;
- indeks untuk posisi aktif, dedup key, dan status.

`jobs` menyimpan antara lain:

- `job_id` stabil;
- posisi tampilan;
- `batch_id`;
- query/source/direct URL;
- title/artist/duration;
- status/progress/error;
- taxonomy error + flag retryable;
- kandidat hasil resolusi (`resolved_url`, `resolved_title`);
- `output_path`;
- `dedup_key`;
- jumlah attempt;
- metadata JSON;
- timestamps dan soft-delete.

`job_history` mencatat event penting seperti added, attempt started/failed, retry scheduled, completed, cancelled, remove, reorder, dan restore interrupted.

`manifest` mempertahankan identitas media yang pernah selesai walaupun row antrean kemudian dihapus. Ini mencegah import ulang media yang sama diam-diam membuat download baru.

## 3. Restore setelah restart/interupsi

Saat UI produksi dibuka, `QueueRepository.restore_queue()` memulihkan row aktif berdasarkan posisi.

Status runtime yang tidak mungkin dipercaya setelah proses lama mati:

- Searching;
- Downloading;
- Paused;
- Retry Wait;

diubah menjadi `Terinterupsi`, bukan `Selesai` dan bukan langsung dianggap gagal permanen.

Kandidat yang sudah dipilih sebelumnya tetap dipertahankan melalui `resolved_url`/`resolved_title`. Downloader memakai kembali kandidat tersebut ketika job dilanjutkan sehingga retry/restart tidak melakukan pencarian baru tanpa alasan.

Item `Selesai` tetap `Selesai` dan QueueWorker melewatinya.

## 4. Stable identity dan dedup

Ditambahkan `app/services/identity.py`.

Identitas media menggunakan data paling kuat yang tersedia:

- Spotify track/album/playlist ID dari URL canonical;
- YouTube video ID/playlist ID;
- URL HTTP lain yang dinormalisasi secara konservatif;
- fallback query fingerprint Unicode NFKC + casefold.

Fingerprint query sengaja tidak menghapus kata versi seperti `live` atau `remix`, sehingga `Artist - Song` tidak otomatis dianggap sama dengan `Artist - Song Live`.

Untuk Spotify, adapter sekarang mempertahankan `song_id` dan `url` yang diberikan spotDL sehingga dedup track tidak bergantung pada teks judul saja.

Parameter tracking umum seperti `si`, `feature`, dan `utm_*` tidak membuat media YouTube yang sama terlihat sebagai media baru.

Kebijakan duplikat Tahap 2:

- duplicate aktif tidak ditambahkan lagi;
- duplicate yang sudah ada di completed manifest tidak ditambahkan lagi;
- UI memberi log jumlah duplicate yang dilewati;
- versi berbeda yang berbeda pada query/source identity tetap dapat menjadi job berbeda.

Tidak ada penghapusan file hasil lama secara otomatis.

## 5. Output collision dan reorder

Template output yt-dlp tidak lagi memiliki prefix nomor row seperti `001 -`.

Nama file sekarang memakai judul + media ID yt-dlp:

`%(title).160B [%(id)s].%(ext)s`

Dengan demikian memindahkan item dari posisi 10 ke posisi 2 tidak mengubah identitas filename media tersebut.

`overwrites=False` tetap dipertahankan. Completed manifest menjadi lapisan dedup lintas session.

## 6. Retry dan error taxonomy

Ditambahkan `app/services/errors.py`.

Kategori utama:

- CANCELLED;
- INVALID_INPUT;
- NOT_FOUND;
- AUTH;
- RATE_LIMITED;
- NETWORK;
- SERVER;
- PERMANENT;
- UNKNOWN.

Auto-retry dibuat konservatif. Hanya kegagalan transient yang dikenal seperti timeout/network, 429 dan 5xx yang otomatis diulang. Unknown/permanent tidak disapu retry berulang.

Backoff memakai exponential delay + deterministic jitter dan dapat dibatalkan melalui stop token.

Retry internal yt-dlp diturunkan menjadi satu kepemilikan yang jelas: QueueWorker memegang retry budget aplikasi. Ini mencegah kombinasi `QueueWorker retry × yt-dlp retry` menghasilkan retry storm.

## 7. Scope operasi berdasarkan ID

QueueWorker menerima snapshot track yang akan dijalankan dan menyimpan `target_job_ids`.

`Retry Gagal` sekarang:

1. mengambil hanya status FAILED/CANCELLED;
2. membentuk target `job_id` eksplisit;
3. reset hanya target tersebut;
4. mencatat `retry_requested`;
5. menjalankan hanya snapshot target tersebut.

Item QUEUED lain tidak ikut berjalan karena tombol Retry Gagal.

Repository juga menyediakan remove/reorder berdasarkan `job_id`, bukan nomor row. UI behavior layer menyimpan `job_id` pada row melalui `Qt.UserRole` dan memiliki API `remove_jobs(...)`/`reorder_jobs(...)` yang divalidasi terhadap job aktif.

Stop hanya membatalkan job yang sedang aktif; item berikutnya yang belum dimulai tetap QUEUED dan dapat dilanjutkan kemudian/restart.

## 8. Checkpoint

Checkpoint dilakukan pada perubahan penting, bukan pada setiap byte:

- sebelum attempt;
- saat progress melewati bucket sekitar 25%;
- setelah attempt gagal;
- saat retry dijadwalkan;
- completed/failed/cancelled;
- queue/batch mutation.

Ini memberi durability tanpa menulis SQLite untuk setiap callback progress yt-dlp.

## 9. Pengujian

CI pertama PR #3 lulus:

- compileall: PASS;
- production UI v3 smoke: `UI_V3_SMOKE_OK`;
- pytest: `36 passed, 4 xfailed`.

Regression Tahap 2 mencakup:

- 100 job bertahan melalui database baru/restart;
- status runtime lama menjadi Terinterupsi;
- YouTube URL dengan tracking berbeda dedup ke video ID sama;
- plain vs Live tetap berbeda;
- completed manifest mencegah re-download setelah row antrean dihapus;
- reorder tidak mengubah job identity;
- retry target tidak menjalankan queued job lain;
- invalid/permanent error gagal cepat tanpa auto-retry;
- timeout transient dapat retry dan berhasil;
- taxonomy unknown tetap konservatif;
- output template tidak bergantung pada nomor queue.

Audit kedua menambahkan gate tambahan untuk:

- kandidat terpilih (`resolved_url/title`) tetap ada setelah restart;
- restored DONE job tidak memanggil downloader lagi;
- stop current job tidak mengubah unstarted job menjadi cancelled.

Empat XFAIL lama tetap sengaja di luar Tahap 2:

- F03 kandidat matching buruk;
- F03 Gemini confidence 0;
- F10 typed/validated CommandPlan;
- F12 hasil download kosong dapat dianggap DONE.

F03/F12 akan ditangani pada Tahap 3. F10 mengikuti tahap AI sesuai master plan.

## 10. Batas verifikasi

Tes restart saat ini deterministik dengan membuat ulang instance repository terhadap file SQLite yang sama; belum melakukan kill proses Windows sungguhan di tengah transfer internet.

`output_path` Tahap 2 disimpan best-effort dari informasi yt-dlp. Verifikasi bahwa file benar-benar audio valid memakai ffprobe adalah target Tahap 3/F12.

SQLite memakai WAL dan transaksi, tetapi Tahap 2 tidak membuat cloud sync/backup eksternal database.

Duplicate policy default adalah skip + log. Override eksplisit untuk sengaja mengunduh copy kedua dari media identik belum diekspos sebagai tombol karena default aman master plan adalah tidak mengunduh ulang file selesai tanpa alasan.

## 11. Gate merge

Tahap 2 hanya boleh digabung jika CI final setelah regression audit kedua tetap hijau. Setelah merge, CI `main` dan Build Windows Portable harus kembali lulus agar perubahan SQLite/lifecycle terbukti tetap dapat dibekukan menjadi paket portable Windows.
