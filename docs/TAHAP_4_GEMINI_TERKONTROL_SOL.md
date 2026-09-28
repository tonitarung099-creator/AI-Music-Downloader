# Tahap 4 — Gemini yang Terkontrol

Implementasi Sol untuk `MASTER_PLAN_ASTRA_UNTUK_SOL_AI_MUSIC_DOWNLOADER`.

## Ringkasan

Tahap ini menangani F09, F10, dan bagian key/model dari F20. Sasaran utamanya adalah memastikan Gemini hanya bertindak sebagai penerjemah intent dan pembantu matching, bukan sebagai jalur eksekusi bebas yang dapat mengubah antrean dengan data yang belum tervalidasi.

Tahap ini juga membatasi kegagalan API agar pool sampai 100 key tidak berubah menjadi 100 request beruntun saat layanan sedang rate-limit atau konfigurasi salah.

## CommandPlan bertipe dan allowlist

Hasil parser bahasa manusia sekarang harus menjadi `CommandPlan` tervalidasi. Action yang diizinkan hanya:

- `add_only`: tambah lagu ke antrean tanpa langsung download,
- `add_and_download`: tambah lagu lalu download batch hasil import,
- `download_queue`: jalankan item antrean yang siap,
- `retry_failed`: coba lagi item gagal/dibatalkan,
- `unknown`: no-op; tidak boleh mengubah antrean.

`scope` wajib konsisten dengan `intent`. `queries`, `quality`, `avoid`, `prefer`, `target_job_ids`, dan `note` divalidasi tipe, ukuran, nilai allowlist, dan kombinasinya sebelum UI boleh memakai hasil model.

Schema tidak valid menghasilkan error/no-op. Field tambahan yang tidak dikenal ditolak. Bentuk berbahaya seperti `quality=["mp3"]` tidak dapat lagi mencapai UI sebagai struktur mentah.

Permintaan chart/top/peringkat **terbaru** tanpa URL playlist atau daftar aktual tidak diizinkan memakai daftar lagu yang dihasilkan dari ingatan model. Jika model tetap mengarang `queries`, aplikasi mengubah hasil menjadi `unknown` dan meminta sumber aktual.

## CandidateChoice yang ketat

Pemilihan kandidat Gemini sekarang memakai `CandidateChoice` bertipe:

- `index` harus integer asli, bukan boolean, dan harus berada dalam rentang kandidat,
- `confidence` harus angka finite antara 0 dan 1,
- field tambahan ditolak,
- confidence di bawah batas minimum tetap menghasilkan review manual,
- kandidat juga tetap harus melewati hard floor skor matcher lokal dari Tahap 3.

Judul/channel kandidat diperlakukan sebagai data tidak tepercaya di prompt, sehingga teks pada metadata kandidat tidak diperlakukan sebagai instruksi untuk model.

## Preferensi versi tersambung ke matcher

`avoid` dan `prefer` sekarang tidak berhenti sebagai teks prompt. Nilai tervalidasi disimpan pada metadata job dan ikut memengaruhi scoring lokal.

Contoh:

- `avoid=["live", "remix"]` memberi penalti kuat pada kandidat yang memiliki versi tersebut,
- `prefer=["acoustic"]` mengizinkan dan memberi bonus pada kandidat acoustic bila identitas judul/artis tetap cocok.

Jika preferensi diterapkan ke job lama yang belum selesai, kandidat hasil resolve lama dibersihkan agar job melakukan matching ulang dengan aturan baru. Preferensi job dipersistenkan ke SQLite.

## Scope perintah

Perintah Gemini dapat bekerja pada seluruh antrean sesuai action atau pada `target_job_ids` yang tervalidasi. Gemini tidak diberi izin untuk menjalankan shell, membuka file secara arbitrer, atau menciptakan action di luar allowlist.

Untuk hasil import baru, preferensi versi ditempel ke track berdasarkan `import_id` sehingga perintah `add_only`/`add_and_download` tetap mempertahankan aturan avoid/prefer setelah worker import selesai.

## Key pool, retry, cooldown, dan budget

Pool key didedup dan dibatasi maksimal 100 key, tetapi satu operasi AI sengaja dibatasi lebih ketat:

