from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

MAX_RAW_JD_CHARS = 50_000


class JobProviderError(Exception):
    """A stable, redacted error at the external-job-provider boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "JOB_PROVIDER_ERROR",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DiscoveredJob(BaseModel):
    external_id: str = Field(min_length=1, max_length=500)
    company_name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    city: str = Field(default="", max_length=100)
    source_url: str = Field(max_length=2048)
    raw_jd: str = Field(min_length=10, max_length=MAX_RAW_JD_CHARS)
    published_at: datetime | None = None
    provider: Literal["greenhouse", "lever", "public_jsonld", "sample"]
    content_quality: str = Field(default="full_jd", max_length=50)
    matched_keywords: list[str] = Field(default_factory=list, max_length=100)


def validate_discovered_jobs(value, *, limit: int) -> list[DiscoveredJob]:
    if not isinstance(value, list):
        raise JobProviderError(
            "岗位来源返回无效数据。",
            code="JOB_PROVIDER_MALFORMED_RESPONSE",
        )
    try:
        return [
            item if isinstance(item, DiscoveredJob) else DiscoveredJob.model_validate(item)
            for item in value[:limit]
        ]
    except (ValidationError, TypeError, ValueError) as exc:
        raise JobProviderError(
            "岗位来源返回无效数据。",
            code="JOB_PROVIDER_MALFORMED_RESPONSE",
        ) from exc


class BaseJobProvider(Protocol):
    async def discover(
        self, *, keywords: list[str], cities: list[str], limit: int
    ) -> list[DiscoveredJob]: ...
