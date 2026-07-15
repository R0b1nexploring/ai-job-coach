from app.config import ROOT

from .base import DiscoveredJob


class SampleJobProvider:
    async def discover(self, *, keywords: list[str], cities: list[str], limit: int):
        import json

        item = json.loads((ROOT / "data/samples/sample_job.json").read_text(encoding="utf-8"))
        raw_jd = "\n".join(
            [
                *item.get("responsibilities", []),
                *item.get("must_have", []),
                *item.get("nice_to_have", []),
                *item.get("work_conditions", []),
            ]
        )
        hits = [word for word in keywords if word.lower() in f"{item['title']} {raw_jd}".lower()]
        return [
            DiscoveredJob(
                external_id="controlled-sample-1",
                company_name=item["company"],
                title=item["title"],
                city=item.get("city", ""),
                source_url=item.get("source_url", ""),
                raw_jd=raw_jd,
                published_at=item.get("published_at"),
                provider="sample",
                content_quality="controlled_sample",
                matched_keywords=hits,
            )
        ][:limit]
