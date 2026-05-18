# Shell out to ptouch-print vs reimplement raster protocol

**Date:** 2026-05-18
**Status:** chosen

## Context

`ptouch-print` (familie-radermacher, v1.8+) already supports PT-P710BT and exposes everything we need via CLI flags: text rendering with fontconfig, multi-line, alignment, image input, PNG preview, chain printing, precut, info query. Alternative is implementing the Brother raster protocol ourselves in Python (e.g. using `treideme/brother_pt` as a starting point).

## Options considered

- **Shell out to `ptouch-print`** — zero protocol code, one subprocess per action. Inherits any future printer fixes from upstream. Mature C codebase with USB perms via udev rule.
- **Reimplement / use a Python library** — full in-process control, can stream preview without writing tempfiles. But: duplicates well-trodden code, owns USB lifecycle, owns font rendering, owns error handling for every printer quirk.

## Decision

**Shell out.** Keep the GUI dumb. Every print/preview action invokes `ptouch-print` as a subprocess. Use `--writepng <tempfile>` for live preview.

## Consequences

- Hard runtime dependency on `ptouch-print` being on `PATH`. App should detect and surface a friendly install message if missing.
- Cannot do partial / streaming preview during typing — must re-run `ptouch-print --writepng` (fast, but not instant). Debounce input.
- Easy to add a "show command" debug button that prints the exact `ptouch-print` invocation — useful for power users.
