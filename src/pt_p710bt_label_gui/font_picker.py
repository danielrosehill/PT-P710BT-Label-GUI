"""Modal dialog for picking a font, with live samples rendered in each face."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .font_installer import is_installed
from .fonts import FontEntry, grouped, is_hebrew_family

SAMPLE_LATIN = "Daniel · 5961 · Label"
SAMPLE_HEBREW = "דניאל · רחוב · 5961"


class FontPickerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, current_family: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose font")
        self.resize(640, 620)
        self._selected_family: str | None = current_family

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("type to filter by name…")
        search_row.addWidget(self.search, 1)
        root.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(2)
        self.list_widget.setUniformItemSizes(False)
        root.addWidget(self.list_widget, 1)

        self._populate()
        self.search.textChanged.connect(self._filter)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.list_widget.itemDoubleClicked.connect(lambda _: self.accept())
        self.list_widget.currentItemChanged.connect(self._on_current_changed)

        if current_family:
            self._select_family(current_family)

    def _populate(self) -> None:
        self.list_widget.clear()
        for label, entries in grouped():
            header = QListWidgetItem(f"  {label}")
            hf = QFont()
            hf.setBold(True)
            hf.setPixelSize(11)
            header.setFont(hf)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(Qt.GlobalColor.gray)
            self.list_widget.addItem(header)

            for e in entries:
                self._add_entry(e)

    def _add_entry(self, e: FontEntry) -> None:
        installed = is_installed(e.family)
        sample = SAMPLE_HEBREW if is_hebrew_family(e.family) else SAMPLE_LATIN

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        name_lbl = QLabel(e.display + ("  (not installed)" if not installed else ""))
        name_font = QFont()
        name_font.setPixelSize(11)
        if not installed:
            name_lbl.setStyleSheet("color: #999;")
        name_lbl.setFont(name_font)
        name_lbl.setMinimumWidth(180)
        layout.addWidget(name_lbl, 0)

        sample_lbl = QLabel(sample)
        sf = QFont(e.family)
        sf.setPixelSize(22)
        sample_lbl.setFont(sf)
        if is_hebrew_family(e.family):
            sample_lbl.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            sample_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        else:
            sample_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if not installed:
            sample_lbl.setStyleSheet("color: #bbb;")
        layout.addWidget(sample_lbl, 1)

        item = QListWidgetItem(self.list_widget)
        item.setData(Qt.ItemDataRole.UserRole, e.family)
        item.setData(Qt.ItemDataRole.UserRole + 1, e.display.lower())
        item.setSizeHint(QSize(0, 44))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row)

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            family = item.data(Qt.ItemDataRole.UserRole)
            if family is None:
                # header — show only if no filter is active
                item.setHidden(bool(needle))
                continue
            display = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(bool(needle) and needle not in display)

    def _select_family(self, family: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == family:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item)
                return

    def _on_current_changed(self, current, _previous) -> None:
        if current is None:
            return
        fam = current.data(Qt.ItemDataRole.UserRole)
        if fam:
            self._selected_family = fam

    def selected_family(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            return self._selected_family
        return item.data(Qt.ItemDataRole.UserRole) or self._selected_family
