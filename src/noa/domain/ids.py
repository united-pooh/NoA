from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Self, TypeAlias
from uuid import RFC_4122, UUID

import uuid6

from .errors import DomainError


def _display_invalid_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, UUID):
        return str(value)
    return f"<{type(value).__name__}>"


def _invalid_typed_id(
    *,
    expected_prefix: str,
    value: object,
    reason: str,
) -> DomainError:
    return DomainError(
        code="invalid_typed_id",
        message=f"Invalid {expected_prefix or 'unprefixed'} UUIDv7 value: {reason}",
        context={
            "expected_prefix": expected_prefix,
            "value": _display_invalid_value(value),
            "reason": reason,
        },
    )


def _validate_uuid7(uuid_value: object, *, expected_prefix: str, value: object) -> UUID:
    if not isinstance(uuid_value, UUID):
        raise _invalid_typed_id(
            expected_prefix=expected_prefix,
            value=value,
            reason="value is not a UUID",
        )
    if uuid_value.version != 7:
        raise _invalid_typed_id(
            expected_prefix=expected_prefix,
            value=value,
            reason="UUID version must be 7",
        )
    if uuid_value.variant != RFC_4122:
        raise _invalid_typed_id(
            expected_prefix=expected_prefix,
            value=value,
            reason="UUID variant must be RFC 4122/RFC 9562",
        )
    return uuid_value


def generate_uuid7_value() -> UUID:
    value = uuid6.uuid7()
    return _validate_uuid7(value, expected_prefix="", value=value)


@dataclass(frozen=True, slots=True)
class TypedId:
    uuid_value: UUID

    PREFIX: ClassVar[str] = ""

    def __post_init__(self) -> None:
        if type(self) is TypedId:
            raise TypeError("TypedId cannot be instantiated directly")
        _validate_uuid7(self.uuid_value, expected_prefix=self.PREFIX, value=self.uuid_value)

    @classmethod
    def _require_concrete_class(cls) -> None:
        if cls is TypedId:
            raise TypeError("TypedId cannot be instantiated directly")

    @classmethod
    def from_uuid7(cls, uuid_value: UUID) -> Self:
        cls._require_concrete_class()
        validated = _validate_uuid7(
            uuid_value,
            expected_prefix=cls.PREFIX,
            value=uuid_value,
        )
        return cls(uuid_value=validated)

    @classmethod
    def parse(cls, text: str) -> Self:
        cls._require_concrete_class()
        if not isinstance(text, str):
            raise _invalid_typed_id(
                expected_prefix=cls.PREFIX,
                value=text,
                reason="value is not a string",
            )

        actual_prefix, separator, uuid_text = text.partition("_")
        if not separator:
            raise _invalid_typed_id(
                expected_prefix=cls.PREFIX,
                value=text,
                reason="missing prefix separator",
            )
        if actual_prefix != cls.PREFIX:
            raise DomainError(
                code="id_prefix_mismatch",
                message=f"Expected ID prefix {cls.PREFIX!r}, got {actual_prefix!r}",
                context={
                    "expected_prefix": cls.PREFIX,
                    "actual_prefix": actual_prefix,
                },
            )
        if len(uuid_text) != 36:
            raise _invalid_typed_id(
                expected_prefix=cls.PREFIX,
                value=text,
                reason="UUID text must contain exactly 36 characters",
            )
        if uuid_text != uuid_text.lower():
            raise _invalid_typed_id(
                expected_prefix=cls.PREFIX,
                value=text,
                reason="UUID text must be lowercase",
            )

        try:
            uuid_value = UUID(uuid_text)
        except ValueError as error:
            raise _invalid_typed_id(
                expected_prefix=cls.PREFIX,
                value=text,
                reason="UUID text is malformed",
            ) from error
        if str(uuid_value) != uuid_text:
            raise _invalid_typed_id(
                expected_prefix=cls.PREFIX,
                value=text,
                reason="UUID text must use canonical lowercase hyphenated form",
            )

        validated = _validate_uuid7(
            uuid_value,
            expected_prefix=cls.PREFIX,
            value=text,
        )
        return cls(uuid_value=validated)

    @property
    def text(self) -> str:
        return f"{self.PREFIX}_{self.uuid_value}"

    def __str__(self) -> str:
        return self.text

    def sort_key(self) -> str:
        return self.text


class WorkId(TypedId):
    __slots__ = ()
    PREFIX = "wrk"


class PublicationId(TypedId):
    __slots__ = ()
    PREFIX = "pub"


class DocumentId(TypedId):
    __slots__ = ()
    PREFIX = "doc"


class IdentifierId(TypedId):
    __slots__ = ()
    PREFIX = "idn"


class PersonId(TypedId):
    __slots__ = ()
    PREFIX = "per"


class VenueId(TypedId):
    __slots__ = ()
    PREFIX = "ven"


class TopicId(TypedId):
    __slots__ = ()
    PREFIX = "top"


class MethodId(TypedId):
    __slots__ = ()
    PREFIX = "mth"


class ResearchTaskId(TypedId):
    __slots__ = ()
    PREFIX = "tsk"


