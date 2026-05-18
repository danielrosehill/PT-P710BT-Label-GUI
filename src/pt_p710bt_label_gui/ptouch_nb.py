"""In-process print backend using the vendored nbuchwitz/ptouch fork.

The patched ptouch library (LGPL-2.1-or-later, with our PT-P710BT and
--precut additions) lives at `pt_p710bt_label_gui._vendor.ptouch`. We
import it directly here — no subprocess, no separate venv, no PATH
hunting. Single integrated codebase.

In-process gives us proper exception handling and the ability to do a
USB reset if libusb returns "Resource busy" / "cannot open resource"
after an interrupted previous job.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

from ._vendor.ptouch.connection import ConnectionUSB, PrinterConnectionError
from ._vendor.ptouch.label import Label, TextLabel
from ._vendor.ptouch.printers import PTP710BT
from ._vendor.ptouch.tape import (
    Tape3_5mm,
    Tape6mm,
    Tape9mm,
    Tape12mm,
    Tape18mm,
    Tape24mm,
)


class NbPtouchError(RuntimeError):
    pass


_TAPE_BY_MM = {
    3.5: Tape3_5mm,
    6: Tape6mm,
    9: Tape9mm,
    12: Tape12mm,
    18: Tape18mm,
    24: Tape24mm,
}


def _tape(mm: float):
    cls = _TAPE_BY_MM.get(mm)
    if cls is None:
        # accept ints too (12 -> 12.0)
        cls = _TAPE_BY_MM.get(float(mm))
    if cls is None:
        raise NbPtouchError(f"Unsupported tape width: {mm} mm")
    return cls()


@dataclass
class NbJob:
    labels: list[str]               # one entry per distinct label (multi-line via \n)
    tape_width_mm: float            # 12 for 12mm tape
    copies: int = 1                 # multiplies labels
    font: str | None = None         # fontconfig family or .ttf path
    font_size: int | None = None    # px, or None for auto
    align_h: str = "center"         # left | center | right
    full_cut: bool = True           # PT-P710BT has no half-cut
    precut: bool = True             # eject the 24mm leader as a scrap first


def _resolve_font(family_or_path: str | None) -> str | None:
    """Resolve a font family name (or TTF path) to a TTF file path."""
    if not family_or_path:
        return None
    p = Path(family_or_path).expanduser()
    if p.exists() and p.is_file():
        return str(p)
    fc = shutil.which("fc-match")
    if not fc:
        return None
    try:
        cp = subprocess.run(
            [fc, "-f", "%{file}", family_or_path],
            capture_output=True, text=True, timeout=4,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    out = (cp.stdout or "").strip()
    return out or None


def _build_text_label(text: str, tape, font_family: str | None,
                      font_size_px: int | None):
    """Build a TextLabel. font_family can be a fontconfig family or TTF path."""
    font_path = _resolve_font(font_family)
    if font_path:
        try:
            font = ImageFont.truetype(font_path, font_size_px or 48)
        except OSError:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    # PIL's load_default() returns ImageFont.ImageFont; TextLabel requires
    # FreeTypeFont. If we didn't get a real font, fall back to a known
    # system font path (DejaVu is virtually always present on Linux).
    if not isinstance(font, ImageFont.FreeTypeFont):
        for fb in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ):
            if Path(fb).exists():
                font = ImageFont.truetype(fb, font_size_px or 48)
                break
    return TextLabel(text, tape=tape, font=font,
                     font_size=font_size_px,
                     auto_size=font_size_px is None)


def _print_with_reset_retry(printer_class, job: NbJob, *, attempts: int = 2):
    """Connect to printer, retrying with USB reset on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            connection = ConnectionUSB()
            printer = printer_class(connection)
            return printer
        except PrinterConnectionError as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "cannot open" in msg or "resource busy" in msg or "busy" in msg:
                # Try a USB reset before retrying.
                try:
                    import usb.core
                    dev = usb.core.find(idVendor=0x04F9, idProduct=0x20AF)
                    if dev is not None:
                        dev.reset()
                        time.sleep(0.4)
                except Exception:
                    pass
                if attempt < attempts - 1:
                    continue
            raise
    if last_exc:
        raise last_exc


def cut_tape(tape_width_mm: float) -> tuple[int, str]:
    """Send a feed-and-cut command — no printing. Returns (rc, log)."""
    try:
        tape = _tape(tape_width_mm)
    except NbPtouchError as exc:
        return 1, str(exc)
    try:
        printer = _print_with_reset_retry(PTP710BT, None)
    except PrinterConnectionError as exc:
        return 1, str(exc)
    try:
        printer.precut(tape)
        return 0, "Tape cut."
    except Exception as exc:
        return 1, f"Error: {exc}"
    finally:
        try:
            printer.disconnect()
        except Exception:
            pass


def print_job(job: NbJob) -> tuple[int, str]:
    """Run a multi-label print. Returns (exit_code, log_text)."""
    log_lines: list[str] = []

    def log(msg: str) -> None:
        log_lines.append(msg)

    try:
        tape = _tape(job.tape_width_mm)
    except NbPtouchError as exc:
        return 1, str(exc)

    # Expand labels by copies count.
    expanded_texts = [t for t in job.labels for _ in range(job.copies)]
    if not expanded_texts:
        return 1, "Nothing to print"

    log(f"Printing {len(expanded_texts)} label(s) to PT-P710BT via USB…")
    log(f"Tape: {job.tape_width_mm} mm  precut={job.precut}  full-cut={job.full_cut}")

    try:
        printer = _print_with_reset_retry(PTP710BT, job)
    except PrinterConnectionError as exc:
        return 1, f"{log_lines[0] if log_lines else ''}\n{exc}".strip()

    try:
        labels = [
            _build_text_label(t, tape, job.font, job.font_size)
            for t in expanded_texts
        ]
        if job.precut:
            printer.precut(tape)
        if len(labels) == 1:
            printer.print(labels[0])
        else:
            printer.print_multi(labels, half_cut=not job.full_cut)
        log("Done.")
        return 0, "\n".join(log_lines)
    except Exception as exc:
        log(f"Error: {exc}")
        return 1, "\n".join(log_lines)
    finally:
        try:
            printer.disconnect()
        except Exception:
            pass
