# Sprint: v1 MVP

**Started:** 2026-05-18

## Goal

Working PyQt6 app that can print a multi-line label with live preview on the PT-P710BT.

## Outstanding tasks

- [ ] `pyproject.toml` with PyQt6 + entry point `ptouch-gui`
- [ ] `src/ptouch_gui/printer.py` — subprocess wrapper around `ptouch-print` (info, preview, print)
- [ ] `src/ptouch_gui/main.py` — Qt window with:
  - tape status bar (width, color, error) auto-refreshed
  - text input (up to 4 lines via separate fields or one `\n`-separated field)
  - font picker (`QFontDialog`)
  - alignment radio (l/c/r)
  - copies spinner
  - chain + precut toggles
  - "preview" pane showing the `--writepng` output at actual scale
  - "print" button
- [ ] Debounced auto-preview on text change
- [ ] Friendly error if `ptouch-print` not found or printer not connected
- [ ] `scripts/install.sh` — one-shot dep install (build ptouch-print + pipx install this)
- [ ] Test print: "5745 - Notes" through the GUI matches CLI output
