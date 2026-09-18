from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar, Self, TypeAlias
from urllib.parse import SplitResult, unquote_to_bytes, urlsplit

from .errors import DomainError
from .ids import (
    ClaimId,
    CollectionId,
    DatasetId,
    DocumentId,
    EvidencePassageId,
    IdentifierId,
    KnowledgeEntityId,
    LineageSynthesisId,
    MethodId,
    NoteId,
    PersonId,
    PublicationId,
    ResearchTaskId,
    ReviewCandidateId,
    SemanticRelationId,
    TechnicalLineageId,
    TopicId,
    TypedId,
    VenueId,
    WorkId,
)

_CONTENT_DIGEST_PATTERN = re.compile(r"sha256:[0-9A-Fa-f]{64}", re.ASCII)
_LANGUAGE_TAG_PATTERN = re.compile(
    r"(?:[A-Za-z]{2,3}|und)(?:-[A-Za-z0-9]{2,8})*",
    re.ASCII,
)
_DOI_PATTERN = re.compile(r"10\.[0-9]{4,9}/[A-Za-z0-9._;()/:\-]+", re.ASCII)
_ARXIV_MODERN_PATTERN = re.compile(
    r"(?P<date>[0-9]{4})\.(?P<sequence>[0-9]{4,5})(?P<version>v[0-9]+)?",
    re.ASCII,
)
_ARXIV_LEGACY_PATTERN = re.compile(
    r"(?P<archive>[a-z0-9.\-]+)/(?P<date>[0-9]{4})(?P<sequence>[0-9]{3})"
    r"(?P<version>v[0-9]+)?",
    re.ASCII,
)
_OPENALEX_PATTERN = re.compile(r"(?P<prefix>[WASICPFT])(?P<number>[1-9][0-9]*)", re.ASCII)
_ORCID_COMPACT_PATTERN = re.compile(r"[0-9]{15}[0-9Xx]", re.ASCII)
_ORCID_CANONICAL_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9Xx]",
    re.ASCII,
)
_ROR_PATTERN = re.compile(r"0[0-9a-hjkmnp-tv-z]{6}[0-9]{2}", re.ASCII)
_ISSN_COMPACT_PATTERN = re.compile(r"[0-9]{7}[0-9Xx]", re.ASCII)
_ISSN_CANONICAL_PATTERN = re.compile(r"[0-9]{4}-[0-9]{3}[0-9Xx]", re.ASCII)
_URI_PREFIX_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://", re.ASCII)
_PERCENT_ESCAPE_PATTERN = re.compile(r"[0-9A-Fa-f]{2}", re.ASCII)

_ASCII_LOWER_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
)
_ASCII_UPPER_TRANSLATION = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
)
_CROCKFORD_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_CROCKFORD_VALUES = {character: index for index, character in enumerate(_CROCKFORD_ALPHABET)}
_OPENALEX_PLURALS = {
    "W": "works",
    "A": "authors",
    "S": "sources",
    "I": "institutions",
    "C": "concepts",
    "P": "publishers",
    "F": "funders",
    "T": "topics",
}


def _display_invalid_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return f"<{type(value).__name__}>"


def _invalid_value_object(*, type_name: str, field_name: str, reason: str) -> DomainError:
    return DomainError(
        code="invalid_value_object",
        message=f"Invalid {type_name}.{field_name}: {reason}",
        context={
            "type": type_name,
            "field": field_name,
            "reason": reason,
        },
    )


def _invalid_attestation(*, attestation_kind: str, reason: str) -> DomainError:
    return DomainError(
        code="invalid_attestation",
        message=f"Invalid {attestation_kind} attestation: {reason}",
        context={
            "attestation_kind": attestation_kind,
            "reason": reason,
        },
    )


def _ascii_lower(value: str) -> str:
    return value.translate(_ASCII_LOWER_TRANSLATION)


def _ascii_upper(value: str) -> str:
    return value.translate(_ASCII_UPPER_TRANSLATION)


def _canonical_nonblank(
    value: object,
    *,
    type_name: str,
    field_name: str,
) -> str:
    if type(value) is not str:
        raise _invalid_value_object(
            type_name=type_name,
            field_name=field_name,
            reason="value is not a string",
        )
    canonical = unicodedata.normalize("NFC", value).strip()
    if not canonical:
        raise _invalid_value_object(
            type_name=type_name,
            field_name=field_name,
            reason="value must be nonblank",
        )
    return canonical


