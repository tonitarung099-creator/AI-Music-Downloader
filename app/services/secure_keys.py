from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

from app.config import app_root


class SecureKeyStoreError(RuntimeError):
    pass


def clean_keys(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= 100:
            break
    return result


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, object]:
    if not value:
        buffer = ctypes.create_string_buffer(b"\x00")
        return _DataBlob(0, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer
    buffer = ctypes.create_string_buffer(value, len(value))
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


class WindowsDpapiKeyStore:
    """Encrypt Gemini keys with the current Windows user's DPAPI profile.

    The encrypted blob stays inside the portable folder, so moving the folder on
    the same Windows user keeps working. Moving it to another Windows user or PC
    can make the blob undecryptable; callers must offer a re-entry path.
    """

    CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self, root: str | Path | None = None) -> None:
        base = Path(root) if root is not None else app_root()
        self.path = base.expanduser().resolve() / "data" / "gemini_keys.dpapi"

    @property
    def available(self) -> bool:
        return os.name == "nt" and hasattr(ctypes, "windll")

    def _protect(self, payload: bytes) -> bytes:
        if not self.available:
            raise SecureKeyStoreError("Penyimpanan aman Windows DPAPI tidak tersedia pada sistem ini.")
        in_blob, in_buffer = _blob_from_bytes(payload)
        entropy_blob, entropy_buffer = _blob_from_bytes(b"AI-Music-Downloader/Gemini/v1")
        out_blob = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "AI Music Downloader Gemini Keys",
            ctypes.byref(entropy_blob),
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        _ = (in_buffer, entropy_buffer)
        if not ok:
            raise SecureKeyStoreError(f"Windows gagal mengenkripsi API key (kode {ctypes.GetLastError()}).")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _unprotect(self, payload: bytes) -> bytes:
        if not self.available:
            raise SecureKeyStoreError("Penyimpanan aman Windows DPAPI tidak tersedia pada sistem ini.")
        in_blob, in_buffer = _blob_from_bytes(payload)
        entropy_blob, entropy_buffer = _blob_from_bytes(b"AI-Music-Downloader/Gemini/v1")
        out_blob = _DataBlob()
        description = wintypes.LPWSTR()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            ctypes.byref(description),
            ctypes.byref(entropy_blob),
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        _ = (in_buffer, entropy_buffer)
        if not ok:
            raise SecureKeyStoreError(
                "API key terenkripsi tidak dapat dibuka oleh akun Windows ini. "
                "Masukkan ulang API key melalui Kelola API Key."
            )
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            if description:
                kernel32.LocalFree(description)
            kernel32.LocalFree(out_blob.pbData)

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            encrypted = self.path.read_bytes()
        except OSError as exc:
            raise SecureKeyStoreError(f"File API key terenkripsi tidak dapat dibaca: {exc}") from exc
        try:
            decoded = self._unprotect(encrypted).decode("utf-8")
            payload = json.loads(decoded)
        except SecureKeyStoreError:
            raise
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise SecureKeyStoreError("Isi penyimpanan API key terenkripsi tidak valid.") from exc
        return clean_keys(payload)

    def save(self, keys: object) -> None:
        cleaned = clean_keys(keys)
        payload = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self._protect(payload)
        temp = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_bytes(encrypted)
            os.replace(temp, self.path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise SecureKeyStoreError(f"Gagal menyimpan API key terenkripsi: {exc}") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecureKeyStoreError(f"Gagal menghapus penyimpanan API key lama: {exc}") from exc
