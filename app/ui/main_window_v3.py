from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from app.agent_worker import AgentCommandWorker
from app.ui.main_window_v2 import MainWindow as BaseMainWindow


class MainWindow(BaseMainWindow):
    """Non-blocking Gemini command layer.

    Keeps network/API work off the Qt UI thread while preserving the v2
    automatic add-and-download behavior.
    """

    def __init__(self) -> None:
        super().__init__()
        self.agent_worker: AgentCommandWorker | None = None

    def run_agent_command(self) -> None:
        command = self.agent_input.toPlainText().strip()
        if not command:
            return
        if not self.gemini.available:
            QMessageBox.information(
                self,
                "Gemini belum aktif",
                "Masukkan API key Gemini terlebih dahulu. Downloader tetap dapat digunakan tanpa Gemini.",
            )
            return
        if self.agent_worker and self.agent_worker.isRunning():
            self.log("Gemini masih memproses perintah sebelumnya...")
            return

        self.agent_run_btn.setEnabled(False)
        self.log("Gemini memahami perintah...")

        worker = AgentCommandWorker(self.gemini, command, parent=self)
        self.agent_worker = worker
        worker.result_ready.connect(self._apply_agent_result)
        worker.failed.connect(self._agent_failed)
        worker.finished.connect(self._agent_finished)
        worker.start()

    def _apply_agent_result(self, data: dict) -> None:
        intent = data.get("intent")
        quality = data.get("quality")
        if quality in {"original", "m4a", "mp3"}:
            idx = self.quality_combo.findData(quality)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)

        queries = data.get("queries") or []
        has_queries = isinstance(queries, list) and bool(queries)
        if has_queries:
            text = "\n".join(str(q).strip() for q in queries if str(q).strip())
            if text:
                self._start_after_import = intent == "add_and_download"
                self.input_text.setPlainText(text)
                self.import_input()

        note = data.get("note") or "Perintah dipahami."
        self.log(f"Gemini: {note}")

        if intent == "download_queue":
            self.start_download()
        elif intent == "retry_failed":
            self.retry_failed()
        elif intent == "add_and_download" and not has_queries:
            self.start_download()

    def _agent_failed(self, message: str) -> None:
        self.log(f"Gemini gagal: {message}")
        QMessageBox.warning(self, "Gemini gagal", message or "Tidak ada respons valid.")

    def _agent_finished(self) -> None:
        self.agent_run_btn.setEnabled(True)
        worker = self.agent_worker
        self.agent_worker = None
        if worker is not None:
            worker.deleteLater()
