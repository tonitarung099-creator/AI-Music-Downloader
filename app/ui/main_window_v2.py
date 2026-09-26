from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from app.ui.main_window import MainWindow as BaseMainWindow


class MainWindow(BaseMainWindow):
    """Small behavior layer on top of the main UI.

    Keeps the large layout file stable while fixing/adding interaction behavior.
    """

    def __init__(self) -> None:
        self._start_after_import = False
        super().__init__()

    def import_input(self) -> None:
        previous_worker = self.import_worker
        super().import_input()
        worker = self.import_worker
        if worker is not None and worker is not previous_worker:
            worker.finished.connect(self._after_import_finished)

    def _import_failed(self, message: str) -> None:
        self._start_after_import = False
        super()._import_failed(message)

    def _after_import_finished(self) -> None:
        if not self._start_after_import:
            return
        self._start_after_import = False
        self.log("Import selesai. Menjalankan download sesuai perintah Gemini...")
        self.start_download()

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

        self.agent_run_btn.setEnabled(False)
        self.log("Gemini memahami perintah...")
        try:
            result = self.gemini.parse_command(command)
            if not result.data:
                self.log(f"Gemini gagal: {result.error}")
                QMessageBox.warning(self, "Gemini gagal", result.error or "Tidak ada respons valid.")
                return

            data = result.data
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
                # If Gemini understood 'download' but there are no new titles,
                # treat it as a request to run the existing queue.
                self.start_download()
        finally:
            self.agent_run_btn.setEnabled(True)