@dataclass(frozen=True, slots=True)
class ContentDigest:
    text: str

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="text",
                reason="value is not a string",
            )
        if _CONTENT_DIGEST_PATTERN.fullmatch(self.text) is None:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="text",
                reason="expected sha256: followed by 64 hexadecimal characters",
            )
        object.__setattr__(self, "text", _ascii_lower(self.text))

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls(text=text)

    def sort_key(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class LanguageTag:
    text: str

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="text",
                reason="value is not a string",
            )
        if _LANGUAGE_TAG_PATTERN.fullmatch(self.text) is None:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="text",
                reason="value is outside the NoA constrained language-tag profile",
            )
        object.__setattr__(self, "text", _ascii_lower(self.text))

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls(text=text)

    def sort_key(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True, order=True)
class UtcInstant:
    value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.value, datetime):
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value is not a datetime",
            )
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="datetime must be timezone-aware",
            )
        try:
            canonical = self.value.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="datetime cannot be converted to UTC",
            ) from error
        object.__setattr__(self, "value", canonical)

    @classmethod
    def from_datetime(cls, value: datetime) -> Self:
        return cls(value=value)

    @property
    def text(self) -> str:
        if self.value.microsecond == 0:
            return self.value.strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def sort_key(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    text: str

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="text",
                reason="value is not a string",
            )
        for character in self.text:
            if unicodedata.category(character) in {"Cc", "Cf", "Cs"}:
                raise _invalid_value_object(
                    type_name=type(self).__name__,
                    field_name="text",
                    reason="control, format, and surrogate code points are not allowed",
                )
        canonical = self.text.strip()
        if not canonical:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="text",
                reason="value must be nonblank",
            )
        object.__setattr__(self, "text", canonical)

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls(text=text)

    def sort_key(self) -> str:
        return self.text


class IdentifierScheme(StrEnum):
    DOI = "doi"
    ARXIV = "arxiv"
    OPENALEX = "openalex"
    ORCID = "orcid"
    ROR = "ror"
    ISSN = "issn"


@dataclass(frozen=True, slots=True, init=False)
class IdentifierKey:
    scheme: IdentifierScheme
    normalized_value: str
    canonical_uri: str = field(compare=False)

    def __init__(
        self,
        scheme: IdentifierScheme,
        normalized_value: str,
        canonical_uri: str,
    ) -> None:
        del scheme, normalized_value, canonical_uri
        raise _invalid_value_object(
            type_name=type(self).__name__,
            field_name="constructor",
            reason="values must be created by normalize_identifier()",
        )

    @classmethod
    def _from_validated(
        cls,
        *,
        scheme: IdentifierScheme,
        normalized_value: str,
        canonical_uri: str,
    ) -> Self:
        instance: Self = object.__new__(cls)
        object.__setattr__(instance, "scheme", scheme)
        object.__setattr__(instance, "normalized_value", normalized_value)
        object.__setattr__(instance, "canonical_uri", canonical_uri)
        return instance

    def sort_key(self) -> tuple[str, str]:
        return (self.scheme.value, self.normalized_value)


class AssertionValueKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DIGEST = "digest"
    LANGUAGE = "language"
    INSTANT = "instant"
    IDENTIFIER = "identifier"


@dataclass(frozen=True, slots=True)
class TextAssertionValue:
    text: str
    language: LanguageTag

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.TEXT

    def __post_init__(self) -> None:
        canonical = _canonical_nonblank(
            self.text,
            type_name=type(self).__name__,
            field_name="text",
        )
        if type(self.language) is not LanguageTag:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="language",
                reason="value must be a LanguageTag",
            )
        object.__setattr__(self, "text", canonical)

    @classmethod
    def create(cls, text: str, language: LanguageTag) -> Self:
        return cls(text=text, language=language)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, str, str]:
        return (self.KIND.value, self.language.text, self.text)


@dataclass(frozen=True, slots=True)
class IntegerAssertionValue:
    value: int

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.INTEGER

    def __post_init__(self) -> None:
        if type(self.value) is not int:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be an integer and must not be bool",
            )

    @classmethod
    def create(cls, value: int) -> Self:
        return cls(value=value)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, int]:
        return (self.KIND.value, self.value)


