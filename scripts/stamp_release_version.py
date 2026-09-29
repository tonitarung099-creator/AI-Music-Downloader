from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.version import APP_NAME, APP_VERSION

ROOT_DIR = "AI-Music-Downloader-Portable"
MANIFEST_NAME = f"{ROOT_DIR}/VERSION_MANIFEST.json"
VERSION_NAME = f"{ROOT_DIR}/VERSION.txt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stamp(zip_path: Path, checksum_path: Path) -> str:
    zip_path = zip_path.resolve()
    checksum_path = checksum_path.resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)

    with zipfile.ZipFile(zip_path, "r") as source:
        names = set(source.namelist())
        if MANIFEST_NAME not in names:
            raise RuntimeError(f"Manifest tidak ditemukan di ZIP: {MANIFEST_NAME}")
        manifest = json.loads(source.read(MANIFEST_NAME).decode("utf-8-sig"))
        manifest["app"] = APP_NAME
        manifest["app_version"] = APP_VERSION
        manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

        fd, temp_name = tempfile.mkstemp(prefix="ai-music-release-", suffix=".zip", dir=str(zip_path.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with zipfile.ZipFile(temp_path, "w") as target:
                for item in source.infolist():
                    if item.filename in {MANIFEST_NAME, VERSION_NAME}:
                        continue
                    target.writestr(item, source.read(item.filename))
                target.writestr(MANIFEST_NAME, manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
                target.writestr(VERSION_NAME, f"{APP_NAME} v{APP_VERSION}\n", compress_type=zipfile.ZIP_DEFLATED)
            os.replace(temp_path, zip_path)
        finally:
            temp_path.unlink(missing_ok=True)

    archive_hash = sha256_file(zip_path)
    checksum_path.write_text(f"{archive_hash}  {zip_path.name}\n", encoding="ascii")
    return archive_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="Stamp versi aplikasi ke portable ZIP dan perbarui checksum.")
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("checksum_path", type=Path)
    args = parser.parse_args()

    archive_hash = stamp(args.zip_path, args.checksum_path)
    print(f"RELEASE_VERSION={APP_VERSION}")
    print(f"VERSIONED_ZIP_SHA256={archive_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
