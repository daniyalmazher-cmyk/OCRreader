# Tesseract language data

The Tesseract OCR engine needs language data files (`.traineddata`) for every
language it reads. The conda-forge `tesseract` package only ships with English.

For this bot we need **Arabic** (and English). One-time setup:

```sh
python scripts/download_tessdata.py
```

That fetches `ara.traineddata` from the upstream `tessdata_best` repo into
this directory. `devdata/env.json` already sets `TESSDATA_PREFIX` so
`pytesseract` finds it.

These files are intentionally not committed — they're ~10 MB each.