@dataclass(frozen=True, slots=True)
class BooleanAssertionValue:
    value: bool

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.BOOLEAN

    def __post_init__(self) -> None:
        if type(self.value) is not bool:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be a boolean",
            )

    @classmethod
    def create(cls, value: bool) -> Self:
        return cls(value=value)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, int]:
        return (self.KIND.value, int(self.value))


@dataclass(frozen=True, slots=True)
class DigestAssertionValue:
    value: ContentDigest

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.DIGEST

    def __post_init__(self) -> None:
        if type(self.value) is not ContentDigest:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be a ContentDigest",
            )

    @classmethod
    def create(cls, value: ContentDigest) -> Self:
        return cls(value=value)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, str]:
        return (self.KIND.value, self.value.text)


@dataclass(frozen=True, slots=True)
class LanguageAssertionValue:
    value: LanguageTag

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.LANGUAGE

    def __post_init__(self) -> None:
        if type(self.value) is not LanguageTag:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be a LanguageTag",
            )

    @classmethod
    def create(cls, value: LanguageTag) -> Self:
        return cls(value=value)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, str]:
        return (self.KIND.value, self.value.text)


@dataclass(frozen=True, slots=True)
class InstantAssertionValue:
    value: UtcInstant

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.INSTANT

    def __post_init__(self) -> None:
        if type(self.value) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be a UtcInstant",
            )

    @classmethod
    def create(cls, value: UtcInstant) -> Self:
        return cls(value=value)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, str]:
        return (self.KIND.value, self.value.text)


@dataclass(frozen=True, slots=True)
class IdentifierAssertionValue:
    value: IdentifierKey

    KIND: ClassVar[AssertionValueKind] = AssertionValueKind.IDENTIFIER

    def __post_init__(self) -> None:
        if type(self.value) is not IdentifierKey:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be an IdentifierKey",
            )

    @classmethod
    def create(cls, value: IdentifierKey) -> Self:
        return cls(value=value)

    @property
    def kind(self) -> AssertionValueKind:
        return self.KIND

    def sort_key(self) -> tuple[str, str, str]:
        return (self.KIND.value, self.value.scheme.value, self.value.normalized_value)


AssertionValue: TypeAlias = (
    TextAssertionValue
    | IntegerAssertionValue
    | BooleanAssertionValue
    | DigestAssertionValue
    | LanguageAssertionValue
    | InstantAssertionValue
    | IdentifierAssertionValue
)


class ReviewAction(StrEnum):
    CONFIRM_CLAIM = "confirm_claim"
    CONFIRM_SEMANTIC_RELATION = "confirm_semantic_relation"
    MERGE_FUZZY = "merge_fuzzy"


class OperationAction(StrEnum):
    SOURCE_INGEST = "source_ingest"
    SOURCE_REFRESH = "source_refresh"
    HUMAN_CORRECTION = "human_correction"
    RETRACT_RECORD = "retract_record"
    MERGE_EXACT_IDENTITY = "merge_exact_identity"
    TOMBSTONE_ENTITY = "tombstone_entity"


class AttestationPrincipalKind(StrEnum):
    HUMAN = "human"
    SERVICE = "service"


_HUMAN_ONLY_OPERATION_ACTIONS = frozenset(
    {
        OperationAction.HUMAN_CORRECTION,
        OperationAction.RETRACT_RECORD,
        OperationAction.TOMBSTONE_ENTITY,
    }
)


@dataclass(frozen=True, slots=True)
class AcceptedReviewAttestation:
    candidate_id: ReviewCandidateId
    candidate_revision: int
    action: ReviewAction
    actor: str
    review_event_reference: str
    payload_digest: ContentDigest
    accepted_at: UtcInstant

    def __post_init__(self) -> None:
        attestation_kind = "review"
        if type(self.candidate_id) is not ReviewCandidateId:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="candidate_id must be a ReviewCandidateId",
            )
        if type(self.candidate_revision) is not int or self.candidate_revision <= 0:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="candidate_revision must be a positive integer and must not be bool",
            )
        if type(self.action) is not ReviewAction:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="action must be a ReviewAction",
            )
        actor = _canonical_attestation_text(
            self.actor,
            attestation_kind=attestation_kind,
            field_name="actor",
        )
        review_reference = _canonical_attestation_text(
            self.review_event_reference,
            attestation_kind=attestation_kind,
            field_name="review_event_reference",
        )
        if type(self.payload_digest) is not ContentDigest:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="payload_digest must be a ContentDigest",
            )
        if type(self.accepted_at) is not UtcInstant:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="accepted_at must be a UtcInstant",
            )
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "review_event_reference", review_reference)

    def sort_key(self) -> tuple[str, int, str, str, str, str]:
        return (
            self.candidate_id.text,
            self.candidate_revision,
            self.action.value,
            self.actor,
            self.review_event_reference,
            self.payload_digest.text,
        )


