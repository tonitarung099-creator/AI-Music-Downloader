from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.services.matcher import Candidate


@dataclass(slots=True)
class GeminiResult:
    data: dict[str, Any] | None
    error: str = ""


class GeminiAgent:
    """Optional Gemini helper using the official REST API.

    The download engine never depends on Gemini to function. API keys are
    rotated when a request fails or a key is rate-limited.
    """

    API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
    REQUEST_TIMEOUT_SECONDS = 15

    def __init__(self, api_keys: list[str] | None = None, model: str = "gemini-3.8-flash") -> None:
        self.api_keys = [k.strip() for k in (api_keys or []) if k.strip()][:100]
        self.model = model
        self._cursor = 0

    @property
    def available(self) -> bool:
        return bool(self.api_keys)

    def update_keys(self, api_keys: list[str]) -> None:
        self.api_keys = [k.strip() for k in api_keys if k.strip()][:100]
        self._cursor = 0

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                return None
            try:
                obj = json.loads(match.group(0))
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            return ""
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()

    def _request_text(self, api_key: str, prompt: str) -> str:
        model = quote(self.model.strip(), safe="-._")
        url = f"{self.API_ROOT}/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        request = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        with urlopen(request, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return self._response_text(payload)

    def _generate_json(
        self,
        prompt: str,
        cancel_event: threading.Event | None = None,
    ) -> GeminiResult:
        if not self.available:
            return GeminiResult(None, "Gemini belum dikonfigurasi.")

        last_error = ""
        for _ in range(len(self.api_keys)):
            if cancel_event is not None and cancel_event.is_set():
                return GeminiResult(None, "Permintaan Gemini dibatalkan.")

            key = self.api_keys[self._cursor % len(self.api_keys)]
            self._cursor = (self._cursor + 1) % len(self.api_keys)
            try:
                text = self._request_text(key, prompt)
                if cancel_event is not None and cancel_event.is_set():
                    return GeminiResult(None, "Permintaan Gemini dibatalkan.")
                data = self._extract_json(text)
                if data is not None:
                    return GeminiResult(data)
                last_error = "Respons Gemini bukan JSON yang valid."
            except HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = ""
                last_error = f"HTTP {exc.code}: {detail or exc.reason}"
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)

        if cancel_event is not None and cancel_event.is_set():
            return GeminiResult(None, "Permintaan Gemini dibatalkan.")
        return GeminiResult(None, last_error or "Semua API key Gemini gagal.")

    def parse_command(
        self,
        command: str,
        cancel_event: threading.Event | None = None,
    ) -> GeminiResult:
        prompt = f"""
Kamu adalah parser perintah untuk aplikasi downloader musik desktop.
Balas HANYA JSON valid, tanpa markdown.
Jangan membuat judul lagu yang tidak disebut pengguna.

Skema:
{{
  "intent": "add_and_download|add_only|download_queue|retry_failed|unknown",
  "queries": ["Artis - Judul"],
  "quality": "original|m4a|mp3|null",
  "avoid": ["live", "remix"],
  "note": "penjelasan singkat"
}}

Perintah pengguna:
{command}
""".strip()
        return self._generate_json(prompt, cancel_event=cancel_event)

    def choose_candidate(
        self,
        query: str,
        candidates: list[Candidate],
        cancel_event: threading.Event | None = None,
    ) -> int | None:
        if not self.available or not candidates:
            return None

        rows = []
        for i, candidate in enumerate(candidates[:6]):
            rows.append({
                "index": i,
                "title": candidate.title,
                "channel": candidate.uploader,
                "duration_seconds": candidate.duration,
                "local_score": round(candidate.score, 3),
            })

        prompt = f"""
Pilih kandidat YouTube yang PALING mungkin merupakan lagu asli yang diminta.
Hindari cover, karaoke, live, sped-up, slowed, remix, reverb atau instrumental kecuali memang diminta.
Utamakan official audio, channel artis resmi, atau channel Topic.
Balas HANYA JSON: {{"index": 0, "confidence": 0.0, "reason": "singkat"}}

Permintaan: {query}
Kandidat: {json.dumps(rows, ensure_ascii=False)}
""".strip()
        result = self._generate_json(prompt, cancel_event=cancel_event)
        if not result.data:
            return None
        try:
            idx = int(result.data.get("index"))
        except (TypeError, ValueError):
            return None
        return idx if 0 <= idx < min(6, len(candidates)) else None
