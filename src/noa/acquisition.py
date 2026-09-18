"""Document acquisition: policy-checked HTTPS download into CAS, text
extraction for plain text/HTML/XML, and evidence locators (contract sections 6.2, 8.2, 8.3)."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from html.parser import HTMLParser
from types import TracebackType
from typing import ClassVar

from .storage import ObjectStore
from .workspace import NetworkPolicy, ResourceBudgets, WorkspaceError

_MAX_TEXT_BYTES = 16 * 1024 * 1024


class AcquisitionError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def _error(code: str, message: str, **context: str) -> AcquisitionError:
    return AcquisitionError(code=code, message=message, context=context)


class _AcquireResponse(AbstractContextManager["_AcquireResponse"]):
    def __init__(self, geturl: str, media_type: str, payload: bytes) -> None:
        self._geturl = geturl
        self.media_type = media_type
        self.payload = payload

    def geturl(self) -> str:
        return self._geturl

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": self.media_type}

    def read(self, amount: int) -> bytes:
        chunk = self.payload[:amount]
        self.payload = self.payload[len(chunk) :]
        return chunk

    def __enter__(self) -> _AcquireResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: TracebackType | None) -> None:
        return None


@dataclass(frozen=True)
class AcquiredDocument:
    digest: str
    size: int
    media_type: str
    final_url: str


@dataclass(frozen=True)
class ExtractedText:
    media_type: str
    text: str
    truncated: bool


def _check_response_url(url: str, policy: NetworkPolicy) -> None:
    policy.assert_url_allowed(url)


def acquire_document(
    url: str,
    *,
    objects: ObjectStore,
    policy: NetworkPolicy,
    budgets: ResourceBudgets,
    opener: Callable[..., AbstractContextManager[_AcquireResponse]] = urllib.request.urlopen,
) -> AcquiredDocument:
    """Download one document under the network policy and publish it to CAS.

    Every redirect hop is re-validated against the policy before following.
    """
    _check_response_url(url, policy)
    try:
        with opener(url, timeout=budgets.download_timeout_seconds) as response:
            final_url = response.geturl()
            _check_response_url(final_url, policy)
            content_type = str(response.headers.get("Content-Type", "application/octet-stream"))
            media_type = content_type.split(";", 1)[0].strip().lower() or "application/octet-stream"
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > budgets.max_document_bytes:
                    raise _error(
                        "document_too_large",
                        f"Download exceeded {budgets.max_document_bytes} bytes",
                        url=url,
                    )
                chunks.append(chunk)
    except urllib.error.HTTPError as error:
        raise _error(
            "download_http_error",
            f"HTTP {error.code} while downloading {url!r}",
            url=url,
            http_status=str(error.code),
        ) from error
    except WorkspaceError:
        raise
    except Exception as error:
        raise _error(
            "download_failed",
            f"Download of {url!r} failed: {type(error).__name__}",
            url=url,
        ) from error
    payload = b"".join(chunks)
    digest = objects.put(payload)
    return AcquiredDocument(digest=digest, size=total, media_type=media_type, final_url=final_url)


class _TagStripper(HTMLParser):
    _SKIP: ClassVar[set[str]] = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._chunks)


def extract_text(media_type: str, payload: bytes) -> ExtractedText:
    """Extract UTF-8 text for trusted-shape content types; PDF stays explicit."""
    if len(payload) > _MAX_TEXT_BYTES:
        raise _error(
            "text_too_large",
            f"Payload of {len(payload)} bytes exceeds the extraction budget",
        )
    truncated = False
    if media_type.startswith("text/plain") or media_type in ("", "application/octet-stream"):
        text = payload.decode("utf-8", errors="replace")
    elif media_type in ("text/html", "application/xhtml+xml"):
        stripper = _TagStripper()
        try:
            stripper.feed(payload.decode("utf-8", errors="replace"))
            stripper.close()
        except Exception as error:
            raise _error(
                "html_parse_failed",
                f"HTML parsing failed: {type(error).__name__}",
            ) from error
        text = stripper.text()
    elif media_type in ("application/xml", "text/xml", "application/tei+xml"):
        if b"<!ENTITY" in payload or b"<!DOCTYPE" in payload:
            raise _error(
                "xml_entities_denied",
                "XML payloads with DTDs or entity declarations are rejected",
            )
        stripper = _TagStripper()
        try:
            stripper.feed(payload.decode("utf-8", errors="replace"))
            stripper.close()
        except Exception as error:
            raise _error(
                "xml_parse_failed",
                f"XML parsing failed: {type(error).__name__}",
            ) from error
        text = stripper.text()
    elif media_type == "application/pdf":
        raise _error(
            "capability_unavailable",
            "PDF text extraction is not available in this build; "
            "store the object and attach an external extraction result instead",
        )
    else:
        raise _error(
            "unsupported_media_type",
            f"No text extraction path for {media_type!r}",
            media_type=media_type,
        )
    if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
        encoded = text.encode("utf-8")[:_MAX_TEXT_BYTES]
        text = encoded.decode("utf-8", errors="ignore")
        truncated = True
    return ExtractedText(media_type=media_type, text=text, truncated=truncated)


def page_locator(page: int) -> str:
    if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
        raise _error("invalid_locator_page", "Page must be a positive integer")
    return f"p.{page}"


__all__ = [
    "AcquiredDocument",
    "AcquisitionError",
    "ExtractedText",
    "acquire_document",
    "extract_text",
    "page_locator",
]
