from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from app.config import AppConfig
from app.models import TrackRequest, TrackStatus
from app.services.gemini_agent import GeminiAgent
from app.version import version_text
from app.workers import ImportWorker, QueueWorker


APP_STYLE = """
QMainWindow, QWidget {
    background: #111318;
    color: #e9edf5;
    font-family: "Segoe UI";
    font-size: 12px;
}
QFrame#card {
    background: #181c23;
    border: 1px solid #2a303a;
    border-radius: 12px;
}
QLabel#title {
    font-size: 22px;
    font-weight: 700;
}
QLabel#muted { color: #8e98a8; }
QLabel#section {
    font-size: 13px;
    font-weight: 700;
}
QLineEdit, QPlainTextEdit, QComboBox, QTableWidget {
    background: #0f1217;
    border: 1px solid #303744;
    border-radius: 8px;
    padding: 7px;
    selection-background-color: #5b7cfa;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #5b7cfa;
}
QPushButton {
    background: #252b35;
    border: 1px solid #363e4b;
    border-radius: 8px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover { background: #303744; }
QPushButton#primary {
    background: #5b7cfa;
    border: 1px solid #6b89ff;
    color: white;
}
QPushButton#danger {
    background: #3a2024;
    border: 1px solid #643039;
}
QHeaderView::section {
    background: #181c23;
    color: #aeb7c5;
    border: none;
    border-bottom: 1px solid #303744;
    padding: 8px;
    font-weight: 700;
}
QTableWidget {
    gridline-color: #242a33;
}
QProgressBar {
    border: 1px solid #303744;
    border-radius: 6px;
    background: #0d1014;
    text-align: center;
    min-height: 18px;
}
QProgressBar::chunk {
    background: #5b7cfa;
    border-radius: 5px;
}
"""


