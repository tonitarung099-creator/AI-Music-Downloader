from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import app_root
from app.models import TrackStatus
from app.services.diagnostics import DiagnosticLog, write_diagnostic_bundle
from app.services.history import HistoryReadError, read_job_history
from app.services.reports import batch_summary, export_batch_csv, export_batch_json


class TrackDetailDialog(QDialog):
    def __init__(self, track, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Detail Lagu")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        metadata = track.metadata if isinstance(track.metadata, dict) else {}

        def value(text: object) -> QLabel:
            label = QLabel(str(text or "—"))
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return label

        form.addRow("Permintaan", value(track.query))
        form.addRow("Sumber", value(track.source))
        form.addRow("Status", value(track.status.value))
        form.addRow("Hasil terpilih", value(track.resolved_title))
        form.addRow("URL hasil", value(track.resolved_url))
        form.addRow("Format nyata", value(metadata.get("verified_container")))
        form.addRow("Codec audio", value(metadata.get("verified_audio_codec")))
        form.addRow("Durasi hasil", value(metadata.get("verified_duration")))
        form.addRow("Ukuran byte", value(metadata.get("verified_size_bytes")))
        form.addRow("File hasil", value(track.output_path))
        layout.addLayout(form)

        reason = QPlainTextEdit()
        reason.setReadOnly(True)
        reason.setMaximumHeight(150)
        reason.setPlainText(str(metadata.get("match_reason") or track.error or "Belum ada alasan tambahan."))
        layout.addWidget(QLabel("Alasan pemilihan / detail error"))
        layout.addWidget(reason)

        variants = []
        avoid = metadata.get("avoid_versions") or []
        prefer = metadata.get("prefer_versions") or []
        if avoid:
            variants.append("Hindari: " + ", ".join(str(item) for item in avoid))
        if prefer:
            variants.append("Utamakan: " + ", ".join(str(item) for item in prefer))
        if variants:
            variant_label = QLabel(" • ".join(variants))
            variant_label.setWordWrap(True)
            variant_label.setObjectName("muted")
            layout.addWidget(variant_label)

        close_btn = QPushButton("Tutup")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)


class HistoryDialog(QDialog):
    def __init__(self, events: list[dict[str, object]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Riwayat")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        note = QLabel("Riwayat perubahan antrean. Data terbaru ditampilkan paling atas.")
        note.setObjectName("muted")
        layout.addWidget(note)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Waktu", "Job", "Peristiwa", "Status", "Detail"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        for event in events:
            row = table.rowCount()
            table.insertRow(row)
            values = (
                event.get("created_at", ""),
                event.get("job_id", ""),
                event.get("event", ""),
                event.get("status", ""),
                event.get("detail", ""),
            )
            for column, text in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(text or "")))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)
        close_btn = QPushButton("Tutup")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)


