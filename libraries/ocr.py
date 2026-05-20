"""OCR backends for KSA ID documents.

Two implementations behind a single ``OCRClient`` protocol so we can swap
engines in one place (``get_ocr_client()``):

* ``TesseractOCRClient`` — local, offline, free. Reads ara+eng with
  light PIL preprocessing. Falls back to raw text and lets
  ``libraries.id_extraction`` parse fields out via regex.

* ``ClaudeOCRClient`` — Anthropic vision. Sends the image plus a JSON-schema
  prompt and gets back structured fields directly (OCR + extraction in one
  call). More accurate on Arabic, costs per request.

The active engine is selected by the ``OCR_ENGINE`` environment variable
(``tesseract`` default, ``claude`` to swap).
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps
from robocorp import log


SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


@dataclass
class OCRResult:
    """Output of an OCR pass over one document image."""
    raw_text: str = ""
    # When the engine extracts fields directly (Claude), populate this dict.
    # When it only returns text (Tesseract), leave empty — id_extraction.py
    # will parse fields from ``raw_text``.
    fields: dict = field(default_factory=dict)
    engine: str = ""


class OCRClient(Protocol):
    name: str

    def read(self, image_path: Path) -> OCRResult: ...


# --------------------------------------------------------------------------- #
# Tesseract                                                                   #
# --------------------------------------------------------------------------- #

def _preprocess(image: Image.Image) -> Image.Image:
    """Grayscale + autocontrast. Deliberately conservative — aggressive
    thresholding hurts more than it helps on Arabic scripts.
    """
    g = ImageOps.exif_transpose(image)
    g = ImageOps.grayscale(g)
    g = ImageOps.autocontrast(g)
    return g


class TesseractOCRClient:
    name = "tesseract"

    def __init__(self, languages: str = "ara+eng") -> None:
        # Import lazily so a missing pytesseract install doesn't break the
        # whole module — only the engine that needs it.
        import pytesseract  # noqa: F401
        self.languages = languages
        # Honor TESSDATA_PREFIX if set (set by devdata/env.json locally).
        self._tessdata = os.environ.get("TESSDATA_PREFIX")

    def read(self, image_path: Path) -> OCRResult:
        import pytesseract

        # PSM 11 ("sparse text") empirically outperforms 6 on ID-card layouts
        # where text is scattered with logos / borders / watermarks rather
        # than laid out in a uniform paragraph block.
        with Image.open(image_path) as img:
            processed = _preprocess(img)
            config_parts = ["--oem 3", "--psm 11"]
            if self._tessdata:
                config_parts.append(f'--tessdata-dir "{self._tessdata}"')
            text = pytesseract.image_to_string(
                processed,
                lang=self.languages,
                config=" ".join(config_parts),
            )

        return OCRResult(raw_text=text or "", engine=self.name)


# --------------------------------------------------------------------------- #
# Claude vision                                                               #
# --------------------------------------------------------------------------- #

SAUDI_ID_EXTRACTION_PROMPT = """You are extracting structured data from a Saudi
Arabian identity document (National ID for citizens, or Iqama for residents).

Return ONLY valid JSON. No prose, no markdown fences. Schema:

{
  "id_number": "10-digit string, or null",
  "id_type": "national_id" or "iqama" or null,
  "name_ar": "full name in Arabic as printed",
  "name_en": "name in English / Latin script as printed",
  "dob_gregorian": "YYYY-MM-DD, or null",
  "dob_hijri": "YYYY-MM-DD, or null",
  "expiry_gregorian": "YYYY-MM-DD, or null",
  "nationality": "as printed, or null",
  "gender": "M" or "F" or null,
  "place_of_issue": "as printed, or null",
  "raw_text": "every readable string on the document, joined with newlines"
}

Use null for any field you cannot read with confidence. Do not invent values.
"""

CLAUDE_VAULT_SECRET = "anthropic_credentials"


class ClaudeOCRClient:
    name = "claude"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @staticmethod
    def _media_type(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(suffix, "image/jpeg")

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Tolerate either a clean JSON object or one wrapped in ```json fences."""
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            log.warn(f"Claude returned non-JSON content: {exc}")
            return {}

    def read(self, image_path: Path) -> OCRResult:
        data = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": SAUDI_ID_EXTRACTION_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": [{
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": self._media_type(image_path),
                        "data": data,
                    },
                }],
            }],
        )

        text = response.content[0].text if response.content else ""
        fields = self._parse_json_response(text)
        return OCRResult(
            raw_text=fields.get("raw_text", "") or text,
            fields=fields,
            engine=self.name,
        )


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #

def get_ocr_client() -> OCRClient:
    """Return the OCR client selected by the ``OCR_ENGINE`` env var.

    Defaults to Tesseract. ``OCR_ENGINE=claude`` reads the Anthropic API key
    from Robocorp Vault under ``anthropic_credentials.api_key``.
    """
    engine = (os.environ.get("OCR_ENGINE") or "tesseract").lower().strip()

    if engine == "tesseract":
        log.info("OCR engine: tesseract (lang=ara+eng)")
        return TesseractOCRClient()

    if engine == "claude":
        from robocorp import vault
        creds = vault.get_secret(CLAUDE_VAULT_SECRET)
        api_key = creds["api_key"]
        log.info("OCR engine: claude (vision)")
        return ClaudeOCRClient(api_key=api_key)

    raise ValueError(f"Unknown OCR_ENGINE={engine!r}; expected 'tesseract' or 'claude'")
