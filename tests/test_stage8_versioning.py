from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from app.version import APP_NAME, APP_VERSION, version_text
from scripts.stamp_release_version import MANIFEST_NAME, VERSION_NAME, stamp


def test_release_candidate_version_is_semver_prerelease():
    assert APP_NAME == "AI Music Downloader"
    assert re.fullmatch(r"\d+\.\d+\.\d+-rc\d+", APP_VERSION)
    assert version_text() == f"AI Music Downloader v{APP_VERSION}"


def test_release_stamper_adds_version_to_manifest_and_version_txt(tmp_path: Path):
    archive = tmp_path / "AI-Music-Downloader-Portable.zip"
    checksum = tmp_path / "AI-Music-Downloader-Portable.zip.sha256"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr(
            MANIFEST_NAME,
            json.dumps({"schema_version": 1, "app": "AI Music Downloader", "git_sha": "abc"}),
        )
        handle.writestr("AI-Music-Downloader-Portable/AI Music Downloader.exe", b"fixture")

    digest = stamp(archive, checksum)

    with zipfile.ZipFile(archive, "r") as handle:
        manifest = json.loads(handle.read(MANIFEST_NAME).decode("utf-8"))
        version_file = handle.read(VERSION_NAME).decode("utf-8").strip()

    assert manifest["app"] == APP_NAME
    assert manifest["app_version"] == APP_VERSION
    assert version_file == version_text()
    assert checksum.read_text(encoding="ascii") == f"{digest}  {archive.name}\n"


def test_windows_workflow_verifies_stamped_release_metadata():
    workflow = Path(".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert "Stamp application version into portable ZIP" in workflow
    assert "scripts/stamp_release_version.py" in workflow
    assert "RELEASE_VERSION_METADATA_OK" in workflow
    assert "VERSION_MANIFEST.json" in workflow
    assert "VERSION.txt" in workflow
