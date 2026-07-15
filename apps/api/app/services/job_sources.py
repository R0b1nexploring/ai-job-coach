import json
from pathlib import Path
from typing import Protocol

from .job_normalizer import normalize_job


class JobSource(Protocol):
    def fetch(self) -> list[dict]: ...
    def normalize(self, raw: dict) -> dict: ...
    def deduplicate_key(self, job: dict) -> str: ...


class ManualJobSource:
    def fetch(self) -> list[dict]:
        return []

    def normalize(self, raw: dict) -> dict:
        return normalize_job(
            raw["raw_jd"], raw.get("title", ""), raw.get("company_name", ""), raw.get("city", "")
        )

    def deduplicate_key(self, job: dict) -> str:
        return "|".join(
            [
                job.get("company_name", ""),
                job.get("title", ""),
                job.get("city", ""),
                job["content_hash"],
            ]
        )


class SampleJobSource(ManualJobSource):
    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> list[dict]:
        return [json.loads(self.path.read_text(encoding="utf-8"))]


class CompanySiteSource(ManualJobSource):
    """Controlled adapter placeholder; no third-party generic scraping in MVP-1."""

    def fetch(self) -> list[dict]:
        raise NotImplementedError("企业官网适配器需逐来源确认访问许可后实现")
