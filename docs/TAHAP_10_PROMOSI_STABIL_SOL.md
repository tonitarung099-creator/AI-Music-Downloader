# TAHAP 10 — Gate Promosi v1.0.0 Stabil

Tanggal: 29 September 2026

## Tujuan

Tahap ini tidak mempromosikan `v1.0.0-rc1` menjadi `v1.0.0` secara otomatis. Promosi stabil tetap memerlukan bukti acceptance Windows 11 fisik dari paket RC1 canonical.

Tahap 10 menambahkan validator deterministik supaya file `acceptance-windows11.json` tidak cukup hanya memiliki `release_ready=true`. Identitas paket yang diuji juga harus cocok dengan RC1 canonical yang sudah dibangun dari `main`.

## RC1 canonical yang dikunci

Identitas disimpan di `release-candidate-lock.json`:

- app: `AI Music Downloader`
- versi: `1.0.0-rc1`
- target stabil: `1.0.0`
- Git SHA RC1: `1a802ec0f7ffd5ade869916e6b0349a6cb8a8d1a`
- SHA-256 ZIP portable final: `6389c233e5b6ed84549867114e42317cf67c50abe25eeca2b3261ab7039b0657`
- SHA-256 `VERSION_MANIFEST.json`: `287584dfaf19504954f0b26ec52be12cfac39aaf0612123447cb54ad38d23639`
- SHA-256 `AI Music Downloader.exe`: `5955c9c74cd058ed7f9ca83686fbd4d8cebb8a2efa44bf948470ce64c4da0a11`
- GitHub Actions run: `36525989928`
- artifact ID: `11014649431`

## Yang divalidasi

`scripts/validate_release_promotion.py` menolak promosi jika salah satu syarat berikut tidak terpenuhi:

1. schema acceptance harus versi 2;
2. `app` dan `app_version` harus cocok dengan RC1 canonical;
3. `manifest_git_sha` harus tepat commit RC1 yang dikunci;
4. `manifest_sha256` dan `executable_sha256` harus cocok dengan paket canonical;
5. report wajib berasal dari mode fisik (`ci_mode=false`);
6. automated acceptance harus lulus;
7. acceptance harus dijalankan sebagai user non-admin;
8. host harus Windows 11 non-Server dengan build Windows 11;
9. tiga manual check harus ada dan `passed=true`:
   - `gui_normal`
   - `real_download`
   - `restart_persistence`
10. timestamp manual check harus berada di dalam jendela waktu acceptance;
11. seluruh automated check penting yang dikunci harus ada dan lulus;
12. `release_ready` harus `true`.

## Cara validasi

Setelah `UJI_WINDOWS_11.bat` selesai dan menghasilkan:

`data\acceptance-windows11.json`

jalankan dari source repo:

```text
python scripts/validate_release_promotion.py acceptance-windows11.json
```

Atau buat evidence yang sudah disanitasi:

```text
python scripts/validate_release_promotion.py acceptance-windows11.json --evidence-out stable-promotion-evidence.json
```

Jika valid, output wajib memuat:

```text
STABLE_PROMOTION_GATE_OK
PROMOTION_ALLOWED=true
```

Jika tidak valid, exit code non-zero dan output dimulai dengan:

```text
STABLE_PROMOTION_GATE_REJECTED
```

## Privasi

Raw `acceptance-windows11.json` tidak perlu disimpan ke repository publik karena dapat memuat metadata host dan detail lingkungan lokal. Validator hanya menghasilkan evidence ringkas yang tidak menyalin blok `windows` atau daftar detail `checks`.

## Batas jaminan

Validator ini adalah gate konsistensi dan provenance paket, bukan tanda tangan kriptografis atas pernyataan manusia. Ia memastikan report mengacu pada RC1 canonical dan kontrak acceptance lengkap, tetapi tetap mengandalkan pengguna untuk menjawab tiga langkah manual dengan benar.

## Syarat promosi final

`app/version.py` tetap `1.0.0-rc1` sampai report fisik yang valid benar-benar diterima. Hanya setelah validator menghasilkan `PROMOTION_ALLOWED=true` versi boleh dinaikkan ke `1.0.0`, kemudian CI dan Windows Portable harus kembali hijau pada commit stabil tersebut.
