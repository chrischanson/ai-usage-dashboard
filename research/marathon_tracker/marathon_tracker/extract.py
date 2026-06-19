from __future__ import annotations

import re
from datetime import datetime

from .llm import extract_with_llm
from .models import Race, RaceResult, RegistrationWindow


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


def extract_dates(race: Race, page_text: str | None, source_url: str | None = None) -> RaceResult:
    result = RaceResult.from_race(race)
    if not page_text:
        result.extraction_method = "seed"
        if not result.notes:
            result.notes = "No page text was fetched; only configured race metadata is available."
        url = source_url or result.source_url or result.official_url
        if url:
            for w in result.registration_windows:
                if not w.official_url:
                    w.official_url = url
        return result

    url = source_url or result.source_url or result.official_url
    llm_result = extract_with_llm(race.name, page_text)
    if llm_result:
        apply_extraction(result, llm_result, replace_existing=True, source_url=url)
        result.extraction_method = "llm"
        if result.notes:
            result.notes = result.notes[:500]
        return result

    fallback = regex_extract(page_text)
    apply_extraction(result, fallback, replace_existing=False, source_url=url)
    result.extraction_method = "regex"
    return result


def apply_extraction(
    result: RaceResult,
    extraction: dict[str, object],
    replace_existing: bool,
    source_url: str | None = None
) -> None:
    # 1. Extract event_date
    value = extraction.get("event_date")
    normalized_event = normalize_date(value) if isinstance(value, str) else None
    if normalized_event and (replace_existing or not result.event_date):
        result.event_date = normalized_event

    # 2. Extract registration_windows
    extracted_windows = extraction.get("registration_windows")
    if isinstance(extracted_windows, list):
        windows = []
        for w in extracted_windows:
            if isinstance(w, dict):
                w_type = w.get("window_type", "standard")
                desc = w.get("description")
                op = normalize_date(w.get("open_date"))
                cl = normalize_date(w.get("close_date"))
                if op or cl:
                    windows.append(RegistrationWindow(
                        window_type=str(w_type),
                        open_date=op,
                        close_date=cl,
                        description=str(desc) if desc else None,
                        official_url=str(w.get("official_url")) if w.get("official_url") else source_url
                    ))
        if windows and (replace_existing or not result.registration_windows):
            result.registration_windows = windows

    # 3. Metadata
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
    
    # Extract event_date
    val, line = find_date_near_keywords(lines, KEYWORD_MAP["event_date"])
    if val:
        extraction["event_date"] = val
        evidence.append(line)
        
    # Extract windows
    windows = []
    
    # Standard Registration
    open_val, open_line = find_date_near_keywords(lines, KEYWORD_MAP["registration_open_date"])
    close_val, close_line = find_date_near_keywords(lines, KEYWORD_MAP["registration_deadline"])
    if open_val or close_val:
        windows.append({
            "window_type": "standard",
            "description": "Standard Registration",
            "open_date": open_val,
            "close_date": close_val
        })
        if open_line: evidence.append(open_line)
        if close_line: evidence.append(close_line)
        
    # Lottery
    lottery_val, lottery_line = find_date_near_keywords(lines, KEYWORD_MAP["lottery_deadline"])
    if lottery_val:
        windows.append({
            "window_type": "lottery",
            "description": "Lottery Application",
            "open_date": None,
            "close_date": lottery_val
        })
        if lottery_line: evidence.append(lottery_line)
        
    # Qualification
    qual_val, qual_line = find_date_near_keywords(lines, KEYWORD_MAP["qualification_deadline"])
    if qual_val:
        windows.append({
            "window_type": "qualification",
            "description": "Qualification Window",
            "open_date": None,
            "close_date": qual_val
        })
        if qual_line: evidence.append(qual_line)
        
    extraction["registration_windows"] = windows
    extraction["raw_evidence"] = evidence[:5]
    if extraction.get("event_date") or windows:
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
