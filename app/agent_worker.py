from __future__ import annotations

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

    def run(self) -> None:
        try:
            result = self.gemini.parse_command(self.command)
        except Exception as exc:  # Defensive boundary around network/API code.
            self.failed.emit(str(exc) or "Gemini gagal diproses.")
            return

        if not result.data:
            self.failed.emit(result.error or "Tidak ada respons Gemini yang valid.")
            return

        self.result_ready.emit(result.data)
