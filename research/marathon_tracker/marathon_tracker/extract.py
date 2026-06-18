from __future__ import annotations

import re
from datetime import datetime

from .llm import extract_with_llm
from .models import DATE_FIELDS, Race, RaceResult


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
MONTH_PATTERN = "|".join(MONTHS)
DATE_PATTERN = re.compile(
    rf"\b(?:{MONTH_PATTERN})\s+\d{{1,2}}(?:,\s+\d{{4}})?\b|\b\d{{1,2}}\s+(?:{MONTH_PATTERN})\s+\d{{4}}\b",
    re.IGNORECASE,
)
KEYWORD_MAP = {
    "event_date": ("race day", "event date", "marathon date", "start date"),
    "registration_open_date": ("registration opens", "entry opens", "ballot opens", "applications open"),
    "registration_deadline": ("registration deadline", "entry deadline", "applications close", "registration closes"),
    "lottery_deadline": ("lottery deadline", "ballot deadline", "drawing application", "non-guaranteed entry"),
    "qualification_deadline": ("qualifying period", "qualification deadline", "qualifying window"),
}


def extract_dates(race: Race, page_text: str | None) -> RaceResult:
    result = RaceResult.from_race(race)
    if not page_text:
        result.extraction_method = "seed"
        if not result.notes:
            result.notes = "No page text was fetched; only configured race metadata is available."
        return result

    llm_result = extract_with_llm(race.name, page_text)
    if llm_result:
        apply_extraction(result, llm_result, replace_existing=True)
        result.extraction_method = "llm"
        if result.notes:
            result.notes = result.notes[:500]
        return result

    fallback = regex_extract(page_text)
    apply_extraction(result, fallback, replace_existing=False)
    result.extraction_method = "regex"
    return result


def apply_extraction(result: RaceResult, extraction: dict[str, object], replace_existing: bool) -> None:
    for field in DATE_FIELDS:
        value = extraction.get(field)
        normalized = normalize_date(value) if isinstance(value, str) else None
        if normalized and (replace_existing or not getattr(result, field)):
            setattr(result, field, normalized)
    confidence = extraction.get("confidence")
    if replace_existing or result.confidence == "unknown":
        result.confidence = str(confidence) if confidence in {"high", "medium", "low", "unknown"} else "unknown"
    notes = extraction.get("notes")
    if notes and (replace_existing or not result.notes):
        result.notes = str(notes)
    evidence = extraction.get("raw_evidence")
    if isinstance(evidence, list):
        result.raw_evidence = [str(item)[:300] for item in evidence[:5]]


def regex_extract(page_text: str) -> dict[str, object]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    extraction: dict[str, object] = {
        "confidence": "low",
        "notes": "Fallback regex extraction; verify against the official source.",
        "raw_evidence": [],
    }
    evidence: list[str] = []
    for field, keywords in KEYWORD_MAP.items():
        value, line = find_date_near_keywords(lines, keywords)
        if value:
            extraction[field] = value
            evidence.append(line)
    extraction["raw_evidence"] = evidence[:5]
    if any(extraction.get(field) for field in DATE_FIELDS):
        extraction["confidence"] = "medium"
    return extraction


def find_date_near_keywords(lines: list[str], keywords: tuple[str, ...]) -> tuple[str | None, str]:
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            match = DATE_PATTERN.search(line)
            if match:
                return match.group(0), line[:300]
    return None, ""


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    formats = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt).date()
            if parsed.year < datetime.now().year - 1:
                return None
            return parsed.isoformat()
        except ValueError:
            continue
    return None