@dataclass(frozen=True, slots=True)
class AcceptedOperationAttestation:
    operation_reference: str
    operation_revision: int
    action: OperationAction
    principal_kind: AttestationPrincipalKind
    principal: str
    review_event_reference: str
    payload_digest: ContentDigest
    accepted_at: UtcInstant

    def __post_init__(self) -> None:
        attestation_kind = "operation"
        operation_reference = _canonical_attestation_text(
            self.operation_reference,
            attestation_kind=attestation_kind,
            field_name="operation_reference",
        )
        if type(self.operation_revision) is not int or self.operation_revision <= 0:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="operation_revision must be a positive integer and must not be bool",
            )
        if type(self.action) is not OperationAction:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="action must be an OperationAction",
            )
        if type(self.principal_kind) is not AttestationPrincipalKind:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="principal_kind must be an AttestationPrincipalKind",
            )
        principal = _canonical_attestation_text(
            self.principal,
            attestation_kind=attestation_kind,
            field_name="principal",
        )
        review_reference = _canonical_attestation_text(
            self.review_event_reference,
            attestation_kind=attestation_kind,
            field_name="review_event_reference",
        )
        if self.action in _HUMAN_ONLY_OPERATION_ACTIONS:
            if self.principal_kind is not AttestationPrincipalKind.HUMAN:
                raise _invalid_attestation(
                    attestation_kind=attestation_kind,
                    reason=f"action {self.action.value} requires a human principal",
                )
        if type(self.payload_digest) is not ContentDigest:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="payload_digest must be a ContentDigest",
            )
        if type(self.accepted_at) is not UtcInstant:
            raise _invalid_attestation(
                attestation_kind=attestation_kind,
                reason="accepted_at must be a UtcInstant",
            )
        object.__setattr__(self, "operation_reference", operation_reference)
        object.__setattr__(self, "principal", principal)
        object.__setattr__(self, "review_event_reference", review_reference)

    def sort_key(self) -> tuple[str, int, str, str, str, str, str]:
        return (
            self.operation_reference,
            self.operation_revision,
            self.action.value,
            self.principal_kind.value,
            self.principal,
            self.review_event_reference,
            self.payload_digest.text,
        )


def _canonical_attestation_text(
    value: object,
    *,
    attestation_kind: str,
    field_name: str,
) -> str:
    if type(value) is not str:
        raise _invalid_attestation(
            attestation_kind=attestation_kind,
            reason=f"{field_name} must be a string",
        )
    canonical = unicodedata.normalize("NFC", value).strip()
    if not canonical:
        raise _invalid_attestation(
            attestation_kind=attestation_kind,
            reason=f"{field_name} must be nonblank",
        )
    return canonical


def create_accepted_review_attestation(
    *,
    candidate_id: ReviewCandidateId,
    candidate_revision: int,
    action: ReviewAction,
    actor: str,
    review_event_reference: str,
    payload_digest: ContentDigest,
    accepted_at: UtcInstant,
) -> AcceptedReviewAttestation:
    return AcceptedReviewAttestation(
        candidate_id=candidate_id,
        candidate_revision=candidate_revision,
        action=action,
        actor=actor,
        review_event_reference=review_event_reference,
        payload_digest=payload_digest,
        accepted_at=accepted_at,
    )


def create_accepted_operation_attestation(
    *,
    operation_reference: str,
    operation_revision: int,
    action: OperationAction,
    principal_kind: AttestationPrincipalKind,
    principal: str,
    review_event_reference: str,
    payload_digest: ContentDigest,
    accepted_at: UtcInstant,
) -> AcceptedOperationAttestation:
    return AcceptedOperationAttestation(
        operation_reference=operation_reference,
        operation_revision=operation_revision,
        action=action,
        principal_kind=principal_kind,
        principal=principal,
        review_event_reference=review_event_reference,
        payload_digest=payload_digest,
        accepted_at=accepted_at,
    )


