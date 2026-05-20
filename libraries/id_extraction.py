"""Extract structured KYC fields from raw OCR text.

Used when the OCR engine returns text rather than structured fields (i.e.
the Tesseract path). The Claude path skips this entirely and returns
pre-extracted fields directly.

The regexes here are deliberately permissive — Tesseract on Arabic ID
photographs introduces noise (stray punctuation, line splits, glyph
substitutions). We prefer "best guess + a confidence note" over "give up
because the regex didn't match exactly".
"""
import re
import unicodedata

# Saudi National ID / Iqama: 10 digits, leading 1 (citizen) or 2 (resident).
# We anchor on digit boundaries rather than \b so a stray Arabic-script char
# adjacent to the run (common in Tesseract output) doesn't kill the match.
SAUDI_ID_PATTERN = re.compile(r"(?<!\d)[12]\d{9}(?!\d)")

# Date formats commonly printed on the card. Tesseract sometimes mangles
# separators so we accept -, /, or .
DATE_PATTERN = re.compile(
    r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"
    r"|"
    r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)"
)

# Eastern Arabic digits (٠١٢٣٤٥٦٧٨٩) and the Persian variants (۰۱۲۳۴۵۶۷۸۹)
# render alongside or in place of Latin 0-9 on Saudi documents. Normalize
# both forms before regex matching.
_EASTERN_ARABIC = "٠١٢٣٤٥٦٧٨٩"
_PERSIAN       = "۰۱۲۳۴۵۶۷۸۹"
_WESTERN       = "0123456789"
_DIGIT_TRANS = str.maketrans(
    _EASTERN_ARABIC + _PERSIAN,
    _WESTERN + _WESTERN,
)


def _normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_TRANS) if text else text

# Arabic letter range (excluding combining marks / punctuation) plus
# *inline* whitespace only — newlines must break the match so we don't
# capture the surrounding label/value on a different line.
ARABIC_LINE_PATTERN = re.compile(r"[ء-ي٠-٩ \t]{4,}")

# An English/Latin name line — at least two whitespace-separated words of
# Latin letters, with optional Saudi-common transliteration punctuation.
# Inline whitespace only, same reason as above.
ENGLISH_NAME_PATTERN = re.compile(r"\b([A-Z][A-Z'\-]{1,}(?:[ \t]+[A-Z][A-Z'\-]{1,}){1,4})\b")

# Header / label fragments to filter out of the name candidates. These come
# from the card's chrome (Kingdom of…, Ministry of…, card title, etc.) and
# would otherwise outrank the actual cardholder name in our greedy match.
_AR_STOPWORDS = (
    "المملكة", "العربية", "السعودية", "وزارة", "الداخلية", "المديرية",
    "العامة", "الجوازات", "بطاقة", "الهوية", "الوطنية", "مقيم",
)
_EN_STOPWORDS = {
    "KINGDOM", "MINISTRY", "INTERIOR", "RESIDENT", "IDENTITY", "NATIONAL",
    "CARD", "DIRECTORATE", "PASSPORT", "DEPT", "SAUDI", "ARABIA",
}


def _looks_like_header(text: str, stopwords) -> bool:
    """True if any stopword appears as a substring/whole-word (depending on
    container type) in the candidate — i.e. it's a card-chrome line, not
    a person's name.
    """
    if isinstance(stopwords, set):
        words = re.findall(r"[A-Za-z]+", text.upper())
        return any(w in stopwords for w in words)
    return any(sw in text for sw in stopwords)


def _normalize_arabic(text: str) -> str:
    """Strip diacritics and unify alef/ya variants — improves match accuracy."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    return text.strip()


def _pick_arabic_name(text: str) -> str | None:
    """Heuristic: a name is the first Arabic run between 8 and 50 chars,
    excluding card-chrome lines (header, ministry, card title).
    """
    for m in ARABIC_LINE_PATTERN.finditer(text):
        candidate = m.group(0).strip()
        if not (8 <= len(candidate) <= 50):
            continue
        if _looks_like_header(candidate, _AR_STOPWORDS):
            continue
        return candidate
    return None


def _pick_english_name(text: str) -> str | None:
    """First all-caps multi-word phrase that isn't a header/label."""
    for m in ENGLISH_NAME_PATTERN.finditer(text.upper()):
        candidate = m.group(1)
        if _looks_like_header(candidate, _EN_STOPWORDS):
            continue
        return candidate.title()
    return None


def _normalize_date(match: re.Match) -> str | None:
    groups = [g for g in match.groups() if g]
    if len(groups) != 3:
        return None
    a, b, c = groups
    if len(a) == 4:           # YYYY-MM-DD
        y, m, d = a, b, c
    elif len(c) == 4:         # DD-MM-YYYY
        y, m, d = c, b, a
    else:
        return None
    try:
        y_i, m_i, d_i = int(y), int(m), int(d)
        if not (1900 <= y_i <= 2100 and 1 <= m_i <= 12 and 1 <= d_i <= 31):
            return None
    except ValueError:
        return None
    return f"{y_i:04d}-{m_i:02d}-{d_i:02d}"


def extract_fields(text: str) -> dict:
    """Best-effort parse of an OCR text blob into KYC fields.

    Returns the same dict shape ``ClaudeOCRClient`` returns, so downstream
    code is engine-agnostic.
    """
    # Normalize Eastern-Arabic / Persian digits to Western so the regexes
    # match consistently. Done on a separate string so we still hand the
    # original (with native digits) to the AR-name extractor.
    text_for_digits = _normalize_digits(text)

    id_match = SAUDI_ID_PATTERN.search(text_for_digits)
    id_number = id_match.group(0) if id_match else None
    id_type = None
    if id_number:
        id_type = "national_id" if id_number.startswith("1") else "iqama"

    name_ar = _pick_arabic_name(text)
    if name_ar:
        name_ar = _normalize_arabic(name_ar)

    name_en = _pick_english_name(text)

    # Collect all parseable dates. The earliest is usually DOB, the latest
    # is usually expiry. Issue date may sit between. This heuristic is good
    # enough for the demo; real production would localize per-card layout.
    dates: list[str] = []
    for m in DATE_PATTERN.finditer(text_for_digits):
        norm = _normalize_date(m)
        if norm:
            dates.append(norm)
    dates_sorted = sorted(set(dates))

    dob_gregorian = dates_sorted[0] if dates_sorted else None
    expiry_gregorian = dates_sorted[-1] if len(dates_sorted) >= 2 else None

    return {
        "id_number": id_number,
        "id_type": id_type,
        "name_ar": name_ar,
        "name_en": name_en,
        "dob_gregorian": dob_gregorian,
        "dob_hijri": None,           # not parsed from Tesseract text — needs cal conversion
        "expiry_gregorian": expiry_gregorian,
        "nationality": None,         # not reliably extractable from raw text alone
        "gender": None,
        "place_of_issue": None,
        "raw_text": text,
    }
