from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TrailerPosition:
    trailer_id: str
    latitude: float
    longitude: float
    speed: Optional[float] = None
    battery_pct: Optional[float] = None
    raw_status: Optional[str] = None
    landmark_state: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)
    provider_name: Optional[str] = None


class TrailerProvider(ABC):
    @abstractmethod
    async def fetch_positions(self) -> list[TrailerPosition]:
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...
