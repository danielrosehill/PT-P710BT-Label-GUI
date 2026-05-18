"""PyQt6 main window for PT-P710BT label GUI."""
from __future__ import annotations

import shlex
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QPixmap
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
    QVBoxLayout,
    QWidget,
)

from .font_install_dialog import FontInstallDialog
from .font_installer import is_installed
from .fonts import DEFAULT_FAMILY, grouped
from .ptouch import PrintJob, PtouchError, print_job, query_info, render_preview


PREVIEW_DEBOUNCE_MS = 350
DEFAULT_FALLBACK_TAPE_PX = 76  # 12mm


class LabelGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PT-P710BT Label GUI")
        self.resize(1100, 600)

        self._tmpdir = Path(tempfile.mkdtemp(prefix="pt-p710bt-"))
        self._preview_path = self._tmpdir / "preview.png"
        self._last_tape_px: int = DEFAULT_FALLBACK_TAPE_PX
        self._printer_online: bool = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(PREVIEW_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._do_preview)

        self._build_ui()
        self._build_menu()
        self._wire_signals()
        self.refresh_info()
        self._schedule_preview()

    def _build_menu(self) -> None:
        m_tools = self.menuBar().addMenu("&Tools")
        act_install = QAction("Install Google Fonts…", self)
        act_install.triggered.connect(self._open_font_installer)
        m_tools.addAction(act_install)
        act_refresh_fonts = QAction("Refresh font list", self)
        act_refresh_fonts.triggered.connect(self._refresh_font_list)
        m_tools.addAction(act_refresh_fonts)

    def _open_font_installer(self) -> None:
        dlg = FontInstallDialog(self)
        dlg.exec()
        self._refresh_font_list()

    def _refresh_font_list(self) -> None:
        current = self.font_combo.currentData() or DEFAULT_FAMILY
        self._populate_font_combo()
        idx = self.font_combo.findData(current)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self._schedule_preview()

    def _populate_font_combo(self) -> None:
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        for label, entries in grouped():
            # category separator
            self.font_combo.addItem(f"── {label} ──")
            self.font_combo.model().item(self.font_combo.count() - 1).setEnabled(False)
            for e in entries:
                tag = "" if is_installed(e.family) else "  (not installed)"
                self.font_combo.addItem(f"{e.display}{tag}", userData=e.family)
        # select default
        idx = self.font_combo.findData(DEFAULT_FAMILY)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_combo.blockSignals(False)

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ---- Left: controls ----
        left = QVBoxLayout()
        root.addLayout(left, 0)

        # Tape info panel
        info_box = QGroupBox("Tape")
        info_layout = QFormLayout(info_box)
        self.info_status = QLabel("—")
        self.info_width = QLabel("—")
        self.info_media = QLabel("—")
        self.info_colors = QLabel("—")
        self.info_error = QLabel("—")
        info_layout.addRow("Printer:", self.info_status)
        info_layout.addRow("Tape width:", self.info_width)
        info_layout.addRow("Media:", self.info_media)
        info_layout.addRow("Colors:", self.info_colors)
        info_layout.addRow("Error:", self.info_error)
        self.refresh_btn = QPushButton("Refresh tape info")
        info_layout.addRow(self.refresh_btn)
        left.addWidget(info_box)

        # Text
        text_box = QGroupBox("Text (up to 4 lines)")
        text_layout = QVBoxLayout(text_box)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Line 1\nLine 2\n…")
        self.text_edit.setFixedHeight(110)
        text_layout.addWidget(self.text_edit)
        left.addWidget(text_box)

        # Font / layout
        fmt_box = QGroupBox("Format")
        fmt_layout = QFormLayout(fmt_box)
        self.font_combo = QComboBox()
        self._populate_font_combo()
        self.font_size = QSpinBox()
        self.font_size.setRange(0, 200)
        self.font_size.setValue(0)
        self.font_size.setSpecialValueText("auto")
        self.align_combo = QComboBox()
        self.align_combo.addItems(["left", "center", "right"])
        self.align_combo.setCurrentIndex(1)
        fmt_layout.addRow("Font:", self.font_combo)
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
        self.precut = QCheckBox("Pre-cut (cut before label, chain mode only)")
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

        # Action buttons
        action_row = QHBoxLayout()
        self.show_cmd_btn = QPushButton("Show command")
        self.print_btn = QPushButton("Print")
        self.print_btn.setStyleSheet("font-weight: bold;")
        action_row.addWidget(self.show_cmd_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.print_btn)
        left.addLayout(action_row)
        left.addStretch(1)

        # ---- Right: preview ----
        right = QVBoxLayout()
        root.addLayout(right, 1)
        right.addWidget(QLabel("Preview (actual tape height, scaled to fit width):"))
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(120)
        self.preview_label.setStyleSheet("background: #222; color: #888; border: 1px solid #444;")
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

        self.setStatusBar(QStatusBar())

    def _wire_signals(self) -> None:
        self.refresh_btn.clicked.connect(self.refresh_info)
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

    # ---------- Helpers ----------

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
            self.info_status.setText(f"<b style='color:#c33'>missing dependency</b>")
            self.statusBar().showMessage(str(exc), 8000)
            return
        if info.found:
            self._printer_online = True
            self.info_status.setText("<b style='color:#2a8'>connected</b>")
            if info.tape_width_px:
                self._last_tape_px = info.tape_width_px
            self.info_width.setText(
                f"{info.media_width_mm or '?'} mm  ({info.tape_width_px or '?'} px usable)"
            )
            self.info_media.setText(info.media_type or "—")
            self.info_colors.setText(
                f"tape {info.tape_color or '?'} / text {info.text_color or '?'}"
            )
            err = info.error_code or "—"
            color = "#2a8" if err == "0x0000" else "#c33"
            self.info_error.setText(f"<span style='color:{color}'>{err}</span>")
        else:
            self._printer_online = False
            self.info_status.setText("<b style='color:#c33'>not detected</b>")
            self.info_width.setText(f"offline preview at {self._last_tape_px} px")
            self.info_media.setText("—")
            self.info_colors.setText("—")
            self.info_error.setText("—")
        self._schedule_preview()

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
                # Scale to fit label width while preserving aspect ratio.
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
        QMessageBox.information(
            self,
            "ptouch-print invocation",
            shlex.join(argv),
        )

    def _on_print(self) -> None:
        if not self._printer_online:
            QMessageBox.warning(
                self, "Printer offline",
                "Printer not detected. Click 'Refresh tape info' first."
            )
            return
        job = self._current_job(for_preview=False)
        if not job.lines and not job.image:
            QMessageBox.warning(self, "Nothing to print", "Enter text or pick an image first.")
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
