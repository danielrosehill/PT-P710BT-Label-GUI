"""Batch printing tab — queue rows of (text, copies) and print them in sequence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .ptouch import PrintJob, PtouchError, print_job


@dataclass
class BatchRow:
    text: str
    copies: int


class BatchWorker(QObject):
    progress = pyqtSignal(int, int, str)   # index, total, text
    row_done = pyqtSignal(int, bool, str)  # index, ok, message
    finished = pyqtSignal(bool, str)       # ok, summary

    def __init__(self, rows: list[BatchRow], job_factory: Callable[[BatchRow], PrintJob]):
        super().__init__()
        self._rows = rows
        self._factory = job_factory
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        total = len(self._rows)
        ok_count = 0
        for i, row in enumerate(self._rows):
            if self._cancel:
                self.finished.emit(False, f"Cancelled after {i}/{total}")
                return
            self.progress.emit(i, total, row.text)
            job = self._factory(row)
            try:
                rc, out = print_job(job)
                if rc == 0:
                    ok_count += 1
                    self.row_done.emit(i, True, "OK")
                else:
                    self.row_done.emit(i, False, f"exit {rc}: {out.strip()[:120]}")
            except PtouchError as exc:
                self.row_done.emit(i, False, str(exc))
        self.finished.emit(True, f"Printed {ok_count}/{total}")


class BatchTab(QWidget):
    """Independent batch tab. Holds its own rows; pulls font/format from a callback."""

    def __init__(
        self,
        job_factory: Callable[[BatchRow], PrintJob],
        printer_online: Callable[[], bool],
    ) -> None:
        super().__init__()
        self._job_factory = job_factory
        self._printer_online = printer_online
        self._thread: QThread | None = None
        self._worker: BatchWorker | None = None

        root = QVBoxLayout(self)

        intro = QLabel(
            "Queue a list of labels and print them one after another. "
            "Format settings (font, size, alignment, cut options) come from the Label tab."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Text", "Copies"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setDefaultSectionSize(28)
        root.addWidget(self.table, 1)

        row_btns = QHBoxLayout()
        self.add_btn = QPushButton("New row")
        self.dup_btn = QPushButton("Duplicate")
        self.del_btn = QPushButton("Delete")
        self.clear_btn = QPushButton("Clear")
        row_btns.addWidget(self.add_btn)
        row_btns.addWidget(self.dup_btn)
        row_btns.addWidget(self.del_btn)
        row_btns.addWidget(self.clear_btn)
        row_btns.addStretch(1)
        self.import_btn = QPushButton("Import manifest…")
        self.save_btn = QPushButton("Save manifest…")
        row_btns.addWidget(self.import_btn)
        row_btns.addWidget(self.save_btn)
        root.addLayout(row_btns)

        run_row = QHBoxLayout()
        self.start_btn = QPushButton("Start batch")
        self.start_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.progress.setValue(0)
        run_row.addWidget(self.start_btn)
        run_row.addWidget(self.cancel_btn)
        run_row.addWidget(self.progress, 1)
        root.addLayout(run_row)

        self.status = QLabel("Idle.")
        root.addWidget(self.status)

        # wiring
        self.add_btn.clicked.connect(lambda: self._append_row("", 1))
        self.dup_btn.clicked.connect(self._on_dup)
        self.del_btn.clicked.connect(self._on_del)
        self.clear_btn.clicked.connect(self._on_clear)
        self.import_btn.clicked.connect(self._on_import)
        self.save_btn.clicked.connect(self._on_save)
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn.clicked.connect(self._on_cancel)

        # seed one empty row
        self._append_row("", 1)

    # ---------- table ops ----------

    def _append_row(self, text: str, copies: int) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(text))
        copies_item = QTableWidgetItem(str(copies))
        copies_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(r, 1, copies_item)

    def _on_dup(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        text = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
        copies = self._copies_at(r)
        self._append_row(text, copies)

    def _on_del(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def _on_clear(self) -> None:
        self.table.setRowCount(0)
        self._append_row("", 1)

    def _copies_at(self, row: int) -> int:
        item = self.table.item(row, 1)
        if not item:
            return 1
        try:
            return max(1, int(item.text().strip() or "1"))
        except ValueError:
            return 1

    def _collect_rows(self) -> list[BatchRow]:
        rows: list[BatchRow] = []
        for r in range(self.table.rowCount()):
            text_item = self.table.item(r, 0)
            text = text_item.text() if text_item else ""
            if not text.strip():
                continue
            rows.append(BatchRow(text=text, copies=self._copies_at(r)))
        return rows

    # ---------- manifest I/O ----------

    def _on_save(self) -> None:
        rows = []
        for r in range(self.table.rowCount()):
            text_item = self.table.item(r, 0)
            rows.append({
                "text": text_item.text() if text_item else "",
                "copies": self._copies_at(r),
            })
        path, _ = QFileDialog.getSaveFileName(
            self, "Save batch manifest", "batch.json",
            "JSON manifest (*.json);;All files (*)",
        )
        if not path:
            return
        Path(path).write_text(json.dumps({"rows": rows}, indent=2))
        self.status.setText(f"Saved {len(rows)} row(s) to {path}")

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import batch manifest", "",
            "JSON manifest (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        rows = data.get("rows", []) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            QMessageBox.critical(self, "Import failed", "Manifest has no rows array.")
            return
        self.table.setRowCount(0)
        for r in rows:
            text = str(r.get("text", "")) if isinstance(r, dict) else str(r)
            copies = int(r.get("copies", 1)) if isinstance(r, dict) else 1
            self._append_row(text, copies)
        if self.table.rowCount() == 0:
            self._append_row("", 1)
        self.status.setText(f"Imported {self.table.rowCount()} row(s) from {path}")

    # ---------- batch run ----------

    def _on_start(self) -> None:
        if self._thread is not None:
            return
        if not self._printer_online():
            QMessageBox.warning(
                self, "Printer offline",
                "Printer not detected. Switch to the Device tab and refresh."
            )
            return
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "Empty batch", "Add at least one row with text.")
            return

        self.progress.setMaximum(len(rows))
        self.progress.setValue(0)
        self._set_running(True)

        self._thread = QThread(self)
        self._worker = BatchWorker(rows, self._job_factory)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.row_done.connect(self._on_row_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self.status.setText("Cancelling after current label…")

    def _on_progress(self, index: int, total: int, text: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(index)
        self.status.setText(f"[{index + 1}/{total}] printing: {text}")
        self.table.selectRow(self._table_row_for_batch_index(index))

    def _on_row_done(self, index: int, ok: bool, msg: str) -> None:
        r = self._table_row_for_batch_index(index)
        marker = "✓" if ok else "✗"
        text_item = self.table.item(r, 0)
        if text_item:
            base = text_item.text().lstrip("✓✗ ").strip()
            text_item.setText(f"{marker} {base}")
            text_item.setToolTip(msg)
        self.progress.setValue(index + 1)

    def _on_finished(self, ok: bool, summary: str) -> None:
        self.status.setText(summary)
        self._set_running(False)

    def _cleanup_thread(self) -> None:
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for b in (self.add_btn, self.dup_btn, self.del_btn, self.clear_btn,
                  self.import_btn, self.save_btn):
            b.setEnabled(not running)
        self.table.setEnabled(not running)

    def _table_row_for_batch_index(self, batch_index: int) -> int:
        # rows with empty text are skipped in _collect_rows; map back
        seen = -1
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            text = item.text().lstrip("✓✗ ").strip() if item else ""
            if not text:
                continue
            seen += 1
            if seen == batch_index:
                return r
        return 0
