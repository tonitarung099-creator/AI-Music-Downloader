from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from app.config import ConfigSaveError, app_root
from app.models import TrackStatus
from app.services.secure_keys import WindowsDpapiKeyStore
from app.storage import QueueStorageError
from app.ui.main_window_v3 import MainWindow as Stage4MainWindow
from app.ui.main_window_v3 import MaskedApiKeysDialog
from app.ui.stage5 import Stage5UiMixin


class SecureApiKeysDialog(MaskedApiKeysDialog):
    def __init__(
        self,
        keys: list[str],
        *,
        storage_mode: str,
        secure_available: bool,
        warning: str = "",
        parent=None,
    ) -> None:
        super().__init__(keys, parent)
        self.setWindowTitle("API Key Gemini")
        self.session_only = QCheckBox("Simpan hanya selama aplikasi ini berjalan")
        self.session_only.setChecked(storage_mode == "session" or not secure_available)
        if not secure_available:
            self.session_only.setEnabled(False)
            self.session_only.setToolTip("Penyimpanan terenkripsi Windows DPAPI tidak tersedia pada sistem ini.")
        self.layout().insertWidget(2, self.session_only)

        if secure_available:
            storage_note = QLabel(
                "Jika mode sesi dimatikan, key disimpan terenkripsi dengan Windows DPAPI. "
                "Folder portable tetap bisa dipindah pada akun Windows yang sama, tetapi key dapat "
                "perlu dimasukkan ulang bila dipindah ke komputer atau akun Windows lain."
            )
        else:
            storage_note = QLabel(
                "Penyimpanan terenkripsi Windows tidak tersedia. Key hanya digunakan selama sesi ini."
            )
        storage_note.setWordWrap(True)
        storage_note.setObjectName("muted")
        self.layout().insertWidget(3, storage_note)

        if warning:
            warning_label = QLabel(warning)
            warning_label.setWordWrap(True)
            warning_label.setObjectName("muted")
            self.layout().insertWidget(4, warning_label)

        tools = QHBoxLayout()
        import_btn = QPushButton("Impor TXT")
        export_btn = QPushButton("Ekspor Daftar Tersamar")
        import_btn.clicked.connect(self.import_keys)
        export_btn.clicked.connect(self.export_masked_keys)
        tools.addWidget(import_btn)
        tools.addWidget(export_btn)
        tools.addStretch(1)
        self.layout().insertLayout(self.layout().count() - 1, tools)

    def storage_mode(self) -> str:
        return "session" if self.session_only.isChecked() else "windows_dpapi"

    def import_keys(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Impor API Key Gemini",
            str(app_root()),
            "Teks (*.txt);;Semua File (*)",
        )
        if not filename:
            return
        try:
            lines = Path(filename).read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "Impor gagal", str(exc))
            return
        current = self.keys()
        self._working_keys = self._clean(current + lines)
        if self._revealed:
            self.editor.setPlainText("\n".join(self._working_keys))
        else:
            self._show_masked()

    def export_masked_keys(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Ekspor Daftar API Key Tersamar",
            str(app_root() / "data" / "gemini-keys-masked.txt"),
            "Teks (*.txt)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".txt":
            path = path.with_suffix(".txt")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(self._mask(key) for key in self.keys()) + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Ekspor gagal", str(exc))
            return
        QMessageBox.information(
            self,
            "Ekspor selesai",
            "Daftar tersamar berhasil disimpan. File ekspor tidak memuat API key lengkap.",
        )


class MainWindow(Stage5UiMixin, Stage4MainWindow):
    """Single production facade for the tested Stage 1-5 behavior stack."""

    def __init__(self) -> None:
        super().__init__()
        self.pause_btn.setText("Lanjutkan" if self._paused else "Jeda")
        self._refresh_agent_status()
        self.apply_queue_filter()
        self._install_selected_retry_action()

    def _install_selected_retry_action(self) -> None:
        self.retry_selected_btn = QPushButton("Coba Lagi Terpilih", self)
        self.retry_selected_btn.setToolTip(
            "Mencoba lagi hanya lagu gagal/dibatalkan yang sedang dipilih, berdasarkan job ID."
        )
        self.retry_selected_btn.clicked.connect(self.retry_selected_failed)
        toolbar = self.remove_selected_btn.parentWidget()
        if toolbar is not None and toolbar.layout() is not None:
            action_item = toolbar.layout().itemAt(1)
            action_layout = action_item.layout() if action_item is not None else None
            if action_layout is not None:
                action_layout.insertWidget(1, self.retry_selected_btn)
                return
        self.statusBar().addPermanentWidget(self.retry_selected_btn)

    def retry_selected_failed(self) -> None:
        if self.coordinator.closing:
            return
        if self.import_worker and self.import_worker.isRunning():
            self.log("Tunggu import selesai sebelum mencoba lagi item terpilih.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            self.log("Antrean masih berjalan; hentikan atau tunggu selesai sebelum retry terpilih.")
            return

        selected_ids = self._selected_job_ids()
        if not selected_ids:
            QMessageBox.information(
                self,
                "Belum ada pilihan",
                "Pilih satu atau beberapa item Gagal/Dibatalkan yang ingin dicoba lagi.",
            )
            return
        targets = [
            track
            for track in self.tracks
            if track.job_id in selected_ids
            and track.status in {TrackStatus.FAILED, TrackStatus.CANCELLED}
        ]
        if not targets:
            QMessageBox.information(
                self,
                "Tidak ada target retry",
                "Item yang dipilih tidak berstatus Gagal atau Dibatalkan.",
            )
            return

        target_ids = {track.job_id for track in targets}
        for track in targets:
            track.status = TrackStatus.QUEUED
            track.progress = 0.0
            track.error = ""
            track.error_code = ""
            track.error_retryable = False
            self._on_item_changed(
                track.job_id,
                TrackStatus.QUEUED.value,
                0.0,
                "Siap dicoba lagi",
            )

        if self.queue_repo is not None:
            try:
                self.queue_repo.record_retry_requested(target_ids)
                self.queue_repo.checkpoint_many(targets, event="retry_selected")
            except QueueStorageError as exc:
                self.log(f"Peringatan persistensi retry terpilih: {exc}")

        self.log(f"Mencoba lagi {len(targets)} item terpilih berdasarkan job ID.")
        self._start_job_ids(target_ids)

    def manage_api_keys(self) -> None:
        secure_store = WindowsDpapiKeyStore()
        dialog = SecureApiKeysDialog(
            self.config.gemini_api_keys,
            storage_mode=self.config.gemini_key_storage,
            secure_available=secure_store.available,
            warning=self.config.key_storage_warning,
            parent=self,
        )
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() != QDialog.Accepted:
            return

        self.config.gemini_api_keys = dialog.keys()
        self.config.gemini_key_storage = dialog.storage_mode()
        try:
            self.config.save()
        except ConfigSaveError as exc:
            QMessageBox.warning(self, "API key tidak dapat disimpan", str(exc))
            return

        self.gemini.update_keys(self.config.gemini_api_keys)
        self._set_model_controls_enabled(self.gemini.available)
        self._refresh_agent_status()
        if self.config.gemini_key_storage == "windows_dpapi":
            self.log(
                f"Gemini: {len(self.config.gemini_api_keys)} API key tersimpan terenkripsi dengan Windows DPAPI."
            )
        else:
            self.log(
                f"Gemini: {len(self.config.gemini_api_keys)} API key aktif hanya untuk sesi ini; tidak ditulis ke config.json."
            )

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
            storage = (
                "DPAPI Windows"
                if getattr(self.config, "gemini_key_storage", "session") == "windows_dpapi"
                else "hanya sesi"
            )
            extra.append(storage)
            suffix = f" • {' • '.join(extra)}" if extra else ""
            self.agent_status.setText(
                f"● Aktif • {diagnostics['total']} API key • {self.gemini.model}{suffix}"
            )
        else:
            self.agent_status.setText("○ Opsional • belum ada API key Gemini")

    def toggle_pause(self) -> None:
        super().toggle_pause()
        self.pause_btn.setText("Lanjutkan" if self._paused else "Jeda")

    def _queue_thread_finished(self) -> None:
        super()._queue_thread_finished()
        self.pause_btn.setText("Jeda")