class Stage5UiMixin:
    """Responsive UI, diagnostics, reports, and ID-safe queue interaction."""

    def __init__(self, *args, **kwargs) -> None:
        self._diagnostic_log = DiagnosticLog(max_entries=1200)
        self._agent_panel_visible = True
        super().__init__(*args, **kwargs)
        if hasattr(self, "review_btn"):
            self.review_btn.setText("Perlu Ditinjau")
        warning = str(getattr(self.config, "key_storage_warning", "") or "")
        if warning:
            self.log(f"Gemini: {warning}", level="WARNING")
        self._update_batch_summary()

    def _build_ui(self) -> None:
        super()._build_ui()
        self.setMinimumSize(960, 640)
        self.resize(1366, 768)
        self.setAcceptDrops(True)

        outer = self.centralWidget().layout()
        body = outer.itemAt(1).layout() if outer and outer.count() > 1 else None
        if body is None:
            return
        cards: list[QWidget] = []
        while body.count():
            item = body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                cards.append(widget)
        if len(cards) < 3:
            for widget in cards:
                body.addWidget(widget)
            return

        self._left_card, self._center_card, self._right_card = cards[:3]
        self._left_card.setMinimumWidth(250)
        self._left_card.setMaximumWidth(440)
        self._right_card.setMinimumWidth(270)
        self._right_card.setMaximumWidth(430)

        self.main_splitter = QSplitter(Qt.Horizontal, self)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self._left_card)
        self.main_splitter.addWidget(self._center_card)
        self.main_splitter.addWidget(self._right_card)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([300, 760, 306])
        body.addWidget(self.main_splitter)

        header = outer.itemAt(0).layout() if outer.count() else None
        self.agent_toggle_btn = QPushButton("Sembunyikan Gemini")
        self.agent_toggle_btn.setToolTip("Tampilkan/sembunyikan panel Gemini untuk memberi ruang lebih pada antrean.")
        self.agent_toggle_btn.clicked.connect(self.toggle_agent_panel)
        if header is not None:
            header.insertWidget(max(0, header.count() - 1), self.agent_toggle_btn)

        self.start_btn.setText("Mulai")
        self.pause_btn.setText("Jeda")
        self.stop_btn.setText("Hentikan")
        for button in self._center_card.findChildren(QPushButton):
            if button.text() == "Retry Gagal":
                button.setText("Coba Lagi yang Gagal")

        center_layout = self._center_card.layout()
        toolbar = QWidget(self._center_card)
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(6)

        find_row = QHBoxLayout()
        self.queue_search = QLineEdit()
        self.queue_search.setPlaceholderText("Cari judul, artis, URL, atau sumber...")
        self.queue_search.setClearButtonEnabled(True)
        self.queue_search.textChanged.connect(self.apply_queue_filter)
        self.status_filter = QComboBox()
        self.status_filter.addItem("Semua status", "all")
        self.status_filter.addItem("Menunggu", "waiting")
        self.status_filter.addItem("Berjalan", "running")
        self.status_filter.addItem("Perlu Ditinjau", "review")
        self.status_filter.addItem("Selesai", "done")
        self.status_filter.addItem("Gagal / Dibatalkan", "failed")
        self.status_filter.currentIndexChanged.connect(self.apply_queue_filter)
        find_row.addWidget(self.queue_search, 1)
        find_row.addWidget(self.status_filter)
        toolbar_layout.addLayout(find_row)

        action_row = QHBoxLayout()
        self.remove_selected_btn = QPushButton("Hapus Terpilih")
        self.detail_btn = QPushButton("Detail Lagu")
        self.open_file_btn = QPushButton("Buka File")
        self.history_btn = QPushButton("Riwayat")
        self.report_btn = QPushButton("Ekspor Laporan")
        self.diagnostic_btn = QPushButton("Ekspor Diagnostik")
        self.remove_selected_btn.clicked.connect(self.remove_selected_jobs)
        self.detail_btn.clicked.connect(self.show_track_detail)
        self.open_file_btn.clicked.connect(self.open_selected_file)
        self.history_btn.clicked.connect(self.show_history)
        self.report_btn.clicked.connect(self.export_batch_report)
        self.diagnostic_btn.clicked.connect(self.export_diagnostics)
        for button in (
            self.remove_selected_btn,
            self.detail_btn,
            self.open_file_btn,
            self.history_btn,
            self.report_btn,
            self.diagnostic_btn,
        ):
            action_row.addWidget(button)
        action_row.addStretch(1)
        toolbar_layout.addLayout(action_row)

        self.batch_summary_label = QLabel()
        self.batch_summary_label.setObjectName("muted")
        toolbar_layout.addWidget(self.batch_summary_label)
        self.empty_state_label = QLabel("Antrean kosong — tambahkan judul, URL, TXT, atau CSV.")
        self.empty_state_label.setObjectName("muted")
        self.empty_state_label.setAlignment(Qt.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        toolbar_layout.addWidget(self.empty_state_label)

        center_layout.insertWidget(1, toolbar)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setToolTip("Urutan antrean tetap mengikuti job ID, meski tampilan sedang difilter.")

    def log(self, message: str, level: str = "INFO") -> None:
        cleaned = self._diagnostic_log.append(message, level=level)
        super().log(cleaned)

    def toggle_agent_panel(self) -> None:
        self._agent_panel_visible = not self._agent_panel_visible
        self._right_card.setVisible(self._agent_panel_visible)
        self.agent_toggle_btn.setText(
            "Sembunyikan Gemini" if self._agent_panel_visible else "Tampilkan Gemini"
        )
        if self._agent_panel_visible:
            self.main_splitter.setSizes([300, 760, 306])
        else:
            self.main_splitter.setSizes([300, 1066, 0])

    def _track_for_row(self, row: int):
        if row < 0 or row >= self.table.rowCount():
            return None
        item = self.table.item(row, 0)
        job_id = str(item.data(Qt.UserRole) or "") if item is not None else ""
        if job_id:
            return next((track for track in self.tracks if track.job_id == job_id), None)
        return self.tracks[row] if row < len(self.tracks) else None

    def _selected_job_ids(self) -> set[str]:
        ids: set[str] = set()
        selection = self.table.selectionModel()
        if selection is None:
            return ids
        for index in selection.selectedRows():
            track = self._track_for_row(index.row())
            if track is not None:
                ids.add(track.job_id)
        return ids

    @staticmethod
    def _status_matches(track, filter_key: str) -> bool:
        if filter_key == "all":
            return True
        if filter_key == "waiting":
            return track.status in {TrackStatus.QUEUED, TrackStatus.INTERRUPTED, TrackStatus.RETRY_WAIT}
        if filter_key == "running":
            return track.status in {
                TrackStatus.SEARCHING,
                TrackStatus.DOWNLOADING,
                TrackStatus.POSTPROCESSING,
                TrackStatus.VERIFYING,
                TrackStatus.PAUSED,
            }
        if filter_key == "review":
            return track.status == TrackStatus.NEEDS_REVIEW
        if filter_key == "done":
            return track.status == TrackStatus.DONE
        if filter_key == "failed":
            return track.status in {TrackStatus.FAILED, TrackStatus.CANCELLED}
        return True

    def apply_queue_filter(self, *_args) -> None:
        if not hasattr(self, "queue_search"):
            return
        needle = self.queue_search.text().strip().casefold()
        filter_key = str(self.status_filter.currentData() or "all")
        visible = 0
        for row in range(self.table.rowCount()):
            track = self._track_for_row(row)
            if track is None:
                self.table.setRowHidden(row, True)
                continue
            haystack = " ".join(
                str(value or "")
                for value in (
                    track.display_name,
                    track.query,
                    track.source,
                    track.resolved_title,
                    track.resolved_url,
                )
            ).casefold()
            show = self._status_matches(track, filter_key) and (not needle or needle in haystack)
            self.table.setRowHidden(row, not show)
            if show:
                visible += 1
        total = len(self.tracks)
        if total == 0:
            self.empty_state_label.setText("Antrean kosong — tambahkan judul, URL, TXT, atau CSV.")
            self.empty_state_label.setVisible(True)
        elif visible == 0:
            self.empty_state_label.setText("Tidak ada item yang cocok dengan pencarian/filter saat ini.")
            self.empty_state_label.setVisible(True)
        else:
            self.empty_state_label.setVisible(False)
        self._update_batch_summary(visible=visible)

    def _update_batch_summary(self, *, visible: int | None = None) -> None:
        if not hasattr(self, "batch_summary_label"):
            return
        summary = batch_summary(self.tracks)
        review = summary.get(TrackStatus.NEEDS_REVIEW.value, 0)
        done = summary.get(TrackStatus.DONE.value, 0)
        failed = summary.get(TrackStatus.FAILED.value, 0) + summary.get(TrackStatus.CANCELLED.value, 0)
        waiting = (
            summary.get(TrackStatus.QUEUED.value, 0)
            + summary.get(TrackStatus.INTERRUPTED.value, 0)
            + summary.get(TrackStatus.RETRY_WAIT.value, 0)
        )
        if visible is None:
            visible = sum(1 for row in range(self.table.rowCount()) if not self.table.isRowHidden(row))
        self.batch_summary_label.setText(
            f"Total {summary.get('total', 0)} • terlihat {visible} • menunggu {waiting} • "
            f"selesai {done} • perlu ditinjau {review} • gagal/dibatalkan {failed}"
        )

    def _append_tracks(self, tracks) -> None:
        super()._append_tracks(tracks)
        self.apply_queue_filter()

    def _rebuild_queue_table(self) -> None:
        super()._rebuild_queue_table()
        self.apply_queue_filter()

    def _on_item_changed(self, job_id, status: str, progress: float, detail: str) -> None:
        super()._on_item_changed(job_id, status, progress, detail)
        self.apply_queue_filter()

    def _update_total_progress(self) -> None:
        super()._update_total_progress()
        self._update_batch_summary()

    def remove_selected_jobs(self) -> None:
        job_ids = self._selected_job_ids()
        if not job_ids:
            QMessageBox.information(self, "Belum ada pilihan", "Pilih satu atau beberapa lagu terlebih dahulu.")
            return
        removed = self.remove_jobs(job_ids)
        if removed:
            self.apply_queue_filter()

    def show_track_detail(self) -> None:
        row = self.table.currentRow()
        track = self._track_for_row(row)
        if track is None:
            QMessageBox.information(self, "Belum ada pilihan", "Pilih lagu yang ingin dilihat detailnya.")
            return
        dialog = TrackDetailDialog(track, self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def open_selected_file(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Belum ada pilihan", "Pilih lagu selesai yang ingin dibuka.")
            return
        self._handle_row_double_click(row, 0)

    def show_history(self) -> None:
        if self.queue_repo is None:
            QMessageBox.warning(self, "Riwayat tidak tersedia", "Database antrean tidak aktif pada sesi ini.")
            return
        ids = self._selected_job_ids()
        job_id = next(iter(ids)) if len(ids) == 1 else None
        try:
            events = read_job_history(self.queue_repo.path, job_id=job_id)
        except HistoryReadError as exc:
            QMessageBox.warning(self, "Riwayat tidak tersedia", str(exc))
            return
        if not events:
            QMessageBox.information(self, "Riwayat", "Belum ada riwayat untuk scope yang dipilih.")
            return
        dialog = HistoryDialog(events, self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def export_batch_report(self) -> None:
        if not self.tracks:
            QMessageBox.information(self, "Antrean kosong", "Belum ada data untuk diekspor.")
            return
        reports_dir = app_root() / "data" / "reports"
        suggested = reports_dir / "laporan-antrean.csv"
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Ekspor Laporan Antrean",
            str(suggested),
            "CSV (*.csv);;JSON (*.json)",
        )
        if not filename:
            return
        path = Path(filename)
        if "JSON" in selected_filter.upper() or path.suffix.lower() == ".json":
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")
            result = export_batch_json(path, self.tracks)
        else:
            if path.suffix.lower() != ".csv":
                path = path.with_suffix(".csv")
            result = export_batch_csv(path, self.tracks)
        self.log(f"Laporan antrean disimpan: {result}")

    def export_diagnostics(self) -> None:
        diagnostics_dir = app_root() / "data" / "diagnostics"
        suggested = diagnostics_dir / "diagnostik-ai-music-downloader.zip"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Ekspor Diagnostik Teredaksi",
            str(suggested),
            "ZIP (*.zip)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".zip":
            path = path.with_suffix(".zip")
        from app.services.downloader import DownloadEngine

        tool_status = {
            "ffmpeg_location": DownloadEngine.ffmpeg_location() or "tidak ditemukan",
            "ffprobe_path": DownloadEngine.ffprobe_path() or "tidak ditemukan",
        }
        result = write_diagnostic_bundle(
            path,
            log=self._diagnostic_log,
            config=self.config,
            tracks=self.tracks,
            tool_status=tool_status,
        )
        self.log(f"Diagnostik teredaksi disimpan: {result}")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        lines: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.suffix.lower() in {".txt", ".csv"}:
                        lines.extend(self._read_drop_file(path))
                else:
                    text = url.toString().strip()
                    if text:
                        lines.append(text)
        if mime.hasText():
            for raw in mime.text().splitlines():
                text = raw.strip()
                if text and text not in lines:
                    lines.append(text)
        clean = [line for line in lines if line][:5000]
        if not clean:
            event.ignore()
            return
        existing = self.input_text.toPlainText().strip()
        combined = "\n".join(([existing] if existing else []) + clean)
        self.input_text.setPlainText(combined)
        self.log(f"Drag/drop: {len(clean)} item dimasukkan ke kotak input. Klik Tambah ke Antrean untuk memproses.")
        event.acceptProposedAction()

    @staticmethod
    def _read_drop_file(path: Path) -> list[str]:
        try:
            if path.suffix.lower() == ".txt":
                return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            rows: list[str] = []
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                for index, row in enumerate(reader):
                    values = [cell.strip() for cell in row if cell.strip()]
                    if not values:
                        continue
                    lowered = {value.casefold() for value in values}
                    if index == 0 and lowered.intersection({"judul", "title", "lagu", "artist", "artis", "url"}):
                        continue
                    first_url = next((value for value in values if "://" in value), "")
                    if first_url:
                        rows.append(first_url)
                    elif len(values) >= 2:
                        rows.append(f"{values[0]} - {values[1]}")
                    else:
                        rows.append(values[0])
            return rows
        except (OSError, UnicodeError, csv.Error):
            return []
