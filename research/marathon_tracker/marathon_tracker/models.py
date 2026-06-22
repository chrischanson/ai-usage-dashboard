from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RegistrationWindow:
    window_type: str  # 'guaranteed-entry', 'lottery', 'charity', 'standard', 'qualification'
    open_date: str | None
    close_date: str | None
    description: str | None = None
    official_url: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RegistrationWindow":
        return cls(
            window_type=str(raw["window_type"]),
            open_date=str(raw["open_date"]) if raw.get("open_date") else None,
            close_date=str(raw["close_date"]) if raw.get("close_date") else None,
            description=str(raw["description"]) if raw.get("description") else None,
            official_url=str(raw["official_url"]) if raw.get("official_url") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_type": self.window_type,
            "open_date": self.open_date,
            "close_date": self.close_date,
            "description": self.description,
            "official_url": self.official_url,
        }


@dataclass(frozen=True)
class Race:
    id: str
    name: str
    city: str
    country: str
    region: str
    official_url: str
    distance: str = "marathon"
    state_province: str | None = None
    state_province_name: str | None = None
    registration_url: str | None = None
    registration_windows: list[RegistrationWindow] = field(default_factory=list)
    confidence: str = "unknown"
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Race":
        required = ["id", "name", "city", "country", "region"]
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ValueError(f"race entry missing required fields: {', '.join(missing)}")
            
        windows = []
        if "registration_windows" in raw and isinstance(raw["registration_windows"], list):
            windows = [RegistrationWindow.from_dict(w) for w in raw["registration_windows"]]
            
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            distance=str(raw.get("distance", "marathon")),
            city=str(raw["city"]),
            state_province=str(raw["state_province"]) if raw.get("state_province") else None,
            state_province_name=str(raw["state_province_name"]) if raw.get("state_province_name") else None,
            country=str(raw["country"]),
            region=str(raw["region"]),
            official_url=str(raw.get("official_url", "")),
            registration_url=raw.get("registration_url"),
            registration_windows=windows,
            confidence=str(raw.get("confidence", "unknown")),
            notes=str(raw.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "distance": self.distance,
            "city": self.city,
            "state_province": self.state_province,
            "state_province_name": self.state_province_name,
            "country": self.country,
            "region": self.region,
            "official_url": self.official_url,
            "registration_url": self.registration_url,
            "registration_windows": [w.to_dict() for w in self.registration_windows],
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class RaceResult:
    id: str
    name: str
    city: str
    country: str
    region: str
    official_url: str
    distance: str = "marathon"
    state_province: str | None = None
    state_province_name: str | None = None
    registration_url: str | None = None
    event_date: str | None = None
    year: int | None = None
    registration_windows: list[RegistrationWindow] = field(default_factory=list)
    source_url: str | None = None
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    extraction_method: str = "seed"
    confidence: str = "unknown"
    status: str = "active"
    notes: str = ""
    raw_evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_race(cls, race: Race, distance: str | None = None) -> "RaceResult":
        dist = distance if distance is not None else race.distance
        return cls(
            id=race.id,
            name=race.name,
            distance=dist,
            city=race.city,
            state_province=race.state_province,
            state_province_name=race.state_province_name,
            country=race.country,
            region=race.region,
            official_url=race.official_url,
            registration_url=race.registration_url,
            event_date=None,
            registration_windows=list(race.registration_windows),
            source_url=race.official_url,
            confidence=race.confidence,
            notes=race.notes,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RaceResult":
        windows = []
        if "registration_windows" in raw and isinstance(raw["registration_windows"], list):
            windows = [RegistrationWindow.from_dict(w) for w in raw["registration_windows"]]
            
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            distance=str(raw.get("distance", "marathon")),
            city=str(raw["city"]),
            state_province=str(raw["state_province"]) if raw.get("state_province") else None,
            state_province_name=str(raw["state_province_name"]) if raw.get("state_province_name") else None,
            country=str(raw["country"]),
            region=str(raw["region"]),
            official_url=str(raw.get("official_url", "")),
            registration_url=raw.get("registration_url"),
            event_date=str(raw["event_date"]) if raw.get("event_date") else None,
            year=raw.get("year"),
            registration_windows=windows,
            source_url=str(raw["source_url"]) if raw.get("source_url") else None,
            extracted_at=str(raw.get("extracted_at", "")),
            extraction_method=str(raw.get("extraction_method", "seed")),
            confidence=str(raw.get("confidence", "unknown")),
            status=str(raw.get("status", "active")),
            notes=str(raw.get("notes", "")),
            raw_evidence=list(raw.get("raw_evidence", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "distance": self.distance,
            "city": self.city,
            "state_province": self.state_province,
            "state_province_name": self.state_province_name,
            "country": self.country,
            "region": self.region,
            "official_url": self.official_url,
            "registration_url": self.registration_url,
            "event_date": self.event_date,
            "year": self.year,
            "registration_windows": [w.to_dict() for w in self.registration_windows],
            "source_url": self.source_url,
            "extracted_at": self.extracted_at,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "status": self.status,
            "notes": self.notes,
            "raw_evidence": self.raw_evidence,
        }
