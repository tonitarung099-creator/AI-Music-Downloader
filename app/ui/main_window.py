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

        self.setWindowTitle("AI Music Downloader")
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
        self.table.setHorizontalHeaderLabels(["#", "Lagu", "Sumber", "Status", "Progress", "Detail"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.Stretch)
        center_layout.addWidget(self.table, 1)

        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setValue(0)
        self.total_progress.setFormat("Total %p%")
        center_layout.addWidget(self.total_progress)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("▶ DOWNLOAD SEMUA")
        self.start_btn.setObjectName("primary")
        self.pause_btn = QPushButton("⏸ Jeda")
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("danger")
        open_btn = QPushButton("Buka Folder")
        retry_btn = QPushButton("Retry Gagal")

        self.start_btn.clicked.connect(self.start_download)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn.clicked.connect(self.stop_download)
        open_btn.clicked.connect(self.open_output_folder)
        retry_btn.clicked.connect(self.retry_failed)

        controls.addWidget(self.start_btn)
        controls.addWidget(self.pause_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        controls.addWidget(retry_btn)
        controls.addWidget(open_btn)
        center_layout.addLayout(controls)

        body.addWidget(center, 1)

        # RIGHT: Gemini agent and log
        right = self._card()
        right.setMinimumWidth(300)
        right.setMaximumWidth(360)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        agent_title = QLabel("GEMINI AGENT")
        agent_title.setObjectName("section")
        right_layout.addWidget(agent_title)

        self.agent_status = QLabel()
        self.agent_status.setWordWrap(True)
        right_layout.addWidget(self.agent_status)

        keys_btn = QPushButton("Kelola API Key")
        keys_btn.clicked.connect(self.manage_api_keys)
        right_layout.addWidget(keys_btn)

        self.agent_input = QPlainTextEdit()
        self.agent_input.setPlaceholderText(
            "Contoh:\n"
            "download semua lagu kualitas terbaik, jangan ambil live atau remix"
        )
        self.agent_input.setMinimumHeight(150)
        right_layout.addWidget(self.agent_input)

        self.agent_run_btn = QPushButton("Jalankan Perintah")
        self.agent_run_btn.setObjectName("primary")
        self.agent_run_btn.clicked.connect(self.run_agent_command)
        right_layout.addWidget(self.agent_run_btn)

        agent_note = QLabel(
            "Gemini hanya membantu memahami perintah dan matching sulit. "
            "Engine download tetap dapat berjalan tanpa AI."
        )
        agent_note.setWordWrap(True)
        agent_note.setObjectName("muted")
        right_layout.addWidget(agent_note)

        log_label = QLabel("LOG")
        log_label.setObjectName("section")
        right_layout.addWidget(log_label)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        right_layout.addWidget(self.log_box, 1)

        body.addWidget(right)

    def log(self, message: str) -> None:
        self.log_box.appendPlainText(message)
        self.header_status.setText(message[:90])

    def _refresh_agent_status(self) -> None:
        if self.gemini.available:
            self.agent_status.setText(f"● Aktif • {len(self.gemini.api_keys)} API key • {self.gemini.model}")
        else:
            self.agent_status.setText("○ Opsional • belum ada API key Gemini")

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pilih Folder Download", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def open_output_folder(self) -> None:
        path = Path(self.output_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def manage_api_keys(self) -> None:
        dlg = ApiKeysDialog(self.config.gemini_api_keys, self)
        dlg.setStyleSheet(APP_STYLE)
        if dlg.exec() == QDialog.Accepted:
            self.config.gemini_api_keys = dlg.keys()
            self.config.save()
            self.gemini.update_keys(self.config.gemini_api_keys)
            self._refresh_agent_status()
            self.log(f"Gemini: {len(self.config.gemini_api_keys)} API key tersimpan.")

    def import_input(self) -> None:
        text = self.input_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Input kosong", "Masukkan URL atau daftar judul lagu terlebih dahulu.")
            return
        if self.import_worker and self.import_worker.isRunning():
            return

        self.add_btn.setEnabled(False)
        self.log("Membaca input...")
        self.import_worker = ImportWorker(text, start_index=len(self.tracks) + 1, parent=self)
        self.import_worker.log.connect(self.log)
        self.import_worker.failed.connect(self._import_failed)
        self.import_worker.tracks_ready.connect(self._append_tracks)
        self.import_worker.finished.connect(lambda: self.add_btn.setEnabled(True))
        self.import_worker.start()

    def _import_failed(self, message: str) -> None:
        self.log(f"Gagal membaca input: {message}")
        QMessageBox.warning(self, "Gagal membaca input", message)

    def _append_tracks(self, tracks: list[TrackRequest]) -> None:
        if not tracks:
            self.log("Tidak ada item baru yang ditemukan.")
            return
        for track in tracks:
            self.tracks.append(track)
            self._insert_track_row(track)
        self.count_label.setText(f"{len(self.tracks)} lagu")
        self.log(f"{len(tracks)} lagu ditambahkan. Total: {len(self.tracks)}.")
        self.input_text.clear()
        self._update_total_progress()

    def _insert_track_row(self, track: TrackRequest) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(track.index)))
        self.table.setItem(row, 1, QTableWidgetItem(track.display_name))
        self.table.setItem(row, 2, QTableWidgetItem(track.source))
        self.table.setItem(row, 3, QTableWidgetItem(track.status.value))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(track.progress))
        bar.setTextVisible(True)
        self.table.setCellWidget(row, 4, bar)
        self.table.setItem(row, 5, QTableWidgetItem(""))

    def clear_queue(self) -> None:
        if self.queue_worker and self.queue_worker.isRunning():
            QMessageBox.information(self, "Sedang download", "Stop download sebelum menghapus antrean.")
            return
        self.tracks.clear()
        self.table.setRowCount(0)
        self.count_label.setText("0 lagu")
        self.total_progress.setValue(0)
        self.log("Antrean dikosongkan.")

    def _save_download_settings(self) -> None:
        self.config.output_dir = self.output_edit.text().strip() or str(Path.cwd() / "downloads")
        self.config.audio_mode = str(self.quality_combo.currentData())
        self.config.save()

    def start_download(self) -> None:
        if not self.tracks:
            QMessageBox.information(self, "Antrean kosong", "Tambahkan lagu ke antrean terlebih dahulu.")
            return
        if self.queue_worker and self.queue_worker.isRunning():
            return

        pending = [t for t in self.tracks if t.status != TrackStatus.DONE]
        if not pending:
            QMessageBox.information(self, "Selesai", "Semua lagu di antrean sudah selesai.")
            return

        self._save_download_settings()
        self.gemini.model = self.config.gemini_model
        self.queue_worker = QueueWorker(self.tracks, self.config, self.gemini, parent=self)
        self.queue_worker.item_changed.connect(self._on_item_changed)
        self.queue_worker.log.connect(self.log)
        self.queue_worker.finished_summary.connect(self._on_queue_finished)
        self.queue_worker.finished.connect(self._queue_thread_finished)
        self.start_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self._paused = False
        self.pause_btn.setText("⏸ Jeda")
        self.log(f"Mulai download {len(pending)} item...")
        self.queue_worker.start()

    def toggle_pause(self) -> None:
        if not self.queue_worker or not self.queue_worker.isRunning():
            return
        self._paused = not self._paused
        if self._paused:
            self.queue_worker.pause()
            self.pause_btn.setText("▶ Lanjut")
        else:
            self.queue_worker.resume()
            self.pause_btn.setText("⏸ Jeda")

    def stop_download(self) -> None:
        if self.queue_worker and self.queue_worker.isRunning():
            self.queue_worker.stop()

    def retry_failed(self) -> None:
        changed = 0
        for row, track in enumerate(self.tracks):
            if track.status in (TrackStatus.FAILED, TrackStatus.CANCELLED):
                track.status = TrackStatus.QUEUED
                track.progress = 0.0
                track.error = ""
                self._on_item_changed(row, TrackStatus.QUEUED.value, 0.0, "Siap dicoba lagi")
                changed += 1
        if changed:
            self.log(f"{changed} item disiapkan untuk retry.")
            self.start_download()
        else:
            self.log("Tidak ada item gagal untuk di-retry.")

    def _on_item_changed(self, row: int, status: str, progress: float, detail: str) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.setItem(row, 3, QTableWidgetItem(status))
        bar = self.table.cellWidget(row, 4)
        if isinstance(bar, QProgressBar):
            bar.setValue(max(0, min(100, int(progress))))
        self.table.setItem(row, 5, QTableWidgetItem(detail))
        self._update_total_progress()

    def _update_total_progress(self) -> None:
        if not self.tracks:
            self.total_progress.setValue(0)
            return
        total = sum(max(0.0, min(100.0, t.progress)) for t in self.tracks) / len(self.tracks)
        self.total_progress.setValue(int(total))

    def _on_queue_finished(self, done: int, failed: int, cancelled: int) -> None:
        self.log(f"Antrean selesai • berhasil {done} • gagal {failed} • dibatalkan {cancelled}")
        if failed:
            self.header_status.setText(f"Selesai dengan {failed} kegagalan")
        else:
            self.header_status.setText("Antrean selesai")

    def _queue_thread_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.add_btn.setEnabled(True)
        self._paused = False
        self.pause_btn.setText("⏸ Jeda")
        self._update_total_progress()

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
            quality = data.get("quality")
            if quality in {"original", "m4a", "mp3"}:
                idx = self.quality_combo.findData(quality)
                if idx >= 0:
                    self.quality_combo.setCurrentIndex(idx)

            queries = data.get("queries") or []
            if isinstance(queries, list) and queries:
                text = "\n".join(str(q).strip() for q in queries if str(q).strip())
                if text:
                    self.input_text.setPlainText(text)
                    self.import_input()

            intent = data.get("intent")
            note = data.get("note") or "Perintah dipahami."
            self.log(f"Gemini: {note}")

            if intent == "download_queue":
                self.start_download()
            elif intent == "retry_failed":
                self.retry_failed()
            elif intent == "add_and_download" and queries:
                self.log("Lagu ditambahkan; download akan dimulai setelah proses import selesai.")
        finally:
            self.agent_run_btn.setEnabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.queue_worker and self.queue_worker.isRunning():
            self.queue_worker.stop()
            self.queue_worker.wait(2500)
        event.accept()
