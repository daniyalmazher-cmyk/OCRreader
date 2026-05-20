"""Write application records to disk.

Two outputs, by design:

* ``output/applications.csv`` — flat summary, one row per application. UTF-8
  with BOM so Excel-on-Windows renders Arabic correctly. This is what the
  Streamlit queue view reads.

* ``output/applications/<app_id>.json`` — full per-application detail (rule
  results, full OCR text, document path). The Streamlit detail view loads
  the matching file when an operator clicks a row.

Splitting the two keeps the CSV small/scannable while preserving the audit
trail needed for SAMA.
"""
import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

CSV_FIELDS = [
    "app_id",
    "received_at",
    "processed_at",
    "source_email",
    "subject",
    "document_path",
    "ocr_engine",
    "id_number",
    "id_type",
    "name_ar",
    "name_en",
    "dob_gregorian",
    "expiry_gregorian",
    "nationality",
    "gender",
    "status",
    "failed_rules",
]


def _flatten_for_csv(record: dict) -> dict:
    fields = record.get("fields") or {}
    decision = record.get("decision") or {}
    failed = [r["rule"] for r in decision.get("results", []) if not r.get("passed")]
    return {
        "app_id":           record.get("app_id", ""),
        "received_at":      record.get("received_at", ""),
        "processed_at":     record.get("processed_at", ""),
        "source_email":     record.get("source_email", ""),
        "subject":          record.get("subject", ""),
        "document_path":    record.get("document_path", ""),
        "ocr_engine":       record.get("ocr_engine", ""),
        "id_number":        fields.get("id_number") or "",
        "id_type":          fields.get("id_type") or "",
        "name_ar":          fields.get("name_ar") or "",
        "name_en":          fields.get("name_en") or "",
        "dob_gregorian":    fields.get("dob_gregorian") or "",
        "expiry_gregorian": fields.get("expiry_gregorian") or "",
        "nationality":      fields.get("nationality") or "",
        "gender":           fields.get("gender") or "",
        "status":           decision.get("status", ""),
        "failed_rules":     ";".join(failed),
    }


def _json_default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Not JSON-serializable: {type(obj).__name__}")


def write_application_record(record: dict, detail_dir: Path) -> Path:
    """Write the per-application detail JSON file and return its path."""
    detail_dir.mkdir(parents=True, exist_ok=True)
    path = detail_dir / f"{record['app_id']}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False, default=_json_default)
    return path


def write_summary_csv(records: list[dict], path: Path) -> None:
    """Append or rewrite the summary CSV. Uses UTF-8 BOM so Excel reads Arabic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig prepends the BOM. csv.QUOTE_MINIMAL handles names with commas.
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in records:
            writer.writerow(_flatten_for_csv(r))
