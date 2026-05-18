"""Dialog for installing missing Google Fonts from the curated list."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .font_installer import (
    install_font,
    installed_families,
    is_installed,
    refresh_cache,
)
from .fonts import FONTS, FontEntry


class _InstallWorker(QThread):
    progress = pyqtSignal(str)        # log line
    item_done = pyqtSignal(int, bool, str)  # row index, ok, message
    finished_all = pyqtSignal()

    def __init__(self, targets: list[tuple[int, FontEntry]]) -> None:
        super().__init__()
        self.targets = targets

    def run(self) -> None:  # noqa: D401
        for row, entry in self.targets:
            self.progress.emit(f"⤓ {entry.display} ({entry.slug}) …")
            ok, msg = install_font(entry.slug)
            self.item_done.emit(row, ok, msg)
            self.progress.emit(f"  → {'OK' if ok else 'FAIL'}: {msg}")
        refresh_cache()
        self.progress.emit("fc-cache refreshed.")
        self.finished_all.emit()


class FontInstallDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Install Google Fonts")
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Curated Google Fonts library. Missing fonts will be downloaded into "
            "<code>~/.local/share/fonts/pt-p710bt-label-gui/</code> and the font cache refreshed."
        ))

        self.table = QTableWidget(len(FONTS), 3)
        self.table.setHorizontalHeaderLabels(["Font", "Category", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, entry in enumerate(FONTS):
            self.table.setItem(row, 0, QTableWidgetItem(entry.display))
            self.table.setItem(row, 1, QTableWidgetItem(entry.category))
            self.table.setItem(row, 2, QTableWidgetItem("…"))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh status")
        self.install_missing_btn = QPushButton("Install missing")
        self.install_all_btn = QPushButton("Reinstall all")
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.install_missing_btn)
        btn_row.addWidget(self.install_all_btn)
        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.refresh_btn.clicked.connect(self.refresh_status)
        self.install_missing_btn.clicked.connect(self.install_missing)
        self.install_all_btn.clicked.connect(self.install_all)

        self.worker: _InstallWorker | None = None
        self.refresh_status()

    # ---------- status ----------

    def refresh_status(self) -> None:
        cache = installed_families()
        for row, entry in enumerate(FONTS):
            installed = is_installed(entry.family, cache)
            item = self.table.item(row, 2)
            item.setText("installed" if installed else "missing")

    def _missing_targets(self) -> list[tuple[int, FontEntry]]:
        cache = installed_families()
        return [
            (row, entry) for row, entry in enumerate(FONTS)
            if not is_installed(entry.family, cache)
        ]

    def _all_targets(self) -> list[tuple[int, FontEntry]]:
        return [(row, entry) for row, entry in enumerate(FONTS)]

    # ---------- install ----------

    def install_missing(self) -> None:
        self._start(self._missing_targets())

    def install_all(self) -> None:
        self._start(self._all_targets())

    def _start(self, targets: list[tuple[int, FontEntry]]) -> None:
        if not targets:
            self.log.appendPlainText("Nothing to install — all fonts already present.")
            return
        if self.worker and self.worker.isRunning():
            return
        for row, _ in targets:
            self.table.item(row, 2).setText("queued")
        self.progress.setVisible(True)
        self.set_buttons_enabled(False)
        self.worker = _InstallWorker(targets)
        self.worker.progress.connect(self.log.appendPlainText)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _on_item_done(self, row: int, ok: bool, msg: str) -> None:
        self.table.item(row, 2).setText("installed" if ok else f"failed ({msg})")

    def _on_finished(self) -> None:
        self.progress.setVisible(False)
        self.set_buttons_enabled(True)
        self.refresh_status()

    def set_buttons_enabled(self, enabled: bool) -> None:
        for b in (self.refresh_btn, self.install_missing_btn, self.install_all_btn):
            b.setEnabled(enabled)
