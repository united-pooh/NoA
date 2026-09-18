"""Append-only provenance: origins, assertions, retractions, source write
batches, and the shared projection input (spec sections 11, 12.1, and 16.2/16.4)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Generic, TypeAlias, TypeVar, cast, get_args

from .entities import (
    _ENDPOINT_KIND_BY_ID_TYPE,
    _ID_TYPE_SETS,
    _SNAPSHOT_KINDS,
    _SOURCE_SYSTEM_PATTERN,
    METADATA_FIELD_REGISTRY,
    PREDICATE_REGISTRY,
    ActiveLifecycle,
    CanonicalBindingField,
    Cardinality,
    Claim,
    ClaimReviewBinding,
    Collection,
    Document,
    EntitySnapshotIndex,
    EvidencePassage,
    ExactMergeOperationBinding,
    FactualPredicate,
    FuzzyMergeReviewBinding,
    HumanMetadataCorrectionBinding,
    HumanRelationshipCorrectionBinding,
    HumanRetractionBinding,
    Identifier,
    LifecycleEntitySnapshot,
    LineageSynthesis,
    MergeableEntitySnapshot,
    MetadataFieldKey,
    MetadataFieldSpec,
    Note,
    PredicateKind,
    Publication,
    RedirectLifecycle,
    RelationshipKey,
    ReviewedSemanticPredicate,
    SemanticRelation,
    SemanticRelationReviewBinding,
    SourceRecord,
    SourceRecordIndex,
    SourceWriteOperationBinding,
    StructuralPredicate,
    TechnicalLineage,
    TombstoneLifecycle,
    _attestation_action_mismatch,
    _attestation_payload_mismatch,
    _attestation_time_invalid,
    _compute_canonical_binding_digest,
    _content_digests_equal,
    _require_entity_index,
    _require_field_type,
    _require_id_type,
    _require_source_record_index,
    canonicalize_relationship,
    compute_operation_payload_digest,
    compute_review_payload_digest,
    resolve_terminal,
)
from .errors import DomainError
from .identifiers import (
    AcceptedOperationAttestation,
    AcceptedReviewAttestation,
    AssertionValue,
    AttestationPrincipalKind,
    ContentDigest,
    IdentifierKey,
    IntegerAssertionValue,
    LanguageTag,
    OperationAction,
    ReviewAction,
    TextAssertionValue,
    UtcInstant,
    _canonical_nonblank,
    _invalid_attestation,
    _invalid_value_object,
    assert_identifier_target_compatible,
)
from .ids import (
    AssertionRetractionId,
    AssertionTargetId,
    ClaimId,
    DocumentId,
    EvidencePassageId,
    KnowledgeEntityId,
    LifecycleEntityId,
    MergeableEntityId,
    MetadataAssertionId,
    RelationshipAssertionId,
    RelationshipEndpointId,
    SemanticRelationId,
    SourceRecordId,
    TypedId,
    WorkId,
)


class AuthorityTier(StrEnum):
    AGGREGATOR = "aggregator"
    AUTHORITATIVE_SOURCE = "authoritative_source"
    HUMAN_CORRECTION = "human_correction"


_AUTHORITY_RANK: Mapping[AuthorityTier, int] = MappingProxyType(
    {
        AuthorityTier.AGGREGATOR: 1,
        AuthorityTier.AUTHORITATIVE_SOURCE: 2,
        AuthorityTier.HUMAN_CORRECTION: 3,
    }
)


def _authority_rank(tier: AuthorityTier) -> int:
    return _AUTHORITY_RANK[tier]


def _invalid_origin(*, origin_kind: str, reason: str) -> DomainError:
    return DomainError(
        code="invalid_origin",
        message=f"Invalid {origin_kind} origin: {reason}",
        context={"origin_kind": origin_kind, "reason": reason},
    )


@dataclass(frozen=True, slots=True)
class SourceOrigin:
    source_record_id: SourceRecordId
    authority_tier: AuthorityTier
    accepted_operation: AcceptedOperationAttestation

    def __post_init__(self) -> None:
        _require_field_type(
            self,
            self.source_record_id,
            SourceRecordId,
            field_name="source_record_id",
        )
        if type(self.authority_tier) is not AuthorityTier:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="authority_tier",
                reason="value must be an AuthorityTier",
            )
        if self.authority_tier is AuthorityTier.HUMAN_CORRECTION:
            raise _invalid_origin(
                origin_kind="source",
                reason="source origins cannot claim the human_correction tier",
            )
        operation = self.accepted_operation
        if type(operation) is not AcceptedOperationAttestation:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="accepted_operation",
                reason="value must be an AcceptedOperationAttestation",
            )
        allowed_actions = (
            OperationAction.SOURCE_INGEST.value,
            OperationAction.SOURCE_REFRESH.value,
        )
        if operation.action not in (OperationAction.SOURCE_INGEST, OperationAction.SOURCE_REFRESH):
            raise _attestation_action_mismatch(
                "source_origin",
                (self.source_record_id.text,),
                allowed_actions,
                operation.action.value,
            )

    def stable_key(self) -> tuple[str, str, str, int, str]:
        operation = self.accepted_operation
        return (
            "source",
            self.source_record_id.text,
            operation.operation_reference,
            operation.operation_revision,
            operation.payload_digest.text,
        )


@dataclass(frozen=True, slots=True)
class HumanCorrectionOrigin:
    accepted_operation: AcceptedOperationAttestation

    def __post_init__(self) -> None:
        operation = self.accepted_operation
        if type(operation) is not AcceptedOperationAttestation:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="accepted_operation",
                reason="value must be an AcceptedOperationAttestation",
            )
        if operation.action not in (
            OperationAction.HUMAN_CORRECTION,
            OperationAction.RETRACT_RECORD,
        ):
            raise _attestation_action_mismatch(
                "human_correction_origin",
                (),
                (
                    OperationAction.HUMAN_CORRECTION.value,
                    OperationAction.RETRACT_RECORD.value,
                ),
                operation.action.value,
            )
        if operation.principal_kind is not AttestationPrincipalKind.HUMAN:
            raise _invalid_attestation(
                attestation_kind="operation",
                reason="human correction origin requires a named human principal",
            )

    def stable_key(self) -> tuple[str, str, int, str, str, str]:
        operation = self.accepted_operation
        return (
            "human",
            operation.operation_reference,
            operation.operation_revision,
            operation.principal,
            operation.review_event_reference,
            operation.payload_digest.text,
        )


AssertionOrigin: TypeAlias = SourceOrigin | HumanCorrectionOrigin


def _metadata_field_spec(field: MetadataFieldKey) -> MetadataFieldSpec:
    if type(field) is not MetadataFieldKey:
        raise _invalid_value_object(
            type_name="MetadataFieldKey",
            field_name="field",
            reason="value must be a MetadataFieldKey",
        )
    return METADATA_FIELD_REGISTRY[field]


def _validate_field_value(spec: MetadataFieldSpec, value: AssertionValue) -> None:
    if not isinstance(value, (TextAssertionValue, IntegerAssertionValue)):
        raise _invalid_value_object(
            type_name="AssertionValue",
            field_name="value",
            reason="value must be a TextAssertionValue or IntegerAssertionValue",
        )
    if spec.language_scoped and not isinstance(value, TextAssertionValue):
        raise DomainError(
            code="assertion_value_mismatch",
            message=(
                f"Field {spec.key.value!r} is language scoped and requires a "
                f"text value, got {value.kind.value!r}"
            ),
            context={
                "field": spec.key.value,
                "expected": "text",
                "actual": value.kind.value,
            },
        )
    if value.kind is not spec.value_kind:
        raise DomainError(
            code="assertion_value_mismatch",
            message=(
                f"Field {spec.key.value!r} requires {spec.value_kind.value!r} values, "
                f"got {value.kind.value!r}"
            ),
            context={
                "field": spec.key.value,
                "expected": spec.value_kind.value,
                "actual": value.kind.value,
            },
        )
    if isinstance(value, IntegerAssertionValue) and spec.integer_range is not None:
        low, high = spec.integer_range
        if not low <= value.value <= high:
            raise DomainError(
                code="assertion_value_mismatch",
                message=(
                    f"Field {spec.key.value!r} requires values in [{low}, {high}], "
                    f"got {value.value}"
                ),
                context={
                    "field": spec.key.value,
                    "expected": f"{low}..{high}",
                    "actual": str(value.value),
                },
            )
    if (
        isinstance(value, TextAssertionValue)
        and spec.allowed_text_values
        and value.text not in spec.allowed_text_values
    ):
        raise DomainError(
            code="assertion_value_mismatch",
            message=(
                f"Field {spec.key.value!r} only allows {spec.allowed_text_values!r}, "
                f"got {value.text!r}"
            ),
            context={
                "field": spec.key.value,
                "expected": spec.allowed_text_values,
                "actual": value.text,
            },
        )


def _validate_metadata_target(
    field: MetadataFieldKey,
    subject_id: KnowledgeEntityId,
    value: AssertionValue,
) -> None:
    spec = _metadata_field_spec(field)
    subject_kind = _ENDPOINT_KIND_BY_ID_TYPE.get(type(subject_id))
    if subject_kind is not spec.target_kind:
        raise DomainError(
            code="metadata_field_target_mismatch",
            message=(
                f"Field {field.value!r} targets {spec.target_kind.value!r} entities, "
                f"got {subject_kind.value if subject_kind else type(subject_id).__name__!r}"
            ),
            context={
                "field": field.value,
                "target_kind": subject_kind.value if subject_kind else type(subject_id).__name__,
            },
        )
    _validate_field_value(spec, value)


@dataclass(frozen=True, slots=True)
class MetadataAssertion:
    id: MetadataAssertionId
    subject_id: KnowledgeEntityId
    field: MetadataFieldKey
    value: AssertionValue
    origin: AssertionOrigin
    asserted_at: UtcInstant

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, MetadataAssertionId, field_name="id")
        _require_id_type(
            self.subject_id,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="subject_id",
        )
        if type(self.field) is not MetadataFieldKey:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="field",
                reason="value must be a MetadataFieldKey",
            )
        if not isinstance(self.origin, (SourceOrigin, HumanCorrectionOrigin)):
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="origin",
                reason="value must be a SourceOrigin or HumanCorrectionOrigin",
            )
        _validate_metadata_target(self.field, self.subject_id, self.value)
        _require_field_type(self, self.asserted_at, UtcInstant, field_name="asserted_at")
        if self.asserted_at < self.origin.accepted_operation.accepted_at:
            raise _attestation_time_invalid(
                "metadata_assertion",
                (self.id.text,),
                self.origin.accepted_operation.accepted_at.text,
                self.asserted_at.text,
            )


@dataclass(frozen=True, slots=True)
class RelationshipAssertion:
    id: RelationshipAssertionId
    predicate: FactualPredicate
    subject_id: RelationshipEndpointId
    object_id: RelationshipEndpointId
    origin: AssertionOrigin
    asserted_at: UtcInstant

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, RelationshipAssertionId, field_name="id")
        if type(self.predicate) is not FactualPredicate:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="predicate",
                reason="value must be a FactualPredicate",
            )
        _require_id_type(
            self.subject_id,
            id_set=_ID_TYPE_SETS["relationship_endpoint"],
            field_name="subject_id",
        )
        _require_id_type(
            self.object_id,
            id_set=_ID_TYPE_SETS["relationship_endpoint"],
            field_name="object_id",
        )
        subject_id, object_id = canonicalize_relationship(
            self.predicate,
            self.subject_id,
            self.object_id,
        )
        if not isinstance(self.origin, (SourceOrigin, HumanCorrectionOrigin)):
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="origin",
                reason="value must be a SourceOrigin or HumanCorrectionOrigin",
            )
        if self.predicate is FactualPredicate.OBSERVED_IDENTIFIER and not (
            isinstance(self.origin, SourceOrigin) and self.origin.source_record_id == subject_id
        ):
            raise _invalid_origin(
                origin_kind="relationship_assertion",
                reason="observed_identifier requires a source origin pointing at its subject",
            )
        _require_field_type(self, self.asserted_at, UtcInstant, field_name="asserted_at")
        if self.asserted_at < self.origin.accepted_operation.accepted_at:
            raise _attestation_time_invalid(
                "relationship_assertion",
                (self.id.text,),
                self.origin.accepted_operation.accepted_at.text,
                self.asserted_at.text,
            )
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "object_id", object_id)


@dataclass(frozen=True, slots=True)
class AssertionRetraction:
    id: AssertionRetractionId
    target_id: AssertionTargetId
    origin: AssertionOrigin
    accepted_operation: AcceptedOperationAttestation
    reason: str
    retracted_at: UtcInstant

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, AssertionRetractionId, field_name="id")
        _require_id_type(
            self.target_id,
            id_set=_ID_TYPE_SETS["assertion_target"],
            field_name="target_id",
        )
        reason = _canonical_nonblank(
            self.reason,
            type_name=type(self).__name__,
            field_name="reason",
        )
        if not isinstance(self.origin, (SourceOrigin, HumanCorrectionOrigin)):
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="origin",
                reason="value must be a SourceOrigin or HumanCorrectionOrigin",
            )
        operation = self.accepted_operation
        if type(operation) is not AcceptedOperationAttestation:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="accepted_operation",
                reason="value must be an AcceptedOperationAttestation",
            )
        if self.origin.accepted_operation != operation:
            raise DomainError(
                code="retraction_origin_mismatch",
                message=(
                    f"Retraction {self.id.text!r} origin operation differs from its "
                    "accepted operation"
                ),
                context={
                    "target_id": self.target_id.text,
                    "reason": "origin operation does not match the retraction operation",
                },
            )
        if isinstance(self.origin, SourceOrigin):
            if operation.action is not OperationAction.SOURCE_REFRESH:
                raise _attestation_action_mismatch(
                    "source_retraction",
                    (self.target_id.text,),
                    OperationAction.SOURCE_REFRESH.value,
                    operation.action.value,
                )
        _require_field_type(self, self.retracted_at, UtcInstant, field_name="retracted_at")
        if self.retracted_at < operation.accepted_at:
            raise _attestation_time_invalid(
                "assertion_retraction",
                (self.target_id.text,),
                operation.accepted_at.text,
                self.retracted_at.text,
            )
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class SourceRecordProposal:
    source_record_id: SourceRecordId
    source_system: str
    source_record_key: str
    retrieved_at: UtcInstant
    payload_digest: ContentDigest
    media_type: str


@dataclass(frozen=True, slots=True)
class SourceMetadataAssertionProposal:
    assertion_id: MetadataAssertionId
    subject_id: KnowledgeEntityId
    field: MetadataFieldKey
    value: AssertionValue
    authority_tier: AuthorityTier
    asserted_at: UtcInstant


@dataclass(frozen=True, slots=True)
class SourceRelationshipAssertionProposal:
    assertion_id: RelationshipAssertionId
    predicate: FactualPredicate
    subject_id: RelationshipEndpointId
    object_id: RelationshipEndpointId
    authority_tier: AuthorityTier
    asserted_at: UtcInstant


@dataclass(frozen=True, slots=True)
class SourceRetractionProposal:
    retraction_id: AssertionRetractionId
    target_id: MetadataAssertionId | RelationshipAssertionId
    reason: str
    retracted_at: UtcInstant


@dataclass(frozen=True, slots=True)
class SourceWriteBatchProposal:
    source_record: SourceRecordProposal
    metadata_assertions: tuple[SourceMetadataAssertionProposal, ...]
    relationship_assertions: tuple[SourceRelationshipAssertionProposal, ...]
    retractions: tuple[SourceRetractionProposal, ...]

    def canonical_digest(self) -> ContentDigest:
        record = self.source_record
        fields: tuple[CanonicalBindingField, ...] = (
            (
                record.source_record_id,
                record.source_system,
                record.source_record_key,
                record.retrieved_at,
                record.payload_digest,
                record.media_type,
            ),
            len(self.metadata_assertions),
            *[
                (
                    item.assertion_id,
                    item.subject_id,
                    item.field,
                    item.value,
                    item.authority_tier,
                    item.asserted_at,
                )
                for item in self.metadata_assertions
            ],
            len(self.relationship_assertions),
            *[
                (
                    item.assertion_id,
                    item.predicate,
                    item.subject_id,
                    item.object_id,
                    item.authority_tier,
                    item.asserted_at,
                )
                for item in self.relationship_assertions
            ],
            len(self.retractions),
            *[
                (item.retraction_id, item.target_id, item.reason, item.retracted_at)
                for item in self.retractions
            ],
        )
        return _compute_canonical_binding_digest(fields)


@dataclass(frozen=True, slots=True)
class SourceWriteBatch:
    source_record: SourceRecord
    metadata_assertions: tuple[MetadataAssertion, ...]
    relationship_assertions: tuple[RelationshipAssertion, ...]
    retractions: tuple[AssertionRetraction, ...]


def _canonical_lowercase(value: object, *, type_name: str, field_name: str) -> str:
    text = _canonical_nonblank(value, type_name=type_name, field_name=field_name)
    if text != text.lower():
        raise _invalid_value_object(
            type_name=type_name,
            field_name=field_name,
            reason="value must be lowercase",
        )
    return text


def create_source_record_proposal(
    source_record_id: SourceRecordId,
    source_system: str,
    source_record_key: str,
    retrieved_at: UtcInstant,
    payload_digest: ContentDigest,
    media_type: str,
) -> SourceRecordProposal:
    _require_field_type(
        source_record_id, source_record_id, SourceRecordId, field_name="source_record_id"
    )
    system = _canonical_lowercase(
        source_system, type_name="SourceRecordProposal", field_name="source_system"
    )
    if _SOURCE_SYSTEM_PATTERN.fullmatch(system) is None:
        raise _invalid_value_object(
            type_name="SourceRecordProposal",
            field_name="source_system",
            reason="source_system must match [a-z][a-z0-9_-]{0,63}",
        )
    key = _canonical_nonblank(
        source_record_key, type_name="SourceRecordProposal", field_name="source_record_key"
    )
    _require_field_type(retrieved_at, retrieved_at, UtcInstant, field_name="retrieved_at")
    _require_field_type(payload_digest, payload_digest, ContentDigest, field_name="payload_digest")
    media = _canonical_lowercase(
        media_type, type_name="SourceRecordProposal", field_name="media_type"
    )
    return SourceRecordProposal(
        source_record_id=source_record_id,
        source_system=system,
        source_record_key=key,
        retrieved_at=retrieved_at,
        payload_digest=payload_digest,
        media_type=media,
    )


def create_source_metadata_assertion_proposal(
    assertion_id: MetadataAssertionId,
    subject_id: KnowledgeEntityId,
    field: MetadataFieldKey,
    value: AssertionValue,
    authority_tier: AuthorityTier,
    asserted_at: UtcInstant,
) -> SourceMetadataAssertionProposal:
    _require_field_type(assertion_id, assertion_id, MetadataAssertionId, field_name="assertion_id")
    _require_id_type(subject_id, id_set=_ID_TYPE_SETS["knowledge_entity"], field_name="subject_id")
    if type(field) is not MetadataFieldKey:
        raise _invalid_value_object(
            type_name="SourceMetadataAssertionProposal",
            field_name="field",
            reason="value must be a MetadataFieldKey",
        )
    if not isinstance(value, get_args(AssertionValue)):
        raise _invalid_value_object(
            type_name="SourceMetadataAssertionProposal",
            field_name="value",
            reason="value must be an AssertionValue variant",
        )
    if (
        type(authority_tier) is not AuthorityTier
        or authority_tier is AuthorityTier.HUMAN_CORRECTION
    ):
        raise _invalid_value_object(
            type_name="SourceMetadataAssertionProposal",
            field_name="authority_tier",
            reason="value must be an aggregator or authoritative_source tier",
        )
    _require_field_type(asserted_at, asserted_at, UtcInstant, field_name="asserted_at")
    return SourceMetadataAssertionProposal(
        assertion_id=assertion_id,
        subject_id=subject_id,
        field=field,
        value=value,
        authority_tier=authority_tier,
        asserted_at=asserted_at,
    )


def create_source_relationship_assertion_proposal(
    assertion_id: RelationshipAssertionId,
    predicate: FactualPredicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
    authority_tier: AuthorityTier,
    asserted_at: UtcInstant,
) -> SourceRelationshipAssertionProposal:
    _require_field_type(
        assertion_id, assertion_id, RelationshipAssertionId, field_name="assertion_id"
    )
    if type(predicate) is not FactualPredicate:
        raise _invalid_value_object(
            type_name="SourceRelationshipAssertionProposal",
            field_name="predicate",
            reason="value must be a FactualPredicate",
        )
    _require_id_type(
        subject_id, id_set=_ID_TYPE_SETS["relationship_endpoint"], field_name="subject_id"
    )
    _require_id_type(
        object_id, id_set=_ID_TYPE_SETS["relationship_endpoint"], field_name="object_id"
    )
    if (
        type(authority_tier) is not AuthorityTier
        or authority_tier is AuthorityTier.HUMAN_CORRECTION
    ):
        raise _invalid_value_object(
            type_name="SourceRelationshipAssertionProposal",
            field_name="authority_tier",
            reason="value must be an aggregator or authoritative_source tier",
        )
    _require_field_type(asserted_at, asserted_at, UtcInstant, field_name="asserted_at")
    return SourceRelationshipAssertionProposal(
        assertion_id=assertion_id,
        predicate=predicate,
        subject_id=subject_id,
        object_id=object_id,
        authority_tier=authority_tier,
        asserted_at=asserted_at,
    )


def create_source_retraction_proposal(
    retraction_id: AssertionRetractionId,
    target_id: MetadataAssertionId | RelationshipAssertionId,
    reason: str,
    retracted_at: UtcInstant,
) -> SourceRetractionProposal:
    _require_field_type(
        retraction_id, retraction_id, AssertionRetractionId, field_name="retraction_id"
    )
    if type(target_id) not in (MetadataAssertionId, RelationshipAssertionId):
        raise _invalid_value_object(
            type_name="SourceRetractionProposal",
            field_name="target_id",
            reason="value must be a MetadataAssertionId or RelationshipAssertionId",
        )
    canonical_reason = _canonical_nonblank(
        reason, type_name="SourceRetractionProposal", field_name="reason"
    )
    _require_field_type(retracted_at, retracted_at, UtcInstant, field_name="retracted_at")
    return SourceRetractionProposal(
        retraction_id=retraction_id,
        target_id=target_id,
        reason=canonical_reason,
        retracted_at=retracted_at,
    )


_RecordT = TypeVar("_RecordT")


def _unique_sorted_records(
    records: Iterable[_RecordT],
    id_of: Callable[[_RecordT], TypedId],
    record_kind: str,
    expected_type: type,
) -> tuple[_RecordT, ...]:
    seen: set[str] = set()
    items: list[_RecordT] = []
    for record in records:
        if type(record) is not expected_type:
            raise _invalid_value_object(
                type_name=type(record).__name__,
                field_name=record_kind,
                reason=f"value must be a {expected_type.__name__}",
            )
        record_id = id_of(record)
        key = record_id.text
        if key in seen:
            raise DomainError(
                code="duplicate_record_id",
                message=f"{expected_type.__name__} ID {key!r} appears more than once in the input",
                context={"record_id": key, "record_kind": record_kind},
            )
        seen.add(key)
        items.append(record)
    return tuple(sorted(items, key=lambda record: id_of(record).text))


def create_source_write_batch_proposal(
    source_record: SourceRecordProposal,
    metadata_assertions: Iterable[SourceMetadataAssertionProposal],
    relationship_assertions: Iterable[SourceRelationshipAssertionProposal],
    retractions: Iterable[SourceRetractionProposal],
) -> SourceWriteBatchProposal:
    if type(source_record) is not SourceRecordProposal:
        raise _invalid_value_object(
            type_name="SourceWriteBatchProposal",
            field_name="source_record",
            reason="value must be a SourceRecordProposal",
        )
    meta = _unique_sorted_records(
        metadata_assertions,
        lambda item: item.assertion_id,
        "metadata_assertion",
        SourceMetadataAssertionProposal,
    )
    rels = _unique_sorted_records(
        relationship_assertions,
        lambda item: item.assertion_id,
        "relationship_assertion",
        SourceRelationshipAssertionProposal,
    )
    rets = _unique_sorted_records(
        retractions, lambda item: item.retraction_id, "source_retraction", SourceRetractionProposal
    )
    return SourceWriteBatchProposal(
        source_record=source_record,
        metadata_assertions=meta,
        relationship_assertions=rels,
        retractions=rets,
    )


def create_source_origin(
    source_record: SourceRecord,
    authority_tier: AuthorityTier,
    accepted_operation: AcceptedOperationAttestation,
) -> SourceOrigin:
    if type(source_record) is not SourceRecord:
        raise _invalid_value_object(
            type_name="SourceOrigin",
            field_name="source_record",
            reason="value must be a SourceRecord",
        )
    if accepted_operation != source_record.accepted_operation:
        raise _invalid_origin(
            origin_kind="source", reason="operation does not match the source record"
        )
    return SourceOrigin(
        source_record_id=source_record.id,
        authority_tier=authority_tier,
        accepted_operation=accepted_operation,
    )


def create_human_correction_origin(
    accepted_operation: AcceptedOperationAttestation,
    required_action: OperationAction,
) -> HumanCorrectionOrigin:
    if required_action not in (OperationAction.HUMAN_CORRECTION, OperationAction.RETRACT_RECORD):
        raise _invalid_value_object(
            type_name="HumanCorrectionOrigin",
            field_name="required_action",
            reason="value must be human_correction or retract_record",
        )
    if accepted_operation.action is not required_action:
        raise _attestation_action_mismatch(
            "human_correction_origin", (), required_action.value, accepted_operation.action.value
        )
    return HumanCorrectionOrigin(accepted_operation=accepted_operation)


@dataclass(frozen=True, slots=True)
class DomainProjectionInput:
    entity_index: EntitySnapshotIndex
    source_record_index: SourceRecordIndex
    semantic_relations: tuple[SemanticRelation, ...]
    metadata_assertions: tuple[MetadataAssertion, ...]
    relationship_assertions: tuple[RelationshipAssertion, ...]
    retractions: tuple[AssertionRetraction, ...]


def _revalidate_source_origin(
    origin: AssertionOrigin,
    source_record_index: SourceRecordIndex,
    record_id: str,
    asserted_at: UtcInstant,
    record_kind: str,
) -> None:
    if not isinstance(origin, SourceOrigin):
        return
    record = source_record_index.by_id.get(origin.source_record_id)
    if record is None:
        raise DomainError(
            code="source_record_not_found",
            message=(
                f"{record_kind} {record_id!r} references a missing "
                f"SourceRecord {origin.source_record_id.text!r}"
            ),
            context={
                "source_record_id": origin.source_record_id.text,
                "record_kind": record_kind,
                "record_id": record_id,
            },
        )
    if record.accepted_operation != origin.accepted_operation:
        raise _invalid_origin(
            origin_kind=record_kind,
            reason="origin operation does not match the referenced source record",
        )
    if asserted_at < record.retrieved_at:
        raise DomainError(
            code="source_asserted_before_retrieval",
            message=f"{record_kind} {record_id!r} predates its source record retrieval",
            context={
                "source_record_id": origin.source_record_id.text,
                "record_id": record_id,
                "recorded_at": asserted_at.text,
                "retrieved_at": record.retrieved_at.text,
            },
        )


def build_domain_projection_input(
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    semantic_relations: Iterable[SemanticRelation],
    metadata_assertions: Iterable[MetadataAssertion],
    relationship_assertions: Iterable[RelationshipAssertion],
    retractions: Iterable[AssertionRetraction],
) -> DomainProjectionInput:
    _require_entity_index(entity_index)
    _require_source_record_index(source_record_index)
    relations = _unique_sorted_records(
        semantic_relations, lambda item: item.id, "semantic_relation", SemanticRelation
    )
    metas = _unique_sorted_records(
        metadata_assertions, lambda item: item.id, "metadata_assertion", MetadataAssertion
    )
    rels = _unique_sorted_records(
        relationship_assertions,
        lambda item: item.id,
        "relationship_assertion",
        RelationshipAssertion,
    )
    rets = _unique_sorted_records(
        retractions, lambda item: item.id, "assertion_retraction", AssertionRetraction
    )
    for meta_assertion in metas:
        _revalidate_source_origin(
            meta_assertion.origin,
            source_record_index,
            meta_assertion.id.text,
            meta_assertion.asserted_at,
            "metadata_assertion",
        )
    for rel_assertion in rels:
        _revalidate_source_origin(
            rel_assertion.origin,
            source_record_index,
            rel_assertion.id.text,
            rel_assertion.asserted_at,
            "relationship_assertion",
        )
    meta_map: dict[str, MetadataAssertion] = {assertion.id.text: assertion for assertion in metas}
    rel_map: dict[str, RelationshipAssertion] = {assertion.id.text: assertion for assertion in rels}
    semantic_map: dict[str, SemanticRelation] = {
        relation.id.text: relation for relation in relations
    }
    seen_targets: dict[str, AssertionRetraction] = {}
    for retraction in rets:
        target_key = retraction.target_id.text
        if target_key in meta_map:
            target_time = meta_map[target_key].asserted_at
        elif target_key in rel_map:
            target_time = rel_map[target_key].asserted_at
        elif target_key in semantic_map:
            target_time = semantic_map[target_key].confirmed_at
        else:
            raise DomainError(
                code="retraction_target_invalid",
                message=f"Retraction {retraction.id.text!r} targets unknown record {target_key!r}",
                context={
                    "target_id": target_key,
                    "reason": "target record does not exist in the projection input",
                },
            )
        if target_key in seen_targets:
            raise DomainError(
                code="assertion_already_retracted",
                message=f"Record {target_key!r} already has a retraction in the input",
                context={
                    "target_id": target_key,
                    "existing_retraction_id": seen_targets[target_key].id.text,
                },
            )
        seen_targets[target_key] = retraction
        if retraction.retracted_at < target_time:
            raise DomainError(
                code="retraction_time_invalid",
                message=f"Retraction {retraction.id.text!r} predates its target record",
                context={"target_id": target_key},
            )
    return DomainProjectionInput(
        entity_index=entity_index,
        source_record_index=source_record_index,
        semantic_relations=relations,
        metadata_assertions=metas,
        relationship_assertions=rels,
        retractions=rets,
    )


def _active_subject_check(
    subject_id: KnowledgeEntityId,
    entity_index: EntitySnapshotIndex,
    *,
    display_predicate: str,
    creator_text: str,
    record_kind: str,
) -> None:
    lifecycle_id = cast("LifecycleEntityId", subject_id)
    if lifecycle_id not in entity_index.by_id:
        raise DomainError(
            code="dangling_structural_reference",
            message=f"{record_kind} {creator_text!r} references missing entity {subject_id.text!r}",
            context={
                "predicate": display_predicate,
                "subject_id": creator_text,
                "target_id": subject_id.text,
            },
        )
    resolution = resolve_terminal(lifecycle_id, entity_index)
    if len(resolution.path) > 1:
        raise DomainError(
            code="noncanonical_write_endpoint",
            message=(
                f"Write endpoints must use active terminal {resolution.terminal_id.text!r} "
                f"instead of redirect loser {subject_id.text!r}"
            ),
            context={
                "endpoint_id": subject_id.text,
                "terminal_id": resolution.terminal_id.text,
                "record_kind": record_kind,
            },
        )
    if isinstance(resolution.terminal_lifecycle, TombstoneLifecycle):
        raise DomainError(
            code="entity_not_active",
            message=f"Entity {resolution.terminal_id.text!r} is tombstoned",
            context={
                "entity_id": resolution.terminal_id.text,
                "lifecycle": resolution.terminal_lifecycle.tag,
            },
        )


def _active_endpoint_check(
    endpoint_id: RelationshipEndpointId,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    *,
    display_predicate: str,
    creator_text: str,
    record_kind: str,
) -> None:
    if isinstance(endpoint_id, SourceRecordId):
        if endpoint_id not in source_record_index.by_id:
            raise DomainError(
                code="source_record_not_found",
                message=(
                    f"{record_kind} {creator_text!r} references a missing "
                    f"SourceRecord {endpoint_id.text!r}"
                ),
                context={
                    "source_record_id": endpoint_id.text,
                    "record_kind": record_kind,
                    "record_id": creator_text,
                },
            )
        return
    _active_subject_check(
        endpoint_id,
        entity_index,
        display_predicate=display_predicate,
        creator_text=creator_text,
        record_kind=record_kind,
    )


def _check_has_identifier_target(
    predicate: FactualPredicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
    entity_index: EntitySnapshotIndex,
    creator_text: str,
) -> None:
    if predicate is not FactualPredicate.HAS_IDENTIFIER:
        return
    target = entity_index.by_id.get(cast("LifecycleEntityId", object_id))
    if not isinstance(target, Identifier):
        raise DomainError(
            code="dangling_structural_reference",
            message=(
                f"has_identifier assertion {creator_text!r} references missing "
                f"Identifier {object_id.text!r}"
            ),
            context={
                "predicate": predicate.value,
                "subject_id": creator_text,
                "target_id": object_id.text,
            },
        )
    assert_identifier_target_compatible(target.key, cast("KnowledgeEntityId", subject_id))


def create_source_write_batch(
    proposal: SourceWriteBatchProposal,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> SourceWriteBatch:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    if type(proposal) is not SourceWriteBatchProposal:
        raise _invalid_value_object(
            type_name="SourceWriteBatchProposal",
            field_name="proposal",
            reason="value must be a SourceWriteBatchProposal",
        )
    operation = accepted_operation
    if type(operation) is not AcceptedOperationAttestation:
        raise _invalid_value_object(
            type_name="create_source_write_batch",
            field_name="accepted_operation",
            reason="value must be an AcceptedOperationAttestation",
        )
    record_proposal = proposal.source_record
    if operation.action not in (OperationAction.SOURCE_INGEST, OperationAction.SOURCE_REFRESH):
        raise _attestation_action_mismatch(
            "source_write_batch",
            (record_proposal.source_record_id.text,),
            (OperationAction.SOURCE_INGEST.value, OperationAction.SOURCE_REFRESH.value),
            operation.action.value,
        )
    if record_proposal.source_record_id in projection_input.source_record_index.by_id:
        raise DomainError(
            code="duplicate_record_id",
            message=f"SourceRecord {record_proposal.source_record_id.text!r} already exists",
            context={
                "record_id": record_proposal.source_record_id.text,
                "record_kind": "source_record",
            },
        )
    lineage_existing = [
        record
        for record in projection_input.source_record_index.by_id.values()
        if record.source_system == record_proposal.source_system
        and record.source_record_key == record_proposal.source_record_key
    ]
    if operation.action is OperationAction.SOURCE_INGEST:
        if lineage_existing:
            raise _invalid_value_object(
                type_name="SourceWriteBatchProposal",
                field_name="source_record",
                reason="source ingest requires an unused lineage key",
            )
        if proposal.retractions:
            raise _invalid_value_object(
                type_name="SourceWriteBatchProposal",
                field_name="retractions",
                reason="source ingest batch cannot include retractions",
            )
    elif not lineage_existing:
        raise _invalid_value_object(
            type_name="SourceWriteBatchProposal",
            field_name="source_record",
            reason="source refresh requires an existing record with the same lineage",
        )
    computed = compute_operation_payload_digest(
        SourceWriteOperationBinding(proposal_digest=proposal.canonical_digest())
    )
    if not _content_digests_equal(computed, operation.payload_digest):
        raise _attestation_payload_mismatch(
            "source_write_batch",
            (record_proposal.source_record_id.text,),
            operation.payload_digest.text,
            computed.text,
        )
    if operation.accepted_at < record_proposal.retrieved_at:
        raise _attestation_time_invalid(
            "source_write_batch",
            (record_proposal.source_record_id.text,),
            operation.accepted_at.text,
            record_proposal.retrieved_at.text,
        )
    record = SourceRecord(
        id=record_proposal.source_record_id,
        source_system=record_proposal.source_system,
        source_record_key=record_proposal.source_record_key,
        retrieved_at=record_proposal.retrieved_at,
        payload_digest=record_proposal.payload_digest,
        media_type=record_proposal.media_type,
        accepted_operation=operation,
    )
    built_meta: list[MetadataAssertion] = []
    for meta_item in proposal.metadata_assertions:
        _active_subject_check(
            meta_item.subject_id,
            projection_input.entity_index,
            display_predicate=meta_item.field.value,
            creator_text=meta_item.assertion_id.text,
            record_kind="metadata_assertion",
        )
        _validate_metadata_target(meta_item.field, meta_item.subject_id, meta_item.value)
        origin = SourceOrigin(
            source_record_id=record.id,
            authority_tier=meta_item.authority_tier,
            accepted_operation=operation,
        )
        if meta_item.asserted_at < record.retrieved_at:
            raise DomainError(
                code="source_asserted_before_retrieval",
                message=(
                    f"Assertion {meta_item.assertion_id.text!r} predates "
                    "its source record retrieval"
                ),
                context={
                    "source_record_id": record.id.text,
                    "record_id": meta_item.assertion_id.text,
                    "recorded_at": meta_item.asserted_at.text,
                    "retrieved_at": record.retrieved_at.text,
                },
            )
        if meta_item.asserted_at < operation.accepted_at:
            raise _attestation_time_invalid(
                "source_metadata_assertion",
                (meta_item.assertion_id.text,),
                operation.accepted_at.text,
                meta_item.asserted_at.text,
            )
        built_meta.append(
            MetadataAssertion(
                id=meta_item.assertion_id,
                subject_id=meta_item.subject_id,
                field=meta_item.field,
                value=meta_item.value,
                origin=origin,
                asserted_at=meta_item.asserted_at,
            )
        )
    built_rels: list[RelationshipAssertion] = []
    for rel_item in proposal.relationship_assertions:
        subject_id, object_id = canonicalize_relationship(
            rel_item.predicate, rel_item.subject_id, rel_item.object_id
        )
        _active_endpoint_check(
            subject_id,
            projection_input.entity_index,
            projection_input.source_record_index,
            display_predicate=rel_item.predicate.value,
            creator_text=rel_item.assertion_id.text,
            record_kind="relationship_assertion",
        )
        _active_endpoint_check(
            object_id,
            projection_input.entity_index,
            projection_input.source_record_index,
            display_predicate=rel_item.predicate.value,
            creator_text=rel_item.assertion_id.text,
            record_kind="relationship_assertion",
        )
        if rel_item.predicate is FactualPredicate.OBSERVED_IDENTIFIER and subject_id != record.id:
            raise _invalid_origin(
                origin_kind="source",
                reason="observed_identifier must originate from its own source record",
            )
        _check_has_identifier_target(
            rel_item.predicate,
            subject_id,
            object_id,
            projection_input.entity_index,
            rel_item.assertion_id.text,
        )
        origin = SourceOrigin(
            source_record_id=record.id,
            authority_tier=rel_item.authority_tier,
            accepted_operation=operation,
        )
        if rel_item.asserted_at < record.retrieved_at:
            raise DomainError(
                code="source_asserted_before_retrieval",
                message=(
                    f"Assertion {rel_item.assertion_id.text!r} predates its source record retrieval"
                ),
                context={
                    "source_record_id": record.id.text,
                    "record_id": rel_item.assertion_id.text,
                    "recorded_at": rel_item.asserted_at.text,
                    "retrieved_at": record.retrieved_at.text,
                },
            )
        if rel_item.asserted_at < operation.accepted_at:
            raise _attestation_time_invalid(
                "source_relationship_assertion",
                (rel_item.assertion_id.text,),
                operation.accepted_at.text,
                rel_item.asserted_at.text,
            )
        built_rels.append(
            RelationshipAssertion(
                id=rel_item.assertion_id,
                predicate=rel_item.predicate,
                subject_id=subject_id,
                object_id=object_id,
                origin=origin,
                asserted_at=rel_item.asserted_at,
            )
        )
    built_rets: list[AssertionRetraction] = []
    if proposal.retractions:
        meta_map = {
            assertion.id.text: assertion for assertion in projection_input.metadata_assertions
        }
        rel_map = {
            assertion.id.text: assertion for assertion in projection_input.relationship_assertions
        }
        retracted_targets: dict[str, str] = {
            retraction.target_id.text: retraction.id.text
            for retraction in projection_input.retractions
        }
        for ret_item in proposal.retractions:
            target_key = ret_item.target_id.text
            target = meta_map.get(target_key) or rel_map.get(target_key)
            if target is None or not isinstance(target.origin, SourceOrigin):
                raise DomainError(
                    code="retraction_target_invalid",
                    message=(
                        f"Retraction {ret_item.retraction_id.text!r} targets a record "
                        "that cannot be source-retracted"
                    ),
                    context={
                        "target_id": ret_item.target_id.text,
                        "reason": "target is not a same-lineage source-origin assertion",
                    },
                )
            target_source = projection_input.source_record_index.by_id.get(
                target.origin.source_record_id
            )
            if target_source is None or (
                target_source.source_system,
                target_source.source_record_key,
            ) != (record.source_system, record.source_record_key):
                raise DomainError(
                    code="retraction_origin_mismatch",
                    message=(
                        f"Retraction {ret_item.retraction_id.text!r} target belongs "
                        "to a different source lineage"
                    ),
                    context={
                        "target_id": ret_item.target_id.text,
                        "reason": "source lineage differs from the refresh batch",
                    },
                )
            if target.origin.source_record_id != record.id:
                raise DomainError(
                    code="retraction_origin_mismatch",
                    message=(
                        f"Retraction {ret_item.retraction_id.text!r} target was not "
                        "written under the batch operation"
                    ),
                    context={
                        "target_id": ret_item.target_id.text,
                        "reason": "origin operation does not match the refresh batch operation",
                    },
                )
            if ret_item.target_id.text in retracted_targets:
                raise DomainError(
                    code="assertion_already_retracted",
                    message=f"Assertion {ret_item.target_id.text!r} is already retracted",
                    context={
                        "target_id": ret_item.target_id.text,
                        "existing_retraction_id": retracted_targets[ret_item.target_id.text],
                    },
                )
            retracted_targets[ret_item.target_id.text] = ret_item.retraction_id.text
            if ret_item.retracted_at < target.asserted_at:
                raise DomainError(
                    code="retraction_time_invalid",
                    message=(
                        f"Retraction {ret_item.retraction_id.text!r} predates its target assertion"
                    ),
                    context={"target_id": ret_item.target_id.text},
                )
            if ret_item.retracted_at < record.retrieved_at:
                raise DomainError(
                    code="source_asserted_before_retrieval",
                    message=(
                        f"Retraction {ret_item.retraction_id.text!r} predates "
                        "its source record retrieval"
                    ),
                    context={
                        "source_record_id": record.id.text,
                        "record_id": ret_item.retraction_id.text,
                        "recorded_at": ret_item.retracted_at.text,
                        "retrieved_at": record.retrieved_at.text,
                    },
                )
            if ret_item.retracted_at < operation.accepted_at:
                raise _attestation_time_invalid(
                    "source_retraction",
                    (ret_item.retraction_id.text,),
                    operation.accepted_at.text,
                    ret_item.retracted_at.text,
                )
            origin = SourceOrigin(
                source_record_id=record.id,
                authority_tier=AuthorityTier.AGGREGATOR,
                accepted_operation=operation,
            )
            built_rets.append(
                AssertionRetraction(
                    id=ret_item.retraction_id,
                    target_id=ret_item.target_id,
                    origin=origin,
                    accepted_operation=operation,
                    reason=ret_item.reason,
                    retracted_at=ret_item.retracted_at,
                )
            )
    return SourceWriteBatch(
        source_record=record,
        metadata_assertions=tuple(sorted(built_meta, key=lambda item: item.id.text)),
        relationship_assertions=tuple(sorted(built_rels, key=lambda item: item.id.text)),
        retractions=tuple(sorted(built_rets, key=lambda item: item.id.text)),
    )


def create_human_metadata_assertion(
    assertion_id: MetadataAssertionId,
    subject_id: KnowledgeEntityId,
    field: MetadataFieldKey,
    value: AssertionValue,
    asserted_at: UtcInstant,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> MetadataAssertion:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    _require_field_type(assertion_id, assertion_id, MetadataAssertionId, field_name="assertion_id")
    _require_id_type(subject_id, id_set=_ID_TYPE_SETS["knowledge_entity"], field_name="subject_id")
    if accepted_operation.action is not OperationAction.HUMAN_CORRECTION:
        raise _attestation_action_mismatch(
            "human_metadata_correction",
            (assertion_id.text,),
            OperationAction.HUMAN_CORRECTION.value,
            accepted_operation.action.value,
        )
    binding = HumanMetadataCorrectionBinding(
        subject_id=subject_id, field=field, value=value, asserted_at=asserted_at
    )
    computed = compute_operation_payload_digest(binding)
    if not _content_digests_equal(computed, accepted_operation.payload_digest):
        raise _attestation_payload_mismatch(
            "human_metadata_correction",
            (assertion_id.text,),
            accepted_operation.payload_digest.text,
            computed.text,
        )
    origin = create_human_correction_origin(accepted_operation, OperationAction.HUMAN_CORRECTION)
    _active_subject_check(
        subject_id,
        projection_input.entity_index,
        display_predicate=field.value,
        creator_text=assertion_id.text,
        record_kind="metadata_assertion",
    )
    _validate_metadata_target(field, subject_id, value)
    if asserted_at < accepted_operation.accepted_at:
        raise _attestation_time_invalid(
            "human_metadata_correction",
            (assertion_id.text,),
            accepted_operation.accepted_at.text,
            asserted_at.text,
        )
    return MetadataAssertion(
        id=assertion_id,
        subject_id=subject_id,
        field=field,
        value=value,
        origin=origin,
        asserted_at=asserted_at,
    )


def create_human_relationship_assertion(
    assertion_id: RelationshipAssertionId,
    predicate: FactualPredicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
    asserted_at: UtcInstant,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> RelationshipAssertion:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    _require_field_type(
        assertion_id, assertion_id, RelationshipAssertionId, field_name="assertion_id"
    )
    if accepted_operation.action is not OperationAction.HUMAN_CORRECTION:
        raise _attestation_action_mismatch(
            "human_relationship_correction",
            (assertion_id.text,),
            OperationAction.HUMAN_CORRECTION.value,
            accepted_operation.action.value,
        )
    binding = HumanRelationshipCorrectionBinding(
        predicate=predicate, subject_id=subject_id, object_id=object_id, asserted_at=asserted_at
    )
    computed = compute_operation_payload_digest(binding)
    if not _content_digests_equal(computed, accepted_operation.payload_digest):
        raise _attestation_payload_mismatch(
            "human_relationship_correction",
            (assertion_id.text,),
            accepted_operation.payload_digest.text,
            computed.text,
        )
    origin = create_human_correction_origin(accepted_operation, OperationAction.HUMAN_CORRECTION)
    if predicate is FactualPredicate.OBSERVED_IDENTIFIER:
        raise _invalid_origin(
            origin_kind="human_correction",
            reason="observed_identifier cannot be created through human correction",
        )
    subject_id, object_id = canonicalize_relationship(predicate, subject_id, object_id)
    _active_endpoint_check(
        subject_id,
        projection_input.entity_index,
        projection_input.source_record_index,
        display_predicate=predicate.value,
        creator_text=assertion_id.text,
        record_kind="relationship_assertion",
    )
    _active_endpoint_check(
        object_id,
        projection_input.entity_index,
        projection_input.source_record_index,
        display_predicate=predicate.value,
        creator_text=assertion_id.text,
        record_kind="relationship_assertion",
    )
    _check_has_identifier_target(
        predicate, subject_id, object_id, projection_input.entity_index, assertion_id.text
    )
    if asserted_at < accepted_operation.accepted_at:
        raise _attestation_time_invalid(
            "human_relationship_correction",
            (assertion_id.text,),
            accepted_operation.accepted_at.text,
            asserted_at.text,
        )
    return RelationshipAssertion(
        id=assertion_id,
        predicate=predicate,
        subject_id=subject_id,
        object_id=object_id,
        origin=origin,
        asserted_at=asserted_at,
    )


def create_human_retraction(
    retraction_id: AssertionRetractionId,
    target_id: AssertionTargetId,
    reason: str,
    retracted_at: UtcInstant,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> AssertionRetraction:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    _require_field_type(
        retraction_id, retraction_id, AssertionRetractionId, field_name="retraction_id"
    )
    _require_id_type(target_id, id_set=_ID_TYPE_SETS["assertion_target"], field_name="target_id")
    if accepted_operation.action is not OperationAction.RETRACT_RECORD:
        raise _attestation_action_mismatch(
            "human_retraction",
            (retraction_id.text,),
            OperationAction.RETRACT_RECORD.value,
            accepted_operation.action.value,
        )
    binding = HumanRetractionBinding(target_id=target_id, reason=reason, retracted_at=retracted_at)
    computed = compute_operation_payload_digest(binding)
    if not _content_digests_equal(computed, accepted_operation.payload_digest):
        raise _attestation_payload_mismatch(
            "human_retraction",
            (retraction_id.text,),
            accepted_operation.payload_digest.text,
            computed.text,
        )
    origin = create_human_correction_origin(accepted_operation, OperationAction.RETRACT_RECORD)
    target_time = _lookup_target_time(target_id, projection_input)
    if retracted_at < target_time:
        raise DomainError(
            code="retraction_time_invalid",
            message=f"Retraction {retraction_id.text!r} predates its target record",
            context={"target_id": target_id.text},
        )
    if retracted_at < accepted_operation.accepted_at:
        raise _attestation_time_invalid(
            "human_retraction",
            (retraction_id.text,),
            accepted_operation.accepted_at.text,
            retracted_at.text,
        )
    for existing in projection_input.retractions:
        if existing.target_id == target_id:
            raise DomainError(
                code="assertion_already_retracted",
                message=f"Record {target_id.text!r} already has a retraction",
                context={"target_id": target_id.text, "existing_retraction_id": existing.id.text},
            )
    return AssertionRetraction(
        id=retraction_id,
        target_id=target_id,
        origin=origin,
        accepted_operation=accepted_operation,
        reason=reason,
        retracted_at=retracted_at,
    )


def _lookup_target_time(
    target_id: AssertionTargetId, projection_input: DomainProjectionInput
) -> UtcInstant:
    for meta_assertion in projection_input.metadata_assertions:
        if meta_assertion.id == target_id:
            return meta_assertion.asserted_at
    for rel_assertion in projection_input.relationship_assertions:
        if rel_assertion.id == target_id:
            return rel_assertion.asserted_at
    for relation in projection_input.semantic_relations:
        if relation.id == target_id:
            return relation.confirmed_at
    raise DomainError(
        code="retraction_target_invalid",
        message=f"Retraction target {target_id.text!r} does not exist in the projection input",
        context={
            "target_id": target_id.text,
            "reason": "target record does not exist in the projection input",
        },
    )


class ProjectionStatus(StrEnum):
    MISSING = "missing"
    RESOLVED = "resolved"
    CONFLICTED = "conflicted"


class ProjectionConflictReason(StrEnum):
    SAME_TIER_VALUE_CONFLICT = "same_tier_value_conflict"
    MAX_ONE_CONFLICT = "max_one_conflict"
    IDENTIFIER_OWNER_CONFLICT = "identifier_owner_conflict"
    DUPLICATE_IDENTIFIER_RECORD = "duplicate_identifier_record"
    IRREFLEXIVE_AFTER_REDIRECT = "irreflexive_after_redirect"
    ACYCLIC_CYCLE = "acyclic_cycle"


class ProjectionExclusionReason(StrEnum):
    RETRACTED = "retracted"
    TOMBSTONED_ENTITY = "tombstoned_entity"
    TOMBSTONED_ENDPOINT = "tombstoned_endpoint"
    REQUIRED_STRUCTURAL_TARGET_NOT_CURRENT = "required_structural_target_not_current"
    TOMBSTONED_EVIDENCE_SOURCE = "tombstoned_evidence_source"
    NO_CURRENT_EVIDENCE = "no_current_evidence"


class GroundingStatus(StrEnum):
    CURRENT = "current"
    EXCLUDED = "excluded"


ProjectionRecordId: TypeAlias = MetadataAssertionId | RelationshipAssertionId | SemanticRelationId
_RelationshipSupportId: TypeAlias = RelationshipAssertionId | SemanticRelationId

_ValueT = TypeVar("_ValueT")


@dataclass(frozen=True, slots=True)
class ProjectionExclusion:
    record_id: ProjectionRecordId
    reason: ProjectionExclusionReason


@dataclass(frozen=True, slots=True)
class ProjectionContender(Generic[_ValueT]):
    value: _ValueT
    authority_tier: AuthorityTier | None
    supporting_record_ids: tuple[ProjectionRecordId, ...]


@dataclass(frozen=True, slots=True)
class ProjectionResult(Generic[_ValueT]):
    status: ProjectionStatus
    resolved_value: _ValueT | None
    contenders: tuple[ProjectionContender[_ValueT], ...]
    excluded: tuple[ProjectionExclusion, ...]
    conflict_reason: ProjectionConflictReason | None


@dataclass(frozen=True, slots=True)
class GroundingExclusion:
    evidence_id: EvidencePassageId
    reason: ProjectionExclusionReason


@dataclass(frozen=True, slots=True)
class ClaimGroundingProjection:
    claim_id: ClaimId
    status: GroundingStatus
    current_evidence_ids: tuple[EvidencePassageId, ...]
    excluded_evidence: tuple[GroundingExclusion, ...]
    record_exclusion_reason: ProjectionExclusionReason | None


@dataclass(frozen=True, slots=True)
class SemanticRelationGroundingProjection:
    semantic_relation_id: SemanticRelationId
    status: GroundingStatus
    current_evidence_ids: tuple[EvidencePassageId, ...]
    excluded_evidence: tuple[GroundingExclusion, ...]
    record_exclusion_reason: ProjectionExclusionReason | None


@dataclass(frozen=True, slots=True)
class SemanticEvidenceSupport:
    semantic_relation_id: SemanticRelationId
    current_evidence_ids: tuple[EvidencePassageId, ...]


@dataclass(frozen=True, slots=True)
class ProjectedRelationship:
    key: RelationshipKey
    status: ProjectionStatus
    supporting_record_ids: tuple[_RelationshipSupportId, ...]
    semantic_evidence_support: tuple[SemanticEvidenceSupport, ...]
    excluded: tuple[ProjectionExclusion, ...]
    conflict_reason: ProjectionConflictReason | None


@dataclass(frozen=True, slots=True)
class ProjectedStructuralRelationship:
    key: RelationshipKey
    supporting_subject_record_ids: tuple[KnowledgeEntityId, ...]


@dataclass(frozen=True, slots=True)
class StructuralExclusion:
    subject_id: KnowledgeEntityId
    relationship_key: RelationshipKey | None
    reason: ProjectionExclusionReason


@dataclass(frozen=True, slots=True)
class StructuralProjection:
    current_record_ids: tuple[KnowledgeEntityId, ...]
    relationships: tuple[ProjectedStructuralRelationship, ...]
    excluded: tuple[StructuralExclusion, ...]


def _origin_authority_tier(origin: AssertionOrigin) -> AuthorityTier:
    if isinstance(origin, HumanCorrectionOrigin):
        return AuthorityTier.HUMAN_CORRECTION
    return origin.authority_tier


def _assertion_display_sort_key(
    assertion: MetadataAssertion | RelationshipAssertion,
) -> tuple[object, ...]:
    return (
        -_authority_rank(_origin_authority_tier(assertion.origin)),
        assertion.origin.stable_key(),
        assertion.asserted_at.text,
        assertion.id.text,
    )


@dataclass(frozen=True, slots=True)
class _CurrentEvaluation:
    current_texts: frozenset[str]
    reasons: Mapping[str, ProjectionExclusionReason]
    current_semantic_texts: frozenset[str]
    entity_by_text: Mapping[str, LifecycleEntitySnapshot]


def _evidence_source_state(
    snapshot: EvidencePassage,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    current: set[str],
    terminal_texts: Mapping[str, str],
) -> str:
    if isinstance(snapshot.source_id, SourceRecordId):
        if source_record_index.by_id.get(snapshot.source_id) is None:
            raise DomainError(
                code="source_record_not_found",
                message=f"Evidence {snapshot.id.text!r} references a missing SourceRecord",
                context={
                    "source_record_id": snapshot.source_id.text,
                    "record_kind": "evidence_passage",
                    "record_id": snapshot.id.text,
                },
            )
        return "current"
    document_terminal = terminal_texts.get(snapshot.source_id.text, snapshot.source_id.text)
    if document_terminal in current:
        return "current"
    resolution = resolve_terminal(cast("LifecycleEntityId", snapshot.source_id), entity_index)
    if isinstance(resolution.terminal_lifecycle, TombstoneLifecycle):
        return "tombstoned"
    return "pending"


def _entity_join_state(
    snapshot: LifecycleEntitySnapshot,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    current: set[str],
    current_semantic: set[str],
    terminal_texts: Mapping[str, str],
) -> bool | str:
    def is_current(target: KnowledgeEntityId) -> bool:
        if isinstance(target, SemanticRelationId):
            return target.text in current_semantic
        return terminal_texts.get(target.text, target.text) in current

    if isinstance(snapshot, EvidencePassage):
        state = _evidence_source_state(
            snapshot, entity_index, source_record_index, current, terminal_texts
        )
        if state == "current":
            return True
        return state
    if isinstance(snapshot, Publication):
        return is_current(snapshot.work_id)
    if isinstance(snapshot, Document):
        return is_current(snapshot.publication_id)
    if isinstance(snapshot, Claim):
        work_ok = is_current(snapshot.work_id)
        evidence_ok = any(is_current(evidence) for evidence in snapshot.evidence_ids)
        return work_ok and evidence_ok
    if isinstance(snapshot, Note):
        return any(is_current(target) for target in snapshot.attached_entity_ids)
    if isinstance(snapshot, TechnicalLineage):
        return any(is_current(member) for member in snapshot.member_ids)
    if isinstance(snapshot, LineageSynthesis):
        lineage_ok = is_current(snapshot.lineage_id)
        citations_ok = any(is_current(claim) for claim in snapshot.claim_ids) or any(
            is_current(evidence) for evidence in snapshot.evidence_ids
        )
        return lineage_ok and citations_ok
    return False


def _semantic_join_state(
    relation: SemanticRelation,
    current: set[str],
    current_semantic: set[str],
    terminal_texts: Mapping[str, str],
) -> tuple[bool, bool]:
    def is_current(target: KnowledgeEntityId) -> bool:
        if isinstance(target, SemanticRelationId):
            return target.text in current_semantic
        return terminal_texts.get(target.text, target.text) in current

    endpoints_ok = is_current(relation.subject_id) and is_current(relation.object_id)
    evidence_ok = any(is_current(evidence) for evidence in relation.evidence_ids)
    return endpoints_ok, evidence_ok


def evaluate_current_set(projection_input: DomainProjectionInput) -> _CurrentEvaluation:
    entity_index = projection_input.entity_index
    snapshots: dict[str, LifecycleEntitySnapshot] = {
        snapshot.id.text: snapshot for snapshot in entity_index.by_id.values()
    }
    retracted_texts = {retraction.target_id.text for retraction in projection_input.retractions}
    terminal_texts: dict[str, str] = {}
    for text, snapshot in snapshots.items():
        terminal_texts[text] = resolve_terminal(snapshot.id, entity_index).terminal_id.text

    current: set[str] = set()
    current_semantic: set[str] = set()
    pending_entities: set[str] = set()
    pending_semantic: dict[str, SemanticRelation] = {}
    reasons: dict[str, ProjectionExclusionReason] = {}

    for text, snapshot in snapshots.items():
        lifecycle = snapshot.lifecycle
        if isinstance(lifecycle, TombstoneLifecycle):
            reasons[text] = ProjectionExclusionReason.TOMBSTONED_ENTITY
        elif isinstance(lifecycle, RedirectLifecycle):
            continue
        elif isinstance(
            snapshot,
            (
                Publication,
                Document,
                EvidencePassage,
                Claim,
                Note,
                TechnicalLineage,
                LineageSynthesis,
            ),
        ):
            pending_entities.add(text)
        else:
            current.add(text)

    for relation in projection_input.semantic_relations:
        text = relation.id.text
        if text in retracted_texts:
            reasons[text] = ProjectionExclusionReason.RETRACTED
        else:
            pending_semantic[text] = relation

    candidate_count = len(pending_entities) + len(pending_semantic)
    scan_count = 0
    while pending_entities or pending_semantic:
        scan_count += 1
        if scan_count > candidate_count + 1:
            raise DomainError(
                code="structural_evaluation_cycle",
                message="Current-set fixed point did not converge",
                context={"candidate_count": candidate_count, "scan_count": scan_count},
            )
        added = False
        for text in sorted(pending_entities):
            snapshot = snapshots[text]
            state = _entity_join_state(
                snapshot,
                entity_index,
                projection_input.source_record_index,
                current,
                current_semantic,
                terminal_texts,
            )
            if state is True:
                current.add(text)
                pending_entities.discard(text)
                added = True
            elif state == "tombstoned":
                reasons[text] = ProjectionExclusionReason.TOMBSTONED_EVIDENCE_SOURCE
                pending_entities.discard(text)
                added = True
        for text in sorted(pending_semantic):
            relation = pending_semantic[text]
            endpoints_ok, evidence_ok = _semantic_join_state(
                relation, current, current_semantic, terminal_texts
            )
            if endpoints_ok and evidence_ok:
                current_semantic.add(text)
                del pending_semantic[text]
                added = True
        if not added:
            break

    for text in pending_entities:
        if text in reasons:
            continue
        snapshot = snapshots[text]
        if isinstance(snapshot, EvidencePassage):
            reasons[text] = ProjectionExclusionReason.TOMBSTONED_EVIDENCE_SOURCE
        elif isinstance(snapshot, Claim):
            work_terminal = terminal_texts.get(snapshot.work_id.text, snapshot.work_id.text)
            work_snapshot = snapshots.get(work_terminal)
            if work_snapshot is not None and isinstance(
                work_snapshot.lifecycle, TombstoneLifecycle
            ):
                reasons[text] = ProjectionExclusionReason.TOMBSTONED_ENDPOINT
            else:
                reasons[text] = ProjectionExclusionReason.NO_CURRENT_EVIDENCE
        else:
            reasons[text] = ProjectionExclusionReason.REQUIRED_STRUCTURAL_TARGET_NOT_CURRENT

    for text, relation in pending_semantic.items():
        endpoints_ok, _ = _semantic_join_state(relation, current, current_semantic, terminal_texts)
        reasons[text] = (
            ProjectionExclusionReason.TOMBSTONED_ENDPOINT
            if not endpoints_ok
            else ProjectionExclusionReason.NO_CURRENT_EVIDENCE
        )

    return _CurrentEvaluation(
        current_texts=frozenset(current),
        reasons=MappingProxyType(dict(reasons)),
        current_semantic_texts=frozenset(current_semantic),
        entity_by_text=MappingProxyType(dict(snapshots)),
    )


def _terminal_map(projection_input: DomainProjectionInput) -> dict[str, str]:
    entity_index = projection_input.entity_index
    return {
        snapshot.id.text: resolve_terminal(snapshot.id, entity_index).terminal_id.text
        for snapshot in entity_index.by_id.values()
    }


def project_structural_relationships(
    projection_input: DomainProjectionInput,
) -> StructuralProjection:
    evaluation = evaluate_current_set(projection_input)
    terminals = _terminal_map(projection_input)

    def is_current(target: TypedId) -> bool:
        if isinstance(target, SourceRecordId):
            return projection_input.source_record_index.by_id.get(target) is not None
        if isinstance(target, SemanticRelationId):
            return target.text in evaluation.current_semantic_texts
        return terminals.get(target.text, target.text) in evaluation.current_texts

    support_groups: dict[tuple[str, str, str], tuple[RelationshipKey, list[KnowledgeEntityId]]] = {}

    def add_edge(key: RelationshipKey, subject_id: KnowledgeEntityId) -> None:
        entry = support_groups.setdefault(key.sort_key(), (key, []))
        if subject_id not in entry[1]:
            entry[1].append(subject_id)

    for relation in projection_input.semantic_relations:
        if relation.id.text not in evaluation.current_semantic_texts:
            continue
        for evidence in relation.evidence_ids:
            if not is_current(evidence):
                continue
            add_edge(
                RelationshipKey(
                    StructuralPredicate.SEMANTIC_SUPPORTED_BY,
                    relation.id,
                    evidence,
                ),
                relation.id,
            )

    for text in sorted(evaluation.current_texts):
        snapshot = evaluation.entity_by_text[text]
        pairs: list[tuple[StructuralPredicate, object]] = []
        if isinstance(snapshot, Publication):
            pairs.append((StructuralPredicate.PUBLICATION_OF, snapshot.work_id))
        elif isinstance(snapshot, Document):
            pairs.append((StructuralPredicate.DOCUMENT_OF, snapshot.publication_id))
        elif isinstance(snapshot, EvidencePassage):
            if isinstance(snapshot.source_id, DocumentId):
                pairs.append((StructuralPredicate.EVIDENCE_FROM, snapshot.source_id))
        elif isinstance(snapshot, Claim):
            pairs.append((StructuralPredicate.CLAIM_OF, snapshot.work_id))
            pairs.extend(
                (StructuralPredicate.CLAIM_SUPPORTED_BY, evidence)
                for evidence in snapshot.evidence_ids
            )
        elif isinstance(snapshot, Collection):
            pairs.extend(
                (StructuralPredicate.COLLECTION_CONTAINS, member) for member in snapshot.member_ids
            )
        elif isinstance(snapshot, Note):
            pairs.extend(
                (StructuralPredicate.NOTE_ATTACHED_TO, target)
                for target in snapshot.attached_entity_ids
            )
        elif isinstance(snapshot, TechnicalLineage):
            pairs.extend(
                (StructuralPredicate.LINEAGE_CONTAINS, member) for member in snapshot.member_ids
            )
        elif isinstance(snapshot, LineageSynthesis):
            pairs.append((StructuralPredicate.SYNTHESIS_OF, snapshot.lineage_id))
            pairs.extend(
                (StructuralPredicate.SYNTHESIS_CITES_CLAIM, claim) for claim in snapshot.claim_ids
            )
            pairs.extend(
                (StructuralPredicate.SYNTHESIS_CITES_EVIDENCE, evidence)
                for evidence in snapshot.evidence_ids
            )
        for predicate, target in pairs:
            if not is_current(cast("TypedId", target)):
                continue
            add_edge(
                RelationshipKey(
                    predicate,
                    snapshot.id,
                    cast("RelationshipEndpointId", target),
                ),
                snapshot.id,
            )

    relationships = tuple(
        ProjectedStructuralRelationship(
            key=key,
            supporting_subject_record_ids=tuple(sorted(set(ids), key=lambda item: item.text)),
        )
        for _, (key, ids) in sorted(support_groups.items())
    )
    excluded = tuple(
        StructuralExclusion(
            subject_id=snapshot.id,
            relationship_key=None,
            reason=evaluation.reasons[text],
        )
        for text, snapshot in sorted(evaluation.entity_by_text.items())
        if text in evaluation.reasons and not isinstance(snapshot.lifecycle, RedirectLifecycle)
    )
    excluded = tuple(sorted(excluded, key=lambda item: (item.reason.value, item.subject_id.text)))
    current_ids = tuple(
        sorted(
            (
                snapshot.id
                for text, snapshot in evaluation.entity_by_text.items()
                if text in evaluation.current_texts
            ),
            key=lambda item: item.text,
        )
    )
    return StructuralProjection(
        current_record_ids=current_ids,
        relationships=relationships,
        excluded=excluded,
    )


def _evidence_block_reason(
    evidence_id: EvidencePassageId,
    evaluation: _CurrentEvaluation,
) -> ProjectionExclusionReason | None:
    snapshot = evaluation.entity_by_text.get(evidence_id.text)
    if not isinstance(snapshot, EvidencePassage):
        raise DomainError(
            code="dangling_structural_reference",
            message=f"Evidence {evidence_id.text!r} does not exist in the entity index",
            context={
                "predicate": "claim_supported_by",
                "subject_id": evidence_id.text,
                "target_id": evidence_id.text,
            },
        )
    if isinstance(snapshot.lifecycle, TombstoneLifecycle):
        return ProjectionExclusionReason.TOMBSTONED_ENTITY
    if evidence_id.text in evaluation.current_texts:
        return None
    return ProjectionExclusionReason.TOMBSTONED_EVIDENCE_SOURCE


def _split_evidence(
    evidence_ids: tuple[EvidencePassageId, ...],
    evaluation: _CurrentEvaluation,
) -> tuple[tuple[EvidencePassageId, ...], tuple[GroundingExclusion, ...]]:
    current: list[EvidencePassageId] = []
    excluded: list[GroundingExclusion] = []
    for evidence_id in sorted(set(evidence_ids), key=lambda item: item.text):
        reason = _evidence_block_reason(evidence_id, evaluation)
        if reason is None:
            current.append(evidence_id)
        else:
            excluded.append(GroundingExclusion(evidence_id=evidence_id, reason=reason))
    return tuple(current), tuple(
        sorted(excluded, key=lambda item: (item.reason.value, item.evidence_id.text))
    )


def evaluate_claim_grounding(
    claim: Claim,
    projection_input: DomainProjectionInput,
) -> ClaimGroundingProjection:
    indexed = projection_input.entity_index.by_id.get(claim.id)
    if indexed is None:
        raise DomainError(
            code="dangling_structural_reference",
            message=f"Claim {claim.id.text!r} does not exist in the entity index",
            context={
                "predicate": StructuralPredicate.CLAIM_OF.value,
                "subject_id": claim.id.text,
                "target_id": claim.id.text,
            },
        )
    if indexed != claim:
        raise DomainError(
            code="record_input_mismatch",
            message=f"Claim {claim.id.text!r} differs from the indexed snapshot",
            context={"record_id": claim.id.text, "record_kind": "claim"},
        )
    evaluation = evaluate_current_set(projection_input)
    current_evidence, excluded_evidence = _split_evidence(claim.evidence_ids, evaluation)
    work_current = claim.work_id.text in evaluation.current_texts or (
        _terminal_map(projection_input).get(claim.work_id.text) in evaluation.current_texts
    )
    if not work_current:
        return ClaimGroundingProjection(
            claim_id=claim.id,
            status=GroundingStatus.EXCLUDED,
            current_evidence_ids=current_evidence,
            excluded_evidence=excluded_evidence,
            record_exclusion_reason=ProjectionExclusionReason.TOMBSTONED_ENDPOINT,
        )
    if not current_evidence:
        return ClaimGroundingProjection(
            claim_id=claim.id,
            status=GroundingStatus.EXCLUDED,
            current_evidence_ids=current_evidence,
            excluded_evidence=excluded_evidence,
            record_exclusion_reason=ProjectionExclusionReason.NO_CURRENT_EVIDENCE,
        )
    return ClaimGroundingProjection(
        claim_id=claim.id,
        status=GroundingStatus.CURRENT,
        current_evidence_ids=current_evidence,
        excluded_evidence=excluded_evidence,
        record_exclusion_reason=None,
    )


def evaluate_semantic_relation_grounding(
    relation: SemanticRelation,
    projection_input: DomainProjectionInput,
) -> SemanticRelationGroundingProjection:
    indexed = next(
        (item for item in projection_input.semantic_relations if item.id == relation.id), None
    )
    if indexed is None:
        raise DomainError(
            code="dangling_structural_reference",
            message=f"SemanticRelation {relation.id.text!r} is not part of the projection input",
            context={
                "predicate": relation.predicate.value,
                "subject_id": relation.id.text,
                "target_id": relation.id.text,
            },
        )
    if indexed != relation:
        raise DomainError(
            code="record_input_mismatch",
            message=f"SemanticRelation {relation.id.text!r} differs from the input record",
            context={"record_id": relation.id.text, "record_kind": "semantic_relation"},
        )
    retracted_texts = {retraction.target_id.text for retraction in projection_input.retractions}
    evaluation = evaluate_current_set(projection_input)
    terminals = _terminal_map(projection_input)
    current_evidence, excluded_evidence = _split_evidence(relation.evidence_ids, evaluation)
    subject_terminal = terminals.get(relation.subject_id.text, relation.subject_id.text)
    object_terminal = terminals.get(relation.object_id.text, relation.object_id.text)
    endpoints_current = (
        subject_terminal in evaluation.current_texts and object_terminal in evaluation.current_texts
    )
    record_reason: ProjectionExclusionReason | None
    if relation.id.text in retracted_texts:
        record_reason = ProjectionExclusionReason.RETRACTED
    elif not endpoints_current:
        record_reason = ProjectionExclusionReason.TOMBSTONED_ENDPOINT
    elif not current_evidence:
        record_reason = ProjectionExclusionReason.NO_CURRENT_EVIDENCE
    else:
        record_reason = None
    status = GroundingStatus.EXCLUDED if record_reason is not None else GroundingStatus.CURRENT
    return SemanticRelationGroundingProjection(
        semantic_relation_id=relation.id,
        status=status,
        current_evidence_ids=current_evidence,
        excluded_evidence=excluded_evidence,
        record_exclusion_reason=record_reason,
    )


def _projection_context(
    projection_input: DomainProjectionInput,
) -> tuple[
    _CurrentEvaluation,
    dict[str, str],
    dict[str, TypedId],
    set[str],
]:
    evaluation = evaluate_current_set(projection_input)
    terminals = _terminal_map(projection_input)
    ids_by_text: dict[str, TypedId] = {
        snapshot.id.text: snapshot.id for snapshot in projection_input.entity_index.by_id.values()
    }
    for relation in projection_input.semantic_relations:
        ids_by_text.setdefault(relation.id.text, relation.id)
    retracted = {retraction.target_id.text for retraction in projection_input.retractions}
    return evaluation, terminals, ids_by_text, retracted


def _sorted_support_ids(
    supports: Sequence[MetadataAssertion | RelationshipAssertion],
) -> tuple[ProjectionRecordId, ...]:
    ordered = sorted(supports, key=_assertion_display_sort_key)
    return tuple(cast("ProjectionRecordId", assertion.id) for assertion in ordered)


def _resolve_or_missing(
    contenders: list[ProjectionContender[_ValueT]],
    conflict_reason: ProjectionConflictReason | None,
) -> ProjectionResult[_ValueT]:
    if not contenders:
        return ProjectionResult(
            status=ProjectionStatus.MISSING,
            resolved_value=None,
            contenders=(),
            excluded=(),
            conflict_reason=None,
        )
    top_tier = max(
        (
            _authority_rank(contender.authority_tier)
            for contender in contenders
            if contender.authority_tier is not None
        ),
        default=-1,
    )
    top = [
        contender
        for contender in contenders
        if contender.authority_tier is not None
        and _authority_rank(contender.authority_tier) == top_tier
    ]
    if len(top) > 1:
        return ProjectionResult(
            status=ProjectionStatus.CONFLICTED,
            resolved_value=None,
            contenders=tuple(contenders),
            excluded=(),
            conflict_reason=conflict_reason,
        )
    return ProjectionResult(
        status=ProjectionStatus.RESOLVED,
        resolved_value=top[0].value,
        contenders=tuple(contenders),
        excluded=(),
        conflict_reason=None,
    )


def project_metadata(
    subject_id: KnowledgeEntityId,
    field: MetadataFieldKey,
    language_slot: LanguageTag | None,
    projection_input: DomainProjectionInput,
) -> ProjectionResult[AssertionValue]:
    spec = _metadata_field_spec(field)
    if spec.language_scoped and language_slot is None:
        raise _invalid_value_object(
            type_name="project_metadata",
            field_name="language_slot",
            reason="language-scoped fields require an explicit language slot",
        )
    if not spec.language_scoped and language_slot is not None:
        raise _invalid_value_object(
            type_name="project_metadata",
            field_name="language_slot",
            reason="non-language-scoped fields must not receive a language slot",
        )
    evaluation, terminals, _, retracted = _projection_context(projection_input)
    subject_terminal = terminals.get(subject_id.text, subject_id.text)
    matching = [
        assertion
        for assertion in projection_input.metadata_assertions
        if assertion.field is field
        and terminals.get(assertion.subject_id.text, assertion.subject_id.text) == subject_terminal
    ]

    def matches_slot(assertion: MetadataAssertion) -> bool:
        if spec.language_scoped and isinstance(assertion.value, TextAssertionValue):
            return language_slot is not None and (
                assertion.value.language.text == language_slot.text
            )
        return True

    groups: dict[str, tuple[AssertionValue, list[MetadataAssertion]]] = {}
    for assertion in matching:
        if assertion.id.text in retracted or not matches_slot(assertion):
            continue
        entry = groups.setdefault(assertion.value.sort_key().__str__(), (assertion.value, []))
        entry[1].append(assertion)

    def tier_of(assertions: list[MetadataAssertion]) -> int:
        return max(
            _authority_rank(_origin_authority_tier(assertion.origin)) for assertion in assertions
        )

    contenders = [
        ProjectionContender(
            value=value,
            authority_tier=AuthorityTier.HUMAN_CORRECTION
            if tier == _authority_rank(AuthorityTier.HUMAN_CORRECTION)
            else AuthorityTier.AUTHORITATIVE_SOURCE
            if tier == _authority_rank(AuthorityTier.AUTHORITATIVE_SOURCE)
            else AuthorityTier.AGGREGATOR,
            supporting_record_ids=_sorted_support_ids(supports),
        )
        for value, supports in groups.values()
        for tier in (tier_of(supports),)
    ]
    contenders.sort(
        key=lambda contender: (
            -_authority_rank(contender.authority_tier)
            if contender.authority_tier is not None
            else 0,
            str(contender.value.sort_key()),
        )
    )

    excluded: list[ProjectionExclusion] = [
        ProjectionExclusion(
            record_id=cast("ProjectionRecordId", assertion.id),
            reason=(
                ProjectionExclusionReason.RETRACTED
                if assertion.id.text in retracted
                else ProjectionExclusionReason.TOMBSTONED_ENTITY
            ),
        )
        for assertion in matching
        if assertion.id.text in retracted or subject_terminal not in evaluation.current_texts
    ]
    excluded.sort(key=lambda item: (item.reason.value, item.record_id.text))
    if subject_terminal not in evaluation.current_texts:
        return ProjectionResult(
            status=ProjectionStatus.MISSING,
            resolved_value=None,
            contenders=(),
            excluded=tuple(excluded),
            conflict_reason=None,
        )
    result = _resolve_or_missing(contenders, ProjectionConflictReason.SAME_TIER_VALUE_CONFLICT)
    return ProjectionResult(
        status=result.status,
        resolved_value=result.resolved_value,
        contenders=result.contenders,
        excluded=tuple(excluded),
        conflict_reason=result.conflict_reason,
    )


def project_relationship_slot(
    subject_id: RelationshipEndpointId,
    predicate: FactualPredicate,
    projection_input: DomainProjectionInput,
) -> ProjectionResult[RelationshipEndpointId]:
    spec = PREDICATE_REGISTRY.get(predicate)
    if (
        spec is None
        or spec.kind is not PredicateKind.FACTUAL
        or (spec.subject_cardinality is not Cardinality.ZERO_OR_ONE)
    ):
        raise DomainError(
            code="projection_slot_not_supported",
            message=(
                f"project_relationship_slot only supports factual predicates with "
                f"0..1 subject cardinality, got {predicate.value!r}"
            ),
            context={
                "predicate": predicate.value,
                "subject_cardinality": spec.subject_cardinality.value if spec else "unknown",
            },
        )
    evaluation, terminals, ids_by_text, retracted = _projection_context(projection_input)
    subject_terminal = terminals.get(subject_id.text, subject_id.text)

    def object_current(assertion: RelationshipAssertion) -> bool:
        object_terminal = terminals.get(assertion.object_id.text, assertion.object_id.text)
        return object_terminal in evaluation.current_texts

    matching = [
        assertion
        for assertion in projection_input.relationship_assertions
        if assertion.predicate is predicate
        and terminals.get(assertion.subject_id.text, assertion.subject_id.text) == subject_terminal
    ]
    excluded = [
        ProjectionExclusion(
            record_id=cast("ProjectionRecordId", assertion.id),
            reason=ProjectionExclusionReason.RETRACTED,
        )
        for assertion in matching
        if assertion.id.text in retracted
    ]
    groups: dict[str, list[RelationshipAssertion]] = {}
    for assertion in matching:
        if assertion.id.text in retracted or not object_current(assertion):
            continue
        object_terminal = terminals.get(assertion.object_id.text, assertion.object_id.text)
        entry = groups.setdefault(object_terminal, [])
        entry.append(assertion)
    contenders: list[ProjectionContender[RelationshipEndpointId]] = []
    for object_terminal, supports in sorted(groups.items()):
        tier = max(_authority_rank(_origin_authority_tier(a.origin)) for a in supports)
        contenders.append(
            ProjectionContender(
                value=cast("RelationshipEndpointId", ids_by_text[object_terminal]),
                authority_tier=_tier_from_rank(tier),
                supporting_record_ids=_sorted_support_ids(supports),
            )
        )
    contenders.sort(
        key=lambda item: (
            -(_authority_rank(item.authority_tier) if item.authority_tier else 0),
            str(item.value.sort_key()),
        )
    )
    result = _resolve_or_missing(contenders, ProjectionConflictReason.MAX_ONE_CONFLICT)
    return ProjectionResult(
        status=result.status,
        resolved_value=result.resolved_value,
        contenders=result.contenders,
        excluded=tuple(sorted(excluded, key=lambda item: item.record_id.text)),
        conflict_reason=result.conflict_reason,
    )


def _tier_from_rank(rank: int) -> AuthorityTier:
    if rank >= _authority_rank(AuthorityTier.HUMAN_CORRECTION):
        return AuthorityTier.HUMAN_CORRECTION
    if rank >= _authority_rank(AuthorityTier.AUTHORITATIVE_SOURCE):
        return AuthorityTier.AUTHORITATIVE_SOURCE
    return AuthorityTier.AGGREGATOR


def project_identifier_owner(
    key: IdentifierKey,
    projection_input: DomainProjectionInput,
) -> ProjectionResult[KnowledgeEntityId]:
    evaluation, terminals, ids_by_text, retracted = _projection_context(projection_input)
    identifier_terms = {
        terminals.get(snapshot.id.text, snapshot.id.text)
        for snapshot in projection_input.entity_index.by_id.values()
        if isinstance(snapshot, Identifier) and snapshot.key == key
    }
    active_terms = {term for term in identifier_terms if term in evaluation.current_texts}
    if len(active_terms) > 1:
        return ProjectionResult(
            status=ProjectionStatus.CONFLICTED,
            resolved_value=None,
            contenders=(),
            excluded=(),
            conflict_reason=ProjectionConflictReason.DUPLICATE_IDENTIFIER_RECORD,
        )
    if len(active_terms) != 1:
        return ProjectionResult(
            status=ProjectionStatus.MISSING,
            resolved_value=None,
            contenders=(),
            excluded=(),
            conflict_reason=None,
        )
    identifier_term = next(iter(active_terms))
    groups: dict[str, list[RelationshipAssertion]] = {}
    for assertion in projection_input.relationship_assertions:
        if assertion.predicate is not FactualPredicate.HAS_IDENTIFIER:
            continue
        if assertion.id.text in retracted:
            continue
        object_terminal = terminals.get(assertion.object_id.text, assertion.object_id.text)
        if object_terminal != identifier_term:
            continue
        subject_terminal = terminals.get(assertion.subject_id.text, assertion.subject_id.text)
        if subject_terminal not in evaluation.current_texts:
            continue
        groups.setdefault(subject_terminal, []).append(assertion)
    contenders: list[ProjectionContender[KnowledgeEntityId]] = []
    for subject_terminal, supports in sorted(groups.items()):
        tier = max(_authority_rank(_origin_authority_tier(a.origin)) for a in supports)
        contenders.append(
            ProjectionContender(
                value=cast("KnowledgeEntityId", ids_by_text[subject_terminal]),
                authority_tier=_tier_from_rank(tier),
                supporting_record_ids=_sorted_support_ids(supports),
            )
        )
    contenders.sort(
        key=lambda item: (
            -(_authority_rank(item.authority_tier) if item.authority_tier else 0),
            str(item.value.sort_key()),
        )
    )
    return _resolve_or_missing(contenders, ProjectionConflictReason.IDENTIFIER_OWNER_CONFLICT)


def _review_support_sort_key(relation: SemanticRelation) -> tuple[object, ...]:
    review = relation.accepted_review
    return (
        "review",
        review.candidate_id.text,
        review.candidate_revision,
        review.actor,
        review.review_event_reference,
        review.payload_digest.text,
    )


@dataclass
class _RelationshipEntry:
    key: RelationshipKey
    supports: list[_RelationshipSupportId] = field(default_factory=list)
    semantic_supports: list[SemanticEvidenceSupport] = field(default_factory=list)
    excluded: list[ProjectionExclusion] = field(default_factory=list)
    conflict: ProjectionConflictReason | None = None


def project_relationships(
    predicate: FactualPredicate | ReviewedSemanticPredicate,
    projection_input: DomainProjectionInput,
) -> tuple[ProjectedRelationship, ...]:
    spec = PREDICATE_REGISTRY[predicate]
    evaluation, terminals, ids_by_text, retracted = _projection_context(projection_input)
    entries: dict[tuple[str, str, str], _RelationshipEntry] = {}

    def terminal_id(entity_id: RelationshipEndpointId) -> TypedId:
        text = terminals.get(entity_id.text, entity_id.text)
        return ids_by_text[text]

    def entry_for(key_sort: tuple[str, str, str], key: RelationshipKey) -> _RelationshipEntry:
        return entries.setdefault(key_sort, _RelationshipEntry(key=key))

    if isinstance(predicate, FactualPredicate):
        per_subject_tiers: dict[str, dict[int, set[str]]] = {}
        edge_assertions: list[tuple[RelationshipKey, RelationshipAssertion]] = []
        for assertion in projection_input.relationship_assertions:
            if assertion.predicate is not predicate:
                continue
            if assertion.id.text in retracted:
                continue
            subject_ok = (
                terminals.get(assertion.subject_id.text, assertion.subject_id.text)
                in evaluation.current_texts
            )
            object_ok = (
                terminals.get(assertion.object_id.text, assertion.object_id.text)
                in evaluation.current_texts
            )
            if not (subject_ok and object_ok):
                continue
            key = RelationshipKey(
                predicate,
                cast("RelationshipEndpointId", terminal_id(assertion.subject_id)),
                cast("RelationshipEndpointId", terminal_id(assertion.object_id)),
            )
            edge_assertions.append((key, assertion))
            if spec.object_cardinality is Cardinality.ZERO_OR_ONE:
                subject_text = key.sort_key()[1]
                tiers = per_subject_tiers.setdefault(subject_text, {})
                tiers.setdefault(
                    _authority_rank(_origin_authority_tier(assertion.origin)), set()
                ).add(key.sort_key()[2])
        conflicted_objects: set[str] = set()
        if spec.object_cardinality is Cardinality.ZERO_OR_ONE:
            for tiers in per_subject_tiers.values():
                top = max(tiers)
                if len(tiers[top]) > 1:
                    conflicted_objects.update(tiers[top])
        cycle_keys: set[tuple[str, str, str]] = set()
        if spec.acyclic:
            adjacency: dict[str, set[str]] = {}
            edge_lookup: dict[tuple[str, str], tuple[str, str, str]] = {}
            for key, _ in edge_assertions:
                _, subject_text, object_text = key.sort_key()
                if subject_text == object_text:
                    cycle_keys.add(key.sort_key())
                    continue
                adjacency.setdefault(subject_text, set()).add(object_text)
                edge_lookup[(subject_text, object_text)] = key.sort_key()
            cycle_nodes = _cycle_nodes(adjacency)
            for (subject_text, object_text), key_sort in edge_lookup.items():
                if subject_text in cycle_nodes and object_text in cycle_nodes:
                    cycle_keys.add(key_sort)
        grouped: dict[tuple[str, str, str], list[RelationshipAssertion]] = {}
        keys_by_sort: dict[tuple[str, str, str], RelationshipKey] = {}
        for key, assertion in edge_assertions:
            grouped.setdefault(key.sort_key(), []).append(assertion)
            keys_by_sort[key.sort_key()] = key
        for key_sort, supports in sorted(grouped.items()):
            entry = entry_for(key_sort, keys_by_sort[key_sort])
            if key_sort[2] in conflicted_objects:
                entry.conflict = ProjectionConflictReason.MAX_ONE_CONFLICT
            if key_sort in cycle_keys:
                entry.conflict = ProjectionConflictReason.ACYCLIC_CYCLE
            entry.supports = [item.id for item in sorted(supports, key=_assertion_display_sort_key)]
        for assertion in projection_input.relationship_assertions:
            if assertion.predicate is not predicate:
                continue
            if assertion.id.text not in retracted:
                subject_ok = (
                    terminals.get(assertion.subject_id.text, assertion.subject_id.text)
                    in evaluation.current_texts
                )
                object_ok = (
                    terminals.get(assertion.object_id.text, assertion.object_id.text)
                    in evaluation.current_texts
                )
                if subject_ok and object_ok:
                    continue
            candidate_sort: tuple[str, str, str] | None = None
            for candidate_key, candidate_assertion in edge_assertions:
                if candidate_assertion.id == assertion.id:
                    candidate_sort = candidate_key.sort_key()
                    break
            reason = (
                ProjectionExclusionReason.RETRACTED
                if assertion.id.text in retracted
                else ProjectionExclusionReason.TOMBSTONED_ENDPOINT
            )
            if candidate_sort is not None:
                entry_for(candidate_sort, keys_by_sort[candidate_sort]).excluded.append(
                    ProjectionExclusion(
                        record_id=cast("ProjectionRecordId", assertion.id),
                        reason=reason,
                    )
                )
    else:
        grouped_relations: dict[tuple[str, str, str], list[SemanticRelation]] = {}
        semantic_keys_by_sort: dict[tuple[str, str, str], RelationshipKey] = {}
        for relation in projection_input.semantic_relations:
            if relation.predicate is not predicate:
                continue
            subject_terminal = terminal_id(cast("RelationshipEndpointId", relation.subject_id))
            object_terminal = terminal_id(cast("RelationshipEndpointId", relation.object_id))
            key = RelationshipKey(
                predicate,
                cast("KnowledgeEntityId", subject_terminal),
                cast("KnowledgeEntityId", object_terminal),
            )
            semantic_keys_by_sort[key.sort_key()] = key
            entry = entry_for(key.sort_key(), key)
            if relation.id.text in retracted:
                entry.excluded.append(
                    ProjectionExclusion(
                        record_id=relation.id,
                        reason=ProjectionExclusionReason.RETRACTED,
                    )
                )
                continue
            grounding = evaluate_semantic_relation_grounding(relation, projection_input)
            if (
                grounding.record_exclusion_reason is not None
                and grounding.status is GroundingStatus.EXCLUDED
            ):
                entry.excluded.append(
                    ProjectionExclusion(
                        record_id=relation.id,
                        reason=grounding.record_exclusion_reason,
                    )
                )
                continue
            if subject_terminal == object_terminal:
                entry.conflict = ProjectionConflictReason.IRREFLEXIVE_AFTER_REDIRECT
                continue
            grouped_relations.setdefault(key.sort_key(), []).append(relation)
        if spec.acyclic and grouped_relations:
            semantic_adjacency: dict[str, set[str]] = {}
            for key_sort in grouped_relations:
                _, subject_text, object_text = key_sort
                if subject_text == object_text:
                    continue
                semantic_adjacency.setdefault(subject_text, set()).add(object_text)
            semantic_cycle_nodes = _cycle_nodes(semantic_adjacency)
            for key_sort in grouped_relations:
                _, subject_text, object_text = key_sort
                if subject_text in semantic_cycle_nodes and object_text in semantic_cycle_nodes:
                    entry_for(
                        key_sort, semantic_keys_by_sort[key_sort]
                    ).conflict = ProjectionConflictReason.ACYCLIC_CYCLE
        for key_sort, relations in sorted(grouped_relations.items()):
            entry = entry_for(key_sort, semantic_keys_by_sort[key_sort])
            ordered = sorted(relations, key=_review_support_sort_key)
            entry.supports = [relation.id for relation in ordered]
            entry.semantic_supports = [
                SemanticEvidenceSupport(
                    semantic_relation_id=relation.id,
                    current_evidence_ids=_relation_current_evidence(relation, projection_input),
                )
                for relation in ordered
            ]

    results: list[ProjectedRelationship] = []
    for key_sort in sorted(entries):
        entry = entries[key_sort]
        has_support = bool(entry.supports) or bool(entry.semantic_supports)
        status = (
            ProjectionStatus.CONFLICTED
            if entry.conflict is not None
            else ProjectionStatus.RESOLVED
            if has_support
            else ProjectionStatus.MISSING
        )
        results.append(
            ProjectedRelationship(
                key=entry.key,
                status=status,
                supporting_record_ids=tuple(entry.supports),
                semantic_evidence_support=tuple(entry.semantic_supports),
                excluded=tuple(entry.excluded),
                conflict_reason=entry.conflict,
            )
        )
    return tuple(results)


def _relation_current_evidence(
    relation: SemanticRelation, projection_input: DomainProjectionInput
) -> tuple[EvidencePassageId, ...]:
    grounding = evaluate_semantic_relation_grounding(relation, projection_input)
    return grounding.current_evidence_ids


def _cycle_nodes(adjacency: dict[str, set[str]]) -> set[str]:
    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    cycle_nodes: set[str] = set()

    def strongconnect(node: str) -> None:
        nonlocal index_counter
        indices[node] = index_counter
        lowlinks[node] = index_counter
        index_counter += 1
        stack.append(node)
        on_stack.add(node)
        for successor in sorted(adjacency.get(node, ())):
            if successor not in indices:
                strongconnect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                cycle_nodes.update(component)

    for node in sorted(adjacency):
        if node not in indices:
            strongconnect(node)
    return cycle_nodes


def confirm_claim(
    claim_id: ClaimId,
    work_id: WorkId,
    statement: str,
    language: LanguageTag,
    evidence_ids: Iterable[EvidencePassageId],
    accepted_review: AcceptedReviewAttestation,
    confirmed_at: UtcInstant,
    projection_input: DomainProjectionInput,
) -> Claim:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    _require_field_type(claim_id, claim_id, ClaimId, field_name="claim_id")
    _require_field_type(work_id, work_id, WorkId, field_name="work_id")
    review = accepted_review
    if type(review) is not AcceptedReviewAttestation:
        raise _invalid_value_object(
            type_name="confirm_claim",
            field_name="accepted_review",
            reason="value must be an AcceptedReviewAttestation",
        )
    if review.action is not ReviewAction.CONFIRM_CLAIM:
        raise _attestation_action_mismatch(
            "confirm_claim",
            (claim_id.text,),
            ReviewAction.CONFIRM_CLAIM.value,
            review.action.value,
        )
    binding = ClaimReviewBinding(
        work_id=work_id,
        statement=statement,
        language=language,
        evidence_ids=tuple(evidence_ids),
    )
    computed = compute_review_payload_digest(binding)
    if not _content_digests_equal(computed, review.payload_digest):
        raise _attestation_payload_mismatch(
            "confirm_claim",
            (claim_id.text,),
            review.payload_digest.text,
            computed.text,
        )
    _require_field_type(confirmed_at, confirmed_at, UtcInstant, field_name="confirmed_at")
    if confirmed_at < review.accepted_at:
        raise _attestation_time_invalid(
            "confirm_claim",
            (claim_id.text,),
            review.accepted_at.text,
            confirmed_at.text,
        )
    entity_index = projection_input.entity_index
    _active_subject_check(
        work_id,
        entity_index,
        display_predicate=StructuralPredicate.CLAIM_OF.value,
        creator_text=claim_id.text,
        record_kind="claim",
    )
    for evidence_id in binding.evidence_ids:
        snapshot = entity_index.by_id.get(evidence_id)
        if not isinstance(snapshot, EvidencePassage):
            raise DomainError(
                code="dangling_structural_reference",
                message=f"Claim {claim_id.text!r} references missing evidence {evidence_id.text!r}",
                context={
                    "predicate": StructuralPredicate.CLAIM_SUPPORTED_BY.value,
                    "subject_id": claim_id.text,
                    "target_id": evidence_id.text,
                },
            )
        resolution = resolve_terminal(evidence_id, entity_index)
        if len(resolution.path) > 1:
            raise DomainError(
                code="noncanonical_write_endpoint",
                message=(
                    f"Claim {claim_id.text!r} must reference active terminal "
                    f"{resolution.terminal_id.text!r} instead of {evidence_id.text!r}"
                ),
                context={
                    "endpoint_id": evidence_id.text,
                    "terminal_id": resolution.terminal_id.text,
                    "record_kind": "claim",
                },
            )
        if isinstance(resolution.terminal_lifecycle, TombstoneLifecycle):
            raise DomainError(
                code="entity_not_active",
                message=f"Evidence {resolution.terminal_id.text!r} is tombstoned",
                context={
                    "entity_id": resolution.terminal_id.text,
                    "lifecycle": resolution.terminal_lifecycle.tag,
                },
            )
    return Claim(
        id=claim_id,
        work_id=work_id,
        statement=binding.statement,
        language=binding.language,
        evidence_ids=binding.evidence_ids,
        accepted_review=review,
        confirmed_at=confirmed_at,
        lifecycle=ActiveLifecycle(),
    )


def confirm_semantic_relation(
    relation_id: SemanticRelationId,
    predicate: ReviewedSemanticPredicate,
    subject_id: KnowledgeEntityId,
    object_id: KnowledgeEntityId,
    evidence_ids: Iterable[EvidencePassageId],
    accepted_review: AcceptedReviewAttestation,
    confirmed_at: UtcInstant,
    projection_input: DomainProjectionInput,
) -> SemanticRelation:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    _require_field_type(relation_id, relation_id, SemanticRelationId, field_name="relation_id")
    review = accepted_review
    if type(review) is not AcceptedReviewAttestation:
        raise _invalid_value_object(
            type_name="confirm_semantic_relation",
            field_name="accepted_review",
            reason="value must be an AcceptedReviewAttestation",
        )
    if review.action is not ReviewAction.CONFIRM_SEMANTIC_RELATION:
        raise _attestation_action_mismatch(
            "confirm_semantic_relation",
            (relation_id.text,),
            ReviewAction.CONFIRM_SEMANTIC_RELATION.value,
            review.action.value,
        )
    canonical_subject, canonical_object = canonicalize_relationship(
        predicate, subject_id, object_id
    )
    knowledge_subject = cast("KnowledgeEntityId", canonical_subject)
    knowledge_object = cast("KnowledgeEntityId", canonical_object)
    binding = SemanticRelationReviewBinding(
        predicate=predicate,
        subject_id=knowledge_subject,
        object_id=knowledge_object,
        evidence_ids=tuple(evidence_ids),
    )
    computed = compute_review_payload_digest(binding)
    if not _content_digests_equal(computed, review.payload_digest):
        raise _attestation_payload_mismatch(
            "confirm_semantic_relation",
            (relation_id.text,),
            review.payload_digest.text,
            computed.text,
        )
    _require_field_type(confirmed_at, confirmed_at, UtcInstant, field_name="confirmed_at")
    if confirmed_at < review.accepted_at:
        raise _attestation_time_invalid(
            "confirm_semantic_relation",
            (relation_id.text,),
            review.accepted_at.text,
            confirmed_at.text,
        )
    entity_index = projection_input.entity_index
    for endpoint in (canonical_subject, canonical_object):
        if isinstance(endpoint, SourceRecordId):
            continue
        _active_subject_check(
            endpoint,
            entity_index,
            display_predicate=predicate.value,
            creator_text=relation_id.text,
            record_kind="semantic_relation",
        )
    return SemanticRelation(
        id=relation_id,
        predicate=predicate,
        subject_id=knowledge_subject,
        object_id=knowledge_object,
        evidence_ids=binding.evidence_ids,
        accepted_review=review,
        confirmed_at=confirmed_at,
    )


def _merge_basis_invalid(
    survivor: MergeableEntitySnapshot,
    loser: MergeableEntitySnapshot,
    reason: str,
) -> DomainError:
    return DomainError(
        code="merge_basis_invalid",
        message=f"Merge basis does not match the merge inputs: {reason}",
        context={
            "survivor_id": survivor.id.text,
            "loser_id": loser.id.text,
            "reason": reason,
        },
    )


@dataclass(frozen=True, slots=True)
class DuplicateIdentifierBasis:
    identifier_key: IdentifierKey
    accepted_operation: AcceptedOperationAttestation

    @classmethod
    def create(
        cls,
        identifier_key: IdentifierKey,
        accepted_operation: AcceptedOperationAttestation,
    ) -> DuplicateIdentifierBasis:
        _require_field_type(
            identifier_key, identifier_key, IdentifierKey, field_name="identifier_key"
        )
        _require_field_type(
            accepted_operation,
            accepted_operation,
            AcceptedOperationAttestation,
            field_name="accepted_operation",
        )
        if accepted_operation.action is not OperationAction.MERGE_EXACT_IDENTITY:
            raise _attestation_action_mismatch(
                "merge_exact_identity",
                (),
                OperationAction.MERGE_EXACT_IDENTITY.value,
                accepted_operation.action.value,
            )
        return cls(identifier_key=identifier_key, accepted_operation=accepted_operation)


@dataclass(frozen=True, slots=True)
class SharedIdentifierBasis:
    identifier_key: IdentifierKey
    survivor_assertion_id: RelationshipAssertionId
    loser_assertion_id: RelationshipAssertionId
    accepted_operation: AcceptedOperationAttestation

    @classmethod
    def create(
        cls,
        identifier_key: IdentifierKey,
        survivor_assertion_id: RelationshipAssertionId,
        loser_assertion_id: RelationshipAssertionId,
        accepted_operation: AcceptedOperationAttestation,
    ) -> SharedIdentifierBasis:
        _require_field_type(
            identifier_key, identifier_key, IdentifierKey, field_name="identifier_key"
        )
        _require_field_type(
            survivor_assertion_id,
            survivor_assertion_id,
            RelationshipAssertionId,
            field_name="survivor_assertion_id",
        )
        _require_field_type(
            loser_assertion_id,
            loser_assertion_id,
            RelationshipAssertionId,
            field_name="loser_assertion_id",
        )
        _require_field_type(
            accepted_operation,
            accepted_operation,
            AcceptedOperationAttestation,
            field_name="accepted_operation",
        )
        if accepted_operation.action is not OperationAction.MERGE_EXACT_IDENTITY:
            raise _attestation_action_mismatch(
                "merge_exact_identity",
                (),
                OperationAction.MERGE_EXACT_IDENTITY.value,
                accepted_operation.action.value,
            )
        return cls(
            identifier_key=identifier_key,
            survivor_assertion_id=survivor_assertion_id,
            loser_assertion_id=loser_assertion_id,
            accepted_operation=accepted_operation,
        )


@dataclass(frozen=True, slots=True)
class ReviewedFuzzyMergeBasis:
    survivor_id: MergeableEntityId
    loser_id: MergeableEntityId
    accepted_review: AcceptedReviewAttestation

    @classmethod
    def create(
        cls,
        survivor_id: MergeableEntityId,
        loser_id: MergeableEntityId,
        accepted_review: AcceptedReviewAttestation,
    ) -> ReviewedFuzzyMergeBasis:
        _require_mergeable_id(survivor_id, field_name="survivor_id")
        _require_mergeable_id(loser_id, field_name="loser_id")
        if type(accepted_review) is not AcceptedReviewAttestation:
            raise _invalid_value_object(
                type_name="ReviewedFuzzyMergeBasis",
                field_name="accepted_review",
                reason="value must be an AcceptedReviewAttestation",
            )
        if accepted_review.action is not ReviewAction.MERGE_FUZZY:
            raise _attestation_action_mismatch(
                "merge_fuzzy",
                (survivor_id.text, loser_id.text),
                ReviewAction.MERGE_FUZZY.value,
                accepted_review.action.value,
            )
        binding = FuzzyMergeReviewBinding(survivor_id=survivor_id, loser_id=loser_id)
        computed = compute_review_payload_digest(binding)
        if not _content_digests_equal(computed, accepted_review.payload_digest):
            raise _attestation_payload_mismatch(
                "merge_fuzzy",
                (survivor_id.text, loser_id.text),
                accepted_review.payload_digest.text,
                computed.text,
            )
        return cls(
            survivor_id=survivor_id,
            loser_id=loser_id,
            accepted_review=accepted_review,
        )


def _require_mergeable_id(value: object, *, field_name: str) -> None:
    if not isinstance(value, get_args(MergeableEntityId)):
        raise _invalid_value_object(
            type_name="MergeableEntityId",
            field_name=field_name,
            reason="value is not a mergeable typed entity ID",
        )


ExactIdentityMergeBasis: TypeAlias = DuplicateIdentifierBasis | SharedIdentifierBasis
MergeBasis: TypeAlias = ExactIdentityMergeBasis | ReviewedFuzzyMergeBasis


def _basis_attestation(
    basis: MergeBasis,
) -> AcceptedOperationAttestation | AcceptedReviewAttestation:
    if isinstance(basis, ReviewedFuzzyMergeBasis):
        return basis.accepted_review
    return basis.accepted_operation


@dataclass(frozen=True, slots=True)
class MergeResult:
    survivor: MergeableEntitySnapshot
    redirected_loser: MergeableEntitySnapshot
    basis: MergeBasis
    merged_at: UtcInstant


def merge_entities(
    survivor: MergeableEntitySnapshot,
    loser: MergeableEntitySnapshot,
    basis: MergeBasis,
    merged_at: UtcInstant,
    projection_input: DomainProjectionInput,
) -> MergeResult:
    _require_entity_index(projection_input.entity_index)
    _require_source_record_index(projection_input.source_record_index)
    for entity in (survivor, loser):
        if not isinstance(entity, get_args(MergeableEntitySnapshot)):
            raise DomainError(
                code="merge_not_supported",
                message=f"Entity kind {type(entity).__name__!r} does not support merges",
                context={"entity_kind": type(entity).__name__},
            )
    if survivor.id == loser.id:
        raise DomainError(
            code="merge_self",
            message=f"Entity {survivor.id.text!r} cannot merge with itself",
            context={"entity_id": survivor.id.text},
        )
    if type(survivor) is not type(loser):
        raise DomainError(
            code="entity_type_mismatch",
            message=(
                f"Merge requires the same concrete entity type, got "
                f"{type(survivor).__name__!r} and {type(loser).__name__!r}"
            ),
            context={"left_kind": type(survivor).__name__, "right_kind": type(loser).__name__},
        )
    entity_index = projection_input.entity_index
    for entity in (survivor, loser):
        indexed = entity_index.by_id.get(entity.id)
        if indexed is None or indexed != entity:
            raise DomainError(
                code="record_input_mismatch",
                message=f"Entity {entity.id.text!r} does not match the unique indexed snapshot",
                context={
                    "record_id": entity.id.text,
                    "record_kind": _SNAPSHOT_KINDS[type(entity)].value,
                },
            )
        if not isinstance(entity.lifecycle, ActiveLifecycle):
            raise DomainError(
                code="entity_not_active",
                message=f"Entity {entity.id.text!r} is not active",
                context={"entity_id": entity.id.text, "lifecycle": entity.lifecycle.tag},
            )
    attestation = _basis_attestation(basis)
    _require_field_type(merged_at, merged_at, UtcInstant, field_name="merged_at")
    if merged_at < attestation.accepted_at:
        raise _attestation_time_invalid(
            "merge",
            (survivor.id.text, loser.id.text),
            attestation.accepted_at.text,
            merged_at.text,
        )
    supporting_assertions: tuple[RelationshipAssertionId, ...] = ()
    if isinstance(basis, (DuplicateIdentifierBasis, SharedIdentifierBasis)):
        operation = basis.accepted_operation
        identifier_key = basis.identifier_key
        if isinstance(basis, DuplicateIdentifierBasis):
            if not isinstance(survivor, Identifier) or not isinstance(loser, Identifier):
                raise _merge_basis_invalid(
                    survivor, loser, "duplicate identifier basis requires two Identifier entities"
                )
            if survivor.key != basis.identifier_key or loser.key != basis.identifier_key:
                raise DomainError(
                    code="merge_identifier_key_mismatch",
                    message="Duplicate identifier merge requires identical IdentifierKeys",
                    context={
                        "survivor_key": survivor.key.normalized_value,
                        "loser_key": loser.key.normalized_value,
                    },
                )
        else:
            if isinstance(survivor, Identifier):
                raise _merge_basis_invalid(
                    survivor, loser, "shared identifier basis cannot merge Identifier entities"
                )
            assertion_map = {item.id: item for item in projection_input.relationship_assertions}
            retracted_texts = {item.target_id.text for item in projection_input.retractions}
            terminals = _terminal_map(projection_input)
            supporting_assertions = tuple(
                sorted(
                    (basis.survivor_assertion_id, basis.loser_assertion_id),
                    key=lambda item: item.text,
                )
            )
            expected_subjects = (
                terminals.get(survivor.id.text, survivor.id.text),
                terminals.get(loser.id.text, loser.id.text),
            )
            seen_identifier_terms: set[str] = set()
            for assertion_id, expected_subject in zip(
                (basis.survivor_assertion_id, basis.loser_assertion_id),
                expected_subjects,
                strict=True,
            ):
                assertion = assertion_map.get(assertion_id)
                if assertion is None or assertion.predicate is not FactualPredicate.HAS_IDENTIFIER:
                    raise _merge_basis_invalid(
                        survivor,
                        loser,
                        f"supporting assertion {assertion_id.text!r} is not a has_identifier edge",
                    )
                if assertion_id.text in retracted_texts:
                    raise _merge_basis_invalid(
                        survivor,
                        loser,
                        f"supporting assertion {assertion_id.text!r} is retracted",
                    )
                subject_terminal = terminals.get(
                    assertion.subject_id.text, assertion.subject_id.text
                )
                object_terminal = terminals.get(assertion.object_id.text, assertion.object_id.text)
                if subject_terminal != expected_subject:
                    raise _merge_basis_invalid(
                        survivor,
                        loser,
                        f"supporting assertion {assertion_id.text!r} subject mismatch",
                    )
                seen_identifier_terms.add(object_terminal)
                assert_identifier_target_compatible(
                    basis.identifier_key,
                    cast(
                        "KnowledgeEntityId", terminal_id_of(projection_input, assertion.subject_id)
                    ),
                )
            if len(seen_identifier_terms) != 1:
                raise _merge_basis_invalid(
                    survivor,
                    loser,
                    "supporting assertions do not point at one shared active Identifier terminal",
                )
            identifier_term = next(iter(seen_identifier_terms))
            identifier_id = ids_by_text(projection_input)[identifier_term]
            identifier_snapshot = (
                entity_index.by_id.get(cast("LifecycleEntityId", identifier_id))
                if isinstance(identifier_id, get_args(LifecycleEntityId))
                else None
            )
            if not isinstance(identifier_snapshot, Identifier) or (
                identifier_term not in evaluate_current_set(projection_input).current_texts
            ):
                raise _merge_basis_invalid(
                    survivor,
                    loser,
                    "the shared Identifier terminal is missing or not current",
                )
        binding = ExactMergeOperationBinding(
            survivor_id=survivor.id,
            loser_id=loser.id,
            identifier_key=identifier_key,
            supporting_assertion_ids=supporting_assertions,
            merged_at=merged_at,
        )
        computed = compute_operation_payload_digest(binding)
        if not _content_digests_equal(computed, operation.payload_digest):
            raise _attestation_payload_mismatch(
                "merge_exact_identity",
                (survivor.id.text, loser.id.text),
                operation.payload_digest.text,
                computed.text,
            )
    else:
        binding_review = FuzzyMergeReviewBinding(survivor_id=survivor.id, loser_id=loser.id)
        computed = compute_review_payload_digest(binding_review)
        if not _content_digests_equal(computed, basis.accepted_review.payload_digest):
            raise _attestation_payload_mismatch(
                "merge_fuzzy",
                (survivor.id.text, loser.id.text),
                basis.accepted_review.payload_digest.text,
                computed.text,
            )
    if isinstance(survivor, Publication):
        loser_publication = cast("Publication", loser)
        survivor_work = resolve_terminal(survivor.work_id, entity_index)
        loser_work = resolve_terminal(loser_publication.work_id, entity_index)
        work_terminal_active = survivor_work.terminal_id == loser_work.terminal_id and (
            not isinstance(survivor_work.terminal_lifecycle, TombstoneLifecycle)
        )
        if not work_terminal_active:
            raise DomainError(
                code="merge_structural_anchor_mismatch",
                message="Merged publications must share one active Work terminal",
                context={
                    "survivor_id": survivor.id.text,
                    "loser_id": loser.id.text,
                    "predicate": StructuralPredicate.PUBLICATION_OF.value,
                    "survivor_target": survivor_work.terminal_id.text,
                    "loser_target": loser_work.terminal_id.text,
                },
            )
    redirected_loser = replace(
        loser,
        lifecycle=RedirectLifecycle(
            target_id=survivor.id,
            transition_attestation=attestation,
            redirected_at=merged_at,
        ),
    )
    return MergeResult(
        survivor=survivor,
        redirected_loser=redirected_loser,
        basis=basis,
        merged_at=merged_at,
    )


def terminal_id_of(
    projection_input: DomainProjectionInput,
    entity_id: RelationshipEndpointId,
) -> TypedId:
    ids = ids_by_text(projection_input)
    return ids[_terminal_map(projection_input).get(entity_id.text, entity_id.text)]


def ids_by_text(projection_input: DomainProjectionInput) -> dict[str, TypedId]:
    mapping: dict[str, TypedId] = {
        snapshot.id.text: snapshot.id for snapshot in projection_input.entity_index.by_id.values()
    }
    for relation in projection_input.semantic_relations:
        mapping.setdefault(relation.id.text, relation.id)
    return mapping


__all__ = [
    "AssertionOrigin",
    "AssertionRetraction",
    "AuthorityTier",
    "ClaimGroundingProjection",
    "DomainProjectionInput",
    "DuplicateIdentifierBasis",
    "ExactIdentityMergeBasis",
    "GroundingExclusion",
    "GroundingStatus",
    "HumanCorrectionOrigin",
    "MergeBasis",
    "MergeResult",
    "MetadataAssertion",
    "ProjectedRelationship",
    "ProjectedStructuralRelationship",
    "ProjectionConflictReason",
    "ProjectionContender",
    "ProjectionExclusion",
    "ProjectionExclusionReason",
    "ProjectionResult",
    "ProjectionStatus",
    "RelationshipAssertion",
    "ReviewedFuzzyMergeBasis",
    "SemanticEvidenceSupport",
    "SemanticRelationGroundingProjection",
    "SharedIdentifierBasis",
    "SourceMetadataAssertionProposal",
    "SourceOrigin",
    "SourceRecordProposal",
    "SourceRelationshipAssertionProposal",
    "SourceRetractionProposal",
    "SourceWriteBatch",
    "SourceWriteBatchProposal",
    "StructuralExclusion",
    "StructuralProjection",
    "build_domain_projection_input",
    "confirm_claim",
    "confirm_semantic_relation",
    "create_human_correction_origin",
    "create_human_metadata_assertion",
    "create_human_relationship_assertion",
    "create_human_retraction",
    "create_source_metadata_assertion_proposal",
    "create_source_origin",
    "create_source_record_proposal",
    "create_source_relationship_assertion_proposal",
    "create_source_retraction_proposal",
    "create_source_write_batch",
    "create_source_write_batch_proposal",
    "evaluate_claim_grounding",
    "evaluate_current_set",
    "evaluate_semantic_relation_grounding",
    "merge_entities",
    "project_identifier_owner",
    "project_metadata",
    "project_relationship_slot",
    "project_relationships",
    "project_structural_relationships",
]
