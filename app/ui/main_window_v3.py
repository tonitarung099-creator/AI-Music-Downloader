from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.agent_worker import AgentCommandWorker, GeminiModelWorker
from app.config import ConfigSaveError
from app.models import TrackRequest, TrackStatus
from app.services.gemini_agent import CommandIntent, CommandPlan
from app.storage import QueueStorageError
from app.ui.main_window_v2 import MainWindow as BaseMainWindow
from app.workers import ImportResult


class MaskedApiKeysDialog(QDialog):
    """Keep saved keys masked until the user explicitly chooses to reveal them."""

    def __init__(self, keys: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API Key Gemini")
        self.resize(620, 450)
        self._working_keys = self._clean(keys)
        self._revealed = False

        layout = QVBoxLayout(self)
        info = QLabel(
            "Maksimal 100 API key, satu per baris. Key tersimpan disembunyikan secara default. "
            "Klik Tampilkan key hanya bila memang perlu mengeditnya."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        self.reveal = QCheckBox("Tampilkan key tersimpan")
        self.reveal.toggled.connect(self._toggle_reveal)
        layout.addWidget(self.reveal)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("AIza...\nAIza...\n...")
        layout.addWidget(self.editor, 1)
        self._show_masked()

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Batal")
        save = QPushButton("Simpan")
        save.setObjectName("primary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

    @staticmethod
    def _clean(keys: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in keys:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
            if len(result) >= 100:
                break
        return result

    @staticmethod
    def _mask(key: str) -> str:
        if len(key) <= 8:
            return "•" * max(6, len(key))
        return f"{key[:4]}{'•' * 12}{key[-4:]}"

    def _show_masked(self) -> None:
        self.editor.setReadOnly(True)
        self.editor.setPlainText("\n".join(self._mask(key) for key in self._working_keys))
        self._revealed = False

    def _toggle_reveal(self, checked: bool) -> None:
        if checked:
            self.editor.setReadOnly(False)
            self.editor.setPlainText("\n".join(self._working_keys))
            self._revealed = True
            return
        if self._revealed:
            self._working_keys = self._clean(self.editor.toPlainText().splitlines())
        self._show_masked()

    def keys(self) -> list[str]:
        if self._revealed:
            self._working_keys = self._clean(self.editor.toPlainText().splitlines())
        return list(self._working_keys)


class MainWindow(BaseMainWindow):
    """Production UI layer with controlled Gemini and coordinated shutdown."""

    def __init__(self) -> None:
        self._agent_import_preferences: dict[str, dict[str, list[str]]] = {}
        self._model_worker: GeminiModelWorker | None = None
        self._discovered_models: set[str] = set()
        super().__init__()
        self.agent_worker: AgentCommandWorker | None = None
        self._allow_close = False
        self._shutdown_poll_scheduled = False
        self._configure_stage4_gemini_ui()

        # v2 installs candidate review on double-click. Production v3 broadens
        # the gesture: review uncertain rows, or open a verified completed file.
        try:
            self.table.cellDoubleClicked.disconnect()
        except RuntimeError:
            pass
        self.table.cellDoubleClicked.connect(self._handle_row_double_click)

    def _configure_stage4_gemini_ui(self) -> None:
        self.model_combo = QComboBox(self)
        self.model_combo.setMinimumWidth(190)
        self.model_combo.addItem(self.config.gemini_model)
        self.model_combo.setToolTip("Model Gemini. Gunakan Muat Model untuk mengambil model generateContent yang tersedia.")
        self.model_combo.activated.connect(lambda _index: self._model_selected())

        self.model_refresh_btn = QPushButton("Muat Model", self)
        self.model_refresh_btn.clicked.connect(self.refresh_gemini_models)
        self.model_test_btn = QPushButton("Tes Gemini", self)
        self.model_test_btn.clicked.connect(self.test_gemini_connection)

        self.statusBar().addPermanentWidget(QLabel("Model Gemini:"))
        self.statusBar().addPermanentWidget(self.model_combo)
        self.statusBar().addPermanentWidget(self.model_refresh_btn)
        self.statusBar().addPermanentWidget(self.model_test_btn)
        self._set_model_controls_enabled(self.gemini.available)

    def _refresh_agent_status(self) -> None:
        if not hasattr(self, "gemini") or not hasattr(self, "agent_status"):
            return
        if self.gemini.available:
            diagnostics = self.gemini.key_diagnostics()
            extra = []
            if diagnostics["cooldown"]:
                extra.append(f"{diagnostics['cooldown']} cooldown")
            if diagnostics["disabled"]:
                extra.append(f"{diagnostics['disabled']} ditolak")
            suffix = f" • {' • '.join(extra)}" if extra else ""
            self.agent_status.setText(
                f"● Aktif • {diagnostics['total']} API key • {self.gemini.model}{suffix}"
            )
        else:
            self.agent_status.setText("○ Opsional • belum ada API key Gemini")

    def manage_api_keys(self) -> None:
        dialog = MaskedApiKeysDialog(self.config.gemini_api_keys, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() != QDialog.Accepted:
            return
        self.config.gemini_api_keys = dialog.keys()
        try:
            self.config.save()
        except ConfigSaveError as exc:
            QMessageBox.warning(self, "API key tidak dapat disimpan", str(exc))
            return
        self.gemini.update_keys(self.config.gemini_api_keys)
        self._set_model_controls_enabled(self.gemini.available)
        self._refresh_agent_status()
        self.log(f"Gemini: {len(self.config.gemini_api_keys)} API key tersimpan.")

    def _set_model_controls_enabled(self, enabled: bool) -> None:
        if hasattr(self, "model_combo"):
            self.model_combo.setEnabled(enabled)
            self.model_refresh_btn.setEnabled(enabled)
            self.model_test_btn.setEnabled(enabled)

    def _model_selected(self) -> None:
        selected = str(self.model_combo.currentText() or "").strip()
        if not selected:
            return
        if self._discovered_models and selected not in self._discovered_models:
            self.log("Model tersimpan belum tervalidasi pada daftar terbaru. Jalankan Tes Gemini sebelum digunakan.")
            return
        self.gemini.model = selected
        self.config.gemini_model = selected
        try:
            self.config.save()
        except ConfigSaveError as exc:
            self.log(str(exc))
            return
        self._refresh_agent_status()
        self.log(f"Model Gemini dipilih: {selected}")

    def _can_run_model_operation(self) -> bool:
        if not self.gemini.available:
            QMessageBox.information(self, "Gemini belum aktif", "Masukkan API key Gemini terlebih dahulu.")
            return False
        if self.coordinator.closing:
            return False
        if self._model_worker and self._model_worker.isRunning():
            self.log("Operasi model Gemini sebelumnya masih berjalan...")
            return False
        if self.agent_worker and self.agent_worker.isRunning():
            self.log("Tunggu perintah Gemini aktif selesai sebelum menguji model.")
            return False
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Tunggu antrean download selesai sebelum menguji atau memuat model Gemini.")
            return False
        return True

    def refresh_gemini_models(self) -> None:
        if not self._can_run_model_operation():
            return
        worker = GeminiModelWorker(self.gemini, "list", parent=self)
        self._model_worker = worker
        self._set_model_controls_enabled(False)
        self.log("Mengambil daftar model Gemini yang mendukung generateContent...")
        worker.models_ready.connect(self._models_ready)
        worker.failed.connect(self._model_operation_failed)
        worker.finished.connect(lambda owned=worker: self._model_worker_finished(owned))
        worker.start()

    def test_gemini_connection(self) -> None:
        if not self._can_run_model_operation():
            return
        selected = str(self.model_combo.currentText() or self.config.gemini_model).strip()
        worker = GeminiModelWorker(self.gemini, "test", model=selected, parent=self)
        self._model_worker = worker
        self._set_model_controls_enabled(False)
        self.log(f"Menguji koneksi Gemini dengan model {selected}...")
        worker.test_ready.connect(lambda ok, message, model=selected: self._model_test_ready(ok, message, model))
        worker.failed.connect(self._model_operation_failed)
        worker.finished.connect(lambda owned=worker: self._model_worker_finished(owned))
        worker.start()

    def _models_ready(self, models: list[str]) -> None:
        clean = [str(model).strip() for model in models if str(model).strip()]
        self._discovered_models = set(clean)
        current = self.config.gemini_model
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if current and current not in self._discovered_models:
            self.model_combo.addItem(current)
        self.model_combo.addItems(clean)
        current_index = self.model_combo.findText(current)
        if current_index >= 0:
            self.model_combo.setCurrentIndex(current_index)
        self.model_combo.blockSignals(False)
        self.log(f"Gemini: {len(clean)} model generateContent tersedia.")

    def _model_test_ready(self, ok: bool, message: str, model: str) -> None:
        if not ok:
            return
        self.gemini.model = model
        self.config.gemini_model = model
        try:
            self.config.save()
        except ConfigSaveError as exc:
            self.log(str(exc))
            return
        self._refresh_agent_status()
        self.log(f"Tes Gemini berhasil • {model} • {message}")

    def _model_operation_failed(self, message: str) -> None:
        self._refresh_agent_status()
        self.log(f"Gemini: {message}")
        QMessageBox.warning(self, "Operasi Gemini gagal", message)

    def _model_worker_finished(self, worker: GeminiModelWorker) -> None:
        if self._model_worker is worker:
            self._model_worker = None
        worker.deleteLater()
        if not self.coordinator.closing:
            self._set_model_controls_enabled(self.gemini.available)

    def _handle_row_double_click(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.tracks):
            return
        track = self.tracks[row]
        if track.status == TrackStatus.NEEDS_REVIEW:
            self.review_uncertain(row)
            return
        if track.status != TrackStatus.DONE or not track.output_path:
            return

        target = Path(track.output_path).expanduser()
        try:
            valid = target.exists() and target.is_file() and target.stat().st_size > 0
        except OSError:
            valid = False
        if not valid:
            QMessageBox.warning(
                self,
                "File tidak ditemukan",
                "File audio yang tercatat tidak lagi tersedia di lokasi hasil download.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))

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
        if self._model_worker and self._model_worker.isRunning():
            self.log("Tunggu operasi model Gemini selesai terlebih dahulu.")
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
            lambda plan, command_id=worker.command_id: self._apply_agent_result(command_id, plan)
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

    @staticmethod
    def _plan_directives(plan: CommandPlan) -> dict[str, list[str]]:
        directives: dict[str, list[str]] = {}
        if plan.avoid_versions:
            directives["avoid_versions"] = list(plan.avoid_versions)
        if plan.prefer_versions:
            directives["prefer_versions"] = list(plan.prefer_versions)
        return directives

    def _apply_preferences_to_tracks(self, tracks: list[TrackRequest], plan: CommandPlan) -> None:
        directives = self._plan_directives(plan)
        if not directives:
            return
        for track in tracks:
            track.metadata.update(directives)
            if not track.direct_url:
                track.resolved_url = None
                track.resolved_title = None
                for key in (
                    "match_state",
                    "match_score",
                    "match_top_score",
                    "match_margin",
                    "match_reason",
                    "matched_channel",
                    "matched_versions",
                    "review_candidates",
                ):
                    track.metadata.pop(key, None)
        if tracks and self.queue_repo is not None:
            try:
                self.queue_repo.checkpoint_many(tracks, event="ai_preferences")
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi preferensi Gemini: {exc}")

    def _scope_tracks(self, plan: CommandPlan, statuses: set[TrackStatus]) -> list[TrackRequest]:
        target_ids = set(plan.target_job_ids)
        return [
            track
            for track in self.tracks
            if track.status in statuses and (not target_ids or track.job_id in target_ids)
        ]

    def _retry_plan_targets(self, plan: CommandPlan) -> None:
        targets = self._scope_tracks(plan, {TrackStatus.FAILED, TrackStatus.CANCELLED})
        if not targets:
            self.log("Gemini: tidak ada item gagal/dibatalkan yang cocok dengan scope retry.")
            return
        self._apply_preferences_to_tracks(targets, plan)
        target_ids = {track.job_id for track in targets}
        for track in targets:
            track.status = TrackStatus.QUEUED
            track.progress = 0.0
            track.error = ""
            track.error_code = ""
            track.error_retryable = False
            self._on_item_changed(track.job_id, TrackStatus.QUEUED.value, 0.0, "Siap dicoba lagi")
        if self.queue_repo is not None:
            try:
                self.queue_repo.checkpoint_many(targets, event="ai_retry")
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi retry Gemini: {exc}")
        self._start_job_ids(target_ids)

    def _apply_agent_result(self, command_id: str, plan: object) -> None:
        if not self.coordinator.is_current_agent(command_id):
            self.log("Hasil Gemini lama diabaikan karena operasi sudah berubah.")
            return
        if not isinstance(plan, CommandPlan):
            self.log("Respons Gemini ditolak karena bukan CommandPlan tervalidasi.")
            return

        if plan.intent is CommandIntent.UNKNOWN:
            self.log(f"Gemini: {plan.note or 'Perintah tidak termasuk action yang diizinkan; tidak ada perubahan.'}")
            return

        if plan.quality is not None:
            idx = self.quality_combo.findData(plan.quality)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)

        if plan.intent in {CommandIntent.ADD_ONLY, CommandIntent.ADD_AND_DOWNLOAD}:
            self.input_text.setPlainText("\n".join(plan.queries))
            import_id = self.import_input()
            if import_id:
                directives = self._plan_directives(plan)
                if directives:
                    self._agent_import_preferences[import_id] = directives
                if plan.intent is CommandIntent.ADD_AND_DOWNLOAD:
                    self._start_after_import_id = import_id
            self.log(f"Gemini: {plan.note or 'Daftar lagu tervalidasi dan siap diproses.'}")
            return

        if plan.intent is CommandIntent.DOWNLOAD_QUEUE:
            targets = self._scope_tracks(plan, {TrackStatus.QUEUED, TrackStatus.INTERRUPTED})
            if plan.target_job_ids and not targets:
                self.log("Gemini: target job tidak ditemukan atau tidak dalam status siap download.")
                return
            self._apply_preferences_to_tracks(targets, plan)
            self.log(f"Gemini: {plan.note or 'Menjalankan antrean sesuai scope.'}")
            if plan.target_job_ids:
                self._start_job_ids({track.job_id for track in targets})
            else:
                self.start_download()
            return

        if plan.intent is CommandIntent.RETRY_FAILED:
            self.log(f"Gemini: {plan.note or 'Mencoba lagi item gagal sesuai scope.'}")
            if plan.target_job_ids or plan.avoid_versions or plan.prefer_versions:
                self._retry_plan_targets(plan)
            else:
                self.retry_failed()
            return

    def _handle_import_result(self, result: ImportResult) -> None:
        directives = self._agent_import_preferences.get(result.import_id)
        if directives:
            for track in result.tracks:
                track.metadata.update(directives)
        super()._handle_import_result(result)

    def _import_thread_finished(self, import_id: str, worker) -> None:
        super()._import_thread_finished(import_id, worker)
        self._agent_import_preferences.pop(import_id, None)

    def _agent_failed(self, command_id: str, message: str) -> None:
        if not self.coordinator.is_current_agent(command_id):
            return
        self._refresh_agent_status()
        self.log(f"Gemini gagal: {message}")
        QMessageBox.warning(self, "Gemini gagal", message or "Tidak ada respons valid.")

    def _agent_finished(self, command_id: str, worker: AgentCommandWorker) -> None:
        was_current = self.coordinator.finish_agent(command_id)
        if self.agent_worker is worker:
            self.agent_worker = None
        worker.deleteLater()
        self._refresh_agent_status()
        if was_current and not self.coordinator.closing:
            self.agent_run_btn.setEnabled(True)

    def _running_workers(self) -> list[object]:
        workers = [self.import_worker, self.queue_worker, self.agent_worker, self._model_worker]
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
        self._set_model_controls_enabled(False)

        if self.import_worker and self.import_worker.isRunning():
            self.import_worker.cancel()
        if self.queue_worker and self.queue_worker.isRunning():
            self.queue_worker.stop()
        if self.agent_worker and self.agent_worker.isRunning():
            self.agent_worker.cancel()
        if self._model_worker and self._model_worker.isRunning():
            self._model_worker.cancel()

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
