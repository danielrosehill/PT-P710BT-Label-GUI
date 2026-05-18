"""Thin wrapper around the `ptouch-print` CLI."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


BINARY = "ptouch-print"


class PtouchError(RuntimeError):
    pass


@dataclass
class TapeInfo:
    found: bool = False
    dpi: int | None = None
    max_width_px: int | None = None
    tape_width_px: int | None = None
    media_type: str | None = None
    media_width_mm: int | None = None
    tape_color: str | None = None
    text_color: str | None = None
    error_code: str | None = None
    raw: str = ""

    @property
    def ready(self) -> bool:
        return self.found and self.error_code in (None, "0x0000")


@dataclass
class PrintJob:
    lines: list[str] = field(default_factory=list)
    font: str | None = None
    font_size: int | None = None
    align: str = "c"          # l|c|r
    copies: int = 1
    pad: int | None = None
    chain: bool = False
    precut: bool = False
    cutmark: bool = False
    image: Path | None = None
    force_tape_width_px: int | None = None  # used for offline preview

    def argv(self, *, write_png: Path | None = None) -> list[str]:
        argv: list[str] = [BINARY]
        if self.font:
            argv += [f"--font={self.font}"]
        if self.font_size:
            argv += [f"--font-size={self.font_size}"]
        if self.copies and self.copies > 1 and write_png is None:
            argv += [f"--copies={self.copies}"]
        if write_png is not None:
            argv += [f"--writepng={write_png}"]
            if self.force_tape_width_px:
                argv += [f"--force-tape-width={self.force_tape_width_px}"]
        if self.chain and write_png is None:
            argv += ["--chain"]
        if self.precut and write_png is None:
            argv += ["--precut"]
        if self.cutmark:
            argv += ["--cutmark"]
        if self.pad:
            argv += [f"--pad={self.pad}"]
        argv += [f"--align={self.align}"]
        if self.image:
            argv += [f"--image={self.image}"]
        lines = [ln for ln in self.lines if ln != ""]
        if not lines and not self.image:
            lines = [" "]
        if lines:
            argv += [f"--text={lines[0]}"]
            for ln in lines[1:]:
                argv += [f"--newline={ln}"]
        return argv


def ensure_binary() -> None:
    if shutil.which(BINARY) is None:
        raise PtouchError(
            f"`{BINARY}` not found on PATH. Install from "
            "https://git.familie-radermacher.ch/linux/ptouch-print.git"
        )


def query_info(timeout: float = 5.0) -> TapeInfo:
    ensure_binary()
    info = TapeInfo()
    try:
        cp = subprocess.run(
            [BINARY, "--info"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PtouchError("ptouch-print --info timed out") from exc
    info.raw = (cp.stdout or "") + (cp.stderr or "")
    if "found" in info.raw:
        info.found = True
    for line in info.raw.splitlines():
        if m := re.search(r"(\d+)\s*dpi.*?(\d+)\s*px", line):
            info.dpi = int(m.group(1))
            info.max_width_px = int(m.group(2))
        elif m := re.search(r"maximum printing width for this tape is (\d+)px", line):
            info.tape_width_px = int(m.group(1))
        elif m := re.search(r"media type\s*=\s*(\S+)\s*\(([^)]+)\)", line):
            info.media_type = m.group(2)
        elif m := re.search(r"media width\s*=\s*(\d+)\s*mm", line):
            info.media_width_mm = int(m.group(1))
        elif m := re.search(r"tape color\s*=\s*\S+\s*\(([^)]+)\)", line):
            info.tape_color = m.group(1)
        elif m := re.search(r"text color\s*=\s*\S+\s*\(([^)]+)\)", line):
            info.text_color = m.group(1)
        elif m := re.search(r"error\s*=\s*(\S+)", line):
            info.error_code = m.group(1)
    if cp.returncode != 0 and not info.found:
        # not a hard error — caller decides; preserve stderr in raw
        pass
    return info


def render_preview(job: PrintJob, out_png: Path, timeout: float = 10.0) -> tuple[int, str]:
    ensure_binary()
    argv = job.argv(write_png=out_png)
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def print_job(job: PrintJob, timeout: float = 60.0) -> tuple[int, str]:
    ensure_binary()
    argv = job.argv(write_png=None)
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
