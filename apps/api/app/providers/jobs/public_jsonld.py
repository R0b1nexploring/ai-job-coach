import asyncio
import hashlib
import ipaddress
import json
import socket
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, time
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

from .base import DiscoveredJob, JobProviderError
from .common import plain_text, relevance

USER_AGENT = "AIJobCoachBot/0.1"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect an allowlisted hostname only to its pre-validated IP set.

    URL validation followed by a normal HTTP request has a DNS-rebinding gap:
    the HTTP stack may resolve a different (private) address at connect time.
    httpcore still uses the original hostname for Host/SNI, while this backend
    replaces only the TCP destination with a previously validated public IP.
    """

    def __init__(self, host: str, addresses: Iterable[str], backend=None):
        self.host = host.rstrip(".").casefold()
        self.addresses = tuple(dict.fromkeys(str(value) for value in addresses))
        self.backend = backend or AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        requested_host = host.decode() if isinstance(host, bytes) else str(host)
        if requested_host.rstrip(".").casefold() != self.host:
            raise httpcore.ConnectError("未验证的网络目标")
        last_error = None
        for address in self.addresses:
            try:
                return await self.backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise httpcore.ConnectError("没有可用的已验证地址")

    async def connect_unix_socket(self, path: str, timeout=None, socket_options=None):
        raise httpcore.ConnectError("不允许 Unix socket")

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, host: str, addresses: Iterable[str]):
        # Ignore environment proxy settings: proxy DNS/connect behavior would
        # bypass the pinned network backend and reintroduce the TOCTOU gap.
        super().__init__(trust_env=False, retries=0)
        self._pool._network_backend = _PinnedNetworkBackend(host, addresses)


class _JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._capturing = False
        self._parts: list[str] = []
        self.documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        values = {name.lower(): (value or "").lower() for name, value in attrs}
        if values.get("type", "").split(";", 1)[0].strip() == "application/ld+json":
            self._capturing = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capturing:
            self.documents.append("".join(self._parts))
            self._capturing = False
            self._parts = []


def _allowed_host(host: str, allowed_hosts: set[str]) -> bool:
    normalized = host.rstrip(".").lower()
    for entry in allowed_hosts:
        value = entry.strip().rstrip(".").lower()
        if value.startswith("*.") and normalized.endswith(value[1:]) and normalized != value[2:]:
            return True
        if normalized == value:
            return True
    return False


def _validate_url(source_url: str, allowed_hosts: set[str]):
    try:
        parsed = urlsplit(source_url.strip())
        port = parsed.port
    except ValueError as exc:
        raise JobProviderError("公开招聘页 URL 无效。") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        raise JobProviderError("公开招聘页必须使用白名单域名的 HTTPS URL。")
    host = parsed.hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise JobProviderError("公开招聘页不允许使用 IP 地址。")
    if not allowed_hosts or not _allowed_host(host, allowed_hosts):
        raise JobProviderError(
            "该公开招聘页域名未加入白名单/允许列表（JOB_SOURCE_ALLOWED_HOSTS 或已导入投递渠道）。"
        )
    return parsed, host


def _resolve_host(host: str) -> list[str]:
    try:
        return list(
            dict.fromkeys(
                item[4][0]
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                if item[4]
            )
        )
    except OSError as exc:
        raise JobProviderError("公开招聘页域名解析失败。") from exc


def _ensure_public_addresses(addresses: Iterable[str]) -> None:
    values = list(addresses)
    if not values:
        raise JobProviderError("公开招聘页域名没有可用地址。")
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise JobProviderError("公开招聘页域名解析结果无效。") from exc
        if not address.is_global:
            raise JobProviderError("公开招聘页不能指向本机或私有网络。")


async def _limited_get(client: httpx.AsyncClient, url: str, max_bytes: int) -> httpx.Response:
    try:
        async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
            if response.is_redirect:
                raise JobProviderError("公开招聘页不跟随重定向，请输入最终 HTTPS URL。")
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and int(declared) > max_bytes:
                raise JobProviderError("公开招聘页响应内容过大。")
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > max_bytes:
                    raise JobProviderError("公开招聘页响应内容过大。")
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(chunks),
                request=response.request,
            )
    except JobProviderError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise JobProviderError("公开招聘页读取失败。") from exc


def _job_postings(value) -> Iterable[dict]:
    if isinstance(value, list):
        for item in value:
            yield from _job_postings(item)
        return
    if not isinstance(value, dict):
        return
    item_type = value.get("@type")
    types = item_type if isinstance(item_type, list) else [item_type]
    if any(str(name).lower() == "jobposting" for name in types):
        yield value
    if "@graph" in value:
        yield from _job_postings(value["@graph"])


def _as_text(value) -> str:
    if isinstance(value, str):
        return plain_text(value)
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _as_text(item)))
    return ""


def _company(item: dict, host: str) -> str:
    organization = item.get("hiringOrganization")
    if isinstance(organization, dict) and str(organization.get("name") or "").strip():
        return str(organization["name"]).strip()
    return host


def _city(item: dict) -> str:
    locations = item.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    values = []
    for location in locations if isinstance(locations, list) else []:
        if not isinstance(location, dict):
            continue
        address = location.get("address") or {}
        if not isinstance(address, dict):
            continue
        parts = [
            str(address.get(key) or "").strip()
            for key in ("addressLocality", "addressRegion", "addressCountry")
        ]
        text_value = " · ".join(part for part in parts if part)
        if text_value:
            values.append(text_value)
    return " / ".join(dict.fromkeys(values))


def _published_at(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            return datetime.combine(datetime.fromisoformat(raw).date(), time.min, tzinfo=UTC)
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _external_id(item: dict, source_url: str, title: str, company_name: str) -> str:
    identifier = item.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name")
    value = str(identifier or item.get("url") or "").strip()
    if value:
        return value[:500]
    return hashlib.sha256(f"{source_url}|{company_name}|{title}".encode()).hexdigest()


class PublicJsonLdJobProvider:
    """Read schema.org JobPosting data from explicitly allowlisted public pages."""

    def __init__(
        self,
        source_url: str,
        allowed_hosts: set[str],
        transport=None,
        resolver: Callable[[str], list[str]] | None = None,
    ):
        self.source_url = source_url.strip()
        self.parsed_url, self.host = _validate_url(self.source_url, allowed_hosts)
        self.transport = transport
        self.resolver = resolver or _resolve_host

    async def discover(self, *, keywords: list[str], cities: list[str], limit: int):
        addresses = await asyncio.to_thread(self.resolver, self.host)
        _ensure_public_addresses(addresses)
        robots_url = f"https://{self.host}/robots.txt"
        transport = self.transport or _PinnedAsyncHTTPTransport(self.host, addresses)
        async with httpx.AsyncClient(
            timeout=20,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            try:
                robots_response = await _limited_get(client, robots_url, MAX_ROBOTS_BYTES)
            except JobProviderError as exc:
                missing_robots = (
                    isinstance(exc.__cause__, httpx.HTTPStatusError)
                    and exc.__cause__.response.status_code == 404
                )
                if missing_robots:
                    robots_response = None
                else:
                    raise JobProviderError("无法确认公开招聘页的 robots.txt 访问规则。") from exc
            if robots_response is not None:
                robots = RobotFileParser()
                robots.set_url(robots_url)
                robots.parse(robots_response.text.splitlines())
                if not robots.can_fetch(USER_AGENT, self.source_url):
                    raise JobProviderError("该网站的 robots.txt 不允许读取此招聘页。")
            response = await _limited_get(client, self.source_url, MAX_PAGE_BYTES)

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise JobProviderError("公开招聘页不是可解析的 HTML 页面。")
        parser = _JsonLdParser()
        parser.feed(response.text)
        postings = []
        for document in parser.documents:
            try:
                postings.extend(_job_postings(json.loads(document)))
            except (json.JSONDecodeError, TypeError):
                continue
        if not postings:
            raise JobProviderError("页面未提供可识别的 JobPosting 结构化岗位数据。")

        results = []
        for item in postings:
            title = str(item.get("title") or "").strip()
            body = "\n".join(
                dict.fromkeys(
                    part
                    for key in (
                        "description",
                        "responsibilities",
                        "qualifications",
                        "skills",
                        "experienceRequirements",
                        "educationRequirements",
                    )
                    if (part := _as_text(item.get(key)))
                )
            )
            if not title or len(body) < 10:
                continue
            city = _city(item)
            hits = relevance(title, body, keywords, cities, city)
            if keywords and not hits:
                continue
            company_name = _company(item, self.host)
            results.append(
                DiscoveredJob(
                    external_id=_external_id(item, self.source_url, title, company_name),
                    company_name=company_name,
                    title=title,
                    city=city,
                    source_url=self.source_url,
                    raw_jd=body,
                    published_at=_published_at(item.get("datePosted")),
                    provider="public_jsonld",
                    content_quality="structured_jobposting",
                    matched_keywords=hits,
                )
            )
            if len(results) >= limit:
                break
        return results
