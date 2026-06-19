from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .models import Race


WORLD_ATHLETICS_GRAPHQL = "https://worldathletics.org/graphql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

COUNTRY_ALPHA3_TO_NAME: dict[str, str] = {}


def _load_country_map() -> dict[str, str]:
    if COUNTRY_ALPHA3_TO_NAME:
        return COUNTRY_ALPHA3_TO_NAME
    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/main/all/all.json",
            headers={"User-Agent": "marathon-tracker/0.1"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            entries = json.loads(resp.read().decode("utf-8"))
        for entry in entries:
            code = entry.get("alpha-3")
            name = entry.get("name")
            if code and name:
                COUNTRY_ALPHA3_TO_NAME[code] = name
    except Exception:
        pass
    return COUNTRY_ALPHA3_TO_NAME


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
    seen_keys: set[str] = set()

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

                race_id = _slugify(name)
                if race_id in seen_keys:
                    continue
                seen_keys.add(race_id)

                candidates.append(
                    Race(
                        id=race_id,
                        name=name,
                        city=city,
                        country=country,
                        region=_guess_region(country),
                        official_url="",
                        registration_url=None,
                        source_url=None,
                        event_date=event_date or None,
                        confidence="low",
                        notes=f"Auto-discovered from World Athletics ({subgroup} - {season})",
                    )
                )
    return candidates


def discover_from_wikipedia() -> list[Race]:
    url = (
        f"{WIKIPEDIA_API}?action=parse"
        "&page=List_of_World_Athletics_Label_marathon_races"
        "&prop=text&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "marathon-tracker/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Wikipedia parse error: {exc}") from exc

    html = raw.get("parse", {}).get("text", {}).get("*", "")
    if not html:
        return []

    parser = _WikiTableParser()
    parser.feed(html)
    rows = parser.rows

    candidates: list[Race] = []
    seen_keys: set[str] = set()
    for name, city, country in rows:
        if name.lower() in ("name", "race", "event", ""):
            continue
        race_id = _slugify(name)
        if race_id in seen_keys:
            continue
        seen_keys.add(race_id)
        candidates.append(
            Race(
                id=race_id,
                name=name,
                city=city,
                country=country,
                region=_guess_region(country),
                official_url="",
                event_date=None,
                confidence="low",
                notes="Auto-discovered from Wikipedia (World Athletics Label list)",
            )
        )
    return candidates


def discover_races(sources: tuple[str, ...] = ("world-athletics",)) -> list[Race]:
    discovered: list[Race] = []
    seen_ids: set[str] = set()

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
            if race.id not in seen_ids:
                seen_ids.add(race.id)
                discovered.append(race)
    return discovered


def merge_races(
    curated: list[Race],
    discovered: list[Race],
    previous: dict[str, Race] | None = None,
) -> list[Race]:
    merged: dict[str, Race] = {}
    seen_urls: set[str] = set()

    for race in curated:
        merged[race.id] = race
        for url in (race.official_url, race.registration_url):
            if url:
                seen_urls.add(url.rstrip("/"))

    if previous:
        for race_id, race in previous.items():
            if race_id not in merged:
                dup = False
                for url in (race.official_url, race.registration_url):
                    if url and url.rstrip("/") in seen_urls:
                        dup = True
                        break
                if not dup:
                    merged[race_id] = race

    for race in discovered:
        if race.id in merged:
            continue
        dup = False
        for url in (race.official_url, race.registration_url):
            if url and url.rstrip("/") in seen_urls:
                dup = True
                break
        if not dup:
            merged[race.id] = race

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
