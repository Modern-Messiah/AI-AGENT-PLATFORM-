from __future__ import annotations

import asyncio
import html as html_lib
import io
import ipaddress
import json
import logging
import posixpath
import re
import socket
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from packages.core import settings

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_MAX_REDIRECTS = 3
URL_SOURCE_HEADERS = {
    "User-Agent": "AI-Agent-Platform/1.0 (self-hosted URL source fetcher)",
}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/markdown",
}
_PDF_TYPES = {"application/pdf"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MIN_DECLARED_IMAGE_EDGE = 120
_NOISE_IMAGE_RE = re.compile(
    r"(avatar|badge|button|captcha|favicon|icon|logo|pixel|sprite|tracking)",
    re.IGNORECASE,
)
_MARKDOWN_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+['\"]([^'\"]*)['\"])?\s*\)"
)
_RST_IMAGE_RE = re.compile(r"(?im)^\s*\.\.\s+(?:image|figure)::\s+(\S+)\s*$")
_SUPPORTED_SUFFIX_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": "application/pdf",
}
_GITHUB_TEXT_SUFFIXES = {".md", ".markdown", ".mdx", ".rst", ".txt"}
_GITHUB_DIAGRAM_SUFFIXES = {".drawio", ".mmd", ".mermaid", ".plantuml", ".puml"}
_GITHUB_CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
_GITHUB_USEFUL_FILENAMES = {
    ".env.example",
    "docker-compose.yml",
    "docker-compose.yaml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
}
_GITHUB_USEFUL_PREFIXES = ("readme", "changelog", "contributing", "license")
_GITHUB_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
_GITHUB_MAX_FILES = 100
_GITHUB_MAX_FILE_BYTES = 512 * 1024
_GITHUB_MAX_ARCHIVE_BYTES = 75 * 1024 * 1024
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
_E2E_LOCAL_HOSTS = {"host.docker.internal"}


class UrlSourceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class UrlImageSource:
    url: str
    alt: str = ""
    title: str = ""


@dataclass(frozen=True)
class _GitHubSourceUrl:
    owner: str
    repo: str
    kind: str
    ref: str | None = None
    path: str = ""


@dataclass(frozen=True)
class FetchedUrlSource:
    requested_url: str
    final_url: str
    title: str | None
    filename: str
    content_type: str
    data: bytes
    image_sources: list[UrlImageSource] = field(default_factory=list)
    source_type: str = "url"
    discovered_files: list[str] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def file_count(self) -> int:
        return len(self.discovered_files)


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
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


class _ImageSourceParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.sources: list[UrlImageSource] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "img":
            return
        attr = {str(key).lower(): str(value or "") for key, value in attrs}
        if not _declared_image_size_is_useful(attr):
            return
        raw_url = _image_attr_url(attr)
        if not raw_url:
            return
        url = urljoin(self.base_url, raw_url.strip())
        if not _is_supported_image_url(url):
            return
        descriptor = " ".join(
            value for value in (url, attr.get("alt", ""), attr.get("title", "")) if value
        )
        if _NOISE_IMAGE_RE.search(descriptor):
            return
        if url in self._seen:
            return
        self._seen.add(url)
        self.sources.append(UrlImageSource(
            url=url,
            alt=attr.get("alt", "").strip()[:500],
            title=attr.get("title", "").strip()[:500],
        ))


class _ImageRefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "img":
            return
        attr = {str(key).lower(): str(value or "") for key, value in attrs}
        if not _declared_image_size_is_useful(attr):
            return
        raw_url = _image_attr_url(attr)
        if not raw_url:
            return
        self.refs.append((
            raw_url.strip(),
            attr.get("alt", "").strip(),
            attr.get("title", "").strip(),
        ))


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


def _int_attr(value: str) -> int | None:
    match = re.match(r"^\s*([0-9]{1,5})", value or "")
    return int(match.group(1)) if match else None


def _declared_image_size_is_useful(attrs: dict[str, str]) -> bool:
    width = _int_attr(attrs.get("width", ""))
    height = _int_attr(attrs.get("height", ""))
    if width is None or height is None:
        return True
    return max(width, height) >= _MIN_DECLARED_IMAGE_EDGE


