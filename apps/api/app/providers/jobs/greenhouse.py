import re

import httpx

from .base import DiscoveredJob, JobProviderError
from .common import plain_text, relevance


class GreenhouseJobProvider:
    def __init__(self, board_token: str, transport=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", board_token):
            raise JobProviderError("无效的 Greenhouse 企业标识。")
        self.board_token = board_token
        self.transport = transport

    async def discover(self, *, keywords: list[str], cities: list[str], limit: int):
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_token}/jobs"
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                response = await client.get(url, params={"content": "true"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise JobProviderError("Greenhouse 公开职位读取失败。") from exc
        results = []
        for item in payload.get("jobs", []):
            body = plain_text(str(item.get("content") or ""))
            title = str(item.get("title") or "").strip()
            city = str((item.get("location") or {}).get("name") or "").strip()
            hits = relevance(title, body, keywords, cities, city)
            if keywords and not hits:
                continue
            results.append(
                DiscoveredJob(
                    external_id=str(item.get("id") or item.get("absolute_url") or title),
                    company_name=self.board_token,
                    title=title,
                    city=city,
                    source_url=str(item.get("absolute_url") or ""),
                    raw_jd=body,
                    provider="greenhouse",
                    matched_keywords=hits,
                )
            )
            if len(results) >= limit:
                break
        return results
