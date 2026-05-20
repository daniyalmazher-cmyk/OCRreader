# KSA Account Opening Bot

Demo bot for a Saudi bank. Picks up account-opening emails with attached
National ID / Iqama documents, runs Arabic+English OCR, extracts and validates
KYC fields, then writes a CSV the Streamlit dashboard renders.

> Companion artifact: `../DEMO_PLAN.md` (in repo root) is the source of truth
> for scope and decisions. Update both if anything material changes.

## What it does

```
Gmail inbox  →  OCR (Tesseract / Claude)  →  Field extraction
            →  KYC rules + sanctions screening (stub)
            →  output/applications.csv  +  output/audit_log.json
            →  Streamlit dashboard
```

## One-time setup

1. Install [rcc](https://github.com/robocorp/rcc).
2. Copy `devdata/vault.example.json` → `devdata/vault.json` and fill in your
   Gmail App Password (and Anthropic API key if you'll demo the Claude OCR
   path).
3. Download the Arabic language pack:
   ```sh
   python scripts/download_tessdata.py
   ```

## Running the bot

From this directory:

```sh
rcc run
```

Send an email with subject `ACCOUNT OPENING` and an ID image attached. The
bot reads it, processes it, marks it as read, and writes:

- `output/applications.csv` — one row per processed application
- `output/audit_log.json` — chronological event log for the run
- `output/log.html` — Robocorp's HTML log (this is what `rcc run` opens)

### Local bypass (no Gmail needed)

For a quick demo without setting up Gmail, set `OCR_INPUT_ONLY=1`. The bot
then skips email fetch and the `input/` reset, processing whatever images
are already there:

```sh
python scripts/generate_sample_ids.py        # one-time: makes 4 sample cards
cp sample_inputs/*.png input/                # whatever you want to process
OCR_INPUT_ONLY=1 rcc run
```

## Running the dashboard

After at least one `rcc run`, launch the viewer:

```sh
streamlit run streamlit_app.py
```

## Picking an OCR engine

`OCR_ENGINE` environment variable selects the backend:

| Value (default) | Engine | When to use |
|---|---|---|
| `tesseract` (default) | Local Tesseract + ara/eng | Offline demo, no API costs |
| `claude` | Anthropic Claude vision | Higher accuracy on Arabic; needs API key in vault |

Both implement the same `OCRClient` protocol — see `libraries/ocr.py`.

## Layout

```
account_opening_bot/
├── tasks.py                 # Robocorp entry point
├── process.py               # Orchestrator (start / finish)
├── conda.yaml               # Hermetic Python env (includes tesseract)
├── robot.yaml               # Robocorp manifest
├── streamlit_app.py         # IT-manager-facing dashboard
├── libraries/
│   ├── email_source.py      # Gmail IMAP intake
│   ├── ocr.py               # OCRClient protocol + Tesseract / Claude impls
│   ├── id_extraction.py     # Regex extraction over OCR text
│   ├── kyc_rules.py         # Saudi ID checksum, expiry, age, name consistency
│   ├── sanctions.py         # Sanctions/PEP screening (STUB — hardcoded list)
│   ├── audit.py             # Per-run append-only event log
│   └── reporting.py         # applications.csv writer (UTF-8 BOM, Arabic-safe)
├── scripts/
│   ├── download_tessdata.py # Fetch Arabic language pack
│   └── generate_sample_ids.py # Synthesize variants from reference image
├── tessdata/                # Arabic language data lives here (not committed)
├── reference/               # Reference KSA ID image (user-provided)
└── devdata/                 # Local dev: env.json + vault.json
```