class ApiKeysDialog(QDialog):
    def __init__(self, keys: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API Key Gemini")
        self.resize(620, 430)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Masukkan maksimal 100 API key, satu key per baris. "
            "Key disimpan lokal di config.json pada folder aplikasi."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("AIza...\nAIza...\n...")
        self.editor.setPlainText("\n".join(keys))
        layout.addWidget(self.editor, 1)

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

    def keys(self) -> list[str]:
        return [x.strip() for x in self.editor.toPlainText().splitlines() if x.strip()][:100]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = AppConfig.load()
        self.gemini = GeminiAgent(self.config.gemini_api_keys, self.config.gemini_model)
        self.tracks: list[TrackRequest] = []
        self.import_worker: ImportWorker | None = None
        self.queue_worker: QueueWorker | None = None
        self._paused = False

        self.setWindowTitle(version_text())
        self.resize(1500, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._refresh_agent_status()

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        return frame

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("AI Music Downloader")
        title.setObjectName("title")
        subtitle = QLabel("Download massal • Best Audio • Gemini opsional")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.header_status = QLabel("Siap")
        self.header_status.setObjectName("muted")
        header.addWidget(self.header_status)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # LEFT: input and settings
        left = self._card()
        left.setMinimumWidth(330)
        left.setMaximumWidth(390)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        sec = QLabel("MASUKKAN LAGU")
        sec.setObjectName("section")
        left_layout.addWidget(sec)

        self.input_text = QPlainTextEdit()
        self.input_text.setPlaceholderText(
            "Satu item per baris:\n\n"
            "https://open.spotify.com/playlist/...\n"
            "https://youtube.com/playlist?...\n"
            "Artis - Judul Lagu\n"
            "Artis - Judul Lagu 2"
        )
        self.input_text.setMinimumHeight(260)
        left_layout.addWidget(self.input_text)

        input_actions = QHBoxLayout()
        self.add_btn = QPushButton("Tambah ke Antrean")
        self.add_btn.setObjectName("primary")
        clear_input_btn = QPushButton("Kosongkan")
        self.add_btn.clicked.connect(self.import_input)
        clear_input_btn.clicked.connect(self.input_text.clear)
        input_actions.addWidget(self.add_btn, 1)
        input_actions.addWidget(clear_input_btn)
        left_layout.addLayout(input_actions)

        settings_label = QLabel("PENGATURAN DOWNLOAD")
        settings_label.setObjectName("section")
        left_layout.addWidget(settings_label)

        form = QFormLayout()
        form.setSpacing(8)

        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Original / Best Audio", "original")
        self.quality_combo.addItem("M4A source preferred", "m4a")
        self.quality_combo.addItem("MP3 high quality", "mp3")
        idx = self.quality_combo.findData(self.config.audio_mode)
        self.quality_combo.setCurrentIndex(max(0, idx))
        form.addRow("Kualitas", self.quality_combo)

        folder_wrap = QWidget()
        folder_row = QHBoxLayout(folder_wrap)
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(6)
        self.output_edit = QLineEdit(self.config.output_dir)
        browse = QPushButton("...")
        browse.setFixedWidth(40)
        browse.clicked.connect(self.choose_output_folder)
        folder_row.addWidget(self.output_edit, 1)
        folder_row.addWidget(browse)
        form.addRow("Folder", folder_wrap)
        left_layout.addLayout(form)

        quality_note = QLabel(
            "Original / Best Audio direkomendasikan karena tidak melakukan transcoding tambahan."
        )
        quality_note.setWordWrap(True)
        quality_note.setObjectName("muted")
        left_layout.addWidget(quality_note)
        left_layout.addStretch(1)

        body.addWidget(left)

        # CENTER: queue
        center = self._card()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(14, 14, 14, 14)
        center_layout.setSpacing(10)

        queue_head = QHBoxLayout()
        queue_title = QLabel("ANTREAN DOWNLOAD")
        queue_title.setObjectName("section")
        self.count_label = QLabel("0 lagu")
        self.count_label.setObjectName("muted")
        clear_queue_btn = QPushButton("Hapus Antrean")
        clear_queue_btn.clicked.connect(self.clear_queue)
        queue_head.addWidget(queue_title)
        queue_head.addWidget(self.count_label)
        queue_head.addStretch(1)
        queue_head.addWidget(clear_queue_btn)
        center_layout.addLayout(queue_head)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "Lagu", "Artis", "Status", "Progres", "Pesan"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        center_layout.addWidget(self.table, 1)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Mulai Download")
        self.start_btn.setObjectName("primary")
        self.pause_btn = QPushButton("Jeda")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.retry_btn = QPushButton("Retry Gagal")
        self.start_btn.clicked.connect(self.start_download)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn.clicked.connect(self.stop_download)
        self.retry_btn.clicked.connect(self.retry_failed)
        controls.addWidget(self.start_btn)
        controls.addWidget(self.pause_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.retry_btn)
        controls.addStretch(1)
        center_layout.addLayout(controls)

        body.addWidget(center, 1)

        # RIGHT: Gemini agent
        right = self._card()
        right.setMinimumWidth(310)
        right.setMaximumWidth(370)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        agent_head = QHBoxLayout()
        agent_title = QLabel("AGEN AI GEMINI")
        agent_title.setObjectName("section")
        self.agent_status = QLabel("Tidak aktif")
        self.agent_status.setObjectName("muted")
        agent_head.addWidget(agent_title)
        agent_head.addStretch(1)
        agent_head.addWidget(self.agent_status)
        right_layout.addLayout(agent_head)

        agent_info = QLabel(
            "Gemini hanya membantu memahami perintah bahasa manusia atau memilih kandidat sulit. "
            "Download tetap menggunakan yt-dlp."
        )
        agent_info.setWordWrap(True)
        agent_info.setObjectName("muted")
        right_layout.addWidget(agent_info)

        self.agent_input = QPlainTextEdit()
        self.agent_input.setPlaceholderText(
            "Contoh:\n"
            "Download semua lagu di antrean sebagai best audio\n\n"
            "atau:\n"
            "Retry yang gagal dan pakai MP3"
        )
        self.agent_input.setMinimumHeight(180)
        right_layout.addWidget(self.agent_input)

        run_agent = QPushButton("Jalankan Perintah")
        run_agent.setObjectName("primary")
        run_agent.clicked.connect(self.run_agent_command)
        right_layout.addWidget(run_agent)

        key_row = QHBoxLayout()
        keys_btn = QPushButton("API Key")
        test_btn = QPushButton("Tes Gemini")
        keys_btn.clicked.connect(self.edit_api_keys)
        test_btn.clicked.connect(self.test_gemini)
        key_row.addWidget(keys_btn)
        key_row.addWidget(test_btn)
        right_layout.addLayout(key_row)

        self.agent_log = QPlainTextEdit()
        self.agent_log.setReadOnly(True)
        self.agent_log.setPlaceholderText("Log agen Gemini akan muncul di sini.")
        right_layout.addWidget(self.agent_log, 1)

        body.addWidget(right)

    def _append_log(self, text: str) -> None:
        self.agent_log.appendPlainText(text)

    def _refresh_agent_status(self) -> None:
        if self.gemini.enabled:
            self.agent_status.setText(f"Aktif • {len(self.config.gemini_api_keys)} key")
        else:
            self.agent_status.setText("Tidak aktif")

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pilih folder output", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def import_input(self) -> None:
        text = self.input_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Info", "Masukkan judul lagu atau URL terlebih dahulu.")
            return

        self.header_status.setText("Membaca input...")
        self.add_btn.setEnabled(False)
        self.import_worker = ImportWorker(text)
        self.import_worker.tracks_ready.connect(self._append_tracks)
        self.import_worker.error.connect(self._show_error)
        self.import_worker.finished.connect(lambda: self.add_btn.setEnabled(True))
        self.import_worker.start()

    def _append_tracks(self, tracks: list) -> None:
        for track in tracks:
            self.tracks.append(track)
            self._append_row(track)
        self.count_label.setText(f"{len(self.tracks)} lagu")
        self.header_status.setText("Siap")
        self.input_text.clear()

    def _append_row(self, track: TrackRequest) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table.setItem(row, 1, QTableWidgetItem(track.title))
        self.table.setItem(row, 2, QTableWidgetItem(track.artist))
        self.table.setItem(row, 3, QTableWidgetItem(track.status.value))

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        self.table.setCellWidget(row, 4, bar)
        self.table.setItem(row, 5, QTableWidgetItem(""))

    def clear_queue(self) -> None:
        if self.queue_worker and self.queue_worker.isRunning():
            QMessageBox.warning(self, "Sedang berjalan", "Stop download sebelum menghapus antrean.")
            return
        self.tracks.clear()
        self.table.setRowCount(0)
        self.count_label.setText("0 lagu")

    def start_download(self) -> None:
        if self.queue_worker and self.queue_worker.isRunning():
            return
        if not self.tracks:
            QMessageBox.information(self, "Info", "Antrean masih kosong.")
            return

        self.config.output_dir = self.output_edit.text().strip() or "downloads"
        self.config.audio_mode = str(self.quality_combo.currentData())
        self.config.save()

        self.queue_worker = QueueWorker(self.tracks, self.config)
        self.queue_worker.item_changed.connect(self._on_item_changed)
        self.queue_worker.error.connect(self._show_error)
        self.queue_worker.finished.connect(self._queue_finished)
        self.queue_worker.start()
        self.header_status.setText("Download berjalan")
        self.start_btn.setEnabled(False)

    def toggle_pause(self) -> None:
        if not self.queue_worker or not self.queue_worker.isRunning():
            return
        self._paused = not self._paused
        self.queue_worker.set_paused(self._paused)
        self.pause_btn.setText("Lanjutkan" if self._paused else "Jeda")
        self.header_status.setText("Dijeda" if self._paused else "Download berjalan")

    def stop_download(self) -> None:
        if self.queue_worker and self.queue_worker.isRunning():
            self.queue_worker.stop()
            self.header_status.setText("Menghentikan...")

    def retry_failed(self) -> None:
        for track in self.tracks:
            if track.status == TrackStatus.FAILED:
                track.status = TrackStatus.PENDING
                track.progress = 0
                track.message = ""
        self._sync_table()

    def _queue_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.pause_btn.setText("Jeda")
        self._paused = False
        self.header_status.setText("Selesai")

    def _on_item_changed(self, index: int, status: str, progress: float, message: str) -> None:
        if index < 0 or index >= len(self.tracks):
            return
        self.table.setItem(index, 3, QTableWidgetItem(status))
        bar = self.table.cellWidget(index, 4)
        if isinstance(bar, QProgressBar):
            bar.setValue(max(0, min(100, int(progress))))
        self.table.setItem(index, 5, QTableWidgetItem(message))

    def _sync_table(self) -> None:
        for i, track in enumerate(self.tracks):
            self.table.setItem(i, 3, QTableWidgetItem(track.status.value))
            bar = self.table.cellWidget(i, 4)
            if isinstance(bar, QProgressBar):
                bar.setValue(track.progress)
            self.table.setItem(i, 5, QTableWidgetItem(track.message))

    def edit_api_keys(self) -> None:
        dialog = ApiKeysDialog(self.config.gemini_api_keys, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.config.gemini_api_keys = dialog.keys()
        self.config.save()
        self.gemini = GeminiAgent(self.config.gemini_api_keys, self.config.gemini_model)
        self._refresh_agent_status()
        self._append_log("API key diperbarui.")

    def test_gemini(self) -> None:
        if not self.gemini.enabled:
            QMessageBox.information(self, "Gemini", "Belum ada API key Gemini.")
            return
        self._append_log("Menguji Gemini...")
        try:
            data = self.gemini.parse_command("gunakan kualitas original dan jalankan")
            self._append_log(f"Tes berhasil: {data}")
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"Tes gagal: {exc}")

    def run_agent_command(self) -> None:
        command = self.agent_input.toPlainText().strip()
        if not command:
            return
        if not self.gemini.enabled:
            QMessageBox.information(self, "Gemini", "Masukkan API key Gemini terlebih dahulu.")
            return

        self._append_log(f"> {command}")
        try:
            plan = self.gemini.parse_command(command)
        except Exception as exc:  # noqa: BLE001
            self._append_log(f"Perintah gagal: {exc}")
            return

        quality = plan.get("quality")
        if quality in {"original", "m4a", "mp3"}:
            idx = self.quality_combo.findData(quality)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)

        if plan.get("retry_failed"):
            self.retry_failed()
        if plan.get("start"):
            self.start_download()
        self._append_log(f"Rencana: {plan}")

    def _show_error(self, message: str) -> None:
        self.header_status.setText("Ada error")
        QMessageBox.warning(self, "Error", message)
