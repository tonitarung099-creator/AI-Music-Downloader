from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from scripts.validate_release_promotion import validate_report, validate_report_file


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "release-candidate-lock.json"


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _good_report() -> dict:
    lock = _lock()
    candidate = lock["candidate"]
    required_checks = [
        {"name": name, "passed": True, "detail": "ok"}
        for name in lock["required_automated_checks"]
    ]
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
        "checks": required_checks,
    }


def test_canonical_physical_report_is_accepted():
    report = _good_report()
    result = validate_report(report, _lock(), report_sha256="a" * 64)

    assert result.ok is True
    assert result.errors == ()
    assert result.evidence is not None
    assert result.evidence["promotion_allowed"] is True
    assert result.evidence["candidate"]["stable_version"] == "1.0.0"
    assert [item["id"] for item in result.evidence["manual_checks"]] == [
        "gui_normal",
        "real_download",
        "restart_persistence",
    ]


def test_ci_report_can_never_promote():
    report = _good_report()
    report["ci_mode"] = True
    report["manual_confirmation_required"] = False
    report["manual_checks"] = []

    result = validate_report(report, _lock())

    assert result.ok is False
    assert any("bukan CI" in error for error in result.errors)
    assert any("Manual check wajib tidak ada" in error for error in result.errors)


def test_wrong_candidate_identity_is_rejected():
    report = _good_report()
    report["manifest_git_sha"] = "0" * 40
    report["manifest_sha256"] = "0" * 64
    report["executable_sha256"] = "f" * 64

    result = validate_report(report, _lock())

    assert result.ok is False
    joined = "\n".join(result.errors)
    assert "manifest_git_sha" in joined
    assert "manifest_sha256" in joined
    assert "executable_sha256" in joined


def test_failed_or_missing_manual_gate_is_rejected():
    report = _good_report()
    report["manual_checks"][1]["passed"] = False
    report["manual_checks"] = report["manual_checks"][:2]

    result = validate_report(report, _lock())

    assert result.ok is False
    joined = "\n".join(result.errors)
    assert "real_download" in joined
    assert "restart_persistence" in joined


def test_admin_or_non_windows11_host_is_rejected():
    report = _good_report()
    report["elevated"] = True
    report["windows"] = {"caption": "Microsoft Windows Server 2025 Datacenter", "version": "10.0.26100"}

    result = validate_report(report, _lock())

    assert result.ok is False
    joined = "\n".join(result.errors)
    assert "non-admin" in joined
    assert "bukan Windows 11 fisik" in joined


def test_required_automated_check_must_be_present_and_passed():
    report = _good_report()
    report["checks"][0]["passed"] = False
    report["checks"] = report["checks"][:-1]

    result = validate_report(report, _lock())

    assert result.ok is False
    joined = "\n".join(result.errors)
    assert "Automated check wajib gagal" in joined
    assert "Automated check wajib tidak ada" in joined


def test_report_file_hash_is_bound_into_sanitized_evidence(tmp_path):
    report = _good_report()
    report_path = tmp_path / "acceptance-windows11.json"
    raw = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    report_path.write_bytes(raw)

    result = validate_report_file(report_path, LOCK_PATH)

    assert result.ok is True
    assert result.evidence is not None
    assert result.evidence["acceptance_report_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "windows" not in result.evidence
    assert "checks" not in result.evidence


def test_timestamp_outside_acceptance_window_is_rejected():
    report = _good_report()
    report["manual_checks"][0]["attested_at_utc"] = "2026-09-29T11:59:59+07:00"

    result = validate_report(report, _lock())

    assert result.ok is False
    assert any("lebih awal" in error for error in result.errors)