def _srcset_largest_url(value: str) -> str:
    best_url = ""
    best_score = -1
    for candidate in value.split(","):
        parts = candidate.strip().split()
        if not parts:
            continue
        score = 0
        if len(parts) > 1:
            descriptor = parts[1].lower()
            if descriptor.endswith("w") and descriptor[:-1].isdigit():
                score = int(descriptor[:-1])
            elif descriptor.endswith("x"):
                try:
                    score = int(float(descriptor[:-1]) * 1000)
                except ValueError:
                    score = 0
        if score >= best_score:
            best_score = score
            best_url = parts[0]
    return best_url


def _image_attr_url(attrs: dict[str, str]) -> str:
    for key in ("src", "data-src", "data-original", "data-lazy-src"):
        value = attrs.get(key, "").strip()
        if value:
            return value
    srcset = attrs.get("srcset", "").strip() or attrs.get("data-srcset", "").strip()
    return _srcset_largest_url(srcset) if srcset else ""


def _is_supported_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    suffix = PurePosixPath(parsed.path).suffix.lower()
    return suffix in _IMAGE_SUFFIXES


def extract_html_image_sources(data: bytes, base_url: str) -> list[UrlImageSource]:
    parser = _ImageSourceParser(base_url)
    parser.feed(data.decode("utf-8", errors="ignore"))
    selected = max(0, settings.url_source_max_images)
    if len(parser.sources) > selected:
        log.info(
            "URL image source limit applied | base_url=%s found=%s selected=%s",
            base_url,
            len(parser.sources),
            selected,
        )
    return parser.sources[:selected]


def url_image_sidecar_key(object_key: str) -> str:
    return f"{object_key}.url-images.json"


