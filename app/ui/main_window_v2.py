from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton

from app.config import ConfigSaveError, resolve_output_dir
from app.controllers.lifecycle import OperationCoordinator
from app.models import TrackRequest, TrackStatus
from app.storage import QueueRepository, QueueStorageError
from app.ui.candidate_review import CandidateReviewDialog
from app.ui.main_window import MainWindow as BaseMainWindow
from app.workers import ImportResult, ImportWorker, QueueWorker


RUNNABLE_STATUSES = {TrackStatus.QUEUED, TrackStatus.INTERRUPTED}
RETRYABLE_BY_USER_STATUSES = {TrackStatus.FAILED, TrackStatus.CANCELLED}


class MainWindow(BaseMainWindow):
    """Behavior/lifecycle layer over the legacy layout."""

    def __init__(self) -> None:
        self._start_after_import_id: str | None = None
        self.coordinator = OperationCoordinator()
        self.queue_repo: QueueRepository | None = None
        super().__init__()
        self._configure_stage3_ui()
        self._open_queue_repository()

    def _configure_stage3_ui(self) -> None:
        m4a_idx = self.quality_combo.findData("m4a")
        if m4a_idx >= 0:
            self.quality_combo.setItemText(m4a_idx, "Utamakan M4A (format bisa berbeda)")
        mp3_idx = self.quality_combo.findData("mp3")
        if mp3_idx >= 0:
            self.quality_combo.setItemText(mp3_idx, "MP3 (konversi kompatibilitas)")

        self.review_btn = QPushButton("Tinjau Kandidat Ragu")
        self.review_btn.clicked.connect(self.review_uncertain)
        self.statusBar().addPermanentWidget(self.review_btn)
        self.table.cellDoubleClicked.connect(lambda row, _column: self.review_uncertain(row))

    def _open_queue_repository(self) -> None:
        try:
            self.queue_repo = QueueRepository()
            restored = self.queue_repo.restore_queue()
        except QueueStorageError as exc:
            self.queue_repo = None
            self.log(f"Peringatan: antrean berjalan tanpa persistensi SQLite. {exc}")
            return

        if not restored:
            return
        BaseMainWindow._append_tracks(self, restored)
        interrupted = sum(1 for track in restored if track.status == TrackStatus.INTERRUPTED)
        review = sum(1 for track in restored if track.status == TrackStatus.NEEDS_REVIEW)
        suffix_parts = []
        if interrupted:
            suffix_parts.append(f"{interrupted} terinterupsi siap dilanjutkan")
        if review:
            suffix_parts.append(f"{review} perlu ditinjau")
        suffix = f" • {' • '.join(suffix_parts)}" if suffix_parts else ""
        self.log(f"Memulihkan {len(restored)} item dari antrean sebelumnya{suffix}.")

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
            self._append_tracks(result.tracks)
        elif not result.cancelled:
            self.log("Tidak ada item valid yang berhasil diimpor.")

        if result.issues:
            self.log(
                f"Import selesai dengan {len(result.issues)} item gagal; item valid tetap dipertahankan."
            )
        if result.cancelled:
            self.log("Import dibatalkan.")

    def _append_tracks(self, tracks: list[TrackRequest]) -> None:
        if not tracks:
            return
        items = tracks
        duplicates = []
        if self.queue_repo is not None:
            try:
                result = self.queue_repo.add_tracks(tracks)
                items = result.added
                duplicates = result.duplicates
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi: {exc}")

        if items:
            BaseMainWindow._append_tracks(self, items)
        if duplicates:
            done_duplicates = sum(1 for item in duplicates if item.status == TrackStatus.DONE.value)
            self.log(
                f"{len(duplicates)} duplikat tidak ditambahkan"
                + (f" • {done_duplicates} sudah pernah selesai" if done_duplicates else "")
                + "."
            )
        if not items and duplicates:
            self.input_text.clear()

    def _insert_track_row(self, track: TrackRequest) -> None:
        BaseMainWindow._insert_track_row(self, track)
        row = self.table.rowCount() - 1
        item = self.table.item(row, 0)
        if item is not None:
            item.setData(Qt.UserRole, track.job_id)
        if track.status == TrackStatus.NEEDS_REVIEW:
            self.table.setItem(row, 5, self._detail_item("Double-click atau klik Tinjau Kandidat Ragu"))

    @staticmethod
    def _detail_item(text: str):
        from PySide6.QtWidgets import QTableWidgetItem

        return QTableWidgetItem(text)

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
        if self.queue_worker and self.queue_worker.isRunning():
            QMessageBox.information(self, "Sedang download", "Stop download sebelum menghapus antrean.")
            return
        if self.import_worker and self.import_worker.isRunning():
            self.coordinator.invalidate_import()
            self._start_after_import_id = None
            self.import_worker.cancel()
            self.log("Import aktif dibatalkan; hasil terlambat akan diabaikan.")

        ids = [track.job_id for track in self.tracks]
        if ids and self.queue_repo is not None:
            try:
                self.queue_repo.remove_jobs(ids, detail="Antrean dikosongkan")
            except QueueStorageError as exc:
                self.log(str(exc))
                QMessageBox.warning(self, "Antrean tidak dapat dihapus", str(exc))
                return
        BaseMainWindow.clear_queue(self)

    def _save_download_settings(self) -> None:
        self.config.output_dir = resolve_output_dir(self.output_edit.text())
        self.output_edit.setText(self.config.output_dir)
        self.config.audio_mode = str(self.quality_combo.currentData())
        self.config.save()

    def open_output_folder(self) -> None:
        self.output_edit.setText(resolve_output_dir(self.output_edit.text()))
        super().open_output_folder()

    def _launch_tracks(self, pending: list[TrackRequest]) -> bool:
        if not pending:
            return False

        batch_id = uuid4().hex
        for track in pending:
            track.batch_id = batch_id
        if self.queue_repo is not None:
            try:
                self.queue_repo.checkpoint_many(pending, event="batch_queued")
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi: {exc}")

        try:
            self._save_download_settings()
        except ConfigSaveError as exc:
            self.log(str(exc))
            QMessageBox.warning(self, "Pengaturan tidak dapat disimpan", str(exc))
            return False

        self.gemini.model = self.config.gemini_model
        worker = QueueWorker(
            pending,
            self.config,
            self.gemini,
            parent=self,
            repository=self.queue_repo,
        )
        self.queue_worker = worker
        worker.item_changed.connect(self._on_item_changed)
        worker.log.connect(self.log)
        worker.finished_summary.connect(self._on_queue_finished)
        worker.finished.connect(self._queue_thread_finished)

        self.coordinator.begin_queue(batch_id)
        self.start_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self._paused = False
        self.pause_btn.setText("⏸ Jeda")
        self.log(f"Mulai download {len(pending)} item...")
        worker.start()
        return True

    def start_download(self) -> None:
        if self.coordinator.closing:
            return
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import selesai sebelum memulai download.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            return
        if not self.tracks:
            QMessageBox.information(self, "Antrean kosong", "Tambahkan lagu ke antrean terlebih dahulu.")
            return

        pending = [track for track in self.tracks if track.status in RUNNABLE_STATUSES]
        if not pending:
            if all(track.status == TrackStatus.DONE for track in self.tracks):
                QMessageBox.information(self, "Selesai", "Semua lagu di antrean sudah selesai.")
            elif any(track.status == TrackStatus.NEEDS_REVIEW for track in self.tracks):
                self.log("Ada item Perlu Ditinjau. Pilih kandidatnya sebelum melanjutkan item tersebut.")
            else:
                self.log("Tidak ada item menunggu. Gunakan Retry Gagal untuk item gagal/dibatalkan.")
            return
        self._launch_tracks(pending)

    def _start_job_ids(self, job_ids: set[str]) -> None:
        if not job_ids:
            return
        pending = [
            track
            for track in self.tracks
            if track.job_id in job_ids and track.status in RUNNABLE_STATUSES
        ]
        self._launch_tracks(pending)

    def _on_item_changed(self, job_id, status: str, progress: float, detail: str) -> None:
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

    def _on_queue_finished(self, done: int, failed: int, cancelled: int) -> None:
        BaseMainWindow._on_queue_finished(self, done, failed, cancelled)
        review = sum(1 for track in self.tracks if track.status == TrackStatus.NEEDS_REVIEW)
        if review:
            self.log(f"{review} item belum diunduh karena kandidat perlu ditinjau.")
            self.header_status.setText(f"Antrean selesai • {review} perlu ditinjau")

    def _queue_thread_finished(self) -> None:
        batch_id = self.coordinator.queue_batch_id
        BaseMainWindow._queue_thread_finished(self)
        if batch_id is not None:
            self.coordinator.finish_queue(batch_id)

    def review_uncertain(self, row: int | None = None) -> bool:
        if self.coordinator.closing:
            return False
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Tinjau kandidat setelah antrean aktif selesai agar pilihan tidak bertabrakan.")
            return False

        track: TrackRequest | None = None
        if isinstance(row, int) and 0 <= row < len(self.tracks):
            candidate_track = self.tracks[row]
            if candidate_track.status == TrackStatus.NEEDS_REVIEW:
                track = candidate_track
        if track is None:
            track = next(
                (item for item in self.tracks if item.status == TrackStatus.NEEDS_REVIEW),
                None,
            )
        if track is None:
            self.log("Tidak ada item yang perlu ditinjau.")
            return False

        candidates = track.metadata.get("review_candidates") or []
        if not isinstance(candidates, list) or not candidates:
            QMessageBox.warning(
                self,
                "Kandidat tidak tersedia",
                "Data kandidat tidak tersedia. Gunakan Retry Gagal setelah menghapus pilihan lama jika diperlukan.",
            )
            return False

        dialog = CandidateReviewDialog(track.display_name, candidates, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() != QDialog.Accepted:
            return False
        selected = dialog.selected_candidate()
        if not selected:
            return False

        url = str(selected.get("url") or "").strip()
        if not url:
            return False
        track.resolved_url = url
        track.resolved_title = str(selected.get("title") or track.display_name)
        track.metadata["match_state"] = "MATCHED_USER"
        track.metadata["match_score"] = float(selected.get("score") or 0.0)
        track.metadata["matched_channel"] = str(selected.get("uploader") or "")
        track.metadata["matched_versions"] = selected.get("versions") or []
        track.metadata.pop("review_candidates", None)
        track.status = TrackStatus.QUEUED
        track.progress = 0.0
        track.error = ""
        track.error_code = ""
        track.error_retryable = False

        if self.queue_repo is not None:
            try:
                self.queue_repo.checkpoint(
                    track,
                    event="review_resolved",
                    detail=f"Kandidat dipilih pengguna: {track.resolved_title}",
                )
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi review: {exc}")
        self._on_item_changed(track.job_id, TrackStatus.QUEUED.value, 0.0, "Kandidat dikonfirmasi; siap diunduh")
        self.log(f"Kandidat dikonfirmasi: {track.display_name} → {track.resolved_title}")
        return True

    def retry_failed(self) -> None:
        if self.coordinator.closing:
            return
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import selesai sebelum retry.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Antrean masih berjalan; retry ditunda.")
            return

        targets = [track for track in self.tracks if track.status in RETRYABLE_BY_USER_STATUSES]
        target_ids = {track.job_id for track in targets}
        if not targets:
            self.log("Tidak ada item gagal untuk di-retry.")
            return

        for track in targets:
            track.status = TrackStatus.QUEUED
            track.progress = 0.0
            track.error = ""
            track.error_code = ""
            track.error_retryable = False
            self._on_item_changed(track.job_id, TrackStatus.QUEUED.value, 0.0, "Siap dicoba lagi")

        if self.queue_repo is not None:
            try:
                self.queue_repo.record_retry_requested(target_ids)
                self.queue_repo.checkpoint_many(targets)
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi retry: {exc}")

        self.log(f"{len(targets)} item gagal disiapkan untuk retry berdasarkan job ID.")
        self._start_job_ids(target_ids)

    def remove_jobs(self, job_ids: set[str]) -> int:
        """Remove exactly the requested jobs; never infer scope from row numbers."""
        if not job_ids or self.coordinator.closing:
            return 0
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import selesai sebelum menghapus item.")
            return 0
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Hentikan antrean sebelum menghapus item.")
            return 0

        existing = {track.job_id for track in self.tracks}
        targets = existing.intersection(job_ids)
        if not targets:
            return 0

        if self.queue_repo is not None:
            try:
                self.queue_repo.remove_jobs(targets)
            except QueueStorageError as exc:
                self.log(str(exc))
                return 0

        self.tracks = [track for track in self.tracks if track.job_id not in targets]
        self._rebuild_queue_table()
        if self.queue_repo is not None:
            try:
                self.queue_repo.reorder(track.job_id for track in self.tracks)
            except QueueStorageError as exc:
                self.log(f"Peringatan urutan antrean: {exc}")
        self.log(f"{len(targets)} item dihapus dari antrean.")
        return len(targets)

    def reorder_jobs(self, ordered_job_ids: list[str]) -> bool:
        """Persist a full active ordering by stable job IDs."""
        if self.coordinator.closing:
            return False
        if self.import_worker and self.import_worker.isRunning():
            return False
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Urutan tidak dapat diubah saat download berjalan.")
            return False

        current_ids = [track.job_id for track in self.tracks]
        if len(ordered_job_ids) != len(current_ids) or set(ordered_job_ids) != set(current_ids):
            return False
        mapping = {track.job_id: track for track in self.tracks}
        self.tracks = [mapping[job_id] for job_id in ordered_job_ids]
        self._rebuild_queue_table()

        if self.queue_repo is not None:
            try:
                self.queue_repo.reorder(ordered_job_ids)
            except QueueStorageError as exc:
                self.log(str(exc))
                return False
        return True

    def _rebuild_queue_table(self) -> None:
        self.table.setRowCount(0)
        for position, track in enumerate(self.tracks, start=1):
            track.index = position
            self._insert_track_row(track)
        self.count_label.setText(f"{len(self.tracks)} lagu")
        self._update_total_progress()

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
