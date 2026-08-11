import time
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import ApplicationChannel

_CACHE_SECONDS = 300
_host_cache: dict[str, tuple[float, set[str]]] = {}


def allowed_job_source_hosts(db: Session) -> set[str]:
    cache_key = str(db.get_bind().url)
    cached = _host_cache.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        channel_hosts = set(cached[1])
    else:
        rows = db.scalars(
            select(ApplicationChannel.url).where(
                ApplicationChannel.channel_type == "career_page",
                ApplicationChannel.verify_status != "dead",
                ApplicationChannel.url != "",
            )
        )
        channel_hosts = {
            host for url in rows if (host := (urlsplit(url).hostname or "").rstrip(".").casefold())
        }
        _host_cache[cache_key] = (now + _CACHE_SECONDS, channel_hosts)
    return get_settings().allowed_job_source_hosts() | channel_hosts


def visible_channel_query(user_id: str):
    return select(ApplicationChannel).where(
        or_(
            ApplicationChannel.owner_user_id.is_(None),
            ApplicationChannel.owner_user_id == user_id,
        )
    )


def invalidate_channel_host_cache(db: Session | None = None) -> None:
    if db is None:
        _host_cache.clear()
        return
    _host_cache.pop(str(db.get_bind().url), None)
