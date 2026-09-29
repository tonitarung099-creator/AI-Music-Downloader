from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_release_promotion import DEFAULT_LOCK_PATH, validate_report_file


VERSION_PATTERN = re.compile(r'^(APP_VERSION\s*=\s*)["\']([^"\']+)["\']\s*$', re.MULTILINE)
SEMVER_STABLE = re.compile(r'^\d+\.\d+\.\d+$')


@dataclass(frozen=True)
class PromotionPreparation:
    ok: bool
    errors: tuple[str, ...]
    from_version: str | None = None
    to_version: str | None = None
    changed: bool = False
    evidence: dict[str, Any] | None = None


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'Root JSON harus object: {path}')
    return data


def _replace_version(text: str, expected_current: str, stable_version: str) -> str:
    matches = list(VERSION_PATTERN.finditer(text))
    if len(matches) != 1:
        raise ValueError(f'app/version.py harus memiliki tepat satu APP_VERSION assignment; ditemukan {len(matches)}.')
    match = matches[0]
    actual = match.group(2)
    if actual != expected_current:
        raise ValueError(
            f'APP_VERSION saat ini bukan RC canonical yang dikunci; expected={expected_current!r} actual={actual!r}'
        )
    replacement = f'{match.group(1)}"{stable_version}"'
    return text[: match.start()] + replacement + text[match.end() :]


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def prepare_stable_release(
    report_path: Path,
    *,
    root: Path = ROOT,
    lock_path: Path = DEFAULT_LOCK_PATH,
    evidence_path: Path | None = None,
    apply: bool = False,
) -> PromotionPreparation:
    validation = validate_report_file(report_path, lock_path)
    if not validation.ok:
        return PromotionPreparation(False, validation.errors)
    if validation.evidence is None:
        return PromotionPreparation(False, ('Validator tidak menghasilkan promotion evidence.',))

    try:
        lock = _read_json(lock_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return PromotionPreparation(False, (f'Gagal membaca release lock: {exc}',))

    candidate = lock.get('candidate')
    if not isinstance(candidate, dict):
        return PromotionPreparation(False, ('release-candidate-lock.json candidate wajib object.',))

    current_version = candidate.get('version')
    stable_version = candidate.get('stable_version')
    if not isinstance(current_version, str) or not current_version:
        return PromotionPreparation(False, ('candidate.version tidak valid.',))
    if not isinstance(stable_version, str) or not SEMVER_STABLE.fullmatch(stable_version):
        return PromotionPreparation(False, ('candidate.stable_version harus semantic version stabil seperti 1.0.0.',))
    if current_version == stable_version:
        return PromotionPreparation(False, ('RC version dan stable version tidak boleh sama.',))

    version_path = root / 'app' / 'version.py'
    try:
        original_version_text = version_path.read_text(encoding='utf-8')
        promoted_version_text = _replace_version(original_version_text, current_version, stable_version)
    except (OSError, ValueError) as exc:
        return PromotionPreparation(False, (str(exc),))

    source_version_sha256 = hashlib.sha256(original_version_text.encode('utf-8')).hexdigest()
    evidence = dict(validation.evidence)
    evidence['stable_promotion'] = {
        'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'from_version': current_version,
        'to_version': stable_version,
        'source_app_version_sha256': source_version_sha256,
        'app_version_file': 'app/version.py',
        'mutation_applied': bool(apply),
    }

    if not apply:
        return PromotionPreparation(
            True,
            (),
            from_version=current_version,
            to_version=stable_version,
            changed=False,
            evidence=evidence,
        )

    if evidence_path is None:
        evidence_path = root / 'stable-promotion-evidence.json'

    original_exists = evidence_path.exists()
    original_evidence_bytes = evidence_path.read_bytes() if original_exists else None
    version_changed = False
    try:
        _write_text_atomic(version_path, promoted_version_text)
        version_changed = True
        _write_json_atomic(evidence_path, evidence)
    except OSError as exc:
        if version_changed:
            try:
                _write_text_atomic(version_path, original_version_text)
            except OSError:
                pass
        try:
            if original_exists and original_evidence_bytes is not None:
                temp = evidence_path.with_name(evidence_path.name + '.rollback.tmp')
                temp.write_bytes(original_evidence_bytes)
                os.replace(temp, evidence_path)
            elif evidence_path.exists():
                evidence_path.unlink()
        except OSError:
            pass
        return PromotionPreparation(False, (f'Gagal menerapkan promosi secara atomik: {exc}',))

    return PromotionPreparation(
        True,
        (),
        from_version=current_version,
        to_version=stable_version,
        changed=True,
        evidence=evidence,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Siapkan promosi AI Music Downloader RC1 ke v1.0.0 stabil hanya setelah acceptance fisik valid.'
    )
    parser.add_argument('report', type=Path, help='Path acceptance-windows11.json dari RC canonical.')
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK_PATH, help='Path release-candidate-lock.json.')
    parser.add_argument('--root', type=Path, default=ROOT, help='Root repository yang berisi app/version.py.')
    parser.add_argument(
        '--evidence-out',
        type=Path,
        default=None,
        help='Path evidence sanitasi. Default stable-promotion-evidence.json saat --apply.',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Benar-benar ubah APP_VERSION ke stable_version. Tanpa flag ini hanya dry-run.',
    )
    args = parser.parse_args(argv)

    result = prepare_stable_release(
        args.report,
        root=args.root,
        lock_path=args.lock,
        evidence_path=args.evidence_out,
        apply=args.apply,
    )
    if not result.ok:
        print('STABLE_RELEASE_PREPARE_REJECTED', file=sys.stderr)
        for error in result.errors:
            print(f'- {error}', file=sys.stderr)
        return 1

    print('STABLE_RELEASE_PREPARE_OK')
    print(f'FROM_VERSION={result.from_version}')
    print(f'TO_VERSION={result.to_version}')
    print(f'APPLIED={str(result.changed).lower()}')
    if result.changed:
        print('NEXT_STEP=jalankan CI + Build Windows Portable dari commit promosi stabil')
    else:
        print('NEXT_STEP=jalankan ulang dengan --apply hanya setelah siap membuat commit promosi')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
