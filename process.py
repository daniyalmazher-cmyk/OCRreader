"""Process orchestrator — KSA Account Opening.

start() pulls fresh emails from Gmail (via libraries.email_source), then runs
each attached ID document through OCR → field extraction → KYC validation.
finish() writes the summary CSV + per-application JSON + audit log. finish()
runs in a finally block so partial work is preserved even when start() fails.

Set ``OCR_INPUT_ONLY=1`` to skip email fetch and skip the input/ wipe — the
bot then processes whatever images are already in ``input/``. Useful for
local demos without Gmail credentials.
"""
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from robocorp import log

from libraries import id_extraction, kyc_rules
from libraries.audit import AuditLogger
from libraries.email_source import fetch_attachments, read_message_meta
from libraries.ocr import SUPPORTED_IMAGE_EXTENSIONS, get_ocr_client
from libraries.reporting import write_application_record, write_summary_csv


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_images(root: Path) -> list[Path]:
    """Walk the input tree for supported image files (sorted, dedup)."""
    if not root.exists():
        return []
    found: set[Path] = set()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            found.add(path)
    return sorted(found)


class Process:
    def __init__(self) -> None:
        self.input_dir = Path("input")
        self.output_dir = Path("output")
        self.detail_dir = self.output_dir / "applications"
        self.output_dir.mkdir(exist_ok=True)

        self.audit = AuditLogger()
        self.records: list[dict] = []
        self.ocr = None        # lazy — only initialized when we actually have docs

    # ---------- start ---------------------------------------------------------

    def start(self) -> None:
        """Fetch new emails, then OCR + validate each attached ID document."""
        input_only = os.environ.get("OCR_INPUT_ONLY", "").lower() in ("1", "true", "yes")
        self.audit.event("start", {
            "input_dir": str(self.input_dir),
            "input_only_mode": input_only,
        })

        if input_only:
            log.info("OCR_INPUT_ONLY=1 — skipping email fetch and input/ wipe")
            self.input_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._reset_input_dir()
            try:
                downloaded = fetch_attachments(self.input_dir)
                log.info(f"Downloaded {len(downloaded)} attachment(s) from Gmail")
                self.audit.event("email_fetch_complete", {
                    "downloaded_count": len(downloaded),
                    "files": [str(f) for f in downloaded],
                })
            except Exception as exc:
                # Don't abort — finish() still writes whatever we have, and an
                # operator can drop images directly into input/ as a fallback.
                log.exception(f"Email fetch failed: {exc}")
                self.audit.event("email_fetch_failed", {"error": str(exc)})

        documents = _discover_images(self.input_dir)
        log.info(f"Discovered {len(documents)} document(s)")
        self.audit.event("discovery_complete", {
            "document_count": len(documents),
            "files": [str(p) for p in documents],
        })

        if not documents:
            return

        self.ocr = get_ocr_client()
        self.audit.event("ocr_engine_selected", {"engine": self.ocr.name})

        for path in documents:
            self._process_document(path)

    def _reset_input_dir(self) -> None:
        if self.input_dir.exists():
            shutil.rmtree(self.input_dir)
        self.input_dir.mkdir(parents=True)

    def _process_document(self, document_path: Path) -> None:
        app_id = str(uuid.uuid4())
        meta = read_message_meta(document_path.parent)
        log.info(f"[{app_id[:8]}] Processing {document_path.name}")
        self.audit.event("application_start", {
            "app_id": app_id,
            "document": str(document_path),
            "source_email": meta.get("from", ""),
        })

        try:
            ocr_result = self.ocr.read(document_path)
            self.audit.event("ocr_complete", {
                "app_id": app_id,
                "engine": ocr_result.engine,
                "raw_text_chars": len(ocr_result.raw_text or ""),
                "got_structured_fields": bool(ocr_result.fields),
            })

            # Claude already returns structured fields; Tesseract returns raw
            # text and id_extraction parses it.
            if ocr_result.fields:
                fields = ocr_result.fields
            else:
                fields = id_extraction.extract_fields(ocr_result.raw_text)

            decision = kyc_rules.evaluate(fields)
            self.audit.event("validation_complete", {
                "app_id": app_id,
                "status": decision.status,
                "failed_rules": [r.rule for r in decision.results if not r.passed],
            })

            record = {
                "app_id": app_id,
                "received_at": _now(),       # TODO: pull message Date header in email_source
                "processed_at": _now(),
                "source_email": meta.get("from", ""),
                "subject": meta.get("subject", ""),
                "document_path": str(document_path),
                "ocr_engine": ocr_result.engine,
                "fields": fields,
                "decision": {
                    "status": decision.status,
                    "results": [
                        {
                            "rule": r.rule, "passed": r.passed,
                            "severity": r.severity, "detail": r.detail,
                        }
                        for r in decision.results
                    ],
                },
                "raw_ocr_text": ocr_result.raw_text,
            }
            self.records.append(record)

        except Exception as exc:
            log.exception(f"[{app_id[:8]}] Processing failed: {exc}")
            self.audit.event("application_error", {
                "app_id": app_id,
                "document": str(document_path),
                "error": str(exc),
            })

    # ---------- finish --------------------------------------------------------

    def finish(self) -> None:
        """Persist all artifacts. Always runs (called from finally)."""
        csv_path = self.output_dir / "report.csv"
        audit_path = self.output_dir / "audit_log.json"

        # Write per-application JSON details first so the CSV row never
        # points at a file the dashboard can't find.
        for record in self.records:
            write_application_record(record, self.detail_dir)

        write_summary_csv(self.records, csv_path)
        self.audit.event("reports_written", {
            "csv": str(csv_path),
            "detail_dir": str(self.detail_dir),
            "record_count": len(self.records),
        })
        self.audit.flush(audit_path)

        log.info(f"Done. Processed {len(self.records)} application(s).")
        log.info(f"  CSV:    {csv_path}")
        log.info(f"  Detail: {self.detail_dir}")
        log.info(f"  Audit:  {audit_path}")
