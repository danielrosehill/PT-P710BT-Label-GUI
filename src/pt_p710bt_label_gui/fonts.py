"""Google Fonts library shipped with the GUI."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FontEntry:
    display: str   # shown to the user
    family: str    # fontconfig family name (passed to ptouch-print --font)
    slug: str      # gwfh / google-fonts slug for installation
    category: str  # sans | serif | mono | display | handwriting | hebrew


# Maintained list per Daniel's request. Ordering preserved.
FONTS: list[FontEntry] = [
    FontEntry("Lato",                 "Lato",                 "lato",                 "sans"),
    FontEntry("Akatab",               "Akatab",               "akatab",               "sans"),         # interpreted "Akt"
    FontEntry("Rubik",                "Rubik",                "rubik",                "sans"),
    FontEntry("Roboto Slab",          "Roboto Slab",          "roboto-slab",          "serif"),
    FontEntry("Merriweather",         "Merriweather",         "merriweather",         "serif"),
    FontEntry("Outfit",               "Outfit",               "outfit",               "sans"),
    FontEntry("Bebas Neue",           "Bebas Neue",           "bebas-neue",           "display"),
    FontEntry("Caudex",               "Caudex",               "caudex",               "serif"),        # interpreted "Cause" — best-guess match on Google Fonts
    FontEntry("Bricolage Grotesque",  "Bricolage Grotesque",  "bricolage-grotesque",  "sans"),
    FontEntry("Saira",                "Saira",                "saira",                "sans"),
    FontEntry("IBM Plex Sans",        "IBM Plex Sans",        "ibm-plex-sans",        "sans"),
    FontEntry("Fira Sans",            "Fira Sans",            "fira-sans",            "sans"),
    FontEntry("Share Tech",           "Share Tech",           "share-tech",           "display"),
    FontEntry("Source Sans 3",        "Source Sans 3",        "source-sans-3",        "sans"),
    FontEntry("Intel One Mono",       "Intel One Mono",       "intel-one-mono",       "mono"),
    FontEntry("Jost",                 "Jost",                 "jost",                 "sans"),
    FontEntry("Noto Serif",           "Noto Serif",           "noto-serif",           "serif"),
    FontEntry("Dancing Script",       "Dancing Script",       "dancing-script",       "handwriting"),
    FontEntry("Anton",                "Anton",                "anton",                "display"),
    FontEntry("EB Garamond",          "EB Garamond",          "eb-garamond",          "serif"),
    FontEntry("JetBrains Mono",       "JetBrains Mono",       "jetbrains-mono",       "mono"),
    FontEntry("Cabin",                "Cabin",                "cabin",                "sans"),
    FontEntry("Pacifico",             "Pacifico",             "pacifico",             "handwriting"),
    FontEntry("Bungee",               "Bungee",               "bungee",               "display"),
    FontEntry("Google Sans Code",     "Google Sans Code",     "google-sans-code",     "mono"),         # interpreted "Google Sans Flex" → only open variant on Google Fonts
    FontEntry("Caveat",               "Caveat",               "caveat",               "handwriting"),
    FontEntry("Crimson Text",         "Crimson Text",         "crimson-text",         "serif"),
    FontEntry("Urbanist",             "Urbanist",             "urbanist",             "sans"),
    FontEntry("Cinzel",               "Cinzel",               "cinzel",               "display"),
    FontEntry("Heebo",                "Heebo",                "heebo",                "hebrew"),
    FontEntry("Assistant",            "Assistant",            "assistant",            "hebrew"),
    FontEntry("Noto Sans Hebrew",     "Noto Sans Hebrew",     "noto-sans-hebrew",     "hebrew"),
    FontEntry("Noto Serif Hebrew",    "Noto Serif Hebrew",    "noto-serif-hebrew",    "hebrew"),
    FontEntry("Frank Ruhl Libre",     "Frank Ruhl Libre",     "frank-ruhl-libre",     "hebrew"),
    FontEntry("David Libre",          "David Libre",          "david-libre",          "hebrew"),
    FontEntry("Suez One",             "Suez One",             "suez-one",             "hebrew"),
    FontEntry("Secular One",          "Secular One",          "secular-one",          "hebrew"),
    FontEntry("Miriam Libre",         "Miriam Libre",         "miriam-libre",         "hebrew"),
    FontEntry("Bellefair",            "Bellefair",            "bellefair",            "hebrew"),
]


def is_hebrew_family(family: str) -> bool:
    """Whether this font family is in the Hebrew category (RTL hint)."""
    for f in FONTS:
        if f.family == family and f.category == "hebrew":
            return True
    return False


def contains_hebrew(text: str) -> bool:
    """Detect Hebrew unicode block (U+0590..U+05FF) or presentation forms (U+FB1D..U+FB4F)."""
    for ch in text:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F:
            return True
    return False

DEFAULT_FAMILY = "IBM Plex Sans"

CATEGORY_LABEL = {
    "sans":        "Sans-serif",
    "serif":       "Serif",
    "mono":        "Monospace",
    "display":     "Display",
    "handwriting": "Handwriting",
    "hebrew":      "Hebrew",
}


def by_family(family: str) -> FontEntry | None:
    for f in FONTS:
        if f.family == family:
            return f
    return None


def grouped() -> list[tuple[str, list[FontEntry]]]:
    """Return [(category_label, [entries…]), …] preserving list order within."""
    order = ["sans", "serif", "mono", "display", "handwriting", "hebrew"]
    seen_by_family: set[str] = set()
    buckets: dict[str, list[FontEntry]] = {k: [] for k in order}
    for f in FONTS:
        if f.family in seen_by_family:
            continue
        seen_by_family.add(f.family)
        buckets[f.category].append(f)
    return [(CATEGORY_LABEL[k], buckets[k]) for k in order if buckets[k]]