def _identifier_error(
    *,
    scheme: IdentifierScheme | object,
    raw: object,
    reason: str,
) -> DomainError:
    scheme_text = (
        scheme.value if type(scheme) is IdentifierScheme else _display_invalid_value(scheme)
    )
    return DomainError(
        code="invalid_identifier",
        message=f"Invalid {scheme_text} identifier: {reason}",
        context={
            "scheme": scheme_text,
            "value": _display_invalid_value(raw),
            "reason": reason,
        },
    )


def _checksum_error(*, scheme: IdentifierScheme, normalized_value: str) -> DomainError:
    return DomainError(
        code="identifier_checksum_mismatch",
        message=f"Checksum mismatch for {scheme.value} identifier {normalized_value!r}",
        context={
            "scheme": scheme.value,
            "normalized_value": normalized_value,
        },
    )


def _require_identifier_input(scheme: IdentifierScheme, raw: object) -> str:
    if type(raw) is not str:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason="value is not a string",
        )
    canonical = raw.strip()
    if not canonical:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason="value must be nonblank",
        )
    return canonical


def _looks_like_uri(value: str) -> bool:
    return _URI_PREFIX_PATTERN.match(value) is not None


def _parse_identifier_uri(
    value: str,
    *,
    scheme: IdentifierScheme,
    allowed_schemes: frozenset[str],
    allowed_hosts: frozenset[str],
) -> SplitResult:
    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI is malformed",
        ) from error

    uri_scheme = _ascii_lower(parts.scheme)
    if uri_scheme not in allowed_schemes:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI scheme is not allowed",
        )
    if not parts.netloc:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI host is required",
        )
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI userinfo is not allowed",
        )
    try:
        port = parts.port
    except ValueError as error:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI port is invalid",
        ) from error
    host = parts.hostname
    if host is None:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI host is required",
        )
    host = _ascii_lower(host)
    if port is not None or _ascii_lower(parts.netloc) != host:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="explicit URI ports are not allowed",
        )
    if host not in allowed_hosts:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI host is not allowed",
        )
    if "?" in value or "#" in value or parts.query or parts.fragment:
        raise _identifier_error(
            scheme=scheme,
            raw=value,
            reason="URI query and fragment are not allowed",
        )
    return parts


def _strict_percent_decode(value: str, *, scheme: IdentifierScheme, raw: str) -> str:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        escape = value[index + 1 : index + 3]
        if len(escape) != 2 or _PERCENT_ESCAPE_PATTERN.fullmatch(escape) is None:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="URI path contains an invalid percent escape",
            )
        index += 3
    try:
        return unquote_to_bytes(value).decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason="URI path is not valid UTF-8",
        ) from error


def _normalize_doi(raw: object) -> tuple[str, str]:
    scheme = IdentifierScheme.DOI
    value = _require_identifier_input(scheme, raw)
    if _ascii_lower(value[:4]) == "doi:":
        value = value[4:]
    if _looks_like_uri(value):
        parts = _parse_identifier_uri(
            value,
            scheme=scheme,
            allowed_schemes=frozenset({"http", "https"}),
            allowed_hosts=frozenset({"doi.org", "dx.doi.org"}),
        )
        if not parts.path.startswith("/"):
            raise _identifier_error(scheme=scheme, raw=raw, reason="URI path is invalid")
        value = _strict_percent_decode(parts.path[1:], scheme=scheme, raw=value)
    if _DOI_PATTERN.fullmatch(value) is None:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason="value is outside the DOI ASCII compatibility profile",
        )
    normalized = _ascii_lower(value)
    return normalized, f"https://doi.org/{normalized}"


def _validate_arxiv_version(
    version: str | None,
    *,
    raw: object,
) -> None:
    if version is None:
        return
    digits = version[1:]
    if digits.startswith("0") or int(digits) < 1:
        raise _identifier_error(
            scheme=IdentifierScheme.ARXIV,
            raw=raw,
            reason="version must start at v1 and must not contain leading zeroes",
        )


