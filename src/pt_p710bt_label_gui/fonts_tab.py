"""'Fonts' tab — curated Google Fonts list with install controls."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .font_installer import install_font, installed_families, is_installed, refresh_cache
from .fonts import FONTS, CATEGORY_LABEL, FontEntry


class _Worker(QThread):
    progress = pyqtSignal(str)
    item_done = pyqtSignal(int, bool, str)
    finished_all = pyqtSignal()

    def __init__(self, targets: list[tuple[int, FontEntry]]) -> None:
        super().__init__()
        self.targets = targets

    def run(self) -> None:
        for row, entry in self.targets:
            self.progress.emit(f"⤓ {entry.display} ({entry.slug}) …")
            ok, msg = install_font(entry.slug)
            self.item_done.emit(row, ok, msg)
            self.progress.emit(f"  → {'OK' if ok else 'FAIL'}: {msg}")
        self.progress.emit("Refreshing fc-cache…")
        refresh_cache()
        self.progress.emit("Done.")
        self.finished_all.emit()


class FontsTab(QWidget):
    """Embedded font browser + installer."""

    fonts_changed = pyqtSignal()  # emitted when a batch install finishes

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "<b>Curated Google Fonts library.</b><br>"
            "Missing fonts download from <code>github.com/google/fonts</code> into "
            "<code>~/.local/share/fonts/pt-p710bt-label-gui/</code> and refresh the "
            "system font cache."
        ))

        # Counts header
        self.summary = QLabel("—")
        layout.addWidget(self.summary)

        # Action buttons — prominent, above the table
        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh status")
        self.install_missing_btn = QPushButton("Install missing")
        self.install_missing_btn.setStyleSheet("font-weight: bold;")
        self.install_all_btn = QPushButton("Reinstall all")
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.install_missing_btn)
        btn_row.addWidget(self.install_all_btn)
        layout.addLayout(btn_row)

        # Table
        self.table = QTableWidget(len(FONTS), 3)
        self.table.setHorizontalHeaderLabels(["Font", "Category", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for row, entry in enumerate(FONTS):
            self.table.setItem(row, 0, QTableWidgetItem(entry.display))
            self.table.setItem(row, 1, QTableWidgetItem(CATEGORY_LABEL[entry.category]))
            self.table.setItem(row, 2, QTableWidgetItem("…"))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        self.log.setPlaceholderText("Install activity will appear here…")
        layout.addWidget(self.log)

        self.refresh_btn.clicked.connect(self.refresh_status)
        self.install_missing_btn.clicked.connect(self.install_missing)
        self.install_all_btn.clicked.connect(self.install_all)

        self.worker: _Worker | None = None
        self.refresh_status()

    # ---------- status ----------

    def refresh_status(self) -> None:
        cache = installed_families()
        installed_n = 0
        for row, entry in enumerate(FONTS):
            ok = is_installed(entry.family, cache)
            if ok:
                installed_n += 1
            item = self.table.item(row, 2)
            item.setText("✓ installed" if ok else "✗ missing")
            item.setForeground(QColor("#2a8") if ok else QColor("#c33"))
        missing = len(FONTS) - installed_n
        self.summary.setText(
            f"<b>{installed_n}</b> installed · <b>{missing}</b> missing · "
            f"{len(FONTS)} total"
        )
        self.install_missing_btn.setEnabled(missing > 0)

    # ---------- install ----------

    def install_missing(self) -> None:
        cache = installed_families()
        targets = [
            (row, e) for row, e in enumerate(FONTS)
            if not is_installed(e.family, cache)
        ]
        self._start(targets)

    def install_all(self) -> None:
        self._start([(row, e) for row, e in enumerate(FONTS)])

    def _start(self, targets: list[tuple[int, FontEntry]]) -> None:
        if not targets:
            self.log.appendPlainText("Nothing to do — all fonts already present.")
            return
        if self.worker and self.worker.isRunning():
            return
        for row, _ in targets:
            item = self.table.item(row, 2)
            item.setText("queued")
            item.setForeground(QColor("#888"))
        self.progress.setVisible(True)
        self._set_buttons(False)
        self.worker = _Worker(targets)
        self.worker.progress.connect(self.log.appendPlainText)
        self.worker.item_done.connect(self._on_done)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _on_done(self, row: int, ok: bool, msg: str) -> None:
        item = self.table.item(row, 2)
        item.setText("✓ installed" if ok else f"✗ {msg}")
        item.setForeground(QColor("#2a8") if ok else QColor("#c33"))

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self._set_buttons(True)
        self.refresh_status()
        self.fonts_changed.emit()

    def _set_buttons(self, enabled: bool) -> None:
        for b in (self.refresh_btn, self.install_missing_btn, self.install_all_btn):
            b.setEnabled(enabled)
