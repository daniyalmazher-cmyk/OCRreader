"""KYC validation rules for Saudi account opening.

Each ``check_*`` function returns a ``RuleResult``. ``evaluate(fields)``
runs them all and produces an overall routing decision:

* ``auto_approve`` — every rule passes
* ``needs_review`` — at least one non-blocking rule failed
* ``auto_reject`` — a blocking rule failed (bad ID format / failed checksum /
  underage / sanctions hit)

The checksum implementation follows the publicly documented Saudi National
ID algorithm. Verify against a real card before the demo — if it disagrees,
treat the doc as the source of truth and adjust here.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable

from libraries import sanctions


@dataclass
class RuleResult:
    rule: str
    passed: bool
    severity: str           # "blocking" | "warning"
    detail: str = ""


@dataclass
class Decision:
    status: str             # auto_approve | needs_review | auto_reject
    results: list[RuleResult] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Individual checks                                                            #
# --------------------------------------------------------------------------- #

def check_id_format(id_number: str | None) -> RuleResult:
    if not id_number or not id_number.isdigit() or len(id_number) != 10:
        return RuleResult(
            rule="id_format",
            passed=False,
            severity="blocking",
            detail="ID number must be exactly 10 digits",
        )
    if id_number[0] not in "12":
        return RuleResult(
            rule="id_format",
            passed=False,
            severity="blocking",
            detail="ID must start with 1 (citizen) or 2 (resident)",
        )
    return RuleResult(rule="id_format", passed=True, severity="blocking",
                      detail="10-digit, leading 1 or 2")


def check_id_checksum(id_number: str | None) -> RuleResult:
    """Saudi National ID / Iqama checksum.

    Algorithm (public references):
      - Digits 1..9 are the content; digit 10 is the check digit.
      - For positions 1, 3, 5, 7, 9 (0-indexed 0,2,4,6,8): multiply by 2;
        if result > 9, subtract 9.
      - For positions 2, 4, 6, 8: leave as-is.
      - Sum all nine. check_digit = (10 - (sum % 10)) % 10.
    """
    if not id_number or not id_number.isdigit() or len(id_number) != 10:
        return RuleResult(rule="id_checksum", passed=False, severity="blocking",
                          detail="Cannot compute checksum on malformed ID")

    total = 0
    for i, ch in enumerate(id_number[:9]):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    expected = (10 - (total % 10)) % 10

    if expected == int(id_number[9]):
        return RuleResult(rule="id_checksum", passed=True, severity="blocking",
                          detail="Checksum digit matches")
    return RuleResult(
        rule="id_checksum",
        passed=False,
        severity="blocking",
        detail=f"Checksum mismatch — expected last digit {expected}, got {id_number[9]} (likely OCR misread)",
    )


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def check_age_18plus(dob: str | None, today: date | None = None) -> RuleResult:
    today = today or date.today()
    d = _parse_date(dob)
    if d is None:
        return RuleResult(rule="age_18plus", passed=False, severity="warning",
                          detail="Date of birth not readable")
    years = (today - d).days // 365
    if years < 18:
        return RuleResult(rule="age_18plus", passed=False, severity="blocking",
                          detail=f"Applicant is {years} years old; minimum is 18")
    return RuleResult(rule="age_18plus", passed=True, severity="blocking",
                      detail=f"Applicant is {years} years old")


def check_name_present(name_ar: str | None, name_en: str | None) -> RuleResult:
    has_ar = bool(name_ar and len(name_ar.strip()) >= 3)
    has_en = bool(name_en and len(name_en.strip()) >= 3)
    if has_ar and has_en:
        return RuleResult(rule="name_present", passed=True, severity="warning",
                          detail="Arabic and English names both extracted")
    if has_ar or has_en:
        return RuleResult(rule="name_present", passed=True, severity="warning",
                          detail="Only one of (Arabic, English) name extracted — partial")
    return RuleResult(rule="name_present", passed=False, severity="warning",
                      detail="No name could be extracted")


def check_sanctions(name_ar: str | None, name_en: str | None) -> RuleResult:
    hits = sanctions.screen(name_ar=name_ar, name_en=name_en)
    if hits:
        names = ", ".join(h["matched"] for h in hits)
        return RuleResult(
            rule="sanctions",
            passed=False,
            severity="blocking",
            detail=f"Hit against stub list: {names}",
        )
    return RuleResult(rule="sanctions", passed=True, severity="blocking",
                      detail="No match against stub sanctions list")


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #

def evaluate(fields: dict, today: date | None = None) -> Decision:
    results = [
        check_id_format(fields.get("id_number")),
        check_id_checksum(fields.get("id_number")),
        check_age_18plus(fields.get("dob_gregorian"), today=today),
        check_name_present(fields.get("name_ar"), fields.get("name_en")),
        check_sanctions(fields.get("name_ar"), fields.get("name_en")),
    ]
    return Decision(status=_status(results), results=results)


def _status(results: Iterable[RuleResult]) -> str:
    blocking_fail = any((not r.passed) and r.severity == "blocking" for r in results)
    warning_fail = any((not r.passed) and r.severity == "warning" for r in results)
    if blocking_fail:
        return "auto_reject"
    if warning_fail:
        return "needs_review"
    return "auto_approve"