def _normalize_arxiv(raw: object) -> tuple[str, str]:
    scheme = IdentifierScheme.ARXIV
    value = _require_identifier_input(scheme, raw)
    if _ascii_lower(value[:6]) == "arxiv:":
        value = value[6:]
    if _looks_like_uri(value):
        parts = _parse_identifier_uri(
            value,
            scheme=scheme,
            allowed_schemes=frozenset({"http", "https"}),
            allowed_hosts=frozenset({"arxiv.org"}),
        )
        path = parts.path
        if path.startswith("/abs/"):
            value = path[len("/abs/") :]
        elif path.startswith("/pdf/"):
            value = path[len("/pdf/") :]
            if value.endswith(".pdf"):
                value = value[:-4]
        else:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="URI path must be /abs/{id}, /pdf/{id}, or /pdf/{id}.pdf",
            )
    normalized = _ascii_lower(value)

    modern_match = _ARXIV_MODERN_PATTERN.fullmatch(normalized)
    if modern_match is not None:
        date = modern_match.group("date")
        month = int(date[2:])
        sequence = modern_match.group("sequence")
        if not 1 <= month <= 12:
            raise _identifier_error(scheme=scheme, raw=raw, reason="month must be in 01..12")
        if set(sequence) == {"0"}:
            raise _identifier_error(scheme=scheme, raw=raw, reason="sequence must not be zero")
        if len(sequence) == 4 and not "0704" <= date <= "1412":
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="four-digit modern sequences require a date in 0704..1412",
            )
        if len(sequence) == 5 and not "1501" <= date <= "9912":
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="five-digit modern sequences require a date from 1501 onward",
            )
        _validate_arxiv_version(modern_match.group("version"), raw=raw)
        return normalized, f"https://arxiv.org/abs/{normalized}"

    legacy_match = _ARXIV_LEGACY_PATTERN.fullmatch(normalized)
    if legacy_match is not None:
        date = legacy_match.group("date")
        month = int(date[2:])
        sequence = legacy_match.group("sequence")
        date_is_valid = "9107" <= date <= "9912" or "0001" <= date <= "0703"
        if not 1 <= month <= 12 or not date_is_valid:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="legacy date must be in 1991-07..2007-03",
            )
        if set(sequence) == {"0"}:
            raise _identifier_error(scheme=scheme, raw=raw, reason="sequence must not be zero")
        _validate_arxiv_version(legacy_match.group("version"), raw=raw)
        return normalized, f"https://arxiv.org/abs/{normalized}"

    raise _identifier_error(scheme=scheme, raw=raw, reason="identifier grammar is invalid")


def _normalize_openalex(raw: object) -> tuple[str, str]:
    scheme = IdentifierScheme.OPENALEX
    value = _require_identifier_input(scheme, raw)
    if _ascii_lower(value[:9]) == "openalex:":
        value = value[9:]
    uri_plural: str | None = None
    if _looks_like_uri(value):
        parts = _parse_identifier_uri(
            value,
            scheme=scheme,
            allowed_schemes=frozenset({"https"}),
            allowed_hosts=frozenset({"openalex.org", "api.openalex.org"}),
        )
        host = _ascii_lower(parts.hostname or "")
        path_parts = parts.path.split("/")
        if len(path_parts) == 2 and path_parts[0] == "" and host == "openalex.org":
            value = path_parts[1]
        elif len(path_parts) == 3 and path_parts[0] == "":
            uri_plural = path_parts[1]
            value = path_parts[2]
        else:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="URI path must contain one ID with an optional matching plural",
            )
        if host == "api.openalex.org" and uri_plural is None:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="api.openalex.org requires a plural path segment",
            )
    if not value:
        raise _identifier_error(scheme=scheme, raw=raw, reason="identifier is empty")
    normalized = _ascii_upper(value[0]) + value[1:]
    match = _OPENALEX_PATTERN.fullmatch(normalized)
    if match is None:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason=(
                "identifier must use a supported prefix and a positive integer "
                "without leading zeroes"
            ),
        )
    prefix = match.group("prefix")
    if uri_plural is not None and uri_plural != _OPENALEX_PLURALS[prefix]:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason="URI plural does not match the identifier prefix",
        )
    return normalized, f"https://openalex.org/{normalized}"


