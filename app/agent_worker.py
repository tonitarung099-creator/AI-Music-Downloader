from __future__ import annotations

import threading
from uuid import uuid4

from PySide6.QtCore import QThread, Signal

from app.services.gemini_agent import GeminiAgent


class AgentCommandWorker(QThread):
    """Run a Gemini natural-language command outside the Qt UI thread."""

    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, gemini: GeminiAgent, command: str, parent=None) -> None:
        super().__init__(parent)
        self.gemini = gemini
        self.command = command
        self.command_id = uuid4().hex
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.requestInterruption()

    def run(self) -> None:
        if self.cancel_event.is_set() or self.isInterruptionRequested():
            return
        try:
            result = self.gemini.parse_command(self.command, cancel_event=self.cancel_event)
        except Exception as exc:  # Defensive boundary around network/API code.
            if not self.cancel_event.is_set():
                self.failed.emit(str(exc) or "Gemini gagal diproses.")
            return

        if self.cancel_event.is_set() or self.isInterruptionRequested():
            return
        if not result.data:
            self.failed.emit(result.error or "Tidak ada respons Gemini yang valid.")
            return

        self.result_ready.emit(result.data)