def url_image_sidecar_payload(sources: list[UrlImageSource]) -> bytes:
    return json.dumps(
        {
            "images": [
                {"url": source.url, "alt": source.alt, "title": source.title}
                for source in sources
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


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


def _github_filename(source: _GitHubSourceUrl) -> str:
    return f"{_safe_name(f'GitHub_{source.owner}_{source.repo}')}.txt"


def _github_title(source: _GitHubSourceUrl) -> str:
    return f"GitHub: {source.owner}/{source.repo}"


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


def _parse_github_url(url: str) -> _GitHubSourceUrl | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if host == "github.com":
        if len(parts) < 2:
            return None
        owner = parts[0]
        repo = parts[1].removesuffix(".git")
        if len(parts) == 2:
            return _GitHubSourceUrl(owner=owner, repo=repo, kind="repo")
        if len(parts) >= 5 and parts[2] in {"blob", "tree"}:
            return _GitHubSourceUrl(
                owner=owner,
                repo=repo,
                kind=parts[2],
                ref=parts[3],
                path="/".join(parts[4:]),
            )
        return None

    if host == "raw.githubusercontent.com" and len(parts) >= 4:
        return _GitHubSourceUrl(
            owner=parts[0],
            repo=parts[1].removesuffix(".git"),
            kind="blob",
            ref=parts[2],
            path="/".join(parts[3:]),
        )

    return None


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


def _is_e2e_local_host_allowed(host: str) -> bool:
    return (
        settings.app_env.strip().lower() == "local"
        and settings.e2e_allow_local_url_sources
        and host.rstrip(".").lower() in _E2E_LOCAL_HOSTS
    )


async def validate_fetch_url(url: str) -> str:
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    host = parsed.hostname
    if not host:
        raise UrlSourceError("URL host is required")

    if _is_e2e_local_host_allowed(host):
        return normalized

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


async def _get_with_redirects(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    allowed_statuses: set[int] | None = None,
) -> tuple[str, httpx.Response]:
    current_url = await validate_fetch_url(url)
    allowed_statuses = allowed_statuses or set()
    for _ in range(_MAX_REDIRECTS + 1):
        try:
            response = await client.get(current_url)
        except httpx.RequestError as exc:
            raise UrlSourceError(f"URL request failed: {exc}") from exc

        if 300 <= response.status_code < 400 and response.headers.get("location"):
            current_url = await validate_fetch_url(urljoin(current_url, response.headers["location"]))
            continue

        if response.status_code in allowed_statuses:
            return current_url, response

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

        if len(response.content) > max_bytes:
            raise UrlSourceError(
                f"URL content exceeds {max_bytes // (1024 * 1024)} MB limit",
                status_code=413,
            )

        return current_url, response

    raise UrlSourceError("URL redirected too many times")


def _with_source_header(text: str, *, url: str, title: str | None) -> bytes:
    lines = [f"Source URL: {url}"]
    if title:
        lines.append(f"Title: {title}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines).encode("utf-8")


def _github_raw_url(source: _GitHubSourceUrl) -> str:
    if not source.ref or not source.path:
        raise UrlSourceError("GitHub file URL must include a ref and path")
    return f"https://raw.githubusercontent.com/{source.owner}/{source.repo}/{source.ref}/{source.path}"


def _github_raw_file_url(source: _GitHubSourceUrl, ref: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{source.owner}/{source.repo}/{ref}/{path}"


def _github_archive_url(source: _GitHubSourceUrl, ref: str) -> str:
    return f"https://codeload.github.com/{source.owner}/{source.repo}/zip/refs/heads/{ref}"


def _github_is_useful_path(path: str) -> bool:
    normalized = PurePosixPath(path)
    parts = [part.lower() for part in normalized.parts]
    if any(part in _GITHUB_SKIP_DIRS for part in parts):
        return False
    name = normalized.name.lower()
    suffix = normalized.suffix.lower()
    if name in _GITHUB_USEFUL_FILENAMES:
        return True
    if any(name.startswith(prefix) for prefix in _GITHUB_USEFUL_PREFIXES):
        return True
    return suffix in _GITHUB_TEXT_SUFFIXES | _GITHUB_DIAGRAM_SUFFIXES | _GITHUB_CONFIG_SUFFIXES


def _github_file_priority(path: str) -> tuple[int, str]:
    lower = path.lower()
    name = PurePosixPath(lower).name
    suffix = PurePosixPath(lower).suffix
    if name.startswith("readme"):
        rank = 0
    elif lower.startswith("docs/") or "/docs/" in lower:
        rank = 10
    elif suffix in _GITHUB_DIAGRAM_SUFFIXES:
        rank = 11
    elif suffix in _GITHUB_TEXT_SUFFIXES:
        rank = 20
    elif name in _GITHUB_USEFUL_FILENAMES:
        rank = 30
    else:
        rank = 40
    return rank, lower


def _decode_github_text(data: bytes, path: str) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "")
    if not text.strip():
        raise UrlSourceError(f"GitHub file has no readable text: {path}")
    return text.strip()


def _github_image_url_from_ref(
    source: _GitHubSourceUrl,
    *,
    ref: str,
    file_path: str,
    target: str,
) -> str | None:
    target = target.strip().strip("<>")
    if not target or target.startswith("#") or target.lower().startswith("data:"):
        return None

    parsed = urlparse(target)
    if parsed.scheme in {"http", "https"}:
        github_target = _parse_github_url(target)
        if github_target and github_target.kind == "blob":
            raw_url = _github_raw_url(github_target)
            return raw_url if _is_supported_image_url(raw_url) else None
        return target if _is_supported_image_url(target) else None
    if parsed.scheme:
        return None

    cleaned = target.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
    if not cleaned:
        return None
    if cleaned.startswith("/"):
        root = source.path.strip("/") if source.kind == "tree" and source.path else ""
        rel_path = posixpath.normpath(posixpath.join(root, cleaned.lstrip("/")))
    else:
        rel_path = posixpath.normpath(posixpath.join(posixpath.dirname(file_path), cleaned))
    if rel_path == "." or rel_path.startswith("../"):
        return None

    url = _github_raw_file_url(source, ref, rel_path)
    return url if _is_supported_image_url(url) else None


def _github_image_source(
    source: _GitHubSourceUrl,
    *,
    ref: str,
    file_path: str,
    target: str,
    alt: str = "",
    title: str = "",
) -> UrlImageSource | None:
    url = _github_image_url_from_ref(source, ref=ref, file_path=file_path, target=target)
    if not url:
        return None
    descriptor = " ".join(value for value in (url, alt, title) if value)
    if _NOISE_IMAGE_RE.search(descriptor):
        return None
    return UrlImageSource(url=url, alt=alt.strip()[:500], title=title.strip()[:500])


def _github_referenced_image_sources(
    source: _GitHubSourceUrl,
    *,
    ref: str,
    files: list[tuple[str, str]],
) -> list[UrlImageSource]:
    sources: list[UrlImageSource] = []
    seen: set[str] = set()
    selected = max(0, settings.github_source_max_images)
    if selected == 0:
        return []

    def add(candidate: UrlImageSource | None) -> None:
        if candidate is None or candidate.url in seen or len(sources) >= selected:
            return
        seen.add(candidate.url)
        sources.append(candidate)

    for file_path, text in files:
        for match in _MARKDOWN_IMAGE_RE.finditer(text):
            add(
                _github_image_source(
                    source,
                    ref=ref,
                    file_path=file_path,
                    target=match.group(2),
                    alt=match.group(1) or "",
                    title=match.group(3) or "",
                )
            )
        for match in _RST_IMAGE_RE.finditer(text):
            add(
                _github_image_source(
                    source,
                    ref=ref,
                    file_path=file_path,
                    target=match.group(1),
                )
            )
        html_parser = _ImageRefParser()
        html_parser.feed(text)
        for target, alt, title in html_parser.refs:
            add(
                _github_image_source(
                    source,
                    ref=ref,
                    file_path=file_path,
                    target=target,
                    alt=alt,
                    title=title,
                )
            )
        if len(sources) >= selected:
            break

    return sources


def _github_data(
    source: _GitHubSourceUrl,
    *,
    requested_url: str,
    ref: str,
    files: list[tuple[str, str]],
) -> bytes:
    lines = [
        f"Source URL: {requested_url}",
        f"GitHub Repository: {source.owner}/{source.repo}",
        f"Ref: {ref}",
        f"Files indexed: {len(files)}",
        "",
    ]
    for path, text in files:
        lines.extend([f"--- FILE: {path} ---", text, ""])
    return "\n".join(lines).encode("utf-8")


async def _fetch_github_blob_source(
    client: httpx.AsyncClient,
    source: _GitHubSourceUrl,
    *,
    requested_url: str,
    max_bytes: int,
) -> FetchedUrlSource:
    if not source.path or not _github_is_useful_path(source.path):
        raise UrlSourceError(
            "unsupported GitHub file type; use Markdown, text, diagram source, README, or config files"
        )
    raw_url = _github_raw_url(source)
    _, response = await _get_with_redirects(client, raw_url, max_bytes=max_bytes)
    if len(response.content) > _GITHUB_MAX_FILE_BYTES:
        raise UrlSourceError(
            f"GitHub file exceeds {_GITHUB_MAX_FILE_BYTES // 1024} KB limit",
            status_code=413,
        )
    text = _decode_github_text(response.content, source.path)
    files = [(source.path, text)]
    data = _github_data(
        source,
        requested_url=requested_url,
        ref=source.ref or "",
        files=files,
    )
    return FetchedUrlSource(
        requested_url=requested_url,
        final_url=requested_url,
        title=_github_title(source),
        filename=_github_filename(source),
        content_type="text/plain; charset=utf-8",
        data=data,
        image_sources=_github_referenced_image_sources(
            source,
            ref=source.ref or "",
            files=files,
        ),
        source_type="github",
        discovered_files=[source.path],
    )


def _github_files_from_archive(
    source: _GitHubSourceUrl,
    archive_data: bytes,
    *,
    max_bytes: int,
) -> list[tuple[str, str]]:
    prefix = source.path.strip("/")
    selected: list[tuple[str, zipfile.ZipInfo]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                parts = PurePosixPath(info.filename).parts
                if len(parts) < 2:
                    continue
                rel_path = PurePosixPath(*parts[1:]).as_posix()
                if prefix and rel_path != prefix and not rel_path.startswith(f"{prefix}/"):
                    continue
                if info.file_size > _GITHUB_MAX_FILE_BYTES:
                    continue
                if not _github_is_useful_path(rel_path):
                    continue
                selected.append((rel_path, info))

            selected.sort(key=lambda item: _github_file_priority(item[0]))
            files: list[tuple[str, str]] = []
            total = 0
            for rel_path, info in selected[:_GITHUB_MAX_FILES]:
                data = archive.read(info)
                text = _decode_github_text(data, rel_path)
                section_size = len(text.encode("utf-8")) + len(rel_path.encode("utf-8")) + 32
                if files and total + section_size > max_bytes:
                    break
                if not files and section_size > max_bytes:
                    raise UrlSourceError(
                        f"GitHub content exceeds {max_bytes // (1024 * 1024)} MB limit",
                        status_code=413,
                    )
                files.append((rel_path, text))
                total += section_size
    except zipfile.BadZipFile as exc:
        raise UrlSourceError("GitHub archive could not be read") from exc

    if not files:
        location = f" under '{prefix}'" if prefix else ""
        raise UrlSourceError(f"no useful GitHub files found{location}")
    return files


async def _fetch_github_archive_source(
    client: httpx.AsyncClient,
    source: _GitHubSourceUrl,
    *,
    requested_url: str,
    max_bytes: int,
) -> FetchedUrlSource:
    refs = [source.ref] if source.ref else ["main", "master"]
    last_404 = False
    for ref in refs:
        if not ref:
            continue
        archive_url = _github_archive_url(source, ref)
        _, response = await _get_with_redirects(
            client,
            archive_url,
            max_bytes=_GITHUB_MAX_ARCHIVE_BYTES,
            allowed_statuses={404},
        )
        if response.status_code == 404:
            last_404 = True
            continue

        files = _github_files_from_archive(source, response.content, max_bytes=max_bytes)
        data = _github_data(source, requested_url=requested_url, ref=ref, files=files)
        if len(data) > max_bytes:
            raise UrlSourceError(
                f"GitHub content exceeds {max_bytes // (1024 * 1024)} MB limit",
                status_code=413,
            )
        return FetchedUrlSource(
            requested_url=requested_url,
            final_url=requested_url,
            title=_github_title(source),
            filename=_github_filename(source),
            content_type="text/plain; charset=utf-8",
            data=data,
            image_sources=_github_referenced_image_sources(source, ref=ref, files=files),
            source_type="github",
            discovered_files=[path for path, _ in files],
        )

    if last_404:
        raise UrlSourceError("GitHub repository branch was not found")
    raise UrlSourceError("GitHub repository could not be fetched")


async def _fetch_github_source(source: _GitHubSourceUrl, requested_url: str) -> FetchedUrlSource:
    max_bytes = settings.url_source_max_bytes
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=False,
        headers=URL_SOURCE_HEADERS,
    ) as client:
        if source.kind == "blob":
            return await _fetch_github_blob_source(
                client,
                source,
                requested_url=requested_url,
                max_bytes=max_bytes,
            )
        return await _fetch_github_archive_source(
            client,
            source,
            requested_url=requested_url,
            max_bytes=max_bytes,
        )


async def fetch_url_source(url: str) -> FetchedUrlSource:
    requested_url = await validate_fetch_url(url)
    github_source = _parse_github_url(requested_url)
    if github_source is not None:
        return await _fetch_github_source(github_source, requested_url)

    max_bytes = settings.url_source_max_bytes

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=False,
        headers=URL_SOURCE_HEADERS,
    ) as client:
        current_url, response = await _get_with_redirects(
            client,
            requested_url,
            max_bytes=max_bytes,
        )

    data = response.content
    original_type = _supported_content_type(
        response.headers.get("content-type", ""),
        current_url,
    )
    title = extract_html_title(data) if original_type in _HTML_TYPES else None
    image_sources: list[UrlImageSource] = []

    if original_type in _HTML_TYPES:
        image_sources = extract_html_image_sources(data, current_url)
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
        image_sources=image_sources,
    )
