from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Race


WORLD_ATHLETICS_GRAPHQL = "https://worldathletics.org/graphql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

COUNTRY_ALPHA3_TO_NAME: dict[str, str] = {}
SUBDIVISION_MAP: dict[str, Any] = {}


def _load_country_map() -> dict[str, str]:
    global COUNTRY_ALPHA3_TO_NAME
    if COUNTRY_ALPHA3_TO_NAME:
        return COUNTRY_ALPHA3_TO_NAME
    
    cache_path = Path(__file__).parent / "iso_3166_countries.json"
    entries = []
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            pass
            
    if not entries:
        try:
            req = urllib.request.Request(
                "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.json",
                headers={"User-Agent": "marathon-tracker/0.1"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                entries = json.loads(resp.read().decode("utf-8"))
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2)
            except Exception:
                pass
        except Exception:
            pass

    for entry in entries:
        if isinstance(entry, dict):
            code = entry.get("alpha-3")
            name = entry.get("name")
            if code and name:
                COUNTRY_ALPHA3_TO_NAME[code] = name
                
    return COUNTRY_ALPHA3_TO_NAME


def _load_subdivision_map() -> dict[str, Any]:
    global SUBDIVISION_MAP
    if SUBDIVISION_MAP:
        return SUBDIVISION_MAP
        
    cache_path = Path(__file__).parent / "iso_3166_2.json"
    if not cache_path.exists():
        try:
            req = urllib.request.Request(
                "https://raw.githubusercontent.com/olahol/iso-3166-2.json/master/iso-3166-2.json",
                headers={"User-Agent": "marathon-tracker/0.1"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
            SUBDIVISION_MAP = data
        except Exception as exc:
            print(f"subdivision fetch warning: {exc}")
            return {}
    else:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                SUBDIVISION_MAP = json.load(f)
        except Exception:
            return {}
            
    return SUBDIVISION_MAP


def _extract_state_and_city(city: str, country_code: str) -> tuple[str, str | None]:
    """
    Extracts subdivision code (state/province) and returns cleaned city name.
    E.g. "Boston, MA" -> ("Boston", "MA")
    """
    city = city.strip()
    country_code = country_code.upper()
    
    # Check for standard patterns like "City, ST" (e.g. "Boston, MA" or "Toronto, ON")
    match = re.search(r",\s*([A-Za-z]{2})\b", city)
    if not match:
        return city, None
        
    state_code = match.group(1).upper()
    
    # Map country codes to their 2-letter ISO country keys (e.g., USA -> US, CAN -> CA)
    country_key = country_code
    if country_code == "USA":
        country_key = "US"
    elif country_code == "CAN":
        country_key = "CA"
    elif country_code == "DEU":
        country_key = "DE"
    elif country_code == "GBR":
        country_key = "GB"
        
    sub_map = _load_subdivision_map()
    if country_key in sub_map:
        # Check standard divisions like "US-MA" or "CA-ON"
        full_code = f"{country_key}-{state_code}"
        divisions = sub_map[country_key].get("divisions", {})
        if full_code in divisions:
            cleaned_city = re.sub(r",\s*[A-Za-z]{2}\b", "", city).strip()
            return cleaned_city, state_code
            
    return city, None


GRAPHQL_QUERY = """query Calendar($season: Int!, $competitionGroupId: ID!) {
  competitions(season: $season, competitionGroupId: $competitionGroupId) {
    id
    name
    startDate
    venue {
      city
      countryCode
    }
    competitionSubgroup
  }
}"""


def _run_graphql(season: int, group_id: str) -> list[dict[str, Any]]:
    body = {
        "query": GRAPHQL_QUERY,
        "variables": {"season": season, "competitionGroupId": group_id},
        "operationName": "Calendar",
    }
    req = urllib.request.Request(
        WORLD_ATHLETICS_GRAPHQL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "marathon-tracker/0.1 (+https://github.com/)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"World Athletics GraphQL error: {exc}") from exc

    data = raw.get("data", {})
    competitions = data.get("competitions") if isinstance(data, dict) else None
    if not isinstance(competitions, list):
        raise RuntimeError(f"unexpected GraphQL response shape: {raw}")
    return competitions


def discover_from_world_athletics() -> list[Race]:
    from datetime import datetime

    current_year = datetime.now().year
    seasons = [current_year, current_year - 1]  # Query both 2026 and 2025
    country_map = _load_country_map()

    candidates: list[Race] = []
    seen_keys: set[tuple[str, str]] = set()

    for season in seasons:
        for group_id in ("12",):  # Label Road Races
            try:
                competitions = _run_graphql(season, group_id)
            except RuntimeError:
                continue

            for comp in competitions:
                if not isinstance(comp, dict):
                    continue
                name = (comp.get("name") or "").strip()
                if not name:
                    continue
                venue = comp.get("venue") or {}
                city = (venue.get("city") or "").strip()
                country_code = (venue.get("countryCode") or "").strip().upper()
                country = country_map.get(country_code, country_code)
                subgroup = comp.get("competitionSubgroup") or ""
                event_date = (comp.get("startDate") or "").strip()[:10]

                # Extract state/province and clean city
                city_clean, state_province = _extract_state_and_city(city, country_code)

                # Infer distance from name
                name_lower = name.lower()
                if "half marathon" in name_lower or "half-marathon" in name_lower or "halfmarathon" in name_lower or " 21k" in name_lower or "21.1k" in name_lower:
                    distance = "half-marathon"
                else:
                    distance = "marathon"

                race_id = _slugify(name)
                if distance == "half-marathon" and not race_id.endswith("half-marathon"):
                    race_id = f"{race_id}-half-marathon"

                key = (race_id, distance)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                candidates.append(
                    Race(
                        id=race_id,
                        name=name,
                        distance=distance,
                        city=city_clean,
                        state_province=state_province,
                        country=country,
                        region=_guess_region(country),
                        official_url="",
                        registration_windows=[],
                        confidence="low",
                        notes=f"Auto-discovered from World Athletics ({subgroup} - {season})",
                    )
                )
    return candidates


def discover_from_wikipedia_page(page_name: str, default_distance: str) -> list[Race]:
    url = (
        f"{WIKIPEDIA_API}?action=parse"
        f"&page={page_name}"
        "&prop=text&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "marathon-tracker/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Wikipedia parse error for {page_name}: {exc}") from exc

    html = raw.get("parse", {}).get("text", {}).get("*", "")
    if not html:
        return []

    parser = _WikiTableParser()
    parser.feed(html)
    rows = parser.rows

    country_map = _load_country_map()
    candidates: list[Race] = []
    seen_keys: set[tuple[str, str]] = set()
    for name, city, country in rows:
        if name.lower() in ("name", "race", "event", ""):
            continue
        
        name_lower = name.lower()
        if "half marathon" in name_lower or "half-marathon" in name_lower or "halfmarathon" in name_lower or " 21k" in name_lower or "21.1k" in name_lower:
            distance = "half-marathon"
        else:
            distance = default_distance
            
        # Find country code from country name for subdivision resolution
        country_code = "Unknown"
        for code, c_name in country_map.items():
            if c_name.lower() == country.lower():
                country_code = code
                break
                
        city_clean, state_province = _extract_state_and_city(city, country_code)

        race_id = _slugify(name)
        if distance == "half-marathon" and not race_id.endswith("half-marathon"):
            race_id = f"{race_id}-half-marathon"
            
        key = (race_id, distance)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(
            Race(
                id=race_id,
                name=name,
                distance=distance,
                city=city_clean,
                state_province=state_province,
                country=country,
                region=_guess_region(country),
                official_url="",
                registration_windows=[],
                confidence="low",
                notes=f"Auto-discovered from Wikipedia ({page_name.replace('_', ' ')})",
            )
        )
    return candidates


def discover_from_wikipedia() -> list[Race]:
    candidates: list[Race] = []
    try:
        candidates.extend(discover_from_wikipedia_page("List_of_World_Athletics_Label_marathon_races", "marathon"))
    except RuntimeError as exc:
        print(f"wikipedia discovery warning (marathons): {exc}")
        
    try:
        candidates.extend(discover_from_wikipedia_page("List_of_World_Athletics_Label_half_marathon_races", "half-marathon"))
    except RuntimeError as exc:
        print(f"wikipedia discovery warning (half-marathons): {exc}")
        
    return candidates


def discover_races(sources: tuple[str, ...] = ("world-athletics",)) -> list[Race]:
    discovered: list[Race] = []
    seen_keys: set[tuple[str, str]] = set()

    for source in sources:
        try:
            if source == "world-athletics":
                batch = discover_from_world_athletics()
            elif source == "wikipedia":
                batch = discover_from_wikipedia()
            else:
                continue
        except RuntimeError as exc:
            print(f"discovery warning ({source}): {exc}")
            continue

        for race in batch:
            key = (race.id, race.distance)
            if key not in seen_keys:
                seen_keys.add(key)
                discovered.append(race)
    return discovered


def merge_races(
    curated: list[Race],
    discovered: list[Race],
    previous: dict[str, Race] | None = None,
) -> list[Race]:
    merged: dict[tuple[str, str], Race] = {}
    seen_urls: set[tuple[str, str]] = set()

    for race in curated:
        merged[(race.id, race.distance)] = race
        for url in (race.official_url, race.registration_url):
            if url:
                seen_urls.add((url.rstrip("/"), race.distance))

    if previous:
        for race_key, race in previous.items():
            if isinstance(race_key, tuple):
                r_id = race_key[0]
                r_dist = race_key[1] if len(race_key) > 1 else race.distance
            else:
                r_id = race_key
                r_dist = getattr(race, "distance", "marathon")
                
            if (r_id, r_dist) not in merged:
                dup = False
                for url in (race.official_url, race.registration_url):
                    if url and (url.rstrip("/"), r_dist) in seen_urls:
                        dup = True
                        break
                if not dup:
                    merged[(r_id, r_dist)] = race

    for race in discovered:
        key = (race.id, race.distance)
        if key in merged:
            continue
        dup = False
        for url in (race.official_url, race.registration_url):
            if url and (url.rstrip("/"), race.distance) in seen_urls:
                dup = True
                break
        if not dup:
            merged[key] = race

    return list(merged.values())


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _guess_region(country: str) -> str:
    north_america = {
        "United States", "Canada", "Mexico", "Greenland", "Bermuda",
        "Bahamas", "Costa Rica", "Cuba", "Dominican Republic", "El Salvador",
        "Guatemala", "Haiti", "Honduras", "Jamaica", "Nicaragua", "Panama",
        "Puerto Rico", "Trinidad and Tobago",
    }
    south_america = {
        "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Venezuela",
        "Bolivia", "Ecuador", "Paraguay", "Uruguay", "Guyana", "Suriname",
    }
    europe = {
        "United Kingdom", "Germany", "France", "Italy", "Spain", "Netherlands",
        "Switzerland", "Sweden", "Norway", "Denmark", "Finland", "Belgium",
        "Austria", "Ireland", "Portugal", "Greece", "Poland", "Czechia",
        "Romania", "Hungary", "Russia", "Turkey", "Ukraine", "Croatia",
        "Serbia", "Slovenia", "Slovakia", "Bulgaria", "Estonia", "Latvia",
        "Lithuania", "Iceland", "Luxembourg", "Monaco", "Cyprus", "England",
        "Northern Ireland", "Scotland", "Wales",
    }
    asia = {
        "Japan", "China", "South Korea", "India", "Thailand", "Singapore",
        "Taiwan", "Indonesia", "Philippines", "Malaysia", "Vietnam",
        "United Arab Emirates", "Qatar", "Saudi Arabia", "Israel", "Kazakhstan",
        "Uzbekistan", "Kyrgyzstan", "Bahrain", "Kuwait", "Oman",
        "Hong Kong", "Sri Lanka", "Nepal",
    }
    africa = {
        "South Africa", "Kenya", "Ethiopia", "Nigeria", "Morocco", "Tunisia",
        "Rwanda", "Uganda", "Tanzania", "Ghana", "Algeria", "Egypt",
        "Zimbabwe", "Zambia", "Namibia", "Botswana", "Ivory Coast",
        "Senegal", "Mozambique", "Djibouti", "Lesotho",
    }
    oceania = {
        "Australia", "New Zealand", "Fiji", "Papua New Guinea", "Samoa",
    }

    if country in north_america:
        return "North America"
    if country in south_america:
        return "South America"
    if country in europe:
        return "Europe"
    if country in asia:
        return "Asia"
    if country in africa:
        return "Africa"
    if country in oceania:
        return "Oceania"
    return "Unknown"


class _WikiTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.skip_depth = 0
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.rows: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if self.skip_depth:
            return
        if tag == "table":
            self.in_table = True
        if tag == "tr" and self.in_table:
            self.in_tr = True
            self.current_row = []
        if tag in ("td", "th") and self.in_tr:
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        if self.skip_depth:
            return
        if tag in ("td", "th") and self.in_td:
            self.in_td = False
            text = "".join(self.current_cell).strip()
            self.current_row.append(text)
        if tag == "tr" and self.in_tr:
            self.in_tr = False
            if len(self.current_row) >= 3:
                name = self.current_row[0]
                city = self.current_row[1]
                country = self._clean_country(self.current_row[2])
                if name and city and country:
                    self.rows.append((name, city, country))
        if tag == "table":
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not self.in_td:
            return
        self.current_cell.append(data)

    @staticmethod
    def _clean_country(raw: str) -> str:
        return clean_country_cell(raw)


def clean_country_cell(raw: str) -> str:
    raw = re.sub(r"\[.*?\]", "", raw)
    raw = re.sub(r"\(.*?\)", "", raw)
    raw = raw.replace("\xa0", " ").strip()
    parts = raw.split()
    if parts and len(parts[-1]) == 3 and parts[-1].isalpha():
        parts.pop()
    return " ".join(parts).strip() or raw
