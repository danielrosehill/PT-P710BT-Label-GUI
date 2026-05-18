# GUI framework choice

**Date:** 2026-05-18
**Status:** chosen

## Context

Need a desktop GUI on Ubuntu 25.10 + KDE Plasma 6 (Wayland) for a small single-purpose label printer wrapper. Single user (workstation tool), one printer model. Must run reliably on Wayland.

## Options considered

- **PyQt6 / PySide6** — Qt6 is native on KDE, themes match the desktop automatically, excellent Wayland support, great widget set, mature Python bindings. Slightly heavier dep.
- **GTK4 (PyGObject)** — Wayland-native, but visually foreign on KDE without effort; default styling will look out of place.
- **Tkinter** — bundled, zero deps, but ugly on KDE, poor HiDPI handling, awkward layouts for a preview pane.
- **Web UI (FastAPI + browser)** — overkill for a workstation tool; adds server lifecycle complexity.

## Decision

**PyQt6.** Native KDE feel, Wayland-stable, the preview pane needs a real image widget with scaling and Qt's `QPixmap`/`QLabel` are ideal.

## Consequences

- Adds `PyQt6` dependency (~50 MB) — fine for workstation install.
- Use `pipx` for end-user install to keep the Qt deps isolated.
- Settings dialogs, font picker, file dialogs all use Qt's native widgets — no extra UX work.
