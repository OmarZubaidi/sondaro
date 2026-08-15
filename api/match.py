"""Artist-name normalisation and cross-provider de-duplication.

This module decides whether the whole thing works. Listings spell artists every
possible way — "National, The", "THE NATIONAL — 2026 TOUR", "Artist A + Artist B"
— and a listing that doesn't match back to the library is a show you never hear
about. Everything here is pure and heavily tested.
"""

import re
import unicodedata

# promoter noise that gets glued onto the billed name
_NOISE = re.compile(
    r"\b("
    r"live in concert|live|world tour|north american tour|european tour|uk tour|"
    r"summer tour|winter tour|farewell tour|reunion tour|anniversary tour|tour|"
    r"presents?|featuring|feat\.?|ft\.?|with special guests?|special guest|"
    r"an evening with|tickets?|vip package|vip|sold out|cancell?ed|postponed"
    r")\b",
    re.IGNORECASE,
)
_TRAILING_YEAR = re.compile(r"\s+(?:19|20)\d{2}$")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")
_LEADING_THE = re.compile(r"^the\s+")

# only split on these when they sit between two plausible names
_BILLING_SPLIT = re.compile(r"\s*(?:,|/|\+|&|\bwith\b|\bw/\b|\band\b)\s*", re.IGNORECASE)


def normalize(name: str) -> str:
    """Fold a billed name down to something comparable across providers."""
    if not name:
        return ""

    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()

    # "National, The" is a sort key, not a name
    if text.endswith(", the"):
        text = "the " + text[: -len(", the")]

    # promoters append the tour name after a dash: "The National — 2026 Tour"
    text = re.split(r"\s+[—–-]\s+", text)[0]

    base = _SPACE.sub(" ", _PUNCT.sub(" ", text)).strip()
    base = _LEADING_THE.sub("", base).strip()

    stripped = _SPACE.sub(" ", _NOISE.sub(" ", base)).strip()
    # only drop a trailing year if something survives it: "The 1975" is a band,
    # "The National 2026" is a band plus a tour year
    if " " in stripped:
        stripped = _TRAILING_YEAR.sub("", stripped).strip()

    # never let noise-stripping erase the whole name — "Live" and "Tickets" are
    # both real artists, and an empty key would match everything
    return stripped or base


def artist_key(mbid: str | None, name: str) -> str:
    """Stable identity for an artist. A MusicBrainz ID when we have one."""
    if mbid:
        return mbid.lower()
    return f"name:{normalize(name)}"


def event_key(artist_name: str, date: str, city: str | None, venue: str | None) -> str:
    """Identity used to collapse the same show reported by two providers."""
    place = normalize(venue or "") or normalize(city or "")
    return f"{normalize(artist_name)}|{date}|{place}"


def split_billing(name: str) -> list[str]:
    """Every act a listing title could plausibly refer to.

    The full title always stays in the list — plenty of real band names contain
    "and", "&" or a comma, and dropping it would lose them.
    """
    if not name:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = value.strip(" -–—:·|")
        key = normalize(cleaned)
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            candidates.append(cleaned)

    add(name)
    for part in _BILLING_SPLIT.split(name):
        add(part)

    return candidates
