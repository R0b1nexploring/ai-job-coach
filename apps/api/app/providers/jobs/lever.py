import re
from datetime import datetime, timezone

import httpx

from .base import DiscoveredJob, JobProviderError
from .common import plain_text, relevance


class LeverJobProvider:
    def __init__(self, site: str, transport=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", site):
            raise JobProviderError("无效的 Lever 企业标识。")
        self.site = site
        self.transport = transport

    async def discover(self, *, keywords: list[str], cities: list[str], limit: int):
        url = f"https://api.lever.co/v0/postings/{self.site}"
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                response = await client.get(url, params={"mode": "json"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise JobProviderError("Lever 公开职位读取失败。") from exc
        results = []
        for item in payload if isinstance(payload, list) else []:
            lists = "\n".join(
                f"{part.get('text', '')}\n{plain_text(str(part.get('content', '')))}"
                for part in (item.get("lists") or [])
            )
            body = "\n".join(
                value
                for value in [
                    str(item.get("descriptionPlain") or ""),
                    lists,
                    plain_text(str(item.get("additionalPlain") or "")),
                ]
                if value
            )
            title = str(item.get("text") or "").strip()
            city = str((item.get("categories") or {}).get("location") or "").strip()
            hits = relevance(title, body, keywords, cities, city)
            if keywords and not hits:
                continue
            published_at = None
            created_at = item.get("createdAt")
            if isinstance(created_at, (int, float)):
                published_at = datetime.fromtimestamp(created_at / 1000, timezone.utc)
            results.append(
                DiscoveredJob(
                    external_id=str(item.get("id") or item.get("hostedUrl") or title),
                    company_name=self.site,
                    title=title,
                    city=city,
                    source_url=str(item.get("hostedUrl") or ""),
                    raw_jd=body,
                    published_at=published_at,
                    provider="lever",
                    matched_keywords=hits,
                )
            )
            if len(results) >= limit:
                break
        return results
