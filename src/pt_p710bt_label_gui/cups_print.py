"""CUPS-based print backend using the philpem ptouch driver.

Sends a rendered PNG to a CUPS queue via `lp`. The philpem driver
(packaged as `printer-driver-ptouch` in Debian/Ubuntu) supports the
PT-P710BT natively and handles cut behaviour at the spool level —
including the "leader once + cut between each copy" pattern that
`ptouch-print` can't produce.

Discovery is automatic: any CUPS queue whose device URI matches the
PT-P710BT USB ID is a candidate. The user can override via the env
var `PT_P710BT_LABEL_GUI_CUPS_QUEUE`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_ENV_QUEUE = "PT_P710BT_LABEL_GUI_CUPS_QUEUE"
_USB_HINT = "PT-P710BT"


class CupsError(RuntimeError):
    pass


def find_queue() -> str | None:
    """Return the CUPS queue name for the PT-P710BT, or None if not configured."""
    override = os.environ.get(_ENV_QUEUE)
    if override:
        return override
    if not shutil.which("lpstat"):
        return None
    try:
        cp = subprocess.run(
            ["lpstat", "-v"], capture_output=True, text=True, timeout=4
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    # lines look like: "device for PT-P710BT: usb://Brother/PT-P710BT?serial=..."
    for line in cp.stdout.splitlines():
        if _USB_HINT in line and line.startswith("device for "):
            name = line.split("device for ", 1)[1].split(":", 1)[0].strip()
            return name
    # Fallback — return a printer named exactly that, if it exists at all.
    if shutil.which("lpstat"):
        try:
            cp = subprocess.run(
                ["lpstat", "-p"], capture_output=True, text=True, timeout=4
            )
            for line in cp.stdout.splitlines():
                if line.startswith("printer "):
                    parts = line.split()
                    if len(parts) >= 2 and _USB_HINT in parts[1]:
                        return parts[1]
        except subprocess.TimeoutExpired:
            pass
    return None


def is_available() -> bool:
    return find_queue() is not None


# CUPS option names (per the installed PT-P710BT PPD shipped by
# printer-driver-ptouch 1.7.1):
#   AutoCut    — cut between labels (default True)
#   AutoEject  — eject/feed after each label (default True). False = chain mode.
#   PageSize   — tape selection, e.g. "tz-12" for 12mm laminated TZe.
#   ExtraMargin — extra margin in mm.
#   MirrorPrint — bool.


@dataclass
class CupsJob:
    png_path: Path                 # rendered label PNG (mono or RGB)
    tape_width_mm: int             # 12 for 12mm tape
    copies: int = 1                # CUPS -n
    auto_cut: bool = True          # AutoCut
    chain_mode: bool = False       # if True → AutoEject=False (no eject; chain)
    extra_margin_mm: int = 0       # ExtraMargin
    mirror: bool = False           # MirrorPrint
    job_title: str = "label"


_TAPE_PAGE = {
    3.5: "tz-4",  # PPD uses "tz-4" for 3.5mm (per the lpoptions dump)
    6: "tz-6",
    9: "tz-9",
    12: "tz-12",
    18: "tz-18",
    24: "tz-24",
}


def _page_size(mm: int) -> str:
    return _TAPE_PAGE.get(mm, "tz-12")


def build_argv(queue: str, job: CupsJob) -> list[str]:
    argv = ["lp", "-d", queue, "-t", job.job_title, "-n", str(job.copies)]
    argv += ["-o", f"PageSize={_page_size(job.tape_width_mm)}"]
    argv += ["-o", f"AutoCut={'True' if job.auto_cut else 'False'}"]
    # AutoEject controls chain printing in the philpem PPD:
    #   AutoEject=True  → tape ejects after each label (default)
    #   AutoEject=False → chain mode (no per-label eject; labels back-to-back)
    argv += ["-o", f"AutoEject={'False' if job.chain_mode else 'True'}"]
    if job.extra_margin_mm:
        argv += ["-o", f"ExtraMargin={job.extra_margin_mm}mm"]
    if job.mirror:
        argv += ["-o", "MirrorPrint=True"]
    argv.append(str(job.png_path))
    return argv


def print_job(job: CupsJob, queue: str | None = None,
              timeout: float = 30.0) -> tuple[int, str, list[str]]:
    """Spool a print job via CUPS lp. Returns (rc, combined_output, argv)."""
    q = queue or find_queue()
    if not q:
        raise CupsError(
            "No CUPS queue found for the PT-P710BT. Install "
            "`printer-driver-ptouch` and add the printer via System Settings → "
            f"Printers, or set ${_ENV_QUEUE} to the queue name."
        )
    if not job.png_path.exists():
        raise CupsError(f"Render PNG missing: {job.png_path}")
    argv = build_argv(q, job)
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or ""), argv
