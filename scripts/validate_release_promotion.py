from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT / "release-candidate-lock.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]
    evidence: dict[str, Any] | None = None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"File tidak ditemukan: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON tidak valid: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Root JSON harus object: {path}")
    return data


def _parse_iso(value: object, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} wajib berupa timestamp ISO-8601 non-kosong.")
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        errors.append(f"{field} bukan timestamp ISO-8601 yang valid: {value!r}")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} wajib memiliki timezone/offset: {value!r}")
        return None
    return parsed.astimezone(timezone.utc)


def _require_hex64(value: object, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str):
        errors.append(f"{field} wajib berupa SHA-256 string.")
        return None
    normalized = value.strip().lower()
    if not HEX64.fullmatch(normalized):
        errors.append(f"{field} bukan SHA-256 64 karakter hex yang valid.")
        return None
    return normalized


def _windows11_physical(report: dict[str, Any], errors: list[str]) -> None:
    windows = report.get("windows")
    if not isinstance(windows, dict):
        errors.append("windows wajib object dari acceptance fisik.")
        return

    caption = str(windows.get("caption") or "")
    version = str(windows.get("version") or "")
    if "server" in caption.lower() or "windows 11" not in caption.lower():
        errors.append(f"Host bukan Windows 11 fisik yang diterima: caption={caption!r}")

    parts = version.split(".")
    build = None
    if len(parts) >= 3:
        try:
            build = int(parts[2])
        except ValueError:
            pass
    if build is None or build < 22000:
        errors.append(f"Build Windows 11 tidak valid/terlalu lama: version={version!r}")


def _manual_checks(report: dict[str, Any], lock: dict[str, Any], start: datetime | None, finish: datetime | None, errors: list[str]) -> list[dict[str, Any]]:
    raw = report.get("manual_checks")
    if not isinstance(raw, list):
        errors.append("manual_checks wajib berupa array.")
        return []

    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"manual_checks[{index}] wajib object.")
            continue
        check_id = item.get("id")
        if not isinstance(check_id, str) or not check_id:
            errors.append(f"manual_checks[{index}].id wajib string non-kosong.")
            continue
        if check_id in by_id:
            errors.append(f"manual_checks memiliki id duplikat: {check_id}")
            continue
        by_id[check_id] = item

    required = lock.get("required_manual_checks")
    if not isinstance(required, list) or not all(isinstance(x, str) and x for x in required):
        errors.append("release-candidate-lock.json memiliki required_manual_checks tidak valid.")
        return []

    accepted: list[dict[str, Any]] = []
    for check_id in required:
        item = by_id.get(check_id)
        if item is None:
            errors.append(f"Manual check wajib tidak ada: {check_id}")
            continue
        if item.get("passed") is not True:
            errors.append(f"Manual check belum lulus: {check_id}")
        attested = _parse_iso(item.get("attested_at_utc"), f"manual_checks[{check_id}].attested_at_utc", errors)
        if attested is not None and start is not None and attested < start:
            errors.append(f"Timestamp manual check lebih awal dari started_at_utc: {check_id}")
        if attested is not None and finish is not None and attested > finish:
            errors.append(f"Timestamp manual check lebih akhir dari finished_at_utc: {check_id}")
        accepted.append(item)
    return accepted


def _automated_checks(report: dict[str, Any], lock: dict[str, Any], errors: list[str]) -> None:
    raw = report.get("checks")
    if not isinstance(raw, list):
        errors.append("checks wajib berupa array.")
        return

    by_name: dict[str, dict[str, Any]] = {}
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            by_name.setdefault(item["name"], item)

    required = lock.get("required_automated_checks")
    if not isinstance(required, list) or not all(isinstance(x, str) and x for x in required):
        errors.append("release-candidate-lock.json memiliki required_automated_checks tidak valid.")
        return

    for name in required:
        item = by_name.get(name)
        if item is None:
            errors.append(f"Automated check wajib tidak ada: {name}")
        elif item.get("passed") is not True:
            errors.append(f"Automated check wajib gagal: {name}")


