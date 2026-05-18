"""Download + install Google Fonts straight from the canonical google/fonts repo.

We hit the GitHub Contents API to list `{license}/{slug}/` directories, then
pull every `.ttf` from its `download_url` (raw.githubusercontent.com — does not
count against the API rate limit). Static fonts are preferred when present.

Why not gftools / gwfh?
  - gftools is Google's font-builder toolkit (~100 MB of deps for fontmake/QA);
    aimed at people *building* fonts, not consuming them.
  - gwfh.mranftl.com is reliable but a third-party mirror — no need for it when
    google/fonts itself is public.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

INSTALL_DIR = Path.home() / ".local" / "share" / "fonts" / "google-fonts"
LEGACY_DIR  = Path.home() / ".local" / "share" / "fonts" / "pt-p710bt-label-gui"
LICENSE_DIRS = ("ofl", "apache", "ufl")  # try in order
API_BASE = "https://api.github.com/repos/google/fonts/contents/{path}"
USER_AGENT = "pt-p710bt-label-gui/0.1"


def installed_families() -> set[str]:
    try:
        cp = subprocess.run(
            ["fc-list", ":family"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return set()
    families: set[str] = set()
    for line in cp.stdout.splitlines():
        for name in line.split(","):
            n = name.strip()
            if n:
                families.add(n.lower())
    return families


def is_installed(family: str, cache: set[str] | None = None) -> bool:
    fams = cache if cache is not None else installed_families()
    return family.lower() in fams


def _http_json(url: str, timeout: float) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def _http_bytes(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _slug_for_gf_repo(slug: str) -> str:
    """gwfh-style slugs use hyphens (e.g. 'roboto-slab'); google/fonts ofl
    folders use lowercase no-hyphen (e.g. 'robotoslab'). Convert."""
    return slug.replace("-", "")


def _find_listing(slug: str, timeout: float) -> tuple[str, list[dict]] | None:
    repo_slug = _slug_for_gf_repo(slug)
    for license_dir in LICENSE_DIRS:
        path = f"{license_dir}/{repo_slug}"
        url = API_BASE.format(path=path)
        status, body = _http_json(url, timeout)
        if status == 200 and isinstance(body, list):
            return path, body
        if status == 403:
            return None  # rate-limited
    return None


def install_font(slug: str, *, timeout: float = 30.0) -> tuple[bool, str]:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    listing = _find_listing(slug, timeout)
    if listing is None:
        return False, f"not found in google/fonts (slug '{slug}')"
    path, entries = listing
    static_entries = [e for e in entries if e.get("type") == "dir" and e["name"] == "static"]
    ttf_entries: list[dict] = []
    if static_entries:
        url = API_BASE.format(path=f"{path}/static")
        status, body = _http_json(url, timeout)
        if status == 200 and isinstance(body, list):
            ttf_entries = [e for e in body if e["name"].lower().endswith(".ttf")]
    if not ttf_entries:
        ttf_entries = [e for e in entries if e["name"].lower().endswith(".ttf")]
    if not ttf_entries:
        return False, "no .ttf files found in repo dir"
    count = 0
    for e in ttf_entries:
        try:
            data = _http_bytes(e["download_url"], timeout)
        except Exception as exc:  # noqa: BLE001
            return False, f"download failed for {e['name']}: {exc}"
        (INSTALL_DIR / e["name"]).write_bytes(data)
        count += 1
    return True, f"{count} file(s)"


def migrate_legacy_dir() -> int:
    """Move any TTFs from the old app-private dir into the shared user font dir.
    Returns the number of files moved (0 if nothing to do)."""
    if not LEGACY_DIR.is_dir():
        return 0
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in LEGACY_DIR.glob("*.ttf"):
        target = INSTALL_DIR / f.name
        if target.exists():
            f.unlink()
        else:
            f.rename(target)
        moved += 1
    try:
        LEGACY_DIR.rmdir()
    except OSError:
        pass  # still has non-ttf contents; leave it
    return moved


def refresh_cache() -> None:
    try:
        # No path arg — rescans all configured user/system font dirs so that
        # `fc-list` (and Qt) see the newly-installed families.
        subprocess.run(
            ["fc-cache", "-f"],
            check=False, capture_output=True, timeout=60,
        )
    except Exception:
        pass
