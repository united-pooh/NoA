"""Collection plans, source adapters (Crossref/OpenAlex payload transforms),
rate-limited pagination, and batch proposal assembly (contract sections 5.5, 6.1)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import (
    AuthorityTier,
    ContentDigest,
    FactualPredicate,
    IdentifierScheme,
    IntegerAssertionValue,
    LanguageTag,
    MetadataAssertionId,
    MetadataFieldKey,
    RelationshipAssertionId,
    SourceMetadataAssertionProposal,
    SourceRecordId,
    SourceRelationshipAssertionProposal,
    SourceWriteBatchProposal,
    TextAssertionValue,
    UtcInstant,
    normalize_identifier,
)
from .domain.ids import PublicationId, WorkId


class AdapterError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def _error(code: str, message: str, **context: str) -> AdapterError:
    return AdapterError(code=code, message=message, context=context)


@dataclass(frozen=True)
class CollectionPlan:
    name: str
    source_system: str
    query: str
    max_records: int
    min_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.max_records <= 0:
            raise _error("invalid_collection_plan", "max_records must be positive")


class PageFetcher(Protocol):
    def __call__(
        self, plan: CollectionPlan, page_token: str | None
    ) -> tuple[list[dict[str, Any]], str | None]: ...


def iter_payloads(
    plan: CollectionPlan,
    fetch_page: PageFetcher,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> Iterator[dict[str, Any]]:
    token: str | None = None
    yielded = 0
    deadline_pages = plan.max_records * 10 + 10
    pages = 0
    while yielded < plan.max_records:
        pages += 1
        if pages > deadline_pages:
            raise _error(
                "collection_page_limit",
                f"Adapter exceeded the page budget for plan {plan.name!r}",
            )
        records, token = fetch_page(plan, token)
        sleeper(plan.min_interval_seconds)
        for record in records:
            if yielded >= plan.max_records:
                return
            yielded += 1
            yield record
        if token is None:
            return


@dataclass(frozen=True)
class RecordDraft:
    source_record_key: str
    doi: str | None
    title: str
    language: str | None
    year: int | None
    container_title: str | None = None
    authors: tuple[str, ...] = field(default_factory=tuple)

    def idempotency_key(self, source_system: str) -> str:
        identity = self.doi or self.source_record_key
        return f"{source_system}:{identity}"


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _error(
            "adapter_payload_invalid",
            f"Payload field {key!r} must be a nonempty string",
        )
    return value.strip()


def _normalize_year(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit() and len(value) == 4:
        return int(value)
    return None


def crossref_draft(payload: dict[str, Any]) -> RecordDraft:
    doi_raw = payload.get("DOI")
    doi: str | None = None
    if isinstance(doi_raw, str) and doi_raw.strip():
        key = normalize_identifier(IdentifierScheme.DOI, doi_raw.strip())
        doi = key.normalized_value
    titles = payload.get("title")
    if isinstance(titles, list) and titles and isinstance(titles[0], str):
        title = titles[0].strip()
    elif isinstance(titles, str):
        title = titles.strip()
    else:
        raise _error(
            "adapter_payload_invalid",
            "Crossref payload is missing a usable title field",
        )
    language = payload.get("language")
    container = payload.get("container-title")
    authors: list[str] = []
    raw_authors = payload.get("author")
    if isinstance(raw_authors, list):
        for author in raw_authors:
            if isinstance(author, dict):
                family = author.get("family")
                given = author.get("given")
                name = " ".join(part.strip() for part in (family or "", given or "") if part)
                if name:
                    authors.append(name)
    issued = payload.get("issued", {})
    year: int | None = None
    if isinstance(issued, dict):
        date_parts = issued.get("date-parts")
        if (
            isinstance(date_parts, list)
            and date_parts
            and isinstance(date_parts[0], list)
            and date_parts[0]
        ):
            year = _normalize_year(date_parts[0][0])
    return RecordDraft(
        source_record_key=_require_str(payload, "DOI") if doi is None else doi,
        doi=doi,
        title=title,
        language=language.strip().lower()
        if isinstance(language, str) and language.strip()
        else None,
        year=year,
        container_title=container[0].strip()
        if isinstance(container, list) and container and isinstance(container[0], str)
        else None,
        authors=tuple(authors),
    )


def openalex_draft(payload: dict[str, Any]) -> RecordDraft:
    openalex_id = _require_str(payload, "id").rsplit("/", 1)[-1]
    display = payload.get("display_name")
    if not isinstance(display, str) or not display.strip():
        raise _error(
            "adapter_payload_invalid",
            "OpenAlex payload is missing display_name",
        )
    doi_value = payload.get("doi")
    doi: str | None = None
    if isinstance(doi_value, str) and doi_value.startswith("https://doi.org/"):
        try:
            doi = normalize_identifier(
                IdentifierScheme.DOI, doi_value.removeprefix("https://doi.org/")
            ).normalized_value
        except Exception:
            doi = None
    language = payload.get("language")
    year = _normalize_year(payload.get("publication_year"))
    host_venue = payload.get("host_venue") or {}
    venue_name = host_venue.get("display_name") if isinstance(host_venue, dict) else None
    return RecordDraft(
        source_record_key=openalex_id,
        doi=doi,
        title=display.strip(),
        language=language.strip().lower()
        if isinstance(language, str) and language.strip()
        else None,
        year=year,
        container_title=venue_name.strip()
        if isinstance(venue_name, str) and venue_name.strip()
        else None,
    )


@dataclass(frozen=True)
class BatchPlanEntry:
    draft: RecordDraft
    source_record_id: SourceRecordId
    work_id: WorkId
    publication_id: PublicationId
    title_assertion_id: MetadataAssertionId
    year_assertion_id: MetadataAssertionId | None
    relationship_assertion_id: RelationshipAssertionId | None


def single_entry_proposal(
    entry: BatchPlanEntry,
    *,
    source_system: str,
    retrieved_at: UtcInstant,
    media_type: str,
    authority_tier: AuthorityTier,
    asserted_at: UtcInstant | None = None,
) -> tuple[SourceWriteBatchProposal, str]:
    """Return (proposal, idempotency_key) for one record draft."""
    import hashlib

    canonical = (
        f"{entry.draft.doi or entry.draft.source_record_key}|{entry.draft.title}|"
        f"{entry.draft.language or ''}|{entry.draft.year or ''}".encode()
    )
    digest_hex = hashlib.sha256(canonical).hexdigest()
    from .domain import SourceRecordProposal

    record = SourceRecordProposal(
        source_record_id=entry.source_record_id,
        source_system=source_system,
        source_record_key=entry.draft.source_record_key,
        retrieved_at=retrieved_at,
        payload_digest=ContentDigest.parse(f"sha256:{digest_hex}"),
        media_type=media_type,
    )
    assert_time = retrieved_at if asserted_at is None else asserted_at
    metas = [
        SourceMetadataAssertionProposal(
            assertion_id=entry.title_assertion_id,
            subject_id=entry.publication_id,
            field=MetadataFieldKey.PUBLICATION_TITLE,
            value=TextAssertionValue.create(
                entry.draft.title,
                LanguageTag.parse(entry.draft.language or "en"),
            ),
            authority_tier=authority_tier,
            asserted_at=assert_time,
        )
    ]
    if entry.year_assertion_id is not None and entry.draft.year is not None:
        metas.append(
            SourceMetadataAssertionProposal(
                assertion_id=entry.year_assertion_id,
                subject_id=entry.publication_id,
                field=MetadataFieldKey.PUBLICATION_YEAR,
                value=IntegerAssertionValue.create(entry.draft.year),
                authority_tier=authority_tier,
                asserted_at=assert_time,
            )
        )
    rels: list[SourceRelationshipAssertionProposal] = []
    if entry.relationship_assertion_id is not None:
        rels.append(
            SourceRelationshipAssertionProposal(
                assertion_id=entry.relationship_assertion_id,
                predicate=FactualPredicate.AUTHORED_BY,
                subject_id=entry.publication_id,
                object_id=entry.work_id,
                authority_tier=authority_tier,
                asserted_at=assert_time,
            )
        )
    proposal = SourceWriteBatchProposal(
        source_record=record,
        metadata_assertions=tuple(metas),
        relationship_assertions=tuple(rels),
        retractions=(),
    )
    return proposal, entry.draft.idempotency_key(source_system)


__all__ = [
    "AdapterError",
    "BatchPlanEntry",
    "CollectionPlan",
    "PageFetcher",
    "RecordDraft",
    "crossref_draft",
    "iter_payloads",
    "openalex_draft",
    "single_entry_proposal",
]
