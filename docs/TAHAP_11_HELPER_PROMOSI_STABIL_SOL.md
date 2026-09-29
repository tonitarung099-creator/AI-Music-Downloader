# Tahap 11 — Helper Promosi Stabil Fail-Closed

Tanggal: 29 September 2026

## Tujuan

Menghilangkan edit manual saat mempromosikan `1.0.0-rc1` menjadi `1.0.0` stabil.

Tahap ini **tidak** melakukan promosi stabil sekarang. `app/version.py` tetap `1.0.0-rc1` sampai acceptance Windows 11 fisik canonical benar-benar tersedia dan lolos Stage 10.

## Helper

File:

`scripts/prepare_stable_release.py`

Alur:

1. menerima `acceptance-windows11.json`;
2. menjalankan validator Stage 10 terhadap `release-candidate-lock.json`;
3. memastikan repository masih berada tepat di versi RC canonical yang dikunci;
4. memastikan target stable version berbentuk semantic version stabil seperti `1.0.0`;
5. default **dry-run** dan tidak menulis file apa pun;
6. hanya dengan `--apply` helper mengubah `APP_VERSION` dari `1.0.0-rc1` menjadi `1.0.0`;
7. bersamaan dengan itu helper membuat `stable-promotion-evidence.json` yang sudah disanitasi;
8. jika penulisan gagal, perubahan version file dicoba di-rollback ke isi awal.

## Fail-closed

Promosi ditolak bila salah satu kondisi berikut terjadi:

- report acceptance tidak lolos Stage 10;
- report berasal dari CI;
- manual checks belum lengkap/lulus;
- hash/identitas RC berbeda dari canonical lock;
- repository tidak lagi memakai `APP_VERSION` RC canonical;
- `app/version.py` memiliki nol atau lebih dari satu assignment `APP_VERSION`;
- target stable version bukan semantic version stabil.

## Cara penggunaan setelah report fisik tersedia

Dry-run:

```bash
python scripts/prepare_stable_release.py path/to/acceptance-windows11.json
```

Expected marker:

```text
STABLE_RELEASE_PREPARE_OK
FROM_VERSION=1.0.0-rc1
TO_VERSION=1.0.0
APPLIED=false
```

Apply hanya setelah dry-run valid:

```bash
python scripts/prepare_stable_release.py path/to/acceptance-windows11.json --apply
```

Expected marker:

```text
STABLE_RELEASE_PREPARE_OK
FROM_VERSION=1.0.0-rc1
TO_VERSION=1.0.0
APPLIED=true
```

Setelah `--apply`, wajib:

1. review diff `app/version.py` dan `stable-promotion-evidence.json`;
2. commit promosi stabil;
3. jalankan CI penuh;
4. jalankan Build Windows Portable dari commit promosi;
5. verifikasi `VERSION.txt` dan `VERSION_MANIFEST.json` berisi `1.0.0`;
6. verifikasi packaged acceptance CI tetap lulus;
7. baru tetapkan artifact tersebut sebagai paket stabil.

## Regression

`tests/test_stage11_promotion_helper.py` mencakup:

- dry-run valid tidak memutasi versi;
- apply valid mengubah tepat RC canonical ke stable version;
- evidence sanitasi dibuat saat apply;
- report manual gagal tidak dapat memutasi repository;
- repository yang bukan lagi RC canonical ditolak.
