from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


DATE_FIELDS = (
    "event_date",
    "registration_open_date",
    "registration_deadline",
    "lottery_deadline",
    "qualification_deadline",
)


@dataclass(frozen=True)
class Race:
    id: str
    name: str
    city: str
    country: str
    region: str
    official_url: str
    registration_url: str | None = None
    source_url: str | None = None
    event_date: str | None = None
    registration_open_date: str | None = None
    registration_deadline: str | None = None
    lottery_deadline: str | None = None
    qualification_deadline: str | None = None
    confidence: str = "unknown"
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Race":
        required = ["id", "name", "city", "country", "region", "official_url"]
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ValueError(f"race entry missing required fields: {', '.join(missing)}")
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            city=str(raw["city"]),
            country=str(raw["country"]),
            region=str(raw["region"]),
            official_url=str(raw["official_url"]),
            registration_url=str(raw["registration_url"]) if raw.get("registration_url") else None,
            source_url=str(raw["source_url"]) if raw.get("source_url") else None,
            event_date=str(raw["event_date"]) if raw.get("event_date") else None,
            registration_open_date=str(raw["registration_open_date"]) if raw.get("registration_open_date") else None,
            registration_deadline=str(raw["registration_deadline"]) if raw.get("registration_deadline") else None,
            lottery_deadline=str(raw["lottery_deadline"]) if raw.get("lottery_deadline") else None,
            qualification_deadline=str(raw["qualification_deadline"]) if raw.get("qualification_deadline") else None,
            confidence=str(raw.get("confidence", "unknown")),
            notes=str(raw.get("notes", "")),
        )


@dataclass
class RaceResult:
    id: str
    name: str
    city: str
    country: str
    region: str
    official_url: str
    registration_url: str | None
    event_date: str | None = None
    registration_open_date: str | None = None
    registration_deadline: str | None = None
    lottery_deadline: str | None = None
    qualification_deadline: str | None = None
    source_url: str | None = None
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    extraction_method: str = "seed"
    confidence: str = "unknown"
    status: str = "active"
    notes: str = ""
    raw_evidence: list[str] = field(default_factory=list)

    @classmethod
    def from_race(cls, race: Race) -> "RaceResult":
        return cls(
            id=race.id,
            name=race.name,
            city=race.city,
            country=race.country,
            region=race.region,
            official_url=race.official_url,
            registration_url=race.registration_url,
            event_date=race.event_date,
            registration_open_date=race.registration_open_date,
            registration_deadline=race.registration_deadline,
            lottery_deadline=race.lottery_deadline,
            qualification_deadline=race.qualification_deadline,
            source_url=race.source_url or race.registration_url or race.official_url,
            confidence=race.confidence,
            notes=race.notes,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RaceResult":
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            city=str(raw["city"]),
            country=str(raw["country"]),
            region=str(raw["region"]),
            official_url=str(raw.get("official_url", "")),
            registration_url=str(raw["registration_url"]) if raw.get("registration_url") else None,
            event_date=str(raw["event_date"]) if raw.get("event_date") else None,
            registration_open_date=str(raw["registration_open_date"]) if raw.get("registration_open_date") else None,
            registration_deadline=str(raw["registration_deadline"]) if raw.get("registration_deadline") else None,
            lottery_deadline=str(raw["lottery_deadline"]) if raw.get("lottery_deadline") else None,
            qualification_deadline=str(raw["qualification_deadline"]) if raw.get("qualification_deadline") else None,
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
            "city": self.city,
            "country": self.country,
            "region": self.region,
            "official_url": self.official_url,
            "registration_url": self.registration_url,
            "event_date": self.event_date,
            "registration_open_date": self.registration_open_date,
            "registration_deadline": self.registration_deadline,
            "lottery_deadline": self.lottery_deadline,
            "qualification_deadline": self.qualification_deadline,
            "source_url": self.source_url,
            "extracted_at": self.extracted_at,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "status": self.status,
            "notes": self.notes,
            "raw_evidence": self.raw_evidence,
        }
