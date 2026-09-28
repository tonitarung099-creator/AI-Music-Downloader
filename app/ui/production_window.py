from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QMessageBox

from app.config import ConfigSaveError
from app.services.secure_keys import WindowsDpapiKeyStore
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

    def storage_mode(self) -> str:
        return "session" if self.session_only.isChecked() else "windows_dpapi"


class MainWindow(Stage5UiMixin, Stage4MainWindow):
    """Single production facade for the tested Stage 1-5 behavior stack."""

    def __init__(self) -> None:
        super().__init__()
        self.pause_btn.setText("Lanjutkan" if self._paused else "Jeda")
        self._refresh_agent_status()

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
        if dialog.exec() != dialog.Accepted:
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