- maksimum **2 request in-flight** total,
- timeout satu request **15 detik**,
- budget satu operasi AI **45 detik**,
- maksimum **3 percobaan transient** per operasi.

Kebijakan error:

- HTTP 400/402/404: berhenti untuk operasi itu; tidak merotasi banyak key untuk request/model yang salah,
- HTTP 401/403: key ditandai ditolak/disabled sampai daftar key diperbarui,
- HTTP 429: key masuk cooldown; `Retry-After` numerik dihormati, default 60 detik bila tidak tersedia,
- HTTP 5xx/network: cooldown singkat dan retry dibatasi budget/attempt,
- cancel dari UI diperiksa sebelum dan di antara request,
- error yang ditampilkan melalui jalur Gemini meredaksi key yang dikenal dan pola API key Gemini.

Karena rate limit Gemini dapat berlaku pada level project, rotasi key tidak dianggap sebagai mekanisme untuk mengabaikan quota. Batas percobaan mencegah aplikasi menyapu seluruh pool ketika kondisi dasarnya sama.

## Cache

Parsing command dan pilihan kandidat memiliki cache singkat berbasis hash dari input yang relevan, termasuk model, query, preferensi, dan kandidat. Cache mengurangi request identik yang berulang.

Guard chart terbaru ditempatkan setelah parsing tervalidasi sehingga cache tidak dipakai untuk menjadikan ingatan model sebagai sumber ranking aktual.

## Model discovery dan tes koneksi

UI production v3 sekarang mempunyai:

- picker model Gemini,
- tombol **Muat Model**,
- tombol **Tes Gemini**.

Daftar model diambil melalui endpoint model Gemini dan hanya model yang menyatakan dukungan `generateContent` yang ditawarkan sebagai hasil discovery. Discovery dan tes koneksi dijalankan pada worker Qt terpisah agar UI tidak membeku.

Model tidak otomatis dipindahkan ke model lain. Pemilihan tetap eksplisit oleh pengguna/aplikasi sesuai konfigurasi yang tervalidasi.

## Pengelolaan key di UI

Key tersimpan tidak lagi langsung ditampilkan plaintext ketika dialog dibuka. Editor berada dalam mode masked/read-only sampai pengguna mencentang **Tampilkan key tersimpan** secara eksplisit.

Tahap ini belum mengubah penyimpanan `config.json` menjadi Windows credential/encrypted storage. Itu termasuk sisa F20 yang dialokasikan untuk tahap UI/diagnostik berikutnya. Karena itu masking UI mencegah paparan tidak sengaja di layar, tetapi bukan pengganti enkripsi at-rest.

## Regression gate

CI PR #5 setelah implementasi utama menghasilkan **69 passed, 0 xfail**. Setelah regression tambahan untuk 429/`Retry-After` dan 401/key-disabled, CI menghasilkan **71 passed, 0 xfail**.

Gate yang terbukti lewat test:

- F10 tidak lagi `xfail`, schema salah menjadi no-op/error,
- 100 key gagal tidak menghasilkan 100 request beruntun; satu operasi dibatasi 3 attempt,
- tanpa key, jalur Gemini tidak mencoba network dan downloader tetap dapat digunakan tanpa AI,
- confidence Gemini rendah tidak melewati review manual,
- 429 memasukkan key ke cooldown,
- 401 menonaktifkan key sampai pool diperbarui,
- error fixture tidak membocorkan key,
- cache mencegah request parsing identik berulang,
- discovery model hanya menerima model `generateContent`,
- avoid/prefer benar-benar memengaruhi matcher,
- compile Python dan smoke UI v3 lulus.

## Batas verifikasi tahap ini

CI menggunakan fixture/mock untuk perilaku Gemini dan tidak memiliki API key pribadi pengguna, sehingga tidak melakukan panggilan live ke akun Gemini pengguna. Endpoint dan bentuk request diimplementasikan mengikuti Gemini REST API, sedangkan validasi koneksi nyata tersedia melalui tombol **Tes Gemini** pada aplikasi.

Windows manual end-to-end dengan akun/key pengguna belum dijadikan klaim pada laporan ini; build Windows portable tetap harus lulus sesudah merge sebelum Tahap 4 ditutup sepenuhnya.
