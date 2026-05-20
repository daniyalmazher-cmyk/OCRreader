"""Sanctions / PEP screening — STUB.

This is intentionally NOT a real integration. A production deployment would
call out to a maintained list (OFAC SDN, UN Consolidated, EU Consolidated,
SAMA local list, plus a PEP feed like Dow Jones / Refinitiv).

The stub returns a hit when the extracted name matches a small hardcoded
list, demoing the *seam* where real screening would plug in. The IT-manager
audience cares that the seam is there and that every check is captured in
the audit log; they do not need a real list for the demo.
"""
import unicodedata

# Pretend hits. Names are deliberately innocuous + obviously fake.
_STUB_LIST: list[dict] = [
    {"name_en": "John Doe Sanctioned", "name_ar": "جون دو محظور", "source": "STUB_LIST"},
    {"name_en": "Test Bad Actor",      "name_ar": "اختبار محظور",  "source": "STUB_LIST"},
]


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.casefold().strip()


def screen(name_ar: str | None, name_en: str | None) -> list[dict]:
    """Return entries from the stub list that match either provided name.

    Match is a substring check on case-folded, diacritic-stripped strings.
    """
    candidates = [_normalize(name_ar), _normalize(name_en)]
    candidates = [c for c in candidates if c]
    if not candidates:
        return []

    hits = []
    for entry in _STUB_LIST:
        haystacks = [_normalize(entry["name_en"]), _normalize(entry["name_ar"])]
        for cand in candidates:
            if any(cand in h or h in cand for h in haystacks if h):
                hits.append({"matched": entry["name_en"], "source": entry["source"]})
                break
    return hits
