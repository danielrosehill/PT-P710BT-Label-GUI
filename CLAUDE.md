# PT-P710BT-Label-GUI — project context

## What this is

GUI wrapper around `ptouch-print` for the Brother PT-P710BT label printer on Ubuntu/KDE.

## Hard constraints

- **Single printer model:** PT-P710BT (USB ID `04f9:20af`). Don't generalise.
- **USB only.** Bluetooth is out of scope.
- **Linux only**, targeting Ubuntu 25.10 + KDE Plasma 6 Wayland.
- **No reinvention of the raster protocol** — always shell out to `ptouch-print` for actual printing.

## Stack decisions (see `planning/decisions/`)

- **GUI:** PyQt6 (native Qt = good fit for KDE Plasma)
- **Packaging:** plain `pyproject.toml`, install via `pipx` for end users
- **Preview:** `ptouch-print --writepng <tempfile>` then display in a `QLabel` — never reimplement the renderer

## Key facts about the printer

- Print resolution: **180 dpi**
- Print head pin count: **128 px** wide
- Tape widths supported: 3.5 / 6 / 9 / 12 / 18 / 24 mm
- Printable pixel height at each width (from `ptouch-print --info`): 12mm tape → 76 px usable
- **Unavoidable leading edge:** ~24mm physical gap between print head and cutter. Mitigate with `--chain` + `--precut` when batching.
- **Error byte:** `0x0000` = ready. `0x0100` = often cover/tape issue. After interruption, may need power-cycle to clear.

## ptouch-print CLI essentials

```
--text "<line>"            up to 4 lines via repeated --text or \n
--newline "<line>"         alternative line marker
--align l|c|r              alignment for multi-line
--font <name>              fontconfig name or .ttf path
--font-size <px>           override auto-sized font
--copies <n>
--pad <n>                  blank pixels padding
--chain                    skip final feed + auto-cut (for batching)
--precut                   cut before label (use with --chain)
--cutmark                  print a cut-mark instead of cutting
--image <file>             monochrome PNG
--writepng <file>          preview to PNG instead of printing
--info                     query tape state
--force-tape-width <px>    use with --writepng when offline
```

## Working preferences

- Per workspace root `~/.claude/CLAUDE.md`: Train-Case naming, autonomy default, planning/ scaffolding live, commit + push always, no plans pasted back.
- Keep this file under 100 lines. Detailed reasoning belongs in `planning/decisions/`.
