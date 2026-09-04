from app.config import get_settings

from .base import JobProviderError, validate_discovered_jobs
from .catalog import PublicCatalogJobProvider
from .greenhouse import GreenhouseJobProvider
from .lever import LeverJobProvider
from .public_jsonld import PublicJsonLdJobProvider
from .sample import SampleJobProvider


async def discover_jobs(
    *,
    provider: str,
    source_key: str,
    keywords: list[str],
    cities: list[str],
    limit: int,
    allowed_hosts: set[str] | None = None,
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
        elif provider == "public_jsonld":
            selected = PublicJsonLdJobProvider(
                source_key,
                allowed_hosts=(
                    allowed_hosts
                    if allowed_hosts is not None
                    else get_settings().allowed_job_source_hosts()
                ),
            )
        elif provider == "sample":
            selected = SampleJobProvider()
        else:
            raise JobProviderError("不支持的岗位来源。")
        jobs = validate_discovered_jobs(
            await selected.discover(keywords=keywords, cities=cities, limit=limit),
            limit=limit,
        )
    except (
        AttributeError,
        KeyError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        # Provider adapters are an untrusted boundary.  Shape errors must not
        # escape as a 500 or expose the upstream body; use the controlled local
        # sample just like an explicit provider failure.
        if provider == "sample":
            raise JobProviderError(
                "受控样例岗位数据无效。",
                code="SAMPLE_PROVIDER_MALFORMED_RESPONSE",
            ) from exc
        fallback_used = True
        error = "岗位来源返回无效数据。"
        jobs = validate_discovered_jobs(
            await SampleJobProvider().discover(keywords=keywords, cities=cities, limit=limit),
            limit=limit,
        )
    except JobProviderError as exc:
        if provider == "sample":
            raise
        fallback_used = True
        error = str(exc)
        jobs = validate_discovered_jobs(
            await SampleJobProvider().discover(keywords=keywords, cities=cities, limit=limit),
            limit=limit,
        )
    return jobs, fallback_used, error
