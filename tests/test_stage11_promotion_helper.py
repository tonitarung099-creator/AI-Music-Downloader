from __future__ import annotations

import json
from pathlib import Path

from scripts.prepare_stable_release import prepare_stable_release


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "release-candidate-lock.json"


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _good_report(lock: dict) -> dict:
    candidate = lock["candidate"]
    return {
        "schema_version": lock["acceptance_schema_version"],
        "app": candidate["app"],
        "app_version": candidate["version"],
        "started_at_utc": "2026-09-29T12:00:00+07:00",
        "finished_at_utc": "2026-09-29T12:10:00+07:00",
        "ci_mode": False,
        "windows": {"caption": "Microsoft Windows 11 Pro", "version": "10.0.26100"},
        "elevated": False,
        "manifest_git_sha": candidate["git_sha"],
        "manifest_sha256": candidate["manifest_sha256"],
        "executable_sha256": candidate["executable_sha256"],
        "automated_passed": True,
        "manual_confirmation_required": True,
        "manual_checks": [
            {
                "id": check_id,
                "name": check_id,
                "passed": True,
                "detail": "dikonfirmasi",
                "attested_at_utc": f"2026-09-29T12:0{index + 2}:00+07:00",
            }
            for index, check_id in enumerate(lock["required_manual_checks"])
        ],
        "release_ready": True,
        "release_gate_reason": "Acceptance otomatis dan tiga konfirmasi manual Windows 11 fisik lulus.",
        "checks": [
            {"name": name, "passed": True, "detail": "ok"}
            for name in lock["required_automated_checks"]
        ],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    version_path = root / "app" / "version.py"
    version_path.parent.mkdir(parents=True)
    version_path.write_text(
        'APP_NAME = "AI Music Downloader"\nAPP_VERSION = "1.0.0-rc1"\n',
        encoding="utf-8",
    )

    lock = _lock()
    lock_path = root / "release-candidate-lock.json"
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

    report_path = root / "acceptance-windows11.json"
    report_path.write_text(json.dumps(_good_report(lock), indent=2), encoding="utf-8")
    evidence_path = root / "stable-promotion-evidence.json"
    return root, lock_path, report_path, evidence_path


def test_dry_run_validates_without_mutating_version(tmp_path):
    root, lock_path, report_path, evidence_path = _fixture(tmp_path)

    result = prepare_stable_release(
        report_path,
        root=root,
        lock_path=lock_path,
        evidence_path=evidence_path,
        apply=False,
    )

    assert result.ok is True
    assert result.changed is False
    assert result.from_version == "1.0.0-rc1"
    assert result.to_version == "1.0.0"
    assert 'APP_VERSION = "1.0.0-rc1"' in (root / "app" / "version.py").read_text(encoding="utf-8")
    assert not evidence_path.exists()


def test_apply_promotes_exact_rc_and_writes_sanitized_evidence(tmp_path):
    root, lock_path, report_path, evidence_path = _fixture(tmp_path)

    result = prepare_stable_release(
        report_path,
        root=root,
        lock_path=lock_path,
        evidence_path=evidence_path,
        apply=True,
    )

    assert result.ok is True
    assert result.changed is True
    version_text = (root / "app" / "version.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "1.0.0"' in version_text
    assert "1.0.0-rc1" not in version_text

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["promotion_allowed"] is True
    assert evidence["stable_promotion"]["from_version"] == "1.0.0-rc1"
    assert evidence["stable_promotion"]["to_version"] == "1.0.0"
    assert evidence["stable_promotion"]["mutation_applied"] is True
    assert "windows" not in evidence
    assert "checks" not in evidence


def test_invalid_physical_report_never_mutates_version(tmp_path):
    root, lock_path, report_path, evidence_path = _fixture(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["manual_checks"][1]["passed"] = False
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    result = prepare_stable_release(
        report_path,
        root=root,
        lock_path=lock_path,
        evidence_path=evidence_path,
        apply=True,
    )

    assert result.ok is False
    assert result.changed is False
    assert 'APP_VERSION = "1.0.0-rc1"' in (root / "app" / "version.py").read_text(encoding="utf-8")
    assert not evidence_path.exists()


def test_helper_refuses_when_repository_is_not_on_canonical_rc(tmp_path):
    root, lock_path, report_path, evidence_path = _fixture(tmp_path)
    (root / "app" / "version.py").write_text(
        'APP_NAME = "AI Music Downloader"\nAPP_VERSION = "1.0.0-rc2"\n',
        encoding="utf-8",
    )

    result = prepare_stable_release(
        report_path,
        root=root,
        lock_path=lock_path,
        evidence_path=evidence_path,
        apply=True,
    )

    assert result.ok is False
    assert any("bukan RC canonical" in error for error in result.errors)
    assert 'APP_VERSION = "1.0.0-rc2"' in (root / "app" / "version.py").read_text(encoding="utf-8")
    assert not evidence_path.exists()
