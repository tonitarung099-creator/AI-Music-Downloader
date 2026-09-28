from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.agent_worker import AgentCommandWorker
from app.ui.main_window_v2 import MainWindow as BaseMainWindow


class MainWindow(BaseMainWindow):
    """Production UI layer with non-blocking Gemini and coordinated shutdown."""

    def __init__(self) -> None:
        super().__init__()
        self.agent_worker: AgentCommandWorker | None = None
        self._allow_close = False
        self._shutdown_poll_scheduled = False

    def run_agent_command(self) -> None:
        command = self.agent_input.toPlainText().strip()
        if not command or self.coordinator.closing:
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
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import aktif selesai sebelum menjalankan perintah Gemini.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Hentikan antrean sebelum menjalankan perintah Gemini yang dapat mengubah antrean.")
            return

        self.agent_run_btn.setEnabled(False)
        self.log("Gemini memahami perintah...")

        worker = AgentCommandWorker(self.gemini, command, parent=self)
        self.agent_worker = worker
        self.coordinator.begin_agent(worker.command_id)
        worker.result_ready.connect(
            lambda data, command_id=worker.command_id: self._apply_agent_result(command_id, data)
        )
        worker.failed.connect(
            lambda message, command_id=worker.command_id: self._agent_failed(command_id, message)
        )
        worker.finished.connect(
            lambda command_id=worker.command_id, owned_worker=worker: self._agent_finished(
                command_id, owned_worker
            )
        )
        worker.start()

    def _apply_agent_result(self, command_id: str, data: dict) -> None:
        if not self.coordinator.is_current_agent(command_id):
            self.log("Hasil Gemini lama diabaikan karena operasi sudah berubah.")
            return

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
                self.input_text.setPlainText(text)
                import_id = self.import_input()
                if intent == "add_and_download":
                    self._start_after_import_id = import_id

        note = data.get("note") or "Perintah dipahami."
        self.log(f"Gemini: {note}")

        if intent == "download_queue":
            self.start_download()
        elif intent == "retry_failed":
            self.retry_failed()
        elif intent == "add_and_download" and not has_queries:
            self.start_download()

    def _agent_failed(self, command_id: str, message: str) -> None:
        if not self.coordinator.is_current_agent(command_id):
            return
        self.log(f"Gemini gagal: {message}")
        QMessageBox.warning(self, "Gemini gagal", message or "Tidak ada respons valid.")

    def _agent_finished(self, command_id: str, worker: AgentCommandWorker) -> None:
        was_current = self.coordinator.finish_agent(command_id)
        if self.agent_worker is worker:
            self.agent_worker = None
        worker.deleteLater()
        if was_current and not self.coordinator.closing:
            self.agent_run_btn.setEnabled(True)

    def _running_workers(self) -> list[object]:
        workers = [self.import_worker, self.queue_worker, self.agent_worker]
        return [worker for worker in workers if worker is not None and worker.isRunning()]

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._allow_close:
            event.accept()
            return

        running = self._running_workers()
        if not running:
            event.accept()
            return

        event.ignore()
        if self.coordinator.closing:
            return

        self.coordinator.request_shutdown()
        self._start_after_import_id = None
        self.header_status.setText("Menutup dengan aman...")
        self.add_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.agent_run_btn.setEnabled(False)

        if self.import_worker and self.import_worker.isRunning():
            self.import_worker.cancel()
        if self.queue_worker and self.queue_worker.isRunning():
            self.queue_worker.stop()
        if self.agent_worker and self.agent_worker.isRunning():
            self.agent_worker.cancel()

        if not self._shutdown_poll_scheduled:
            self._shutdown_poll_scheduled = True
            QTimer.singleShot(100, self._poll_shutdown)

    def _poll_shutdown(self) -> None:
        if self._running_workers():
            QTimer.singleShot(100, self._poll_shutdown)
            return
        self._shutdown_poll_scheduled = False
        self._allow_close = True
        self.close()
