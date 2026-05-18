"""PyQt6 main window for the PT-P710BT label GUI — tabbed layout."""
from __future__ import annotations

import shlex
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .font_installer import is_installed, migrate_legacy_dir, refresh_cache
from .fonts import DEFAULT_FAMILY, FONTS, grouped
from .fonts_tab import FontsTab
from .ptouch import PrintJob, PtouchError, print_job, query_info, render_preview


PREVIEW_DEBOUNCE_MS = 350
DEFAULT_FALLBACK_TAPE_PX = 76  # 12mm


class LabelGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PT-P710BT Label GUI")
        self.resize(1180, 720)

        self._tmpdir = Path(tempfile.mkdtemp(prefix="pt-p710bt-"))
        self._preview_path = self._tmpdir / "preview.png"
        self._last_tape_px: int = DEFAULT_FALLBACK_TAPE_PX
        self._printer_online: bool = False
        self._last_info_raw: str = ""

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(PREVIEW_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._do_preview)

        moved = migrate_legacy_dir()
        if moved:
            refresh_cache()

        self._build_tabs()
        self._wire_signals()
        if moved:
            self.statusBar().showMessage(
                f"Migrated {moved} font file(s) to ~/.local/share/fonts/google-fonts/",
                6000,
            )
        self.refresh_info()
        self._schedule_preview()

    # ---------- Tab construction ----------

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tabs.addTab(self._build_label_tab(),   "Label")
        self.tabs.addTab(self._build_printer_tab(), "Printer")
        self.tabs.addTab(self._build_tape_tab(),    "Tape")
        self.fonts_tab = FontsTab()
        self.fonts_tab.fonts_changed.connect(self._refresh_font_list)
        self.tabs.addTab(self.fonts_tab,            "Fonts")

        self.setStatusBar(QStatusBar())

    # ----- Label tab (the main work area) -----

    def _build_label_tab(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)

        # Left column: input controls
        left = QVBoxLayout()
        root.addLayout(left, 0)

        text_box = QGroupBox("Text (up to 4 lines)")
        text_layout = QVBoxLayout(text_box)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Line 1\nLine 2\n…")
        self.text_edit.setFixedHeight(110)
        text_layout.addWidget(self.text_edit)
        left.addWidget(text_box)

        # Format
        fmt_box = QGroupBox("Format")
        fmt_layout = QFormLayout(fmt_box)
        font_row = QHBoxLayout()
        self.font_combo = QComboBox()
        self._populate_font_combo()
        self.manage_fonts_btn = QPushButton("Manage…")
        self.manage_fonts_btn.setToolTip("Open the Fonts tab to install / update.")
        font_row.addWidget(self.font_combo, 1)
        font_row.addWidget(self.manage_fonts_btn)
        font_row_wrap = QWidget()
        font_row_wrap.setLayout(font_row)
        font_row.setContentsMargins(0, 0, 0, 0)
        self.font_size = QSpinBox()
        self.font_size.setRange(0, 200)
        self.font_size.setValue(0)
        self.font_size.setSpecialValueText("auto")
        self.align_combo = QComboBox()
        self.align_combo.addItems(["left", "center", "right"])
        self.align_combo.setCurrentIndex(1)
        fmt_layout.addRow("Font:", font_row_wrap)
        fmt_layout.addRow("Font size (px):", self.font_size)
        fmt_layout.addRow("Align:", self.align_combo)
        left.addWidget(fmt_box)

        # Print options
        opts_box = QGroupBox("Print options")
        opts_layout = QFormLayout(opts_box)
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.copies.setValue(1)
        self.pad = QSpinBox()
        self.pad.setRange(0, 500)
        self.pad.setValue(0)
        self.auto_cut = QCheckBox("Auto-cut after print")
        self.auto_cut.setChecked(True)
        self.auto_cut.setToolTip(
            "When OFF, passes --chain to ptouch-print (continuous tape, no cut)."
        )
        self.precut = QCheckBox("Pre-cut (chain mode only)")
        self.cutmark = QCheckBox("Print cut-mark")
        opts_layout.addRow("Copies:", self.copies)
        opts_layout.addRow("Padding (px):", self.pad)
        opts_layout.addRow(self.auto_cut)
        opts_layout.addRow(self.precut)
        opts_layout.addRow(self.cutmark)
        left.addWidget(opts_box)

        # Image
        img_box = QGroupBox("Image (optional, monochrome PNG)")
        img_layout = QHBoxLayout(img_box)
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText("(none)")
        self.image_browse = QPushButton("Browse…")
        self.image_clear = QPushButton("Clear")
        img_layout.addWidget(self.image_path, 1)
        img_layout.addWidget(self.image_browse)
        img_layout.addWidget(self.image_clear)
        left.addWidget(img_box)

        # Actions
        action_row = QHBoxLayout()
        self.show_cmd_btn = QPushButton("Show command")
        self.print_btn = QPushButton("Print")
        self.print_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        action_row.addWidget(self.show_cmd_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.print_btn)
        left.addLayout(action_row)
        left.addStretch(1)

        # Right column: preview
        right = QVBoxLayout()
        root.addLayout(right, 1)
        right.addWidget(QLabel("Preview (actual tape height, scaled to width):"))
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        self.preview_label.setStyleSheet(
            "background: #222; color: #888; border: 1px solid #444;"
        )
        self.preview_label.setText("(no preview yet)")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        right.addWidget(scroll, 1)

        self.preview_log = QPlainTextEdit()
        self.preview_log.setReadOnly(True)
        self.preview_log.setMaximumHeight(120)
        self.preview_log.setPlaceholderText("ptouch-print output appears here")
        right.addWidget(self.preview_log)

        return w

    # ----- Printer tab -----

    def _build_printer_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        box = QGroupBox("Printer connection")
        form = QFormLayout(box)
        self.p_status = QLabel("—")
        self.p_dpi = QLabel("—")
        self.p_max_px = QLabel("—")
        form.addRow("Status:", self.p_status)
        form.addRow("Resolution:", self.p_dpi)
        form.addRow("Max print width:", self.p_max_px)
        layout.addWidget(box)

        info_box = QGroupBox("Raw ptouch-print --info output")
        info_layout = QVBoxLayout(info_box)
        self.p_raw = QPlainTextEdit()
        self.p_raw.setReadOnly(True)
        self.p_raw.setMaximumHeight(220)
        self.p_raw.setStyleSheet("font-family: monospace;")
        info_layout.addWidget(self.p_raw)
        layout.addWidget(info_box)

        self.p_refresh_btn = QPushButton("Refresh printer info")
        layout.addWidget(self.p_refresh_btn)
        layout.addStretch(1)

        notes = QLabel(
            "<i>Printer is queried via <code>ptouch-print --info</code> over USB. "
            "If the printer is offline, the Label preview falls back to the last "
            "known tape width.</i>"
        )
        notes.setWordWrap(True)
        layout.addWidget(notes)
        return w

    # ----- Tape tab -----

    def _build_tape_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        box = QGroupBox("Detected tape")
        form = QFormLayout(box)
        self.t_width = QLabel("—")
        self.t_usable = QLabel("—")
        self.t_media = QLabel("—")
        self.t_tape_color = QLabel("—")
        self.t_text_color = QLabel("—")
        self.t_error = QLabel("—")
        form.addRow("Cassette width:", self.t_width)
        form.addRow("Usable print height:", self.t_usable)
        form.addRow("Media type:", self.t_media)
        form.addRow("Tape colour:", self.t_tape_color)
        form.addRow("Text colour:", self.t_text_color)
        form.addRow("Error byte:", self.t_error)
        layout.addWidget(box)

        self.t_refresh_btn = QPushButton("Refresh tape info")
        layout.addWidget(self.t_refresh_btn)

        layout.addWidget(QLabel(
            "<i>0x0000 = ready. 0x0100 typically indicates a cover/tape issue. "
            "After interruptions a power-cycle may be needed to clear errors.</i>"
        ))
        layout.addStretch(1)
        return w

    # ---------- Wiring ----------

    def _wire_signals(self) -> None:
        self.p_refresh_btn.clicked.connect(self.refresh_info)
        self.t_refresh_btn.clicked.connect(self.refresh_info)
        self.manage_fonts_btn.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.fonts_tab)
        )

        self.text_edit.textChanged.connect(self._schedule_preview)
        self.font_combo.currentIndexChanged.connect(self._schedule_preview)
        self.font_size.valueChanged.connect(self._schedule_preview)
        self.align_combo.currentIndexChanged.connect(self._schedule_preview)
        self.pad.valueChanged.connect(self._schedule_preview)
        self.cutmark.toggled.connect(self._schedule_preview)
        self.auto_cut.toggled.connect(self._schedule_preview)
        self.image_path.textChanged.connect(self._schedule_preview)

        self.image_browse.clicked.connect(self._on_browse_image)
        self.image_clear.clicked.connect(lambda: self.image_path.setText(""))
        self.show_cmd_btn.clicked.connect(self._on_show_cmd)
        self.print_btn.clicked.connect(self._on_print)

    # ---------- Font dropdown ----------

    def _populate_font_combo(self) -> None:
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        for label, entries in grouped():
            self.font_combo.addItem(f"── {label} ──")
            self.font_combo.model().item(self.font_combo.count() - 1).setEnabled(False)
            for e in entries:
                tag = "" if is_installed(e.family) else "  (not installed)"
                self.font_combo.addItem(f"{e.display}{tag}", userData=e.family)
        idx = self.font_combo.findData(DEFAULT_FAMILY)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_combo.blockSignals(False)

    def _refresh_font_list(self) -> None:
        current = self.font_combo.currentData() or DEFAULT_FAMILY
        self._populate_font_combo()
        idx = self.font_combo.findData(current)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self._schedule_preview()

    # ---------- Job + preview ----------

    def _current_job(self, *, for_preview: bool) -> PrintJob:
        text = self.text_edit.toPlainText()
        lines = [ln for ln in text.splitlines() if ln.strip() != ""][:4]
        align = {"left": "l", "center": "c", "right": "r"}[self.align_combo.currentText()]
        font_name = self.font_combo.currentData() or DEFAULT_FAMILY
        font_size = self.font_size.value() or None
        img = Path(self.image_path.text()).expanduser() if self.image_path.text().strip() else None
        return PrintJob(
            lines=lines,
            font=font_name,
            font_size=font_size,
            align=align,
            copies=self.copies.value(),
            pad=self.pad.value() or None,
            chain=not self.auto_cut.isChecked(),
            precut=self.precut.isChecked(),
            cutmark=self.cutmark.isChecked(),
            image=img if img and img.exists() else None,
            force_tape_width_px=(
                None if (self._printer_online and for_preview) else self._last_tape_px
            ),
        )

    def _schedule_preview(self) -> None:
        self._debounce.start()

    # ---------- Slots ----------

    def refresh_info(self) -> None:
        try:
            info = query_info()
        except PtouchError as exc:
            self._printer_online = False
            self._update_printer_view(found=False, err=str(exc), info=None)
            self.statusBar().showMessage(str(exc), 8000)
            return
        self._last_info_raw = info.raw
        if info.found:
            self._printer_online = True
            if info.tape_width_px:
                self._last_tape_px = info.tape_width_px
        else:
            self._printer_online = False
        self._update_printer_view(found=info.found, err=None, info=info)
        self._schedule_preview()

    def _update_printer_view(self, *, found: bool, err: str | None, info) -> None:
        # Printer tab
        if err:
            self.p_status.setText(f"<b style='color:#c33'>{err}</b>")
        elif found:
            self.p_status.setText("<b style='color:#2a8'>connected (USB)</b>")
        else:
            self.p_status.setText("<b style='color:#c33'>not detected</b>")
        if info:
            self.p_dpi.setText(f"{info.dpi or '?'} dpi")
            self.p_max_px.setText(f"{info.max_width_px or '?'} px")
            self.p_raw.setPlainText(info.raw)
        else:
            self.p_dpi.setText("—")
            self.p_max_px.setText("—")
            self.p_raw.setPlainText("")

        # Tape tab
        if info and info.found:
            self.t_width.setText(f"{info.media_width_mm or '?'} mm")
            self.t_usable.setText(f"{info.tape_width_px or '?'} px")
            self.t_media.setText(info.media_type or "—")
            self.t_tape_color.setText(info.tape_color or "—")
            self.t_text_color.setText(info.text_color or "—")
            color = "#2a8" if info.error_code == "0x0000" else "#c33"
            self.t_error.setText(
                f"<span style='color:{color}; font-family:monospace'>"
                f"{info.error_code or '—'}</span>"
            )
        else:
            self.t_width.setText(f"<i>offline — using {self._last_tape_px} px</i>")
            for w in (self.t_usable, self.t_media, self.t_tape_color,
                      self.t_text_color, self.t_error):
                w.setText("—")

    def _do_preview(self) -> None:
        job = self._current_job(for_preview=True)
        try:
            rc, out = render_preview(job, self._preview_path)
        except PtouchError as exc:
            self.preview_log.setPlainText(str(exc))
            return
        self.preview_log.setPlainText(out.strip() or f"(exit {rc})")
        if rc == 0 and self._preview_path.exists():
            pix = QPixmap(str(self._preview_path))
            if not pix.isNull():
                target_w = max(400, self.preview_label.width() - 16)
                scaled = pix.scaledToWidth(
                    target_w, Qt.TransformationMode.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled)
                self.preview_label.setText("")
                return
        self.preview_label.setText("(preview failed — see log)")

    def _on_browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose image", "", "PNG images (*.png);;All files (*)"
        )
        if path:
            self.image_path.setText(path)

    def _on_show_cmd(self) -> None:
        job = self._current_job(for_preview=False)
        argv = job.argv()
        QMessageBox.information(self, "ptouch-print invocation", shlex.join(argv))

    def _on_print(self) -> None:
        if not self._printer_online:
            QMessageBox.warning(
                self, "Printer offline",
                "Printer not detected. Switch to the Printer tab and refresh."
            )
            return
        job = self._current_job(for_preview=False)
        if not job.lines and not job.image:
            QMessageBox.warning(self, "Nothing to print",
                                "Enter text or pick an image first.")
            return
        try:
            rc, out = print_job(job)
        except PtouchError as exc:
            QMessageBox.critical(self, "Print error", str(exc))
            return
        self.preview_log.setPlainText(out.strip() or f"(exit {rc})")
        if rc == 0:
            self.statusBar().showMessage("Printed.", 4000)
        else:
            QMessageBox.critical(
                self, "Print failed",
                f"ptouch-print exited {rc}\n\n{out.strip()}"
            )


def main() -> int:
    app = QApplication([])
    w = LabelGUI()
    w.show()
    return app.exec()
