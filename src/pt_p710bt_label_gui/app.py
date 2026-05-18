"""PyQt6 main window for the PT-P710BT label GUI."""
from __future__ import annotations

import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .batch_tab import BatchRow, BatchTab
from .cups_print import CupsError, CupsJob
from .cups_print import find_queue as cups_find_queue
from .cups_print import print_job as cups_print_job
from .font_installer import is_installed, migrate_legacy_dir, refresh_cache
from .font_picker import FontPickerDialog
from .fonts import DEFAULT_FAMILY, contains_hebrew, grouped, is_hebrew_family
from .fonts_tab import FontsTab
from .ptouch import PrintJob, PtouchError, print_job, query_info, render_preview


PREVIEW_DEBOUNCE_MS = 350
DEFAULT_FALLBACK_TAPE_PX = 76  # 12mm
PRINTER_DPI = 180


@dataclass
class PreviewMeta:
    pixel_width: int
    pixel_height: int
    mm_length: float
    mm_width: float


class LabelGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PT-P710BT Label GUI")
        self.resize(1180, 760)

        self._tmpdir = Path(tempfile.mkdtemp(prefix="pt-p710bt-"))
        self._preview_path = self._tmpdir / "preview.png"
        self._last_tape_px: int = DEFAULT_FALLBACK_TAPE_PX
        self._last_tape_mm: int = 12
        self._printer_online: bool = False
        self._last_info_raw: str = ""
        self._zoom: int = 300  # percent
        self._exact_mode: bool = False

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
        self._update_text_direction()
        self._schedule_preview()

    # ---------- Tab construction ----------

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tabs.addTab(self._build_label_tab(),  "Label")
        self.batch_tab = BatchTab(
            job_factory=self._batch_job_factory,
            printer_online=lambda: self._printer_online,
        )
        self.tabs.addTab(self.batch_tab, "Batch")
        self.tabs.addTab(self._build_device_tab(), "Device")
        self.fonts_tab = FontsTab()
        self.fonts_tab.fonts_changed.connect(self._refresh_font_list)
        self.tabs.addTab(self.fonts_tab, "Fonts")

        self.setStatusBar(QStatusBar())

    # ----- Label tab -----

    def _build_label_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # Header status pill
        self.status_pill = QLabel("Checking printer…")
        self.status_pill.setStyleSheet(self._pill_style("neutral"))
        self.status_pill.setMaximumHeight(28)
        root.addWidget(self.status_pill)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Left column
        left = QVBoxLayout()
        left.setSpacing(8)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setMinimumWidth(320)
        left_wrap.setMaximumWidth(380)
        body.addWidget(left_wrap, 0)

        # Text
        text_box = QGroupBox("Text (up to 4 lines)")
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(8, 8, 8, 8)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Line 1\nLine 2\n…")
        self.text_edit.setFixedHeight(96)
        text_layout.addWidget(self.text_edit)
        left.addWidget(text_box)

        # Format + Print options (combined)
        opts_box = QGroupBox("Format & print options")
        form = QFormLayout(opts_box)
        form.setContentsMargins(8, 8, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        self.font_combo = QComboBox()
        self._populate_font_combo()
        self.font_combo.setVisible(False)  # kept for data lookup; UI uses the picker button
        self.font_button = QPushButton()
        self.font_button.setText(DEFAULT_FAMILY)
        self.font_button.setStyleSheet("text-align: left; padding: 4px 8px;")
        self.font_button.clicked.connect(self._on_open_font_picker)
        form.addRow("Font:", self.font_button)

        size_align = QHBoxLayout()
        self.font_size = QSpinBox()
        self.font_size.setRange(0, 200)
        self.font_size.setValue(0)
        self.font_size.setSpecialValueText("auto")
        self.align_combo = QComboBox()
        self.align_combo.addItems(["left", "center", "right"])
        self.align_combo.setCurrentIndex(1)
        size_align.addWidget(QLabel("Size:"))
        size_align.addWidget(self.font_size, 1)
        size_align.addWidget(QLabel("Align:"))
        size_align.addWidget(self.align_combo, 1)
        sa_wrap = QWidget()
        sa_wrap.setLayout(size_align)
        size_align.setContentsMargins(0, 0, 0, 0)
        form.addRow(sa_wrap)

        copies_row = QHBoxLayout()
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.copies.setValue(1)
        self.copies.setToolTip(
            "With auto-cut ON: each copy is printed and cut separately. "
            "The ~24 mm head-to-cutter mechanical gap means each cut leaves "
            "a leading bleed on the next copy — this is physical and "
            "unavoidable.\n\n"
            "With auto-cut OFF: all copies print as one continuous strip "
            "with no cuts between (you cut manually). No wasted tape."
        )
        copies_row.addWidget(QLabel("Copies:"))
        copies_row.addWidget(self.copies, 1)
        copies_row.addStretch(1)
        cp_wrap = QWidget()
        cp_wrap.setLayout(copies_row)
        copies_row.setContentsMargins(0, 0, 0, 0)
        form.addRow(cp_wrap)

        margins_row = QHBoxLayout()
        self.margin_l = QDoubleSpinBox()
        self.margin_l.setRange(0.0, 50.0)
        self.margin_l.setSingleStep(0.5)
        self.margin_l.setSuffix(" mm")
        self.margin_l.setValue(2.0)
        self.margin_r = QDoubleSpinBox()
        self.margin_r.setRange(0.0, 50.0)
        self.margin_r.setSingleStep(0.5)
        self.margin_r.setSuffix(" mm")
        self.margin_r.setValue(2.0)
        self.margin_link = QCheckBox("link")
        self.margin_link.setChecked(True)
        self.margin_link.setToolTip("When ticked, right margin mirrors left.")
        margins_row.addWidget(QLabel("Margin L:"))
        margins_row.addWidget(self.margin_l, 1)
        margins_row.addWidget(QLabel("R:"))
        margins_row.addWidget(self.margin_r, 1)
        margins_row.addWidget(self.margin_link)
        m_wrap = QWidget()
        m_wrap.setLayout(margins_row)
        margins_row.setContentsMargins(0, 0, 0, 0)
        form.addRow(m_wrap)

        self.fill_height = QCheckBox("Fill tape height (auto-size to fit)")
        self.fill_height.setChecked(False)
        self.fill_height.setToolTip(
            "When ON, auto-size text to fill the tape height. "
            "When OFF, use a conservative size (~60% of tape height)."
        )
        self.auto_cut = QCheckBox("Auto-cut after print")
        self.auto_cut.setChecked(True)
        self.auto_cut.setToolTip(
            "When OFF, runs in chain mode (continuous tape, no cut between)."
        )
        self.precut = QCheckBox("Pre-cut (chain mode only)")
        self.cutmark = QCheckBox("Print cut-mark")

        form.addRow(self.fill_height)
        form.addRow(self.auto_cut)
        form.addRow(self.precut)
        form.addRow(self.cutmark)
        left.addWidget(opts_box)

        # Image
        img_box = QGroupBox("Image (optional)")
        img_layout = QHBoxLayout(img_box)
        img_layout.setContentsMargins(8, 8, 8, 8)
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
        self.show_cmd_btn = QToolButton()
        self.show_cmd_btn.setText("Show command")
        self.show_cmd_btn.setAutoRaise(True)
        self.print_btn = QPushButton("Print")
        self.print_btn.setDefault(True)
        self.print_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 8px 24px; "
            "background: #2a7ae0; color: white; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #1c5fc0; }"
            "QPushButton:disabled { background: #888; }"
        )
        action_row.addWidget(self.show_cmd_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.print_btn)
        left.addLayout(action_row)
        left.addStretch(1)

        # Right column: preview
        right = QVBoxLayout()
        right.setSpacing(6)
        body.addLayout(right, 1)

        # Preview header row: title + meta + zoom + mode toggle
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Preview</b>"))
        self.preview_meta = QLabel("—")
        self.preview_meta.setStyleSheet("color: #666;")
        head.addWidget(self.preview_meta)
        head.addStretch(1)
        head.addWidget(QLabel("Zoom:"))
        self.zoom_combo = QComboBox()
        for z in (100, 200, 300, 400, 600, 800):
            self.zoom_combo.addItem(f"{z}%", z)
        self.zoom_combo.setCurrentIndex(2)  # 300%
        head.addWidget(self.zoom_combo)
        self.exact_chk = QCheckBox("Exact (pixel-accurate)")
        self.exact_chk.setToolTip(
            "Off: smooth Qt preview (approximate). "
            "On: use ptouch-print --writepng for an exact rendering of what will print."
        )
        head.addWidget(self.exact_chk)
        right.addLayout(head)

        # Preview canvas
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(140)
        self.preview_label.setStyleSheet(
            "background: #fafafa; color: #888; "
            "border: 1px solid #cfcfcf; border-radius: 4px; padding: 8px;"
        )
        self.preview_label.setText("(no preview yet)")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        right.addWidget(scroll, 1)

        # Collapsible log toggle
        log_head = QHBoxLayout()
        self.log_toggle = QToolButton()
        self.log_toggle.setText("▸ ptouch-print output")
        self.log_toggle.setAutoRaise(True)
        self.log_toggle.setCheckable(True)
        log_head.addWidget(self.log_toggle)
        log_head.addStretch(1)
        right.addLayout(log_head)

        self.preview_log = QPlainTextEdit()
        self.preview_log.setReadOnly(True)
        self.preview_log.setMaximumHeight(110)
        self.preview_log.setPlaceholderText("ptouch-print output appears here")
        self.preview_log.setVisible(False)
        self.preview_log.setStyleSheet("font-family: monospace; font-size: 11px;")
        right.addWidget(self.preview_log)

        return w

    # ----- Device tab (merged printer + tape) -----

    def _build_device_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        box = QGroupBox("Printer")
        form = QFormLayout(box)
        self.p_status = QLabel("—")
        self.p_dpi = QLabel("—")
        self.p_max_px = QLabel("—")
        form.addRow("Status:", self.p_status)
        form.addRow("Resolution:", self.p_dpi)
        form.addRow("Max print width:", self.p_max_px)
        layout.addWidget(box)

        tbox = QGroupBox("Tape")
        tform = QFormLayout(tbox)
        self.t_width = QLabel("—")
        self.t_usable = QLabel("—")
        self.t_media = QLabel("—")
        self.t_tape_color = QLabel("—")
        self.t_text_color = QLabel("—")
        self.t_error = QLabel("—")
        tform.addRow("Cassette width:", self.t_width)
        tform.addRow("Usable print height:", self.t_usable)
        tform.addRow("Media type:", self.t_media)
        tform.addRow("Tape colour:", self.t_tape_color)
        tform.addRow("Text colour:", self.t_text_color)
        tform.addRow("Error byte:", self.t_error)
        layout.addWidget(tbox)

        info_box = QGroupBox("Raw ptouch-print --info output")
        info_layout = QVBoxLayout(info_box)
        self.p_raw = QPlainTextEdit()
        self.p_raw.setReadOnly(True)
        self.p_raw.setMaximumHeight(180)
        self.p_raw.setStyleSheet("font-family: monospace;")
        info_layout.addWidget(self.p_raw)
        layout.addWidget(info_box)

        self.p_refresh_btn = QPushButton("Refresh device info")
        layout.addWidget(self.p_refresh_btn)

        notes = QLabel(
            "<i>Queried via <code>ptouch-print --info</code> over USB. "
            "0x0000 = ready. 0x0100 typically indicates cover/tape issue. "
            "After interruptions a power-cycle may be needed.</i>"
        )
        notes.setWordWrap(True)
        layout.addWidget(notes)
        layout.addStretch(1)
        return w

    # ---------- Wiring ----------

    def _wire_signals(self) -> None:
        self.p_refresh_btn.clicked.connect(self.refresh_info)

        self.text_edit.textChanged.connect(self._schedule_preview)
        self.text_edit.textChanged.connect(self._update_text_direction)
        self.font_combo.currentIndexChanged.connect(self._schedule_preview)
        self.font_combo.currentIndexChanged.connect(self._update_text_direction)
        self.font_combo.currentIndexChanged.connect(self._sync_font_button)
        self.font_size.valueChanged.connect(self._schedule_preview)
        self.align_combo.currentIndexChanged.connect(self._schedule_preview)
        self.margin_l.valueChanged.connect(self._on_margin_l_changed)
        self.margin_r.valueChanged.connect(self._schedule_preview)
        self.margin_link.toggled.connect(self._on_margin_link_toggled)
        self.cutmark.toggled.connect(self._schedule_preview)
        self.auto_cut.toggled.connect(self._schedule_preview)
        self.fill_height.toggled.connect(self._schedule_preview)
        self.image_path.textChanged.connect(self._schedule_preview)

        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        self.exact_chk.toggled.connect(self._on_exact_toggled)

        self.image_browse.clicked.connect(self._on_browse_image)
        self.image_clear.clicked.connect(lambda: self.image_path.setText(""))
        self.show_cmd_btn.clicked.connect(self._on_show_cmd)
        self.print_btn.clicked.connect(self._on_print)

        self.log_toggle.toggled.connect(self._on_log_toggled)

    def _is_rtl(self) -> bool:
        """RTL if a Hebrew-category font is chosen OR text contains Hebrew chars."""
        family = self.font_combo.currentData() or ""
        if is_hebrew_family(family):
            return True
        return contains_hebrew(self.text_edit.toPlainText())

    def _update_text_direction(self) -> None:
        rtl = self._is_rtl()
        opt = self.text_edit.document().defaultTextOption()
        from PyQt6.QtGui import QTextOption
        opt.setTextDirection(
            Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        )
        # default alignment for RTL is right
        if rtl:
            opt.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            opt.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.text_edit.document().setDefaultTextOption(opt)
        self.text_edit.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        )

    def _on_log_toggled(self, on: bool) -> None:
        self.preview_log.setVisible(on)
        self.log_toggle.setText(("▾ " if on else "▸ ") + "ptouch-print output")

    def _on_margin_l_changed(self, value: float) -> None:
        if self.margin_link.isChecked():
            self.margin_r.blockSignals(True)
            self.margin_r.setValue(value)
            self.margin_r.blockSignals(False)
        self._schedule_preview()

    def _on_margin_link_toggled(self, on: bool) -> None:
        if on:
            self.margin_r.blockSignals(True)
            self.margin_r.setValue(self.margin_l.value())
            self.margin_r.blockSignals(False)
            self._schedule_preview()

    @staticmethod
    def _margin_px(mm: float) -> int:
        return int(round(mm / 25.4 * PRINTER_DPI))

    def _on_open_font_picker(self) -> None:
        current = self.font_combo.currentData() or DEFAULT_FAMILY
        dlg = FontPickerDialog(self, current_family=current)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        family = dlg.selected_family()
        if not family:
            return
        idx = self.font_combo.findData(family)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_button.setText(family)

    def _sync_font_button(self) -> None:
        fam = self.font_combo.currentData() or DEFAULT_FAMILY
        self.font_button.setText(fam)

    def _on_zoom_changed(self) -> None:
        self._zoom = self.zoom_combo.currentData()
        self._schedule_preview()

    def _on_exact_toggled(self, on: bool) -> None:
        self._exact_mode = on
        self._schedule_preview()

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

    # ---------- Job ----------

    def _current_job(self, *, for_preview: bool, lines_override: list[str] | None = None,
                     copies_override: int | None = None) -> PrintJob:
        if lines_override is None:
            text = self.text_edit.toPlainText()
            lines = [ln for ln in text.splitlines() if ln.strip() != ""][:4]
        else:
            lines = lines_override[:4]
        align = {"left": "l", "center": "c", "right": "r"}[self.align_combo.currentText()]
        font_name = self.font_combo.currentData() or DEFAULT_FAMILY
        font_size = self.font_size.value() or None
        img = Path(self.image_path.text()).expanduser() if self.image_path.text().strip() else None
        return PrintJob(
            lines=lines,
            font=font_name,
            font_size=font_size,
            align=align,
            copies=copies_override if copies_override is not None else self.copies.value(),
            pad_left=self._margin_px(self.margin_l.value()) or None,
            pad_right=self._margin_px(self.margin_r.value()) or None,
            chain=not self.auto_cut.isChecked(),
            precut=self.precut.isChecked(),
            cutmark=self.cutmark.isChecked(),
            image=img if img and img.exists() else None,
            force_tape_width_px=(
                None if (self._printer_online and for_preview) else self._last_tape_px
            ),
        )

    def _batch_job_factory(self, row: BatchRow) -> PrintJob:
        # split on \n so batch rows can have multi-line text too
        lines = [ln for ln in row.text.splitlines() if ln.strip()][:4] or [row.text]
        return self._current_job(
            for_preview=False, lines_override=lines, copies_override=row.copies
        )

    def _schedule_preview(self) -> None:
        self._debounce.start()

    # ---------- Status pill ----------

    @staticmethod
    def _pill_style(kind: str) -> str:
        palettes = {
            "ok":      ("#e6f5ec", "#1e7f3a"),
            "warn":    ("#fff4d6", "#8a6500"),
            "err":     ("#fbe6e6", "#a01b1b"),
            "neutral": ("#eee", "#444"),
        }
        bg, fg = palettes.get(kind, palettes["neutral"])
        return (
            f"background: {bg}; color: {fg}; "
            "padding: 4px 10px; border-radius: 12px; font-weight: 600;"
        )

    # ---------- Slots ----------

    def refresh_info(self) -> None:
        try:
            info = query_info()
        except PtouchError as exc:
            self._printer_online = False
            self._update_printer_view(found=False, err=str(exc), info=None)
            self._set_pill("err", f"⚠ {exc}")
            self.statusBar().showMessage(str(exc), 8000)
            return
        self._last_info_raw = info.raw
        if info.found:
            self._printer_online = True
            if info.tape_width_px:
                self._last_tape_px = info.tape_width_px
            if info.media_width_mm:
                self._last_tape_mm = info.media_width_mm
        else:
            self._printer_online = False
        self._update_printer_view(found=info.found, err=None, info=info)

        if info.found and info.ready:
            self._set_pill(
                "ok",
                f"● Printer connected · {info.media_width_mm or '?'} mm tape · ready",
            )
        elif info.found:
            self._set_pill("warn", f"● Connected · error byte {info.error_code}")
        else:
            self._set_pill("err", "● Printer not detected")
        self._schedule_preview()

    def _set_pill(self, kind: str, text: str) -> None:
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(self._pill_style(kind))

    def _update_printer_view(self, *, found: bool, err: str | None, info) -> None:
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

    # ---------- Preview ----------

    def _do_preview(self) -> None:
        if self._exact_mode:
            self._do_exact_preview()
        else:
            self._do_soft_preview()

    def _do_exact_preview(self) -> None:
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
                self._apply_preview_pixmap(pix, source_px=(pix.width(), pix.height()))
                return
        self.preview_label.setText("(preview failed — see log)")

    def _do_soft_preview(self) -> None:
        """Render preview with QPainter at high res (anti-aliased)."""
        text = self.text_edit.toPlainText()
        lines = [ln for ln in text.splitlines() if ln.strip() != ""][:4] or [""]
        tape_px = self._last_tape_px
        # Pick font size: user-specified, or auto.
        # Fill mode: 90% of available per-line height.
        # Conservative (default): 60% of available per-line height.
        fill = self.fill_height.isChecked()
        scale = 0.85 if fill else 0.55
        if self.font_size.value() > 0:
            target_px = self.font_size.value()
        else:
            target_px = int(tape_px / max(1, len(lines)) * scale)

        font_family = self.font_combo.currentData() or DEFAULT_FAMILY
        font = QFont(font_family)
        font.setPixelSize(max(6, target_px))

        # Measure to size canvas — true label width (no square minimum).
        fm = QFontMetricsF(font)
        line_h = fm.height()
        widths = [fm.horizontalAdvance(ln) for ln in lines]
        text_w = max(widths) if widths else 0
        pad_l = self._margin_px(self.margin_l.value())
        pad_r = self._margin_px(self.margin_r.value())
        # Minimum width keeps the preview reading horizontally even when empty.
        canvas_w = max(int(text_w + pad_l + pad_r), int(tape_px * 2.5))
        canvas_h = tape_px

        img = QImage(canvas_w, canvas_h, QImage.Format.Format_RGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(QColor("#000000"))
        p.setFont(font)

        align_str = self.align_combo.currentText()
        flag_h = {
            "left":   Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right":  Qt.AlignmentFlag.AlignRight,
        }[align_str]

        rtl = self._is_rtl()
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QTextOption
        opt = QTextOption()
        opt.setAlignment(flag_h | Qt.AlignmentFlag.AlignTop)
        opt.setTextDirection(
            Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        )
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)

        # Vertically centre on the *visible ink* (tightBoundingRect), not on
        # font ascent/descent — otherwise digits/caps drift toward the bottom
        # of the printable area because Qt reserves descender space.
        sample = next((ln for ln in lines if ln.strip()), "Mg")
        ink = fm.tightBoundingRect(sample)
        if ink.height() <= 0:
            ink = fm.tightBoundingRect("Mg")

        n = len(lines)
        block_h = (n - 1) * line_h + ink.height()
        block_top = (canvas_h - block_h) / 2
        first_baseline = block_top - ink.y()  # ink.y() is negative for ascenders

        for i, ln in enumerate(lines):
            baseline = first_baseline + i * line_h
            rect_y = baseline - fm.ascent()
            rect = QRectF(pad_l, rect_y, canvas_w - pad_l - pad_r, line_h)
            p.drawText(rect, ln, opt)
        p.end()

        pix = QPixmap.fromImage(img)
        self._apply_preview_pixmap(pix, source_px=(canvas_w, canvas_h))
        self.preview_log.setPlainText(
            f"(soft preview — {canvas_w}×{canvas_h} px @ font {target_px}px, "
            f"{'fill' if fill else 'conservative'})"
        )

    def _apply_preview_pixmap(self, pix: QPixmap, source_px: tuple[int, int]) -> None:
        src_w, src_h = source_px
        zoom = self._zoom / 100.0
        # Scale the label first, then composite annotations at display scale
        # so the annotation text stays readable regardless of zoom.
        scaled_label = pix.scaledToHeight(
            max(1, int(src_h * zoom)), Qt.TransformationMode.SmoothTransformation
        )
        mm_length = src_w / PRINTER_DPI * 25.4
        mm_printable = src_h / PRINTER_DPI * 25.4
        # Show the physical tape width as the height dimension — matches what the
        # user sees in their hand. Printable area is narrower (margin top/bottom).
        mm_tape = float(self._last_tape_mm)
        annotated = self._annotate_label(scaled_label, mm_length, mm_tape, mm_printable)

        self.preview_label.setPixmap(annotated)
        self.preview_label.setText("")
        self.preview_label.setMinimumSize(annotated.size())

        rtl_tag = " · RTL" if self._is_rtl() else ""
        self.preview_meta.setText(
            f"{src_w}×{src_h} px · {mm_length:.1f} mm long · "
            f"{mm_tape:.0f} mm tape ({mm_printable:.1f} mm printable){rtl_tag}"
        )

    @staticmethod
    def _annotate_label(label_pix: QPixmap, mm_length: float,
                        mm_tape: float, mm_printable: float) -> QPixmap:
        """Wrap printable label pixmap inside a tape strip, with dimension arrows."""
        pw, ph = label_pix.width(), label_pix.height()
        strip_h = int(ph * (mm_tape / mm_printable)) if mm_printable > 0 else ph
        band_h = max(1, (strip_h - ph) // 2)
        sw = pw
        sh = ph + 2 * band_h

        left_margin = 60
        right_margin = 16
        top_margin = 18
        bottom_margin = 44

        cw = sw + left_margin + right_margin
        ch = sh + top_margin + bottom_margin

        out = QPixmap(cw, ch)
        out.fill(QColor("#fafafa"))
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        sx, sy = left_margin, top_margin
        # Full tape strip background + non-printable bands.
        p.fillRect(sx, sy, sw, sh, QColor("#ffffff"))
        p.fillRect(sx, sy, sw, band_h, QColor("#f0f0f0"))
        p.fillRect(sx, sy + sh - band_h, sw, band_h, QColor("#f0f0f0"))
        p.drawPixmap(sx, sy + band_h, label_pix)
        p.setPen(QPen(QColor("#888"), 1))
        p.drawRect(sx, sy, sw, sh)
        p.setPen(QPen(QColor("#d0d0d0"), 1, Qt.PenStyle.DotLine))
        p.drawLine(sx, sy + band_h, sx + sw, sy + band_h)
        p.drawLine(sx, sy + sh - band_h, sx + sw, sy + sh - band_h)

        ann = QPen(QColor("#333"), 1)
        p.setPen(ann)
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        fm = QFontMetricsF(f)

        # --- vertical (tape height) dimension on the left ---
        ax = sx - 22
        p.drawLine(ax, sy, ax, sy + sh)
        for y, dy in ((sy, 4), (sy + sh, -4)):
            p.drawLine(ax, y, ax - 3, y + dy)
            p.drawLine(ax, y, ax + 3, y + dy)
        p.setPen(QPen(QColor("#bbb"), 1, Qt.PenStyle.DashLine))
        p.drawLine(ax + 1, sy, sx, sy)
        p.drawLine(ax + 1, sy + sh, sx, sy + sh)
        p.setPen(ann)
        p.save()
        p.translate(ax - 8, sy + sh / 2)
        p.rotate(-90)
        txt = f"{mm_tape:.0f} mm tape"
        p.drawText(int(-fm.horizontalAdvance(txt) / 2), int(fm.ascent() / 2), txt)
        p.restore()

        # Aliases used by the bottom-dimension code below.
        lx, ly, lw, lh = sx, sy, sw, sh

        # --- horizontal (length) dimension on the bottom ---
        ay = ly + lh + 18
        p.drawLine(lx, ay, lx + lw, ay)
        for x, dx in ((lx, 4), (lx + lw, -4)):
            p.drawLine(x, ay, x + dx, ay - 3)
            p.drawLine(x, ay, x + dx, ay + 3)
        p.setPen(QPen(QColor("#bbb"), 1, Qt.PenStyle.DashLine))
        p.drawLine(lx, ay - 1, lx, ly + lh)
        p.drawLine(lx + lw, ay - 1, lx + lw, ly + lh)
        p.setPen(ann)
        txt = f"{mm_length:.1f} mm"
        tw = fm.horizontalAdvance(txt)
        p.drawText(int(lx + lw / 2 - tw / 2), int(ay + 14), txt)

        p.end()
        return out

    # ---------- Misc slots ----------

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
                "Printer not detected. Switch to the Device tab and refresh."
            )
            return
        job = self._current_job(for_preview=False)
        if not job.lines and not job.image:
            QMessageBox.warning(self, "Nothing to print",
                                "Enter text or pick an image first.")
            return
        self._print_via_cups(job)

    def _print_via_cups(self, job: PrintJob) -> None:
        # 1. Render the label PNG ourselves in portrait (W = tape width,
        #    H = label length), at 180 DPI to match the printer's native res.
        #    The PNG dimensions are then mirrored in a Custom CUPS PageSize
        #    so the driver doesn't scale to fit a fixed page.
        png_w_px, png_h_px = self._render_print_png(job, self._preview_path)
        if png_w_px == 0 or png_h_px == 0:
            QMessageBox.critical(self, "Render failed", "Empty label.")
            return
        page_w_pt = png_w_px / PRINTER_DPI * 72.0
        page_h_pt = png_h_px / PRINTER_DPI * 72.0
        auto_cut = self.auto_cut.isChecked()
        cups_job = CupsJob(
            png_path=self._preview_path,
            tape_width_mm=self._last_tape_mm,
            copies=job.copies,
            auto_cut=auto_cut,
            chain_mode=not auto_cut,
            job_title=("label" if not job.lines else " | ".join(job.lines)[:64]),
            custom_page_w_pt=page_w_pt,
            custom_page_h_pt=page_h_pt,
        )
        try:
            rc, out, argv = cups_print_job(cups_job)
        except CupsError as exc:
            QMessageBox.critical(self, "CUPS error", str(exc))
            return
        self.preview_log.setPlainText(
            f"$ {' '.join(argv)}\n(exit {rc})\n{out.strip()}"
        )
        if rc != 0:
            QMessageBox.critical(
                self, "Print failed",
                f"lp exited {rc}\n\n{out.strip()}"
            )
            return
        self.statusBar().showMessage(
            f"Spooled {job.copies} {'copy' if job.copies == 1 else 'copies'} to CUPS.",
            4000,
        )

    def _render_print_png(self, job: PrintJob, out_png: Path) -> tuple[int, int]:
        """Render the print PNG in portrait at 180 DPI (W = tape width).

        Returns (width_px, height_px) of the written PNG.
        """
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QTextOption
        text = self.text_edit.toPlainText()
        lines = [ln for ln in text.splitlines() if ln.strip() != ""][:4] or [""]
        # Tape width in pixels at 180 DPI (full physical tape, not just
        # printable). The driver maps PageSize → printable area internally.
        tape_w_px = int(round(self._last_tape_mm / 25.4 * PRINTER_DPI))
        printable_h = self._last_tape_px  # what ptouch-print reports as printable
        # Vertical band offset (centre the printable area within the tape width).
        band = max(0, (tape_w_px - printable_h) // 2)

        # Font sizing — same logic as the soft preview.
        fill = self.fill_height.isChecked()
        scale = 0.85 if fill else 0.55
        if self.font_size.value() > 0:
            target_px = self.font_size.value()
        else:
            target_px = int(printable_h / max(1, len(lines)) * scale)
        family = self.font_combo.currentData() or DEFAULT_FAMILY
        font = QFont(family)
        font.setPixelSize(max(6, target_px))
        fm = QFontMetricsF(font)
        line_h = fm.height()
        widths = [fm.horizontalAdvance(ln) for ln in lines]
        text_w = int(max(widths) if widths else 0)
        pad_l = self._margin_px(self.margin_l.value())
        pad_r = self._margin_px(self.margin_r.value())
        # Portrait: width = tape, height = label length.
        content_h_px = max(text_w + pad_l + pad_r, int(tape_w_px * 0.5))
        img = QImage(tape_w_px, content_h_px, QImage.Format.Format_RGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(QColor("#000000"))
        p.setFont(font)
        # Draw the label horizontally in a virtual canvas, then map to portrait
        # by rotating the painter -90° about the centre.
        p.translate(tape_w_px / 2.0, content_h_px / 2.0)
        p.rotate(-90)
        # After rotation, the local coordinate system is:
        #   x ∈ [-content_h/2, +content_h/2]  along the label length
        #   y ∈ [-tape_w/2, +tape_w/2]        along the tape width
        # Translate origin to the top-left of the horizontal label.
        p.translate(-content_h_px / 2.0, -tape_w_px / 2.0)
        canvas_w, canvas_h = content_h_px, tape_w_px

        align_str = self.align_combo.currentText()
        flag_h = {
            "left":   Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right":  Qt.AlignmentFlag.AlignRight,
        }[align_str]
        rtl = self._is_rtl()
        opt = QTextOption()
        opt.setAlignment(flag_h | Qt.AlignmentFlag.AlignTop)
        opt.setTextDirection(
            Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        )
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)

        sample = next((ln for ln in lines if ln.strip()), "Mg")
        ink = fm.tightBoundingRect(sample)
        if ink.height() <= 0:
            ink = fm.tightBoundingRect("Mg")
        n = len(lines)
        block_h = (n - 1) * line_h + ink.height()
        block_top = band + (printable_h - block_h) / 2  # centred in printable area
        first_baseline = block_top - ink.y()

        for i, ln in enumerate(lines):
            baseline = first_baseline + i * line_h
            rect_y = baseline - fm.ascent()
            rect = QRectF(pad_l, rect_y, canvas_w - pad_l - pad_r, line_h)
            p.drawText(rect, ln, opt)
        p.end()
        img.save(str(out_png), "PNG")
        return tape_w_px, content_h_px


def main() -> int:
    app = QApplication([])
    w = LabelGUI()
    w.show()
    return app.exec()
