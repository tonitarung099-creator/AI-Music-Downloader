from __future__ import annotations

from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
)


class CandidateReviewDialog(QDialog):
    def __init__(self, request_name: str, candidates: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self._candidates = [item for item in candidates if isinstance(item, dict)]
        self.setWindowTitle("Tinjau Kandidat Lagu")
        self.resize(980, 520)

        layout = QVBoxLayout(self)
        title = QLabel(f"Permintaan: {request_name}")
        title.setWordWrap(True)
        layout.addWidget(title)

        info = QLabel(
            "Aplikasi tidak cukup yakin untuk memilih otomatis. Pilih kandidat yang benar, "
            "atau batalkan agar item tetap berstatus Perlu Ditinjau."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(len(self._candidates), 6)
        self.table.setHorizontalHeaderLabels(
            ["Judul", "Channel", "Durasi", "Skor", "Versi", "URL"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)

        for row, candidate in enumerate(self._candidates):
            duration = candidate.get("duration")
            if isinstance(duration, (int, float)):
                minutes, seconds = divmod(int(duration), 60)
                duration_text = f"{minutes}:{seconds:02d}"
            else:
                duration_text = "-"
            versions = candidate.get("versions") or []
            values = [
                str(candidate.get("title") or ""),
                str(candidate.get("uploader") or ""),
                duration_text,
                f"{float(candidate.get('score') or 0.0):.3f}",
                ", ".join(str(item) for item in versions) if isinstance(versions, list) else str(versions),
                str(candidate.get("url") or ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

        if self._candidates:
            self.table.selectRow(0)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        open_btn = QPushButton("Buka Sumber")
        cancel_btn = QPushButton("Batal")
        choose_btn = QPushButton("Gunakan Kandidat")
        choose_btn.setObjectName("primary")
        open_btn.clicked.connect(self._open_source)
        cancel_btn.clicked.connect(self.reject)
        choose_btn.clicked.connect(self._accept_selection)
        actions.addWidget(open_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)
        actions.addWidget(choose_btn)
        layout.addLayout(actions)

    def selected_candidate(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._candidates):
            return None
        return self._candidates[row]

    def _open_source(self) -> None:
        candidate = self.selected_candidate()
        if not candidate:
            return
        url = str(candidate.get("url") or "").strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _accept_selection(self) -> None:
        if self.selected_candidate() is None:
            QMessageBox.information(self, "Belum dipilih", "Pilih salah satu kandidat terlebih dahulu.")
            return
        self.accept()