class DatasetId(TypedId):
    __slots__ = ()
    PREFIX = "dts"


class SourceRecordId(TypedId):
    __slots__ = ()
    PREFIX = "src"


class MetadataAssertionId(TypedId):
    __slots__ = ()
    PREFIX = "mas"


class RelationshipAssertionId(TypedId):
    __slots__ = ()
    PREFIX = "ras"


class AssertionRetractionId(TypedId):
    __slots__ = ()
    PREFIX = "ret"


class ClaimId(TypedId):
    __slots__ = ()
    PREFIX = "clm"


class EvidencePassageId(TypedId):
    __slots__ = ()
    PREFIX = "evp"


class SemanticRelationId(TypedId):
    __slots__ = ()
    PREFIX = "sem"


class ReviewCandidateId(TypedId):
    __slots__ = ()
    PREFIX = "rvc"


class CollectionId(TypedId):
    __slots__ = ()
    PREFIX = "col"


class NoteId(TypedId):
    __slots__ = ()
    PREFIX = "nte"


class TechnicalLineageId(TypedId):
    __slots__ = ()
    PREFIX = "lin"


class LineageSynthesisId(TypedId):
    __slots__ = ()
    PREFIX = "syn"


class ResearchRunId(TypedId):
    __slots__ = ()
    PREFIX = "run"


ID_PREFIX_REGISTRY: Mapping[str, type[TypedId]] = MappingProxyType(
    {
        WorkId.PREFIX: WorkId,
        PublicationId.PREFIX: PublicationId,
        DocumentId.PREFIX: DocumentId,
        IdentifierId.PREFIX: IdentifierId,
        PersonId.PREFIX: PersonId,
        VenueId.PREFIX: VenueId,
        TopicId.PREFIX: TopicId,
        MethodId.PREFIX: MethodId,
        ResearchTaskId.PREFIX: ResearchTaskId,
        DatasetId.PREFIX: DatasetId,
        SourceRecordId.PREFIX: SourceRecordId,
        MetadataAssertionId.PREFIX: MetadataAssertionId,
        RelationshipAssertionId.PREFIX: RelationshipAssertionId,
        AssertionRetractionId.PREFIX: AssertionRetractionId,
        ClaimId.PREFIX: ClaimId,
        EvidencePassageId.PREFIX: EvidencePassageId,
        SemanticRelationId.PREFIX: SemanticRelationId,
        ReviewCandidateId.PREFIX: ReviewCandidateId,
        CollectionId.PREFIX: CollectionId,
        NoteId.PREFIX: NoteId,
        TechnicalLineageId.PREFIX: TechnicalLineageId,
        LineageSynthesisId.PREFIX: LineageSynthesisId,
        ResearchRunId.PREFIX: ResearchRunId,
    }
)

KnowledgeEntityId: TypeAlias = (
    WorkId
    | PublicationId
    | DocumentId
    | IdentifierId
    | PersonId
    | VenueId
    | TopicId
    | MethodId
    | ResearchTaskId
    | DatasetId
    | ClaimId
    | EvidencePassageId
    | SemanticRelationId
    | CollectionId
    | NoteId
    | TechnicalLineageId
    | LineageSynthesisId
)
RelationshipEndpointId: TypeAlias = KnowledgeEntityId | SourceRecordId
LifecycleEntityId: TypeAlias = (
    WorkId
    | PublicationId
    | DocumentId
    | IdentifierId
    | PersonId
    | VenueId
    | TopicId
    | MethodId
    | ResearchTaskId
    | DatasetId
    | ClaimId
    | EvidencePassageId
    | CollectionId
    | NoteId
    | TechnicalLineageId
    | LineageSynthesisId
)
MergeableEntityId: TypeAlias = (
    WorkId
    | PublicationId
    | IdentifierId
    | PersonId
    | VenueId
    | TopicId
    | MethodId
    | ResearchTaskId
    | DatasetId
)
AssertionTargetId: TypeAlias = MetadataAssertionId | RelationshipAssertionId | SemanticRelationId
ProvenanceRecordId: TypeAlias = (
    SourceRecordId | MetadataAssertionId | RelationshipAssertionId | AssertionRetractionId
)

__all__ = [
    "ID_PREFIX_REGISTRY",
    "AssertionRetractionId",
    "AssertionTargetId",
    "ClaimId",
    "CollectionId",
    "DatasetId",
    "DocumentId",
    "EvidencePassageId",
    "IdentifierId",
    "KnowledgeEntityId",
    "LifecycleEntityId",
    "LineageSynthesisId",
    "MergeableEntityId",
    "MetadataAssertionId",
    "MethodId",
    "NoteId",
    "PersonId",
    "ProvenanceRecordId",
    "PublicationId",
    "RelationshipAssertionId",
    "RelationshipEndpointId",
    "ResearchRunId",
    "ResearchTaskId",
    "ReviewCandidateId",
    "SemanticRelationId",
    "SourceRecordId",
    "TechnicalLineageId",
    "TopicId",
    "TypedId",
    "VenueId",
    "WorkId",
    "generate_uuid7_value",
]
