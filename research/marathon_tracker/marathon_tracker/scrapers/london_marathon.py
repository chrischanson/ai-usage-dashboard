from ..models import Race, RaceResult
from ..fetch import fetch_text
from ..extract import extract_dates

def extract(race: Race) -> RaceResult:
    """
    Custom extraction logic for the London Marathon.
    Currently falls back to the generic LLM extraction, but this serves
    as the entry point for marathon-specific parsing logic.
    """
    url = race.official_url or race.registration_url
    if not url:
        # Cannot fetch without URL
        result = RaceResult.from_race(race)
        result.status = "stale"
        result.confidence = "low"
        result.notes = "No URL available for custom extraction."
        return result

    page_text = fetch_text(url)
    if not page_text:
        result = RaceResult.from_race(race)
        result.status = "stale"
        result.confidence = "low"
        result.notes = "Page fetch returned no content in custom scraper."
        return result

    # For now, rely on generic extraction. Replace with custom BS4/regex logic as needed.
    result = extract_dates(race, page_text, source_url=url)
    
    # Example of where custom logic could be injected:
    # if 'some-custom-date-logic' in page_text:
    #     result.event_date = '2026-04-26'
        
    return result
