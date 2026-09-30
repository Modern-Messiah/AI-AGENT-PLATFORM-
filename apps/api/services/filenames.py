"""Sanitizers for client-supplied filenames.

Upload filenames end up in MinIO object keys (`{tenant}/{doc}/{filename}`)
and in DB display names. The client controls the raw value: it may carry
path components (`../`), backslashes, control characters, or be None, so
it must never be used verbatim. URL sources already sanitize via
url_sources.safe_url_filename; these helpers do the same job for
multipart uploads.
"""

from __future__ import annotations

import re

_MAX_NAME_CHARS = 200

# Path separators and control characters have no business in a filename.
_UNSAFE_CHARS = re.compile(r"[/\\\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def safe_upload_filename(filename: str | None) -> str:
    """Return a storage- and display-safe version of an upload filename.

    Takes the final path component (clients send absolute paths and ..
    traversal just as often as plain names), strips separators and control
    characters, collapses whitespace, trims leading dots (hidden-file
    prefixes like ".env" become "env"), caps the length, and falls back to
    "unnamed" for empty input.
    """
    name = (filename or "").strip()
    # Basename for both separators, then strip whatever remains.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("_", name)
    name = _WHITESPACE.sub("_", name)
    name = name.strip(" .")
    if len(name) > _MAX_NAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 16:
            name = stem[: _MAX_NAME_CHARS - len(ext) - 1] + "." + ext
        else:
            name = name[:_MAX_NAME_CHARS]
    return name or "unnamed"
