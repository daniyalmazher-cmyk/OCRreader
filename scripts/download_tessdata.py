"""Download Tesseract language data files used by the bot.

Idempotent: skips files already present. Pulls from the official
``tesseract-ocr/tessdata_best`` upstream — these are LSTM-based and
considerably more accurate than the ``tessdata_fast`` variants.

Usage:
    python scripts/download_tessdata.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

LANGS = {
    "ara": "https://github.com/tesseract-ocr/tessdata_best/raw/main/ara.traineddata",
    "eng": "https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata",
}

TARGET_DIR = Path(__file__).resolve().parent.parent / "tessdata"


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for lang, url in LANGS.items():
        target = TARGET_DIR / f"{lang}.traineddata"
        if target.is_file() and target.stat().st_size > 0:
            print(f"[skip] {target.name} already exists ({target.stat().st_size:,} bytes)")
            continue
        print(f"[get ] {url}")
        try:
            urllib.request.urlretrieve(url, target)
        except Exception as exc:
            print(f"[err ] {lang}: {exc}", file=sys.stderr)
            return 1
        print(f"[ok  ] {target.name} ({target.stat().st_size:,} bytes)")
    print(f"\nDone. Set TESSDATA_PREFIX={TARGET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