def _normalize_orcid(raw: object) -> tuple[str, str]:
    scheme = IdentifierScheme.ORCID
    value = _require_identifier_input(scheme, raw)
    if _ascii_lower(value[:6]) == "orcid:":
        value = value[6:]
    if _looks_like_uri(value):
        parts = _parse_identifier_uri(
            value,
            scheme=scheme,
            allowed_schemes=frozenset({"http", "https"}),
            allowed_hosts=frozenset({"orcid.org"}),
        )
        path_parts = parts.path.split("/")
        if len(path_parts) != 2 or path_parts[0] != "" or not path_parts[1]:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="URI path must contain exactly one ORCID",
            )
        value = path_parts[1]
    if _ORCID_COMPACT_PATTERN.fullmatch(value) is not None:
        compact = value
    elif _ORCID_CANONICAL_PATTERN.fullmatch(value) is not None:
        compact = value.replace("-", "")
    else:
        raise _identifier_error(scheme=scheme, raw=raw, reason="identifier grammar is invalid")
    compact = compact[:-1] + _ascii_upper(compact[-1])
    total = 0
    for character in compact[:15]:
        total = (total + int(character)) * 2
    result = (12 - total % 11) % 11
    expected = "X" if result == 10 else str(result)
    normalized = f"{compact[:4]}-{compact[4:8]}-{compact[8:12]}-{compact[12:]}"
    if compact[-1] != expected:
        raise _checksum_error(scheme=scheme, normalized_value=normalized)
    return normalized, f"https://orcid.org/{normalized}"


def _normalize_ror(raw: object) -> tuple[str, str]:
    scheme = IdentifierScheme.ROR
    value = _require_identifier_input(scheme, raw)
    if _ascii_lower(value[:4]) == "ror:":
        value = value[4:]
    elif _ascii_lower(value[:8]) == "ror.org/":
        value = value[8:]
    elif _looks_like_uri(value):
        parts = _parse_identifier_uri(
            value,
            scheme=scheme,
            allowed_schemes=frozenset({"http", "https"}),
            allowed_hosts=frozenset({"ror.org"}),
        )
        path_parts = parts.path.split("/")
        if len(path_parts) != 2 or path_parts[0] != "" or not path_parts[1]:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="URI path must contain exactly one ROR identifier",
            )
        value = path_parts[1]
    normalized = _ascii_lower(value)
    if _ROR_PATTERN.fullmatch(normalized) is None:
        raise _identifier_error(scheme=scheme, raw=raw, reason="identifier grammar is invalid")
    number = 0
    for character in normalized[1:7]:
        number = number * 32 + _CROCKFORD_VALUES[character]
    expected = f"{98 - ((number * 100) % 97):02d}"
    if normalized[-2:] != expected:
        raise _checksum_error(scheme=scheme, normalized_value=normalized)
    return normalized, f"https://ror.org/{normalized}"


def _normalize_issn(raw: object) -> tuple[str, str]:
    scheme = IdentifierScheme.ISSN
    value = _require_identifier_input(scheme, raw)
    if _ascii_lower(value[:5]) == "issn:":
        value = value[5:]
    if _looks_like_uri(value):
        parts = _parse_identifier_uri(
            value,
            scheme=scheme,
            allowed_schemes=frozenset({"https"}),
            allowed_hosts=frozenset({"portal.issn.org"}),
        )
        prefix = "/resource/ISSN/"
        if not parts.path.startswith(prefix) or "/" in parts.path[len(prefix) :]:
            raise _identifier_error(
                scheme=scheme,
                raw=raw,
                reason="URI path must be /resource/ISSN/{value}",
            )
        value = parts.path[len(prefix) :]
    if _ISSN_COMPACT_PATTERN.fullmatch(value) is not None:
        compact = value
    elif _ISSN_CANONICAL_PATTERN.fullmatch(value) is not None:
        compact = value.replace("-", "")
    else:
        raise _identifier_error(scheme=scheme, raw=raw, reason="identifier grammar is invalid")
    compact = compact[:-1] + _ascii_upper(compact[-1])
    normalized = f"{compact[:4]}-{compact[4:]}"
    if compact == "00000000":
        raise _identifier_error(scheme=scheme, raw=raw, reason="all-zero ISSN is not allowed")
    weighted_sum = sum(
        int(character) * weight
        for character, weight in zip(compact[:7], range(8, 1, -1), strict=True)
    )
    check = (11 - weighted_sum % 11) % 11
    expected = "X" if check == 10 else str(check)
    if compact[-1] != expected:
        raise _checksum_error(scheme=scheme, normalized_value=normalized)
    return normalized, f"https://portal.issn.org/resource/ISSN/{normalized}"


