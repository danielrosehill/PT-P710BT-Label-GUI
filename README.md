# PT-P710BT-Label-GUI

A desktop GUI for printing labels on the **Brother P-Touch Cube (PT-P710BT)** from Linux (Ubuntu / KDE Plasma 6, Wayland).

Thin wrapper around [`ptouch-print`](https://git.familie-radermacher.ch/linux/ptouch-print.git) (familie-radermacher) — exposes every useful CLI flag through a friendly interface and adds live tape preview.

## Scope

- **Printer:** Brother PT-P710BT *only*. Detection assumes USB ID `04f9:20af`. No multi-printer abstraction.
- **OS:** Ubuntu 25.10 + KDE Plasma 6 (Wayland). Other DEs may work, untested.
- **Transport:** USB. Bluetooth is out of scope for v1 (PT-P710BT supports both, but ptouch-print is USB-only).
- **Tape widths:** 3.5 / 6 / 9 / 12 / 18 / 24 mm (per PT-P710BT spec, auto-detected via `ptouch-print --info`).

## Features (planned)

- Live tape state (width, type, color, error) read from `ptouch-print --info`
- Multi-line text input with font picker, size, alignment
- Real-time PNG preview (via `--writepng`) rendered at actual tape height
- Chain printing (`--chain` + `--precut`) to minimise leading-edge waste
- Copies, padding, manual cut-mark
- Optional image insert (monochrome PNG)
- Save/load label templates
- One-click print

## Dependencies

- `ptouch-print` v1.8+ — build from <https://git.familie-radermacher.ch/linux/ptouch-print.git>
- Python 3.12+
- PyQt6
- udev rule `/etc/udev/rules.d/20-usb-ptouch-permissions.rules` (installed by ptouch-print)

## Status

Bootstrapped. See `planning/sprints/active/` for current work and `planning/decisions/` for design rationale.
