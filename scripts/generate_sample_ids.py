"""Generate synthetic Saudi ID card images for the demo.

Produces four PNG cards in ``sample_inputs/`` that mirror the field layout
of a real Saudi National ID / Iqama but with synthetic (clearly fake)
data. Each card has:

- a valid 10-digit ID number (correct Saudi checksum) — except the
  ``ocr_trap`` variant which has a deliberate checksum mismatch
- bilingual labels (Arabic + English)
- a photo placeholder
- realistic-looking dates

These cards are intentionally rendered on a clean light background with
high-contrast text — no security patterns, no watermarks — so Tesseract
can read them reliably. The bot's value proposition (OCR + validation +
audit) doesn't depend on the cards looking photo-realistic.

Run:
    python scripts/generate_sample_ids.py

Output:
    sample_inputs/
        01_citizen_valid.png
        02_resident_valid.png
        03_citizen_expired.png
        04_citizen_ocr_trap.png
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, features
except ImportError as exc:
    sys.stderr.write(
        f"Missing dependency: {exc.name}. Run inside the bot's conda env "
        "(rcc task or activated env) which has Pillow.\n"
    )
    sys.exit(1)

if not features.check("raqm"):
    sys.stderr.write(
        "Pillow was built without raqm/HarfBuzz support — Arabic glyphs will "
        "render disconnected. Use a conda-forge Pillow (which bundles raqm).\n"
    )


ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "Amiri-Regular.ttf"
OUTPUT_DIR = ROOT / "sample_inputs"

# Card dimensions — wide enough for Tesseract at high DPI.
W, H = 1100, 700
MARGIN = 40
PHOTO_BOX = (MARGIN, 150, MARGIN + 220, 420)
BG_COLOR = (245, 245, 235)        # warm off-white, easy for OCR
INK = (15, 25, 35)
LABEL = (90, 100, 110)
ACCENT = (0, 110, 90)             # MOI green-ish


# --------------------------------------------------------------------------- #
# Saudi National ID checksum                                                  #
# --------------------------------------------------------------------------- #

def saudi_id_checksum(nine_digits: str) -> int:
    total = 0
    for i, ch in enumerate(nine_digits):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def make_id(prefix: str, middle: str) -> str:
    assert prefix in ("1", "2")
    assert len(middle) == 8 and middle.isdigit()
    nine = prefix + middle
    return nine + str(saudi_id_checksum(nine))


# --------------------------------------------------------------------------- #
# Drawing                                                                     #
# --------------------------------------------------------------------------- #

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def _has_arabic(text: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in text)


def _draw_text_right(draw: ImageDraw.ImageDraw, xy: tuple[int, int],
                     text: str, font: ImageFont.FreeTypeFont,
                     fill=INK) -> None:
    """Right-anchor: ``xy`` is the right edge of the text bbox.

    Pillow's raqm/HarfBuzz integration handles Arabic shaping and BiDi
    when ``direction='rtl'`` is passed for Arabic strings; Latin-only
    strings render with the default direction.
    """
    direction = "rtl" if _has_arabic(text) else None
    bbox = draw.textbbox((0, 0), text, font=font, direction=direction)
    width = bbox[2] - bbox[0]
    draw.text((xy[0] - width, xy[1]), text, font=font, fill=fill,
              direction=direction)


def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int],
               text: str, font: ImageFont.FreeTypeFont, fill=INK) -> None:
    direction = "rtl" if _has_arabic(text) else None
    draw.text(xy, text, font=font, fill=fill, direction=direction)


def render_card(card: dict, output_path: Path) -> None:
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    f_title  = _load_font(28)
    f_header = _load_font(20)
    f_value  = _load_font(24)
    f_label  = _load_font(16)

    # ---- header bar ------------------------------------------------------
    draw.rectangle([(0, 0), (W, 90)], fill=ACCENT)
    draw.text((MARGIN, 18), "KINGDOM OF SAUDI ARABIA", font=f_header,
              fill=(255, 255, 255))
    draw.text((MARGIN, 48), "MINISTRY OF INTERIOR", font=f_label,
              fill=(220, 230, 220))
    _draw_text_right(draw, (W - MARGIN, 18),
                     "المملكة العربية السعودية", f_header,
                     fill=(255, 255, 255))
    _draw_text_right(draw, (W - MARGIN, 48),
                     "وزارة الداخلية", f_label,
                     fill=(220, 230, 220))

    # ---- card title ------------------------------------------------------
    title_en = "NATIONAL IDENTITY CARD" if card["id_type"] == "national_id" else "RESIDENT IDENTITY"
    title_ar = "بطاقة الهوية الوطنية" if card["id_type"] == "national_id" else "هوية مقيم"
    draw.text((MARGIN, 105), title_en, font=f_title, fill=ACCENT)
    _draw_text_right(draw, (W - MARGIN, 105), title_ar, f_title, fill=ACCENT)

    # ---- photo placeholder ----------------------------------------------
    draw.rectangle(PHOTO_BOX, outline=INK, width=2, fill=(220, 220, 215))
    draw.text((PHOTO_BOX[0] + 60, (PHOTO_BOX[1] + PHOTO_BOX[3]) // 2 - 12),
              "PHOTO", font=f_label, fill=LABEL)

    # ---- fields ---------------------------------------------------------
    # Three columns: EN label / value (left side under photo for ID number
    # only) and a right-side stack for Arabic labels + values.
    fields = [
        ("Name",         "الاسم",         card["name_en"],          card["name_ar"]),
        ("ID Number",    "الرقم",         card["id_number"],        card["id_number"]),
        ("Date of Birth","تاريخ الميلاد", card["dob_gregorian"],    card["dob_gregorian"]),
        ("Expiry",       "تاريخ الانتهاء", card["expiry_gregorian"], card["expiry_gregorian"]),
        ("Nationality",  "الجنسية",       card["nationality_en"],   card["nationality_ar"]),
        ("Gender",       "الجنس",         card["gender"],           card["gender_ar"]),
    ]

    y = 160
    x_label_en = PHOTO_BOX[2] + 30
    x_value_en = x_label_en + 130
    x_label_ar = W - MARGIN
    line_height = 42

    for label_en, label_ar, value_en, value_ar in fields:
        draw.text((x_label_en, y), label_en, font=f_label, fill=LABEL)
        draw.text((x_value_en, y - 4), value_en, font=f_value, fill=INK)

        _draw_text_right(draw, (x_label_ar, y + 22),
                         label_ar, f_label, fill=LABEL)
        # Arabic value goes just to the left of the Arabic label
        _draw_text_right(draw, (x_label_ar - 130, y + 22 - 4),
                         value_ar, f_value, fill=INK)
        y += line_height

    # ---- footer barcode placeholder + ID echo ----------------------------
    draw.rectangle([(MARGIN, H - 70), (MARGIN + 320, H - 30)],
                   fill=INK)
    draw.text((MARGIN + 340, H - 60), card["id_number"], font=f_value, fill=INK)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", dpi=(300, 300))


# --------------------------------------------------------------------------- #
# Sample card definitions                                                     #
# --------------------------------------------------------------------------- #

def build_cards() -> list[tuple[Path, dict]]:
    citizen_id  = make_id("1", "23456789")     # 10-digit, valid checksum
    resident_id = make_id("2", "34567890")
    expired_id  = make_id("1", "45678901")
    trap_id     = make_id("1", "56789012")
    # Flip the last digit so the checksum deliberately fails — demos
    # the checksum rule catching an OCR-quality issue.
    trap_id = trap_id[:-1] + str((int(trap_id[-1]) + 5) % 10)

    cards = [
        (OUTPUT_DIR / "01_citizen_valid.png", {
            "id_type":          "national_id",
            "id_number":        citizen_id,
            "name_en":          "AHMED ABDULLAH ALSAUD",
            "name_ar":          "احمد عبدالله السعود",
            "dob_gregorian":    "1990-05-15",
            "expiry_gregorian": "2030-12-31",
            "nationality_en":   "Saudi",
            "nationality_ar":   "السعودية",
            "gender":           "M",
            "gender_ar":        "ذكر",
        }),
        (OUTPUT_DIR / "02_resident_valid.png", {
            "id_type":          "iqama",
            "id_number":        resident_id,
            "name_en":          "RAJESH KUMAR SHARMA",
            "name_ar":          "راجش كومار شارما",
            "dob_gregorian":    "1985-09-20",
            "expiry_gregorian": "2028-06-15",
            "nationality_en":   "Indian",
            "nationality_ar":   "الهند",
            "gender":           "M",
            "gender_ar":        "ذكر",
        }),
        (OUTPUT_DIR / "03_citizen_expired.png", {
            "id_type":          "national_id",
            "id_number":        expired_id,
            "name_en":          "FATIMA KHALID ALGHAMDI",
            "name_ar":          "فاطمه خالد الغامدي",
            "dob_gregorian":    "1988-03-08",
            "expiry_gregorian": "2022-01-10",     # expired
            "nationality_en":   "Saudi",
            "nationality_ar":   "السعودية",
            "gender":           "F",
            "gender_ar":        "انثى",
        }),
        (OUTPUT_DIR / "04_citizen_ocr_trap.png", {
            "id_type":          "national_id",
            "id_number":        trap_id,            # checksum DELIBERATELY wrong
            "name_en":          "KHALID FAISAL ALQAHTANI",
            "name_ar":          "خالد فيصل القحطاني",
            "dob_gregorian":    "1995-11-22",
            "expiry_gregorian": "2029-07-04",
            "nationality_en":   "Saudi",
            "nationality_ar":   "السعودية",
            "gender":           "M",
            "gender_ar":        "ذكر",
        }),
    ]
    return cards


def main() -> int:
    if not FONT_PATH.is_file():
        sys.stderr.write(f"Font not found at {FONT_PATH}\n")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, card in build_cards():
        render_card(card, path)
        print(f"[wrote] {path.relative_to(ROOT)}  (id={card['id_number']})")
    print(f"\nDone. {len(build_cards())} card(s) in {OUTPUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
