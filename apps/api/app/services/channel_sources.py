import time
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import ApplicationChannel

_CACHE_SECONDS = 300
_host_cache: dict[tuple[str, str], tuple[float, set[str]]] = {}


def allowed_job_source_hosts(db: Session, user_id: str | None = None) -> set[str]:
    """Return env/global hosts plus private channel hosts visible to one user."""
    database_key = str(db.get_bind().url)
    cache_key = (database_key, user_id or "global-only")
    cached = _host_cache.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        channel_hosts = set(cached[1])
    else:
        visibility = ApplicationChannel.owner_user_id.is_(None)
        if user_id:
            visibility = or_(visibility, ApplicationChannel.owner_user_id == user_id)
        rows = db.scalars(
            select(ApplicationChannel.url).where(
                visibility,
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
    database_key = str(db.get_bind().url)
    for cache_key in [key for key in _host_cache if key[0] == database_key]:
        _host_cache.pop(cache_key, None)
