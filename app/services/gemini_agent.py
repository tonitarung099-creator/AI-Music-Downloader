from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None

from app.services.matcher import Candidate


@dataclass(slots=True)
class GeminiResult:
    data: dict[str, Any] | None
    error: str = ""


class GeminiAgent:
    """Optional helper. The downloader never requires Gemini to function."""

    def __init__(self, api_keys: list[str] | None = None, model: str = "gemini-2.5-flash") -> None:
        self.api_keys = [k.strip() for k in (api_keys or []) if k.strip()][:100]
        self.model = model
        self._cursor = 0

    @property
    def available(self) -> bool:
        return bool(self.api_keys) and genai is not None

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

    def _generate_json(self, prompt: str) -> GeminiResult:
        if not self.available:
            return GeminiResult(None, "Gemini belum dikonfigurasi.")

        last_error = ""
        attempts = len(self.api_keys)
        for _ in range(attempts):
            key = self.api_keys[self._cursor % len(self.api_keys)]
            self._cursor = (self._cursor + 1) % len(self.api_keys)
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(model=self.model, contents=prompt)
                data = self._extract_json(getattr(response, "text", ""))
                if data is not None:
                    return GeminiResult(data)
                last_error = "Respons Gemini bukan JSON yang valid."
            except Exception as exc:  # provider errors vary by SDK version
                last_error = str(exc)
                continue
        return GeminiResult(None, last_error or "Semua API key Gemini gagal.")

    def parse_command(self, command: str) -> GeminiResult:
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
        return self._generate_json(prompt)

    def choose_candidate(self, query: str, candidates: list[Candidate]) -> int | None:
        if not self.available or not candidates:
            return None

        rows = []
        for i, c in enumerate(candidates[:6]):
            rows.append({
                "index": i,
                "title": c.title,
                "channel": c.uploader,
                "duration_seconds": c.duration,
                "local_score": round(c.score, 3),
            })

        prompt = f"""
Pilih kandidat YouTube yang PALING mungkin merupakan lagu asli yang diminta.
Hindari cover, karaoke, live, sped-up, slowed, remix, reverb atau instrumental kecuali memang diminta.
Utamakan official audio, channel artis resmi, atau channel Topic.
Balas HANYA JSON: {{"index": 0, "confidence": 0.0, "reason": "singkat"}}

Permintaan: {query}
Kandidat: {json.dumps(rows, ensure_ascii=False)}
""".strip()
        result = self._generate_json(prompt)
        if not result.data:
            return None
        try:
            idx = int(result.data.get("index"))
        except (TypeError, ValueError):
            return None
        return idx if 0 <= idx < min(6, len(candidates)) else None
