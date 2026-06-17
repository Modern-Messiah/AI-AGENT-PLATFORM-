from __future__ import annotations

import asyncio
import html as html_lib
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from packages.core import settings

_TIMEOUT = 10.0
_MAX_REDIRECTS = 3
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/markdown",
}
_PDF_TYPES = {"application/pdf"}
_SUPPORTED_SUFFIX_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": "application/pdf",
}
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}


class UrlSourceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class FetchedUrlSource:
    requested_url: str
    final_url: str
    title: str | None
    filename: str
    content_type: str
    data: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self._parts.append(data)

    def text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def extract_html_title(data: bytes) -> str | None:
    text = data[:200_000].decode("utf-8", errors="ignore")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return html_lib.unescape(title)[:512] or None


def html_to_text(data: bytes) -> str:
    parser = _ReadableTextParser()
    parser.feed(data.decode("utf-8", errors="ignore"))
    return parser.text()


def _content_type_header(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _extension_for_type(content_type: str) -> str:
    normalized = _content_type_header(content_type)
    if normalized in _PDF_TYPES:
        return ".pdf"
    if normalized in _TEXT_TYPES:
        return ".md" if "markdown" in normalized else ".txt"
    return ".txt"


def _safe_name(value: str) -> str:
    value = html_lib.unescape(value).strip()
    value = re.sub(r"[^\w.\-]+", "_", value, flags=re.UNICODE)
    value = value.strip("._-")
    return value[:120] or "url-source"


def safe_url_filename(url: str, title: str | None, content_type: str) -> str:
    parsed = urlparse(url)
    suffix = _extension_for_type(content_type)
    if title:
        return f"{_safe_name(title)}{suffix}"

    path_name = PurePosixPath(parsed.path).name
    if path_name:
        base = _safe_name(path_name)
        if "." in base:
            return base[:160]
        return f"{base}{suffix}"

    host = parsed.hostname or "url-source"
    return f"{_safe_name(host)}{suffix}"


def _normalize_url(url: str) -> str:
    raw = url.strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UrlSourceError("only http/https URLs are supported")
    if not parsed.hostname:
        raise UrlSourceError("URL host is required")
    if parsed.username or parsed.password:
        raise UrlSourceError("URL credentials are not allowed")
    return urlunparse(parsed._replace(scheme=parsed.scheme.lower(), fragment=""))


def _allowlist_error(host: str) -> str | None:
    normalized_host = host.rstrip(".").lower()
    for domain in settings.http_fetch_allowed_domains:
        normalized_domain = domain.strip().rstrip(".").lower()
        if normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}"):
            return None
    return f"domain '{host}' is not in HTTP_FETCH_ALLOWED_DOMAINS"


def _is_blocked_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


async def validate_fetch_url(url: str) -> str:
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    host = parsed.hostname
    if not host:
        raise UrlSourceError("URL host is required")

    host_is_ip = False
    try:
        if _is_blocked_ip(host):
            raise UrlSourceError("requests to private or internal network addresses are not allowed")
        host_is_ip = True
    except ValueError:
        pass

    if settings.http_fetch_allowed_domains:
        err = _allowlist_error(host)
        if err:
            raise UrlSourceError(err)
        return normalized

    if host_is_ip:
        return normalized

    if settings.app_env.strip().lower() != "local":
        raise UrlSourceError(
            "HTTP_FETCH_ALLOWED_DOMAINS is required before URL sources can be fetched outside local mode",
            status_code=403,
        )

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.run_in_executor(None, socket.getaddrinfo, host, None)
    except OSError as exc:
        raise UrlSourceError(f"DNS resolution failed: {exc}") from exc

    for _, _, _, _, sockaddr in infos:
        ip = sockaddr[0]
        if _is_blocked_ip(ip):
            raise UrlSourceError("requests to private or internal network addresses are not allowed")

    return normalized


def _supported_content_type(content_type: str, url: str) -> str:
    normalized = _content_type_header(content_type)
    if normalized in _HTML_TYPES | _TEXT_TYPES | _PDF_TYPES:
        return normalized

    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    if suffix in _SUPPORTED_SUFFIX_TYPES:
        return _SUPPORTED_SUFFIX_TYPES[suffix]

    raise UrlSourceError(
        "unsupported URL content type; supported types are HTML, plain text, Markdown, and PDF"
    )


def _with_source_header(text: str, *, url: str, title: str | None) -> bytes:
    lines = [f"Source URL: {url}"]
    if title:
        lines.append(f"Title: {title}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines).encode("utf-8")


async def fetch_url_source(url: str) -> FetchedUrlSource:
    requested_url = await validate_fetch_url(url)
    current_url = requested_url
    max_bytes = settings.url_source_max_bytes

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            try:
                response = await client.get(current_url)
            except httpx.RequestError as exc:
                raise UrlSourceError(f"URL request failed: {exc}") from exc
            if 300 <= response.status_code < 400 and response.headers.get("location"):
                current_url = await validate_fetch_url(urljoin(current_url, response.headers["location"]))
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise UrlSourceError(
                    f"URL returned HTTP {exc.response.status_code}",
                    status_code=400,
                ) from exc

            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise UrlSourceError(
                    f"URL content exceeds {max_bytes // (1024 * 1024)} MB limit",
                    status_code=413,
                )

            data = response.content
            if len(data) > max_bytes:
                raise UrlSourceError(
                    f"URL content exceeds {max_bytes // (1024 * 1024)} MB limit",
                    status_code=413,
                )

            original_type = _supported_content_type(
                response.headers.get("content-type", ""),
                current_url,
            )
            title = extract_html_title(data) if original_type in _HTML_TYPES else None

            if original_type in _HTML_TYPES:
                text = html_to_text(data)
                if not text.strip():
                    raise UrlSourceError("HTML page has no readable text")
                data = _with_source_header(text, url=current_url, title=title)
                content_type = "text/plain; charset=utf-8"
            elif original_type in _TEXT_TYPES:
                text = data.decode("utf-8", errors="ignore")
                data = _with_source_header(text, url=current_url, title=None)
                content_type = response.headers.get("content-type") or "text/plain; charset=utf-8"
            else:
                content_type = response.headers.get("content-type") or "application/pdf"

            return FetchedUrlSource(
                requested_url=requested_url,
                final_url=current_url,
                title=title,
                filename=safe_url_filename(current_url, title, original_type),
                content_type=content_type,
                data=data,
            )

    raise UrlSourceError("URL redirected too many times")
