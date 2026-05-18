"""Print backend: nbuchwitz/ptouch (Python).

The default `ptouch-print` binary cannot do "one leading edge, full cut
between each copy" — it re-finalises per copy, replicating the ~24 mm
leader. nbuchwitz/ptouch can: `print_multi(labels)` sends one job with
multiple raster pages and a single leader.

Daniel's local PT-P710BT support patch lives on the branch
`add-pt-p710bt` of https://github.com/danielrosehill/ptouch (PR open
upstream against nbuchwitz/ptouch).

The library is consumed as a CLI (`python3 -m ptouch ...`) since this
GUI ships as a system .deb that doesn't bring its own venv. Interpreter
selection: env-var override → known venv path → system `python3`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PRINTER_NAME = "P710BT"

_ENV_OVERRIDE = "PT_P710BT_LABEL_GUI_NB_PYTHON"
_KNOWN_VENV_PATHS = [
    Path.home() / "repos/github/nbuchwitz-ptouch/.venv/bin/python",
]


class NbPtouchError(RuntimeError):
    pass


def find_python() -> str | None:
    """Return a Python interpreter that has the `ptouch` module importable."""
    candidates: list[str] = []
    env_path = os.environ.get(_ENV_OVERRIDE)
    if env_path:
        candidates.append(env_path)
    for p in _KNOWN_VENV_PATHS:
        if p.exists():
            candidates.append(str(p))
    sys_python = shutil.which("python3") or shutil.which("python")
    if sys_python:
        candidates.append(sys_python)

    for cand in candidates:
        try:
            cp = subprocess.run(
                [cand, "-c", "import ptouch"],
                capture_output=True, text=True, timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if cp.returncode == 0:
            return cand
    return None


def is_available() -> bool:
    return find_python() is not None


@dataclass
class NbJob:
    labels: list[str]               # one entry per distinct label (multi-line via \n)
    tape_width_mm: int              # 12 for 12mm tape
    copies: int = 1                 # multiplies the label list
    font: str | None = None         # fontconfig family or .ttf path
    font_size: int | None = None    # px, or None for auto
    align_h: str = "center"         # left | center | right
    full_cut: bool = True           # PT-P710BT has no half-cut


def build_argv(python: str, job: NbJob) -> list[str]:
    argv = [
        python, "-m", "ptouch",
        *job.labels,
        "--usb",
        "--printer", PRINTER_NAME,
        "--tape-width", str(job.tape_width_mm),
        "--align", job.align_h, "center",
        "--copies", str(job.copies),
    ]
    if job.full_cut:
        argv.append("--full-cut")
    if job.font:
        argv += ["--font", job.font]
    if job.font_size:
        argv += ["--font-size", str(job.font_size)]
    return argv


def print_job(job: NbJob, timeout: float = 120.0,
              python: str | None = None) -> tuple[int, str, list[str]]:
    """Run a multi-label print via nbuchwitz/ptouch.

    Returns (returncode, combined_output, argv). USB device access needs
    root unless udev rules are set; the caller may already be root, in
    which case sudo is skipped.
    """
    interp = python or find_python()
    if not interp:
        raise NbPtouchError(
            "The nbuchwitz/ptouch backend isn't installed. "
            "Install pyusb + the ptouch module (with PT-P710BT support) "
            "in a venv, then set "
            f"${_ENV_OVERRIDE} to that venv's python interpreter."
        )
    argv = build_argv(interp, job)
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or ""), argv
