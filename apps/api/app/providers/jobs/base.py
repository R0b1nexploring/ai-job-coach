from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class JobProviderError(Exception):
    pass


class DiscoveredJob(BaseModel):
    external_id: str
    company_name: str
    title: str
    city: str = ""
    source_url: str
    raw_jd: str
    published_at: datetime | None = None
    provider: str
    content_quality: str = "full_jd"
    matched_keywords: list[str] = Field(default_factory=list)


class BaseJobProvider(Protocol):
    async def discover(
        self, *, keywords: list[str], cities: list[str], limit: int
    ) -> list[DiscoveredJob]: ...
