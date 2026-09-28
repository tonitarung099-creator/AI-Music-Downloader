from __future__ import annotations

from uuid import uuid4

from PySide6.QtWidgets import QMessageBox

from app.config import ConfigSaveError, resolve_output_dir
from app.controllers.lifecycle import OperationCoordinator
from app.models import TrackStatus
from app.ui.main_window import MainWindow as BaseMainWindow
from app.workers import ImportResult, ImportWorker


class MainWindow(BaseMainWindow):
    """Behavior/lifecycle layer over the legacy layout."""

    def __init__(self) -> None:
        self._start_after_import_id: str | None = None
        self.coordinator = OperationCoordinator()
        super().__init__()

    def import_input(self) -> str | None:
        text = self.input_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Input kosong", "Masukkan URL atau daftar judul lagu terlebih dahulu.")
            return None
        if self.coordinator.closing:
            return None
        if self.import_worker and self.import_worker.isRunning():
            self.log("Import sebelumnya masih berjalan.")
            return None
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Hentikan download sebelum menambah batch baru.")
            return None

        worker = ImportWorker(text, start_index=len(self.tracks) + 1, parent=self)
        self.import_worker = worker
        self.coordinator.begin_import(worker.import_id)
        self.add_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.log("Membaca input...")

        worker.log.connect(self.log)
        worker.failed.connect(lambda message: self.log(f"Import: {message}"))
        worker.result_ready.connect(self._handle_import_result)
        worker.finished.connect(
            lambda import_id=worker.import_id, owned_worker=worker: self._import_thread_finished(
                import_id, owned_worker
            )
        )
        worker.start()
        return worker.import_id

    def _handle_import_result(self, result: ImportResult) -> None:
        if not self.coordinator.is_current_import(result.import_id):
            self.log("Hasil import lama diabaikan karena batch sudah berubah.")
            return

        if result.tracks:
            super()._append_tracks(result.tracks)
        elif not result.cancelled:
            self.log("Tidak ada item valid yang berhasil diimpor.")

        if result.issues:
            self.log(
                f"Import selesai dengan {len(result.issues)} item gagal; item valid tetap dipertahankan."
            )
        if result.cancelled:
            self.log("Import dibatalkan.")

    def _import_thread_finished(self, import_id: str, worker: ImportWorker) -> None:
        was_current = self.coordinator.finish_import(import_id)
        if self.import_worker is worker:
            self.import_worker = None
        worker.deleteLater()

        if was_current and not self.coordinator.closing:
            self.add_btn.setEnabled(not (self.queue_worker and self.queue_worker.isRunning()))
            self.start_btn.setEnabled(not (self.queue_worker and self.queue_worker.isRunning()))

        if self._start_after_import_id != import_id:
            return
        self._start_after_import_id = None
        if was_current and not self.coordinator.closing:
            self.log("Import selesai. Menjalankan download sesuai perintah Gemini...")
            self.start_download()

    def clear_queue(self) -> None:
        if self.import_worker and self.import_worker.isRunning():
            self.coordinator.invalidate_import()
            self._start_after_import_id = None
            self.import_worker.cancel()
            self.log("Import aktif dibatalkan; hasil terlambat akan diabaikan.")
        super().clear_queue()

    def _save_download_settings(self) -> None:
        self.config.output_dir = resolve_output_dir(self.output_edit.text())
        self.output_edit.setText(self.config.output_dir)
        self.config.audio_mode = str(self.quality_combo.currentData())
        self.config.save()

    def open_output_folder(self) -> None:
        self.output_edit.setText(resolve_output_dir(self.output_edit.text()))
        super().open_output_folder()

    def start_download(self) -> None:
        if self.coordinator.closing:
            return
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import selesai sebelum memulai download.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            return

        pending = [track for track in self.tracks if track.status != TrackStatus.DONE]
        batch_id = uuid4().hex
        for track in pending:
            track.batch_id = batch_id

        try:
            super().start_download()
        except ConfigSaveError as exc:
            self.log(str(exc))
            QMessageBox.warning(self, "Pengaturan tidak dapat disimpan", str(exc))
            return

        if self.queue_worker is not None and self.queue_worker.isRunning():
            self.coordinator.begin_queue(batch_id)

    def _on_item_changed(self, job_id, status: str, progress: float, detail: str) -> None:
        # QueueWorker now identifies rows by stable job_id. Keep compatibility
        # with any legacy/manual calls that still pass an integer row.
        if isinstance(job_id, int):
            row = job_id
        else:
            row = next(
                (i for i, track in enumerate(self.tracks) if track.job_id == job_id),
                -1,
            )
        if row < 0:
            return
        BaseMainWindow._on_item_changed(self, row, status, progress, detail)

    def _queue_thread_finished(self) -> None:
        batch_id = self.coordinator.queue_batch_id
        super()._queue_thread_finished()
        if batch_id is not None:
            self.coordinator.finish_queue(batch_id)

    def retry_failed(self) -> None:
        if self.coordinator.closing:
            return
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import selesai sebelum retry.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Antrean masih berjalan; retry ditunda.")
            return

        changed = 0
        for track in self.tracks:
            if track.status in (TrackStatus.FAILED, TrackStatus.CANCELLED):
                track.status = TrackStatus.QUEUED
                track.progress = 0.0
                track.error = ""
                self._on_item_changed(track.job_id, TrackStatus.QUEUED.value, 0.0, "Siap dicoba lagi")
                changed += 1
        if changed:
            self.log(f"{changed} item disiapkan untuk retry.")
            self.start_download()
        else:
            self.log("Tidak ada item gagal untuk di-retry.")

    def run_agent_command(self) -> None:
        """Fallback synchronous implementation; v3 overrides this with QThread."""
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
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import aktif selesai sebelum menjalankan perintah Gemini.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Hentikan antrean sebelum menjalankan perintah Gemini yang dapat mengubah antrean.")
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
        finally:
            self.agent_run_btn.setEnabled(True)
