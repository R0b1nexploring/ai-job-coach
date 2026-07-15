from .base import JobProviderError
from .catalog import PublicCatalogJobProvider
from .greenhouse import GreenhouseJobProvider
from .lever import LeverJobProvider
from .sample import SampleJobProvider


async def discover_jobs(
    *, provider: str, source_key: str, keywords: list[str], cities: list[str], limit: int
):
    fallback_used = False
    error = None
    try:
        if provider == "greenhouse":
            selected = GreenhouseJobProvider(source_key)
        elif provider == "lever":
            selected = LeverJobProvider(source_key)
        elif provider == "public_catalog":
            selected = PublicCatalogJobProvider()
        elif provider == "sample":
            selected = SampleJobProvider()
        else:
            raise JobProviderError("不支持的岗位来源。")
        jobs = await selected.discover(keywords=keywords, cities=cities, limit=limit)
    except JobProviderError as exc:
        if provider == "sample":
            raise
        fallback_used = True
        error = str(exc)
        jobs = await SampleJobProvider().discover(keywords=keywords, cities=cities, limit=limit)
    return jobs, fallback_used, error