def normalize_identifier(scheme: IdentifierScheme, raw: str) -> IdentifierKey:
    if type(scheme) is not IdentifierScheme:
        raise _identifier_error(
            scheme=scheme,
            raw=raw,
            reason="scheme must be an IdentifierScheme",
        )
    if scheme is IdentifierScheme.DOI:
        normalized, canonical_uri = _normalize_doi(raw)
    elif scheme is IdentifierScheme.ARXIV:
        normalized, canonical_uri = _normalize_arxiv(raw)
    elif scheme is IdentifierScheme.OPENALEX:
        normalized, canonical_uri = _normalize_openalex(raw)
    elif scheme is IdentifierScheme.ORCID:
        normalized, canonical_uri = _normalize_orcid(raw)
    elif scheme is IdentifierScheme.ROR:
        normalized, canonical_uri = _normalize_ror(raw)
    elif scheme is IdentifierScheme.ISSN:
        normalized, canonical_uri = _normalize_issn(raw)
    else:
        raise _identifier_error(scheme=scheme, raw=raw, reason="scheme is not supported")
    return IdentifierKey._from_validated(
        scheme=scheme,
        normalized_value=normalized,
        canonical_uri=canonical_uri,
    )


_TARGET_KIND_BY_ID_TYPE: dict[type[TypedId], str] = {
    WorkId: "work",
    PublicationId: "publication",
    DocumentId: "document",
    IdentifierId: "identifier",
    PersonId: "person",
    VenueId: "venue",
    TopicId: "topic",
    MethodId: "method",
    ResearchTaskId: "research_task",
    DatasetId: "dataset",
    ClaimId: "claim",
    EvidencePassageId: "evidence_passage",
    SemanticRelationId: "semantic_relation",
    CollectionId: "collection",
    NoteId: "note",
    TechnicalLineageId: "technical_lineage",
    LineageSynthesisId: "lineage_synthesis",
}


def assert_identifier_target_compatible(
    key: IdentifierKey,
    target_id: KnowledgeEntityId,
) -> None:
    if type(key) is not IdentifierKey:
        raise _invalid_value_object(
            type_name="IdentifierKey",
            field_name="key",
            reason="value must be an IdentifierKey",
        )
    target_type = type(target_id)
    target_kind = _TARGET_KIND_BY_ID_TYPE.get(target_type, target_type.__name__)

    compatible_types: frozenset[type[TypedId]]
    if key.scheme is IdentifierScheme.DOI:
        compatible_types = frozenset({PublicationId, DatasetId})
    elif key.scheme is IdentifierScheme.ARXIV:
        compatible_types = frozenset({PublicationId})
    elif key.scheme is IdentifierScheme.OPENALEX:
        prefix = key.normalized_value[0]
        compatible_types = {
            "W": frozenset({PublicationId}),
            "A": frozenset({PersonId}),
            "S": frozenset({VenueId}),
            "C": frozenset({TopicId}),
            "T": frozenset({TopicId}),
        }.get(prefix, frozenset())
    elif key.scheme is IdentifierScheme.ORCID:
        compatible_types = frozenset({PersonId})
    elif key.scheme is IdentifierScheme.ROR:
        compatible_types = frozenset()
    elif key.scheme is IdentifierScheme.ISSN:
        compatible_types = frozenset({VenueId})
    else:
        compatible_types = frozenset()

    if target_type not in compatible_types:
        raise DomainError(
            code="identifier_target_incompatible",
            message=(
                f"{key.scheme.value} identifier {key.normalized_value!r} cannot target "
                f"{target_kind}"
            ),
            context={
                "scheme": key.scheme.value,
                "normalized_value": key.normalized_value,
                "target_kind": target_kind,
            },
        )


__all__ = [
    "AcceptedOperationAttestation",
    "AcceptedReviewAttestation",
    "AssertionValue",
    "AssertionValueKind",
    "AttestationPrincipalKind",
    "BooleanAssertionValue",
    "ContentDigest",
    "DigestAssertionValue",
    "EvidenceLocator",
    "IdentifierAssertionValue",
    "IdentifierKey",
    "IdentifierScheme",
    "InstantAssertionValue",
    "IntegerAssertionValue",
    "LanguageAssertionValue",
    "LanguageTag",
    "OperationAction",
    "ReviewAction",
    "TextAssertionValue",
    "UtcInstant",
    "assert_identifier_target_compatible",
    "create_accepted_operation_attestation",
    "create_accepted_review_attestation",
    "normalize_identifier",
]