def validate_report(report: dict[str, Any], lock: dict[str, Any], *, report_sha256: str | None = None) -> ValidationResult:
    errors: list[str] = []

    if lock.get("schema_version") != 1:
        errors.append("release-candidate-lock.json schema_version harus 1.")
    candidate = lock.get("candidate")
    if not isinstance(candidate, dict):
        return ValidationResult(False, ("release-candidate-lock.json candidate wajib object.",))

    expected_schema = lock.get("acceptance_schema_version")
    if report.get("schema_version") != expected_schema:
        errors.append(f"schema_version acceptance harus {expected_schema!r}.")
    if report.get("app") != candidate.get("app"):
        errors.append(f"app tidak cocok; expected={candidate.get('app')!r} actual={report.get('app')!r}")
    if report.get("app_version") != candidate.get("version"):
        errors.append(f"app_version bukan RC yang dikunci; expected={candidate.get('version')!r} actual={report.get('app_version')!r}")
    if report.get("manifest_git_sha") != candidate.get("git_sha"):
        errors.append("manifest_git_sha tidak cocok dengan canonical RC1.")
    if report.get("ci_mode") is not False:
        errors.append("Report promosi stabil wajib berasal dari mode fisik, bukan CI.")
    if report.get("automated_passed") is not True:
        errors.append("automated_passed harus true.")
    if report.get("manual_confirmation_required") is not True:
        errors.append("manual_confirmation_required harus true pada acceptance fisik.")
    if report.get("release_ready") is not True:
        errors.append("release_ready harus true.")
    if report.get("elevated") is not False:
        errors.append("Acceptance promosi wajib dijalankan sebagai user non-admin/elevated=false.")

    expected_manifest = _require_hex64(candidate.get("manifest_sha256"), "lock.candidate.manifest_sha256", errors)
    actual_manifest = _require_hex64(report.get("manifest_sha256"), "manifest_sha256", errors)
    if expected_manifest is not None and actual_manifest is not None and actual_manifest != expected_manifest:
        errors.append("manifest_sha256 tidak cocok dengan canonical RC1.")

    expected_exe = _require_hex64(candidate.get("executable_sha256"), "lock.candidate.executable_sha256", errors)
    actual_exe = _require_hex64(report.get("executable_sha256"), "executable_sha256", errors)
    if expected_exe is not None and actual_exe is not None and actual_exe != expected_exe:
        errors.append("executable_sha256 tidak cocok dengan canonical RC1.")

    _windows11_physical(report, errors)
    started = _parse_iso(report.get("started_at_utc"), "started_at_utc", errors)
    finished = _parse_iso(report.get("finished_at_utc"), "finished_at_utc", errors)
    if started is not None and finished is not None and finished < started:
        errors.append("finished_at_utc lebih awal dari started_at_utc.")

    accepted_manual = _manual_checks(report, lock, started, finished, errors)
    _automated_checks(report, lock, errors)

    if errors:
        return ValidationResult(False, tuple(errors))

    if report_sha256 is None:
        report_sha256 = ""

    evidence = {
        "schema_version": 1,
        "gate": "AI Music Downloader stable promotion",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "acceptance_report_sha256": report_sha256,
        "candidate": {
            "version": candidate["version"],
            "stable_version": candidate["stable_version"],
            "git_sha": candidate["git_sha"],
            "portable_zip_sha256": candidate["portable_zip_sha256"],
            "manifest_sha256": candidate["manifest_sha256"],
            "executable_sha256": candidate["executable_sha256"],
        },
        "acceptance_finished_at_utc": report["finished_at_utc"],
        "manual_checks": [
            {
                "id": item["id"],
                "passed": True,
                "attested_at_utc": item["attested_at_utc"],
            }
            for item in accepted_manual
        ],
        "promotion_allowed": True,
    }
    return ValidationResult(True, (), evidence)


def validate_report_file(report_path: Path, lock_path: Path = DEFAULT_LOCK_PATH) -> ValidationResult:
    raw = report_path.read_bytes()
    report_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        report = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        return ValidationResult(False, (f"Report bukan UTF-8: {exc}",))
    except json.JSONDecodeError as exc:
        return ValidationResult(False, (f"Report JSON tidak valid: {exc}",))
    if not isinstance(report, dict):
        return ValidationResult(False, ("Root acceptance report harus object.",))
    try:
        lock = _read_json(lock_path)
    except ValueError as exc:
        return ValidationResult(False, (str(exc),))
    return validate_report(report, lock, report_sha256=report_sha256)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validasi acceptance Windows 11 fisik sebelum promosi RC1 ke v1.0.0 stabil."
    )
    parser.add_argument("report", type=Path, help="Path acceptance-windows11.json dari paket RC1 canonical.")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH, help="Path release-candidate-lock.json.")
    parser.add_argument("--evidence-out", type=Path, default=None, help="Tulis bukti promosi yang sudah disanitasi bila valid.")
    args = parser.parse_args(argv)

    result = validate_report_file(args.report, args.lock)
    if not result.ok:
        print("STABLE_PROMOTION_GATE_REJECTED", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    assert result.evidence is not None
    if args.evidence_out is not None:
        _write_json_atomic(args.evidence_out, result.evidence)
        print(f"PROMOTION_EVIDENCE={args.evidence_out}")

    candidate = result.evidence["candidate"]
    print("STABLE_PROMOTION_GATE_OK")
    print(f"RC_VERSION={candidate['version']}")
    print(f"STABLE_VERSION={candidate['stable_version']}")
    print(f"RC_GIT_SHA={candidate['git_sha']}")
    print(f"ACCEPTANCE_REPORT_SHA256={result.evidence['acceptance_report_sha256']}")
    print("PROMOTION_ALLOWED=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
