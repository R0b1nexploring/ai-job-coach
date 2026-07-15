import asyncio

from .base import JobProviderError
from .greenhouse import GreenhouseJobProvider
from .lever import LeverJobProvider


CATALOG_SOURCES = {
    "greenhouse": [
        ("formlabs", "Formlabs"),
        ("andurilindustries", "Anduril Industries"),
        ("10xgenomics", "10x Genomics"),
        ("astranis", "Astranis"),
    ],
    "lever": [("palantir", "Palantir")],
}


class PublicCatalogJobProvider:
    """Small catalog of employer-operated public feeds relevant to engineering roles."""

    def __init__(self, transport=None):
        self.transport = transport

    async def discover(self, *, keywords: list[str], cities: list[str], limit: int):
        sources = [
            (GreenhouseJobProvider(token, self.transport), company_name)
            for token, company_name in CATALOG_SOURCES["greenhouse"]
        ] + [
            (LeverJobProvider(site, self.transport), company_name)
            for site, company_name in CATALOG_SOURCES["lever"]
        ]
        results = await asyncio.gather(
            *(
                provider.discover(keywords=keywords, cities=[], limit=limit)
                for provider, _company_name in sources
            ),
            return_exceptions=True,
        )
        jobs = []
        for (_provider, company_name), result in zip(sources, results, strict=True):
            if isinstance(result, list):
                for job in result:
                    job.company_name = company_name
                    jobs.append(job)
        if not jobs and all(isinstance(result, Exception) for result in results):
            raise JobProviderError("公开企业职位合集暂时不可用。")

        def rank(job):
            city_match = bool(
                cities and job.city and any(city.lower() in job.city.lower() for city in cities)
            )
            return city_match, len(job.matched_keywords)

        jobs.sort(key=rank, reverse=True)
        unique = {}
        for job in jobs:
            unique.setdefault((job.provider, job.external_id), job)
        return list(unique.values())[:limit]
