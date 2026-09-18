"""Entity-side registries, lifecycle, relationship keys, and payload bindings
(spec sections 7.6, 7.8, 7.10, and 10)."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias, TypeVar, cast, get_args

from .errors import DomainError
from .identifiers import (
    AcceptedOperationAttestation,
    AcceptedReviewAttestation,
    AssertionValue,
    AssertionValueKind,
    AttestationPrincipalKind,
    BooleanAssertionValue,
    ContentDigest,
    DigestAssertionValue,
    EvidenceLocator,
    IdentifierAssertionValue,
    IdentifierKey,
    InstantAssertionValue,
    IntegerAssertionValue,
    LanguageAssertionValue,
    LanguageTag,
    OperationAction,
    ReviewAction,
    TextAssertionValue,
    UtcInstant,
    _canonical_nonblank,
    _invalid_attestation,
    _invalid_value_object,
)
from .ids import (
    AssertionTargetId,
    ClaimId,
    CollectionId,
    DatasetId,
    DocumentId,
    EvidencePassageId,
    IdentifierId,
    KnowledgeEntityId,
    LifecycleEntityId,
    LineageSynthesisId,
    MergeableEntityId,
    MethodId,
    NoteId,
    PersonId,
    PublicationId,
    RelationshipAssertionId,
    RelationshipEndpointId,
    ResearchTaskId,
    SemanticRelationId,
    SourceRecordId,
    TechnicalLineageId,
    TopicId,
    TypedId,
    VenueId,
    WorkId,
)

_CANONICAL_BINDING_PREFIX = b"noa-binding-v1\0"
_MAX_CANONICAL_SCALAR_BYTES = 0xFFFFFFFF


class EndpointKind(StrEnum):
    WORK = "work"
    PUBLICATION = "publication"
    DOCUMENT = "document"
    IDENTIFIER = "identifier"
    PERSON = "person"
    VENUE = "venue"
    TOPIC = "topic"
    METHOD = "method"
    RESEARCH_TASK = "research_task"
    DATASET = "dataset"
    SOURCE_RECORD = "source_record"
    EVIDENCE_PASSAGE = "evidence_passage"
    CLAIM = "claim"
    SEMANTIC_RELATION = "semantic_relation"
    COLLECTION = "collection"
    NOTE = "note"
    TECHNICAL_LINEAGE = "technical_lineage"
    LINEAGE_SYNTHESIS = "lineage_synthesis"


class PredicateKind(StrEnum):
    STRUCTURAL = "structural"
    FACTUAL = "factual"
    REVIEWED_SEMANTIC = "reviewed_semantic"


class Cardinality(StrEnum):
    EXACTLY_ONE = "1"
    ZERO_OR_ONE = "0..1"
    ONE_OR_MORE = "1..*"
    ZERO_OR_MORE = "0..*"


class StructuralPredicate(StrEnum):
    PUBLICATION_OF = "publication_of"
    DOCUMENT_OF = "document_of"
    EVIDENCE_FROM = "evidence_from"
    CLAIM_OF = "claim_of"
    CLAIM_SUPPORTED_BY = "claim_supported_by"
    SEMANTIC_SUPPORTED_BY = "semantic_supported_by"
    COLLECTION_CONTAINS = "collection_contains"
    NOTE_ATTACHED_TO = "note_attached_to"
    LINEAGE_CONTAINS = "lineage_contains"
    SYNTHESIS_OF = "synthesis_of"
    SYNTHESIS_CITES_CLAIM = "synthesis_cites_claim"
    SYNTHESIS_CITES_EVIDENCE = "synthesis_cites_evidence"


class FactualPredicate(StrEnum):
    HAS_IDENTIFIER = "has_identifier"
    OBSERVED_IDENTIFIER = "observed_identifier"
    AUTHORED_BY = "authored_by"
    PUBLISHED_IN = "published_in"
    CITES = "cites"
    IS_VERSION_OF = "is_version_of"
    HAS_TOPIC = "has_topic"
    DESCRIBES_DATASET = "describes_dataset"


class ReviewedSemanticPredicate(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    IMPROVES_ON = "improves_on"
    COMPARES_WITH = "compares_with"
    USES_METHOD = "uses_method"
    ADDRESSES_TASK = "addresses_task"
    USES_DATASET = "uses_dataset"
    ABOUT_TOPIC = "about_topic"
    DERIVED_FROM = "derived_from"


Predicate: TypeAlias = StructuralPredicate | FactualPredicate | ReviewedSemanticPredicate


@dataclass(frozen=True, slots=True)
class PredicateSpec:
    predicate: Predicate
    kind: PredicateKind
    subject_kinds: tuple[EndpointKind, ...]
    object_kinds: tuple[EndpointKind, ...]
    subject_cardinality: Cardinality
    object_cardinality: Cardinality
    irreflexive: bool
    acyclic: bool
    symmetric: bool
    registry_order: int


def _predicate_spec(
    predicate: Predicate,
    *,
    subject_kinds: tuple[EndpointKind, ...],
    object_kinds: tuple[EndpointKind, ...],
    subject_cardinality: Cardinality = Cardinality.ZERO_OR_MORE,
    object_cardinality: Cardinality = Cardinality.ZERO_OR_MORE,
    irreflexive: bool = True,
    acyclic: bool = True,
    symmetric: bool = False,
) -> PredicateSpec:
    if isinstance(predicate, StructuralPredicate):
        kind = PredicateKind.STRUCTURAL
    elif isinstance(predicate, FactualPredicate):
        kind = PredicateKind.FACTUAL
    else:
        kind = PredicateKind.REVIEWED_SEMANTIC
    return PredicateSpec(
        predicate=predicate,
        kind=kind,
        subject_kinds=subject_kinds,
        object_kinds=object_kinds,
        subject_cardinality=subject_cardinality,
        object_cardinality=object_cardinality,
        irreflexive=irreflexive,
        acyclic=acyclic,
        symmetric=symmetric,
        registry_order=0,
    )


_STRUCTURAL_PREDICATE_SPECS: tuple[PredicateSpec, ...] = (
    _predicate_spec(
        StructuralPredicate.PUBLICATION_OF,
        subject_kinds=(EndpointKind.PUBLICATION,),
        object_kinds=(EndpointKind.WORK,),
        subject_cardinality=Cardinality.EXACTLY_ONE,
    ),
    _predicate_spec(
        StructuralPredicate.DOCUMENT_OF,
        subject_kinds=(EndpointKind.DOCUMENT,),
        object_kinds=(EndpointKind.PUBLICATION,),
        subject_cardinality=Cardinality.EXACTLY_ONE,
    ),
    _predicate_spec(
        StructuralPredicate.EVIDENCE_FROM,
        subject_kinds=(EndpointKind.EVIDENCE_PASSAGE,),
        object_kinds=(EndpointKind.DOCUMENT, EndpointKind.SOURCE_RECORD),
        subject_cardinality=Cardinality.EXACTLY_ONE,
    ),
    _predicate_spec(
        StructuralPredicate.CLAIM_OF,
        subject_kinds=(EndpointKind.CLAIM,),
        object_kinds=(EndpointKind.WORK,),
        subject_cardinality=Cardinality.EXACTLY_ONE,
    ),
    _predicate_spec(
        StructuralPredicate.CLAIM_SUPPORTED_BY,
        subject_kinds=(EndpointKind.CLAIM,),
        object_kinds=(EndpointKind.EVIDENCE_PASSAGE,),
        subject_cardinality=Cardinality.ONE_OR_MORE,
    ),
    _predicate_spec(
        StructuralPredicate.SEMANTIC_SUPPORTED_BY,
        subject_kinds=(EndpointKind.SEMANTIC_RELATION,),
        object_kinds=(EndpointKind.EVIDENCE_PASSAGE,),
        subject_cardinality=Cardinality.ONE_OR_MORE,
    ),
    _predicate_spec(
        StructuralPredicate.COLLECTION_CONTAINS,
        subject_kinds=(EndpointKind.COLLECTION,),
        object_kinds=(
            EndpointKind.WORK,
            EndpointKind.PUBLICATION,
            EndpointKind.DOCUMENT,
            EndpointKind.PERSON,
            EndpointKind.VENUE,
            EndpointKind.TOPIC,
            EndpointKind.METHOD,
            EndpointKind.RESEARCH_TASK,
            EndpointKind.DATASET,
            EndpointKind.CLAIM,
            EndpointKind.SEMANTIC_RELATION,
        ),
        subject_cardinality=Cardinality.ZERO_OR_MORE,
    ),
    _predicate_spec(
        StructuralPredicate.NOTE_ATTACHED_TO,
        subject_kinds=(EndpointKind.NOTE,),
        object_kinds=(
            EndpointKind.WORK,
            EndpointKind.PUBLICATION,
            EndpointKind.DOCUMENT,
            EndpointKind.PERSON,
            EndpointKind.VENUE,
            EndpointKind.TOPIC,
            EndpointKind.METHOD,
            EndpointKind.RESEARCH_TASK,
            EndpointKind.DATASET,
            EndpointKind.CLAIM,
            EndpointKind.EVIDENCE_PASSAGE,
            EndpointKind.SEMANTIC_RELATION,
            EndpointKind.COLLECTION,
            EndpointKind.TECHNICAL_LINEAGE,
        ),
        subject_cardinality=Cardinality.ONE_OR_MORE,
    ),
    _predicate_spec(
        StructuralPredicate.LINEAGE_CONTAINS,
        subject_kinds=(EndpointKind.TECHNICAL_LINEAGE,),
        object_kinds=(
            EndpointKind.WORK,
            EndpointKind.CLAIM,
            EndpointKind.METHOD,
            EndpointKind.RESEARCH_TASK,
            EndpointKind.DATASET,
            EndpointKind.SEMANTIC_RELATION,
        ),
        subject_cardinality=Cardinality.ONE_OR_MORE,
    ),
    _predicate_spec(
        StructuralPredicate.SYNTHESIS_OF,
        subject_kinds=(EndpointKind.LINEAGE_SYNTHESIS,),
        object_kinds=(EndpointKind.TECHNICAL_LINEAGE,),
        subject_cardinality=Cardinality.EXACTLY_ONE,
    ),
    _predicate_spec(
        StructuralPredicate.SYNTHESIS_CITES_CLAIM,
        subject_kinds=(EndpointKind.LINEAGE_SYNTHESIS,),
        object_kinds=(EndpointKind.CLAIM,),
    ),
    _predicate_spec(
        StructuralPredicate.SYNTHESIS_CITES_EVIDENCE,
        subject_kinds=(EndpointKind.LINEAGE_SYNTHESIS,),
        object_kinds=(EndpointKind.EVIDENCE_PASSAGE,),
    ),
)

_FACTUAL_PREDICATE_SPECS: tuple[PredicateSpec, ...] = (
    _predicate_spec(
        FactualPredicate.HAS_IDENTIFIER,
        subject_kinds=(
            EndpointKind.PUBLICATION,
            EndpointKind.DATASET,
            EndpointKind.PERSON,
            EndpointKind.VENUE,
            EndpointKind.TOPIC,
        ),
        object_kinds=(EndpointKind.IDENTIFIER,),
        object_cardinality=Cardinality.ZERO_OR_ONE,
    ),
    _predicate_spec(
        FactualPredicate.OBSERVED_IDENTIFIER,
        subject_kinds=(EndpointKind.SOURCE_RECORD,),
        object_kinds=(EndpointKind.IDENTIFIER,),
    ),
    _predicate_spec(
        FactualPredicate.AUTHORED_BY,
        subject_kinds=(EndpointKind.PUBLICATION,),
        object_kinds=(EndpointKind.PERSON,),
    ),
    _predicate_spec(
        FactualPredicate.PUBLISHED_IN,
        subject_kinds=(EndpointKind.PUBLICATION,),
        object_kinds=(EndpointKind.VENUE,),
        subject_cardinality=Cardinality.ZERO_OR_ONE,
    ),
    _predicate_spec(
        FactualPredicate.CITES,
        subject_kinds=(EndpointKind.PUBLICATION,),
        object_kinds=(EndpointKind.PUBLICATION,),
        acyclic=False,
    ),
    _predicate_spec(
        FactualPredicate.IS_VERSION_OF,
        subject_kinds=(EndpointKind.PUBLICATION,),
        object_kinds=(EndpointKind.PUBLICATION,),
        subject_cardinality=Cardinality.ZERO_OR_ONE,
    ),
    _predicate_spec(
        FactualPredicate.HAS_TOPIC,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.TOPIC,),
    ),
    _predicate_spec(
        FactualPredicate.DESCRIBES_DATASET,
        subject_kinds=(EndpointKind.PUBLICATION,),
        object_kinds=(EndpointKind.DATASET,),
    ),
)

_REVIEWED_SEMANTIC_PREDICATE_SPECS: tuple[PredicateSpec, ...] = (
    _predicate_spec(
        ReviewedSemanticPredicate.SUPPORTS,
        subject_kinds=(EndpointKind.CLAIM,),
        object_kinds=(EndpointKind.CLAIM,),
        acyclic=False,
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.CONTRADICTS,
        subject_kinds=(EndpointKind.CLAIM,),
        object_kinds=(EndpointKind.CLAIM,),
        acyclic=False,
        symmetric=True,
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.EXTENDS,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.WORK,),
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.IMPROVES_ON,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.WORK,),
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.COMPARES_WITH,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.WORK,),
        acyclic=False,
        symmetric=True,
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.USES_METHOD,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.METHOD,),
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.ADDRESSES_TASK,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.RESEARCH_TASK,),
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.USES_DATASET,
        subject_kinds=(EndpointKind.WORK,),
        object_kinds=(EndpointKind.DATASET,),
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.ABOUT_TOPIC,
        subject_kinds=(EndpointKind.WORK, EndpointKind.CLAIM),
        object_kinds=(EndpointKind.TOPIC,),
    ),
    _predicate_spec(
        ReviewedSemanticPredicate.DERIVED_FROM,
        subject_kinds=(EndpointKind.METHOD,),
        object_kinds=(EndpointKind.METHOD,),
    ),
)

_PREDICATE_SPEC_SEQUENCE: tuple[PredicateSpec, ...] = (
    _STRUCTURAL_PREDICATE_SPECS + _FACTUAL_PREDICATE_SPECS + _REVIEWED_SEMANTIC_PREDICATE_SPECS
)

PREDICATE_REGISTRY: Mapping[Predicate, PredicateSpec] = MappingProxyType(
    {
        spec.predicate: replace(spec, registry_order=registry_order)
        for registry_order, spec in enumerate(_PREDICATE_SPEC_SEQUENCE, start=1)
    }
)


STRUCTURAL_PREDICATE_SOURCE_FIELDS: Mapping[StructuralPredicate, str] = MappingProxyType(
    {
        StructuralPredicate.PUBLICATION_OF: "work_id",
        StructuralPredicate.DOCUMENT_OF: "publication_id",
        StructuralPredicate.EVIDENCE_FROM: "source_id",
        StructuralPredicate.CLAIM_OF: "work_id",
        StructuralPredicate.CLAIM_SUPPORTED_BY: "evidence_ids",
        StructuralPredicate.SEMANTIC_SUPPORTED_BY: "evidence_ids",
        StructuralPredicate.COLLECTION_CONTAINS: "member_ids",
        StructuralPredicate.NOTE_ATTACHED_TO: "attached_entity_ids",
        StructuralPredicate.LINEAGE_CONTAINS: "member_ids",
        StructuralPredicate.SYNTHESIS_OF: "lineage_id",
        StructuralPredicate.SYNTHESIS_CITES_CLAIM: "claim_ids",
        StructuralPredicate.SYNTHESIS_CITES_EVIDENCE: "evidence_ids",
    }
)


_ID_TYPES_BY_ENDPOINT_KIND: Mapping[EndpointKind, frozenset[type[TypedId]]] = MappingProxyType(
    {
        EndpointKind.WORK: frozenset({WorkId}),
        EndpointKind.PUBLICATION: frozenset({PublicationId}),
        EndpointKind.DOCUMENT: frozenset({DocumentId}),
        EndpointKind.IDENTIFIER: frozenset({IdentifierId}),
        EndpointKind.PERSON: frozenset({PersonId}),
        EndpointKind.VENUE: frozenset({VenueId}),
        EndpointKind.TOPIC: frozenset({TopicId}),
        EndpointKind.METHOD: frozenset({MethodId}),
        EndpointKind.RESEARCH_TASK: frozenset({ResearchTaskId}),
        EndpointKind.DATASET: frozenset({DatasetId}),
        EndpointKind.SOURCE_RECORD: frozenset({SourceRecordId}),
        EndpointKind.EVIDENCE_PASSAGE: frozenset({EvidencePassageId}),
        EndpointKind.CLAIM: frozenset({ClaimId}),
        EndpointKind.SEMANTIC_RELATION: frozenset({SemanticRelationId}),
        EndpointKind.COLLECTION: frozenset({CollectionId}),
        EndpointKind.NOTE: frozenset({NoteId}),
        EndpointKind.TECHNICAL_LINEAGE: frozenset({TechnicalLineageId}),
        EndpointKind.LINEAGE_SYNTHESIS: frozenset({LineageSynthesisId}),
    }
)

_ENDPOINT_KIND_BY_ID_TYPE: dict[type[TypedId], EndpointKind] = {
    id_type: kind for kind, id_types in _ID_TYPES_BY_ENDPOINT_KIND.items() for id_type in id_types
}


def _endpoint_id_types(kinds: tuple[EndpointKind, ...]) -> frozenset[type[TypedId]]:
    collected: set[type[TypedId]] = set()
    for kind in kinds:
        collected.update(_ID_TYPES_BY_ENDPOINT_KIND[kind])
    return frozenset(collected)


_RELATIONSHIP_ENDPOINT_TYPES: Mapping[
    Predicate, tuple[frozenset[type[TypedId]], frozenset[type[TypedId]]]
] = MappingProxyType(
    {
        predicate: (
            _endpoint_id_types(spec.subject_kinds),
            _endpoint_id_types(spec.object_kinds),
        )
        for predicate, spec in PREDICATE_REGISTRY.items()
    }
)


def _endpoint_kind_display(value: object) -> str:
    for id_type, kind in _ENDPOINT_KIND_BY_ID_TYPE.items():
        if type(value) is id_type:
            return kind.value
    return type(value).__name__


def _predicate_display(value: object) -> str:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, str):
        return value
    return f"<{type(value).__name__}>"


def canonicalize_relationship(
    predicate: Predicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
) -> tuple[RelationshipEndpointId, RelationshipEndpointId]:
    if not isinstance(predicate, get_args(Predicate)):
        raise DomainError(
            code="unknown_predicate",
            message=f"Unknown relationship predicate: {_predicate_display(predicate)}",
            context={"predicate": _predicate_display(predicate)},
        )
    subject_types, object_types = _RELATIONSHIP_ENDPOINT_TYPES[predicate]
    if type(subject_id) not in subject_types or type(object_id) not in object_types:
        raise DomainError(
            code="predicate_endpoint_mismatch",
            message=(
                f"Predicate {predicate.value!r} does not accept endpoints "
                f"{_endpoint_kind_display(subject_id)!r} -> "
                f"{_endpoint_kind_display(object_id)!r}"
            ),
            context={
                "predicate": predicate.value,
                "subject_kind": _endpoint_kind_display(subject_id),
                "object_kind": _endpoint_kind_display(object_id),
            },
        )
    if subject_id.text == object_id.text:
        raise DomainError(
            code="irreflexive_relationship",
            message=(
                f"Relationship {predicate.value!r} must not connect {subject_id.text!r} to itself"
            ),
            context={"predicate": predicate.value, "entity_id": subject_id.text},
        )
    if PREDICATE_REGISTRY[predicate].symmetric and subject_id.text > object_id.text:
        return object_id, subject_id
    return subject_id, object_id


@dataclass(frozen=True, slots=True)
class RelationshipKey:
    predicate: Predicate
    subject_id: RelationshipEndpointId
    object_id: RelationshipEndpointId

    def __post_init__(self) -> None:
        subject_id, object_id = canonicalize_relationship(
            self.predicate,
            self.subject_id,
            self.object_id,
        )
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "object_id", object_id)

    def sort_key(self) -> tuple[str, str, str]:
        return (self.predicate.value, self.subject_id.text, self.object_id.text)


class MetadataFieldKey(StrEnum):
    WORK_TITLE = "work.title"
    WORK_ABSTRACT = "work.abstract"
    WORK_YEAR = "work.year"
    WORK_LANGUAGE = "work.language"
    PUBLICATION_TITLE = "publication.title"
    PUBLICATION_ABSTRACT = "publication.abstract"
    PUBLICATION_YEAR = "publication.year"
    PUBLICATION_LANGUAGE = "publication.language"
    PUBLICATION_VOLUME = "publication.volume"
    PUBLICATION_ISSUE = "publication.issue"
    PUBLICATION_PAGES = "publication.pages"
    PUBLICATION_PUBLISHER = "publication.publisher"
    DOCUMENT_LANGUAGE = "document.language"
    PERSON_DISPLAY_NAME = "person.display_name"
    PERSON_GIVEN_NAME = "person.given_name"
    PERSON_FAMILY_NAME = "person.family_name"
    VENUE_NAME = "venue.name"
    VENUE_ABBREVIATED_NAME = "venue.abbreviated_name"
    VENUE_PUBLISHER = "venue.publisher"
    VENUE_TYPE = "venue.type"
    TOPIC_LABEL = "topic.label"
    TOPIC_DESCRIPTION = "topic.description"
    METHOD_LABEL = "method.label"
    METHOD_DESCRIPTION = "method.description"
    RESEARCH_TASK_LABEL = "research_task.label"
    RESEARCH_TASK_DESCRIPTION = "research_task.description"
    DATASET_NAME = "dataset.name"
    DATASET_DESCRIPTION = "dataset.description"
    DATASET_VERSION = "dataset.version"


@dataclass(frozen=True, slots=True)
class MetadataFieldSpec:
    key: MetadataFieldKey
    target_kind: EndpointKind
    value_kind: AssertionValueKind
    language_scoped: bool
    integer_range: tuple[int, int] | None
    allowed_text_values: tuple[str, ...]


def _metadata_field_spec(
    key: MetadataFieldKey,
    *,
    target_kind: EndpointKind,
    value_kind: AssertionValueKind,
    language_scoped: bool = False,
    integer_range: tuple[int, int] | None = None,
    allowed_text_values: tuple[str, ...] = (),
) -> MetadataFieldSpec:
    return MetadataFieldSpec(
        key=key,
        target_kind=target_kind,
        value_kind=value_kind,
        language_scoped=language_scoped,
        integer_range=integer_range,
        allowed_text_values=allowed_text_values,
    )


METADATA_FIELD_REGISTRY: Mapping[MetadataFieldKey, MetadataFieldSpec] = MappingProxyType(
    {
        MetadataFieldKey.WORK_TITLE: _metadata_field_spec(
            MetadataFieldKey.WORK_TITLE,
            target_kind=EndpointKind.WORK,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.WORK_ABSTRACT: _metadata_field_spec(
            MetadataFieldKey.WORK_ABSTRACT,
            target_kind=EndpointKind.WORK,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.WORK_YEAR: _metadata_field_spec(
            MetadataFieldKey.WORK_YEAR,
            target_kind=EndpointKind.WORK,
            value_kind=AssertionValueKind.INTEGER,
            integer_range=(0, 9999),
        ),
        MetadataFieldKey.WORK_LANGUAGE: _metadata_field_spec(
            MetadataFieldKey.WORK_LANGUAGE,
            target_kind=EndpointKind.WORK,
            value_kind=AssertionValueKind.LANGUAGE,
        ),
        MetadataFieldKey.PUBLICATION_TITLE: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_TITLE,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.PUBLICATION_ABSTRACT: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_ABSTRACT,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.PUBLICATION_YEAR: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_YEAR,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.INTEGER,
            integer_range=(0, 9999),
        ),
        MetadataFieldKey.PUBLICATION_LANGUAGE: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_LANGUAGE,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.LANGUAGE,
        ),
        MetadataFieldKey.PUBLICATION_VOLUME: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_VOLUME,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.TEXT,
        ),
        MetadataFieldKey.PUBLICATION_ISSUE: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_ISSUE,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.TEXT,
        ),
        MetadataFieldKey.PUBLICATION_PAGES: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_PAGES,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.TEXT,
        ),
        MetadataFieldKey.PUBLICATION_PUBLISHER: _metadata_field_spec(
            MetadataFieldKey.PUBLICATION_PUBLISHER,
            target_kind=EndpointKind.PUBLICATION,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.DOCUMENT_LANGUAGE: _metadata_field_spec(
            MetadataFieldKey.DOCUMENT_LANGUAGE,
            target_kind=EndpointKind.DOCUMENT,
            value_kind=AssertionValueKind.LANGUAGE,
        ),
        MetadataFieldKey.PERSON_DISPLAY_NAME: _metadata_field_spec(
            MetadataFieldKey.PERSON_DISPLAY_NAME,
            target_kind=EndpointKind.PERSON,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.PERSON_GIVEN_NAME: _metadata_field_spec(
            MetadataFieldKey.PERSON_GIVEN_NAME,
            target_kind=EndpointKind.PERSON,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.PERSON_FAMILY_NAME: _metadata_field_spec(
            MetadataFieldKey.PERSON_FAMILY_NAME,
            target_kind=EndpointKind.PERSON,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.VENUE_NAME: _metadata_field_spec(
            MetadataFieldKey.VENUE_NAME,
            target_kind=EndpointKind.VENUE,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.VENUE_ABBREVIATED_NAME: _metadata_field_spec(
            MetadataFieldKey.VENUE_ABBREVIATED_NAME,
            target_kind=EndpointKind.VENUE,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.VENUE_PUBLISHER: _metadata_field_spec(
            MetadataFieldKey.VENUE_PUBLISHER,
            target_kind=EndpointKind.VENUE,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.VENUE_TYPE: _metadata_field_spec(
            MetadataFieldKey.VENUE_TYPE,
            target_kind=EndpointKind.VENUE,
            value_kind=AssertionValueKind.TEXT,
            allowed_text_values=(
                "journal",
                "conference",
                "repository",
                "book_series",
                "ebook_platform",
                "other",
            ),
        ),
        MetadataFieldKey.TOPIC_LABEL: _metadata_field_spec(
            MetadataFieldKey.TOPIC_LABEL,
            target_kind=EndpointKind.TOPIC,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.TOPIC_DESCRIPTION: _metadata_field_spec(
            MetadataFieldKey.TOPIC_DESCRIPTION,
            target_kind=EndpointKind.TOPIC,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.METHOD_LABEL: _metadata_field_spec(
            MetadataFieldKey.METHOD_LABEL,
            target_kind=EndpointKind.METHOD,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.METHOD_DESCRIPTION: _metadata_field_spec(
            MetadataFieldKey.METHOD_DESCRIPTION,
            target_kind=EndpointKind.METHOD,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.RESEARCH_TASK_LABEL: _metadata_field_spec(
            MetadataFieldKey.RESEARCH_TASK_LABEL,
            target_kind=EndpointKind.RESEARCH_TASK,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.RESEARCH_TASK_DESCRIPTION: _metadata_field_spec(
            MetadataFieldKey.RESEARCH_TASK_DESCRIPTION,
            target_kind=EndpointKind.RESEARCH_TASK,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.DATASET_NAME: _metadata_field_spec(
            MetadataFieldKey.DATASET_NAME,
            target_kind=EndpointKind.DATASET,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.DATASET_DESCRIPTION: _metadata_field_spec(
            MetadataFieldKey.DATASET_DESCRIPTION,
            target_kind=EndpointKind.DATASET,
            value_kind=AssertionValueKind.TEXT,
            language_scoped=True,
        ),
        MetadataFieldKey.DATASET_VERSION: _metadata_field_spec(
            MetadataFieldKey.DATASET_VERSION,
            target_kind=EndpointKind.DATASET,
            value_kind=AssertionValueKind.TEXT,
        ),
    }
)


_ID_TYPE_SETS: dict[str, frozenset[type[TypedId]]] = {
    "knowledge_entity": frozenset(get_args(KnowledgeEntityId)),
    "relationship_endpoint": frozenset(get_args(RelationshipEndpointId)),
    "lifecycle": frozenset(get_args(LifecycleEntityId)),
    "mergeable": frozenset(get_args(MergeableEntityId)),
    "assertion_target": frozenset(get_args(AssertionTargetId)),
}


def _require_id_type(value: object, *, id_set: frozenset[type[TypedId]], field_name: str) -> None:
    if type(value) not in id_set:
        raise _invalid_value_object(
            type_name=type(value).__name__,
            field_name=field_name,
            reason="value is not an allowed typed entity ID",
        )


@dataclass(frozen=True, slots=True)
class ActiveLifecycle:
    @property
    def tag(self) -> str:
        return "active"

    def sort_key(self) -> str:
        return self.tag


@dataclass(frozen=True, slots=True)
class RedirectLifecycle:
    target_id: LifecycleEntityId
    transition_attestation: AcceptedOperationAttestation | AcceptedReviewAttestation
    redirected_at: UtcInstant

    def __post_init__(self) -> None:
        _require_id_type(
            self.target_id,
            id_set=_ID_TYPE_SETS["lifecycle"],
            field_name="target_id",
        )
        if type(self.redirected_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="redirected_at",
                reason="value must be a UtcInstant",
            )
        expected_action: OperationAction | ReviewAction
        if type(self.transition_attestation) is AcceptedOperationAttestation:
            expected_action = OperationAction.MERGE_EXACT_IDENTITY
        elif type(self.transition_attestation) is AcceptedReviewAttestation:
            expected_action = ReviewAction.MERGE_FUZZY
        else:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="transition_attestation",
                reason="value must be an accepted operation or review attestation",
            )
        actual_action = self.transition_attestation.action.value
        if self.transition_attestation.action is not expected_action:
            raise DomainError(
                code="attestation_action_mismatch",
                message=(
                    f"Redirect requires attestation action {expected_action.value!r}, "
                    f"got {actual_action!r}"
                ),
                context={
                    "operation_kind": "redirect",
                    "subject_ids": (self.target_id.text,),
                    "expected_action": expected_action.value,
                    "actual_action": actual_action,
                },
            )
        if self.redirected_at < self.transition_attestation.accepted_at:
            raise DomainError(
                code="attestation_time_invalid",
                message="redirect time must not precede attestation acceptance",
                context={
                    "operation_kind": "redirect",
                    "subject_ids": (self.target_id.text,),
                    "accepted_at": self.transition_attestation.accepted_at.text,
                    "recorded_at": self.redirected_at.text,
                },
            )

    @property
    def tag(self) -> str:
        return "redirect"

    def sort_key(self) -> str:
        return self.tag


@dataclass(frozen=True, slots=True)
class TombstoneLifecycle:
    accepted_operation: AcceptedOperationAttestation
    tombstoned_at: UtcInstant

    def __post_init__(self) -> None:
        if type(self.accepted_operation) is not AcceptedOperationAttestation:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="accepted_operation",
                reason="value must be an AcceptedOperationAttestation",
            )
        if type(self.tombstoned_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="tombstoned_at",
                reason="value must be a UtcInstant",
            )
        if self.accepted_operation.action is not OperationAction.TOMBSTONE_ENTITY:
            raise DomainError(
                code="attestation_action_mismatch",
                message=(
                    "Tombstone requires attestation action 'tombstone_entity', "
                    f"got {self.accepted_operation.action.value!r}"
                ),
                context={
                    "operation_kind": "tombstone",
                    "subject_ids": (),
                    "expected_action": OperationAction.TOMBSTONE_ENTITY.value,
                    "actual_action": self.accepted_operation.action.value,
                },
            )
        if self.tombstoned_at < self.accepted_operation.accepted_at:
            raise DomainError(
                code="attestation_time_invalid",
                message="tombstone time must not precede attestation acceptance",
                context={
                    "operation_kind": "tombstone",
                    "subject_ids": (),
                    "accepted_at": self.accepted_operation.accepted_at.text,
                    "recorded_at": self.tombstoned_at.text,
                },
            )

    @property
    def tag(self) -> str:
        return "tombstone"

    def sort_key(self) -> str:
        return self.tag


EntityLifecycle: TypeAlias = ActiveLifecycle | RedirectLifecycle | TombstoneLifecycle


CanonicalBindingScalar: TypeAlias = (
    str
    | int
    | bool
    | StrEnum
    | TypedId
    | ContentDigest
    | LanguageTag
    | UtcInstant
    | EvidenceLocator
    | IdentifierKey
    | AssertionValue
)
CanonicalBindingField: TypeAlias = CanonicalBindingScalar | tuple[CanonicalBindingScalar, ...]


def _frame_canonical_text(value: str) -> str:
    try:
        payload = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise _invalid_value_object(
            type_name="CanonicalBinding",
            field_name="scalar",
            reason="canonical text is not valid UTF-8",
        ) from error
    if len(payload) > _MAX_CANONICAL_SCALAR_BYTES:
        raise _invalid_value_object(
            type_name="CanonicalBinding",
            field_name="scalar",
            reason="canonical text exceeds the eight-hex-digit byte length limit",
        )
    return f"{len(payload):08x}:{value}"


def _assertion_value_canonical_text(value: AssertionValue) -> str:
    if type(value) is TextAssertionValue:
        return (
            "text" + _frame_canonical_text(value.language.text) + _frame_canonical_text(value.text)
        )
    if type(value) is IntegerAssertionValue:
        return f"integer:{value.value}"
    if type(value) is BooleanAssertionValue:
        return "boolean:true" if value.value else "boolean:false"
    if type(value) is DigestAssertionValue:
        return f"digest:{value.value.text}"
    if type(value) is LanguageAssertionValue:
        return f"language:{value.value.text}"
    if type(value) is InstantAssertionValue:
        return f"instant:{value.value.text}"
    if type(value) is IdentifierAssertionValue:
        return (
            "identifier"
            + _frame_canonical_text(value.value.scheme.value)
            + _frame_canonical_text(value.value.normalized_value)
        )
    raise _invalid_value_object(
        type_name="CanonicalBinding",
        field_name="scalar",
        reason="unsupported AssertionValue variant",
    )


def _canonical_scalar_text(value: CanonicalBindingScalar) -> str:
    if type(value) is str:
        return value
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, TypedId):
        return value.text
    if isinstance(value, (ContentDigest, LanguageTag, UtcInstant, EvidenceLocator)):
        return value.text
    if type(value) is IdentifierKey:
        return (
            "identifier-key"
            + _frame_canonical_text(value.scheme.value)
            + _frame_canonical_text(value.normalized_value)
        )
    if isinstance(
        value,
        (
            TextAssertionValue,
            IntegerAssertionValue,
            BooleanAssertionValue,
            DigestAssertionValue,
            LanguageAssertionValue,
            InstantAssertionValue,
            IdentifierAssertionValue,
        ),
    ):
        return _assertion_value_canonical_text(value)
    raise _invalid_value_object(
        type_name="CanonicalBinding",
        field_name="scalar",
        reason=f"unsupported scalar type {type(value).__name__}",
    )


def _encode_canonical_scalar(value: CanonicalBindingScalar) -> bytes:
    text = _canonical_scalar_text(value)
    try:
        payload = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise _invalid_value_object(
            type_name="CanonicalBinding",
            field_name="scalar",
            reason="canonical text is not valid UTF-8",
        ) from error
    if len(payload) > _MAX_CANONICAL_SCALAR_BYTES:
        raise _invalid_value_object(
            type_name="CanonicalBinding",
            field_name="scalar",
            reason="canonical text exceeds the eight-hex-digit byte length limit",
        )
    return f"{len(payload):08x}:".encode("ascii") + payload


def _encode_canonical_tuple(values: tuple[CanonicalBindingScalar, ...]) -> bytes:
    ordered = sorted(values, key=_canonical_scalar_text)
    encoded = bytearray(f"{len(ordered):08d}:".encode("ascii"))
    for value in ordered:
        encoded.extend(_encode_canonical_scalar(value))
    return bytes(encoded)


def _encode_canonical_binding(fields: tuple[CanonicalBindingField, ...]) -> bytes:
    encoded = bytearray(_CANONICAL_BINDING_PREFIX)
    for value in fields:
        if isinstance(value, tuple):
            encoded.extend(_encode_canonical_tuple(value))
        else:
            encoded.extend(_encode_canonical_scalar(value))
    return bytes(encoded)


def _sha256_content_digest(payload: bytes) -> ContentDigest:
    if type(payload) is not bytes:
        raise _invalid_value_object(
            type_name="CanonicalBinding",
            field_name="payload",
            reason="payload must be bytes",
        )
    return ContentDigest.parse(f"sha256:{hashlib.sha256(payload).hexdigest()}")


def _compute_canonical_binding_digest(
    fields: tuple[CanonicalBindingField, ...],
) -> ContentDigest:
    return _sha256_content_digest(_encode_canonical_binding(fields))


def _content_digests_equal(left: ContentDigest, right: ContentDigest) -> bool:
    if type(left) is not ContentDigest or type(right) is not ContentDigest:
        return False
    return hmac.compare_digest(left.text.encode("ascii"), right.text.encode("ascii"))


_TypedIdT = TypeVar("_TypedIdT", bound=TypedId)

_SYMMETRIC_FACTUAL_PREDICATES: frozenset[FactualPredicate] = frozenset()
_SYMMETRIC_REVIEWED_PREDICATES: frozenset[ReviewedSemanticPredicate] = frozenset(
    {ReviewedSemanticPredicate.CONTRADICTS, ReviewedSemanticPredicate.COMPARES_WITH}
)


def _sorted_unique_typed_ids(
    values: tuple[_TypedIdT, ...],
    id_type: type[_TypedIdT],
) -> tuple[_TypedIdT, ...]:
    for value in values:
        if type(value) is not id_type:
            raise _invalid_value_object(
                type_name=id_type.__name__,
                field_name="ids",
                reason=f"every value must be a {id_type.__name__}",
            )
    return tuple(sorted(set(values), key=lambda item: item.text))


@dataclass(frozen=True, slots=True)
class ClaimReviewBinding:
    work_id: WorkId
    statement: str
    language: LanguageTag
    evidence_ids: tuple[EvidencePassageId, ...]

    def __post_init__(self) -> None:
        if type(self.work_id) is not WorkId:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="work_id",
                reason="value must be a WorkId",
            )
        statement = _canonical_nonblank(
            self.statement,
            type_name=type(self).__name__,
            field_name="statement",
        )
        if type(self.language) is not LanguageTag:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="language",
                reason="value must be a LanguageTag",
            )
        evidence_ids = _sorted_unique_typed_ids(self.evidence_ids, EvidencePassageId)
        object.__setattr__(self, "statement", statement)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def sort_key(self) -> str:
        return compute_review_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class SemanticRelationReviewBinding:
    predicate: ReviewedSemanticPredicate
    subject_id: KnowledgeEntityId
    object_id: KnowledgeEntityId
    evidence_ids: tuple[EvidencePassageId, ...]

    def __post_init__(self) -> None:
        if type(self.predicate) is not ReviewedSemanticPredicate:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="predicate",
                reason="value must be a ReviewedSemanticPredicate",
            )
        _require_id_type(
            self.subject_id,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="subject_id",
        )
        _require_id_type(
            self.object_id,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="object_id",
        )
        subject_id = self.subject_id
        object_id = self.object_id
        if self.predicate in _SYMMETRIC_REVIEWED_PREDICATES and subject_id.text > object_id.text:
            subject_id, object_id = object_id, subject_id
        evidence_ids = _sorted_unique_typed_ids(self.evidence_ids, EvidencePassageId)
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def sort_key(self) -> str:
        return compute_review_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class FuzzyMergeReviewBinding:
    survivor_id: MergeableEntityId
    loser_id: MergeableEntityId

    def __post_init__(self) -> None:
        _require_id_type(
            self.survivor_id,
            id_set=_ID_TYPE_SETS["mergeable"],
            field_name="survivor_id",
        )
        _require_id_type(
            self.loser_id,
            id_set=_ID_TYPE_SETS["mergeable"],
            field_name="loser_id",
        )

    def sort_key(self) -> str:
        return compute_review_payload_digest(self).text


ReviewPayloadBinding: TypeAlias = (
    ClaimReviewBinding | SemanticRelationReviewBinding | FuzzyMergeReviewBinding
)


@dataclass(frozen=True, slots=True)
class SourceWriteOperationBinding:
    proposal_digest: ContentDigest

    def __post_init__(self) -> None:
        if type(self.proposal_digest) is not ContentDigest:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="proposal_digest",
                reason="value must be a ContentDigest",
            )

    def sort_key(self) -> str:
        return compute_operation_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class HumanMetadataCorrectionBinding:
    subject_id: KnowledgeEntityId
    field: MetadataFieldKey
    value: AssertionValue
    asserted_at: UtcInstant

    def __post_init__(self) -> None:
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
        if not isinstance(self.value, get_args(AssertionValue)):
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="value",
                reason="value must be an AssertionValue variant",
            )
        if type(self.asserted_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="asserted_at",
                reason="value must be a UtcInstant",
            )

    def sort_key(self) -> str:
        return compute_operation_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class HumanRelationshipCorrectionBinding:
    predicate: FactualPredicate
    subject_id: RelationshipEndpointId
    object_id: RelationshipEndpointId
    asserted_at: UtcInstant

    def __post_init__(self) -> None:
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
        subject_id = self.subject_id
        object_id = self.object_id
        if self.predicate in _SYMMETRIC_FACTUAL_PREDICATES and subject_id.text > object_id.text:
            subject_id, object_id = object_id, subject_id
        if type(self.asserted_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="asserted_at",
                reason="value must be a UtcInstant",
            )
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "object_id", object_id)

    def sort_key(self) -> str:
        return compute_operation_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class HumanRetractionBinding:
    target_id: AssertionTargetId
    reason: str
    retracted_at: UtcInstant

    def __post_init__(self) -> None:
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
        if type(self.retracted_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="retracted_at",
                reason="value must be a UtcInstant",
            )
        object.__setattr__(self, "reason", reason)

    def sort_key(self) -> str:
        return compute_operation_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class ExactMergeOperationBinding:
    survivor_id: MergeableEntityId
    loser_id: MergeableEntityId
    identifier_key: IdentifierKey
    supporting_assertion_ids: tuple[RelationshipAssertionId, ...]
    merged_at: UtcInstant

    def __post_init__(self) -> None:
        _require_id_type(
            self.survivor_id,
            id_set=_ID_TYPE_SETS["mergeable"],
            field_name="survivor_id",
        )
        _require_id_type(
            self.loser_id,
            id_set=_ID_TYPE_SETS["mergeable"],
            field_name="loser_id",
        )
        if type(self.identifier_key) is not IdentifierKey:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="identifier_key",
                reason="value must be an IdentifierKey",
            )
        supporting_assertion_ids = _sorted_unique_typed_ids(
            self.supporting_assertion_ids,
            RelationshipAssertionId,
        )
        if type(self.merged_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="merged_at",
                reason="value must be a UtcInstant",
            )
        object.__setattr__(self, "supporting_assertion_ids", supporting_assertion_ids)

    def sort_key(self) -> str:
        return compute_operation_payload_digest(self).text


@dataclass(frozen=True, slots=True)
class TombstoneOperationBinding:
    entity_id: LifecycleEntityId
    tombstoned_at: UtcInstant

    def __post_init__(self) -> None:
        _require_id_type(
            self.entity_id,
            id_set=_ID_TYPE_SETS["lifecycle"],
            field_name="entity_id",
        )
        if type(self.tombstoned_at) is not UtcInstant:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="tombstoned_at",
                reason="value must be a UtcInstant",
            )

    def sort_key(self) -> str:
        return compute_operation_payload_digest(self).text


OperationPayloadBinding: TypeAlias = (
    SourceWriteOperationBinding
    | HumanMetadataCorrectionBinding
    | HumanRelationshipCorrectionBinding
    | HumanRetractionBinding
    | ExactMergeOperationBinding
    | TombstoneOperationBinding
)


def compute_review_payload_digest(binding: ReviewPayloadBinding) -> ContentDigest:
    fields: tuple[CanonicalBindingField, ...]
    if type(binding) is ClaimReviewBinding:
        fields = (binding.work_id, binding.statement, binding.language, binding.evidence_ids)
    elif type(binding) is SemanticRelationReviewBinding:
        fields = (
            binding.predicate,
            binding.subject_id,
            binding.object_id,
            binding.evidence_ids,
        )
    elif type(binding) is FuzzyMergeReviewBinding:
        fields = (binding.survivor_id, binding.loser_id)
    else:
        raise _invalid_value_object(
            type_name="ReviewPayloadBinding",
            field_name="binding",
            reason="unsupported binding variant",
        )
    return _compute_canonical_binding_digest(fields)


def compute_operation_payload_digest(binding: OperationPayloadBinding) -> ContentDigest:
    fields: tuple[CanonicalBindingField, ...]
    if type(binding) is SourceWriteOperationBinding:
        fields = (binding.proposal_digest,)
    elif type(binding) is HumanMetadataCorrectionBinding:
        fields = (binding.subject_id, binding.field, binding.value, binding.asserted_at)
    elif type(binding) is HumanRelationshipCorrectionBinding:
        fields = (
            binding.predicate,
            binding.subject_id,
            binding.object_id,
            binding.asserted_at,
        )
    elif type(binding) is HumanRetractionBinding:
        fields = (binding.target_id, binding.reason, binding.retracted_at)
    elif type(binding) is ExactMergeOperationBinding:
        fields = (
            binding.survivor_id,
            binding.loser_id,
            binding.identifier_key,
            binding.supporting_assertion_ids,
            binding.merged_at,
        )
    elif type(binding) is TombstoneOperationBinding:
        fields = (binding.entity_id, binding.tombstoned_at)
    else:
        raise _invalid_value_object(
            type_name="OperationPayloadBinding",
            field_name="binding",
            reason="unsupported binding variant",
        )
    return _compute_canonical_binding_digest(fields)


def _attestation_action_mismatch(
    operation_kind: str,
    subject_ids: tuple[str, ...],
    expected_action: str | tuple[str, ...],
    actual_action: str,
) -> DomainError:
    return DomainError(
        code="attestation_action_mismatch",
        message=(
            f"Operation {operation_kind!r} requires attestation action "
            f"{expected_action!r}, got {actual_action!r}"
        ),
        context={
            "operation_kind": operation_kind,
            "subject_ids": subject_ids,
            "expected_action": expected_action,
            "actual_action": actual_action,
        },
    )


def _attestation_time_invalid(
    operation_kind: str,
    subject_ids: tuple[str, ...],
    accepted_at: str,
    recorded_at: str,
) -> DomainError:
    return DomainError(
        code="attestation_time_invalid",
        message=(
            f"Operation {operation_kind!r} recorded at {recorded_at} must not precede "
            f"attestation acceptance at {accepted_at}"
        ),
        context={
            "operation_kind": operation_kind,
            "subject_ids": subject_ids,
            "accepted_at": accepted_at,
            "recorded_at": recorded_at,
        },
    )


def _attestation_payload_mismatch(
    operation_kind: str,
    subject_ids: tuple[str, ...],
    expected_digest: str,
    actual_digest: str,
) -> DomainError:
    return DomainError(
        code="attestation_payload_mismatch",
        message=(
            f"Operation {operation_kind!r} payload digest mismatch: attestation declares "
            f"{expected_digest}, actual payload hashes to {actual_digest}"
        ),
        context={
            "operation_kind": operation_kind,
            "subject_ids": subject_ids,
            "expected_digest": expected_digest,
            "actual_digest": actual_digest,
        },
    )


_LIFECYCLE_VARIANTS: frozenset[type] = frozenset(
    {ActiveLifecycle, RedirectLifecycle, TombstoneLifecycle}
)

_SOURCE_SYSTEM_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")


def _require_lifecycle(value: object, *, type_name: str) -> None:
    if type(value) not in _LIFECYCLE_VARIANTS:
        raise _invalid_value_object(
            type_name=type_name,
            field_name="lifecycle",
            reason="value must be an EntityLifecycle variant",
        )


def _require_field_type(
    owner: object,
    value: object,
    expected_type: type,
    *,
    field_name: str,
) -> None:
    if type(value) is not expected_type:
        raise _invalid_value_object(
            type_name=type(owner).__name__,
            field_name=field_name,
            reason=f"value must be a {expected_type.__name__}",
        )


def _require_positive_int(owner: object, value: int, *, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise _invalid_value_object(
            type_name=type(owner).__name__,
            field_name=field_name,
            reason="value must be a positive integer",
        )


def _canonical_media_type(owner: object, value: object) -> str:
    text = _canonical_nonblank(value, type_name=type(owner).__name__, field_name="media_type")
    if text != text.lower():
        raise _invalid_value_object(
            type_name=type(owner).__name__,
            field_name="media_type",
            reason="media_type must be lowercase",
        )
    return text


def _normalize_entity_id_tuple(
    values: Iterable[KnowledgeEntityId],
    *,
    id_set: frozenset[type[TypedId]],
    field_name: str,
) -> tuple[KnowledgeEntityId, ...]:
    normalized: list[KnowledgeEntityId] = []
    for value in values:
        if type(value) not in id_set:
            raise _invalid_value_object(
                type_name=type(value).__name__,
                field_name=field_name,
                reason="value is not an allowed typed entity ID",
            )
        normalized.append(value)
    return tuple(sorted(set(normalized), key=lambda item: item.text))


@dataclass(frozen=True, slots=True)
class Work:
    id: WorkId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, WorkId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Publication:
    id: PublicationId
    work_id: WorkId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, PublicationId, field_name="id")
        _require_field_type(self, self.work_id, WorkId, field_name="work_id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Document:
    id: DocumentId
    publication_id: PublicationId
    content_digest: ContentDigest
    media_type: str
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, DocumentId, field_name="id")
        _require_field_type(self, self.publication_id, PublicationId, field_name="publication_id")
        _require_field_type(self, self.content_digest, ContentDigest, field_name="content_digest")
        media_type = _canonical_media_type(self, self.media_type)
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        object.__setattr__(self, "media_type", media_type)


@dataclass(frozen=True, slots=True)
class Identifier:
    id: IdentifierId
    key: IdentifierKey
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, IdentifierId, field_name="id")
        _require_field_type(self, self.key, IdentifierKey, field_name="key")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Person:
    id: PersonId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, PersonId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Venue:
    id: VenueId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, VenueId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Topic:
    id: TopicId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, TopicId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Method:
    id: MethodId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, MethodId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class ResearchTask:
    id: ResearchTaskId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, ResearchTaskId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class Dataset:
    id: DatasetId
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, DatasetId, field_name="id")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: SourceRecordId
    source_system: str
    source_record_key: str
    retrieved_at: UtcInstant
    payload_digest: ContentDigest
    media_type: str
    accepted_operation: AcceptedOperationAttestation

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, SourceRecordId, field_name="id")
        source_system = _canonical_nonblank(
            self.source_system,
            type_name=type(self).__name__,
            field_name="source_system",
        )
        if _SOURCE_SYSTEM_PATTERN.fullmatch(source_system) is None:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="source_system",
                reason="source_system must match [a-z][a-z0-9_-]{0,63}",
            )
        source_record_key = _canonical_nonblank(
            self.source_record_key,
            type_name=type(self).__name__,
            field_name="source_record_key",
        )
        _require_field_type(self, self.retrieved_at, UtcInstant, field_name="retrieved_at")
        _require_field_type(self, self.payload_digest, ContentDigest, field_name="payload_digest")
        media_type = _canonical_media_type(self, self.media_type)
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
                "source_record",
                (self.id.text,),
                allowed_actions,
                operation.action.value,
            )
        object.__setattr__(self, "source_system", source_system)
        object.__setattr__(self, "source_record_key", source_record_key)
        object.__setattr__(self, "media_type", media_type)


@dataclass(frozen=True, slots=True)
class EvidencePassage:
    id: EvidencePassageId
    source_id: DocumentId | SourceRecordId
    locator: EvidenceLocator
    text: str
    source_language: LanguageTag
    recorded_at: UtcInstant
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, EvidencePassageId, field_name="id")
        if type(self.source_id) not in (DocumentId, SourceRecordId):
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="source_id",
                reason="value must be a DocumentId or SourceRecordId",
            )
        _require_field_type(self, self.locator, EvidenceLocator, field_name="locator")
        text = _canonical_nonblank(self.text, type_name=type(self).__name__, field_name="text")
        _require_field_type(self, self.source_language, LanguageTag, field_name="source_language")
        _require_field_type(self, self.recorded_at, UtcInstant, field_name="recorded_at")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class Claim:
    id: ClaimId
    work_id: WorkId
    statement: str
    language: LanguageTag
    evidence_ids: tuple[EvidencePassageId, ...]
    accepted_review: AcceptedReviewAttestation
    confirmed_at: UtcInstant
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, ClaimId, field_name="id")
        _require_field_type(self, self.work_id, WorkId, field_name="work_id")
        statement = _canonical_nonblank(
            self.statement,
            type_name=type(self).__name__,
            field_name="statement",
        )
        _require_field_type(self, self.language, LanguageTag, field_name="language")
        evidence_ids = _sorted_unique_typed_ids(self.evidence_ids, EvidencePassageId)
        if not evidence_ids:
            raise DomainError(
                code="claim_evidence_required",
                message=f"Claim {self.id.text} requires at least one evidence passage",
                context={"claim_id": self.id.text},
            )
        review = self.accepted_review
        if type(review) is not AcceptedReviewAttestation:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="accepted_review",
                reason="value must be an AcceptedReviewAttestation",
            )
        if review.action is not ReviewAction.CONFIRM_CLAIM:
            raise _attestation_action_mismatch(
                "confirm_claim",
                (self.id.text,),
                ReviewAction.CONFIRM_CLAIM.value,
                review.action.value,
            )
        _require_field_type(self, self.confirmed_at, UtcInstant, field_name="confirmed_at")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        if self.confirmed_at < review.accepted_at:
            raise _attestation_time_invalid(
                "confirm_claim",
                (self.id.text,),
                review.accepted_at.text,
                self.confirmed_at.text,
            )
        binding = ClaimReviewBinding(
            work_id=self.work_id,
            statement=statement,
            language=self.language,
            evidence_ids=evidence_ids,
        )
        computed = compute_review_payload_digest(binding)
        if not _content_digests_equal(computed, review.payload_digest):
            raise _attestation_payload_mismatch(
                "confirm_claim",
                (self.id.text,),
                review.payload_digest.text,
                computed.text,
            )
        object.__setattr__(self, "statement", statement)
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class SemanticRelation:
    id: SemanticRelationId
    predicate: ReviewedSemanticPredicate
    subject_id: KnowledgeEntityId
    object_id: KnowledgeEntityId
    evidence_ids: tuple[EvidencePassageId, ...]
    accepted_review: AcceptedReviewAttestation
    confirmed_at: UtcInstant

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, SemanticRelationId, field_name="id")
        _require_field_type(
            self,
            self.predicate,
            ReviewedSemanticPredicate,
            field_name="predicate",
        )
        _require_id_type(
            self.subject_id,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="subject_id",
        )
        _require_id_type(
            self.object_id,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="object_id",
        )
        subject_id, object_id = canonicalize_relationship(
            self.predicate,
            self.subject_id,
            self.object_id,
        )
        evidence_ids = _sorted_unique_typed_ids(self.evidence_ids, EvidencePassageId)
        if not evidence_ids:
            raise DomainError(
                code="semantic_evidence_required",
                message=(f"SemanticRelation {self.id.text} requires at least one evidence passage"),
                context={"semantic_relation_id": self.id.text},
            )
        review = self.accepted_review
        if type(review) is not AcceptedReviewAttestation:
            raise _invalid_value_object(
                type_name=type(self).__name__,
                field_name="accepted_review",
                reason="value must be an AcceptedReviewAttestation",
            )
        if review.action is not ReviewAction.CONFIRM_SEMANTIC_RELATION:
            raise _attestation_action_mismatch(
                "confirm_semantic_relation",
                (self.id.text,),
                ReviewAction.CONFIRM_SEMANTIC_RELATION.value,
                review.action.value,
            )
        _require_field_type(self, self.confirmed_at, UtcInstant, field_name="confirmed_at")
        if self.confirmed_at < review.accepted_at:
            raise _attestation_time_invalid(
                "confirm_semantic_relation",
                (self.id.text,),
                review.accepted_at.text,
                self.confirmed_at.text,
            )
        binding = SemanticRelationReviewBinding(
            predicate=self.predicate,
            subject_id=cast("KnowledgeEntityId", subject_id),
            object_id=cast("KnowledgeEntityId", object_id),
            evidence_ids=evidence_ids,
        )
        computed = compute_review_payload_digest(binding)
        if not _content_digests_equal(computed, review.payload_digest):
            raise _attestation_payload_mismatch(
                "confirm_semantic_relation",
                (self.id.text,),
                review.payload_digest.text,
                computed.text,
            )
        object.__setattr__(self, "subject_id", subject_id)
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True, slots=True)
class Collection:
    id: CollectionId
    name: str
    member_ids: tuple[KnowledgeEntityId, ...]
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, CollectionId, field_name="id")
        name = _canonical_nonblank(self.name, type_name=type(self).__name__, field_name="name")
        member_ids = _normalize_entity_id_tuple(
            self.member_ids,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="member_ids",
        )
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "member_ids", member_ids)


@dataclass(frozen=True, slots=True)
class Note:
    id: NoteId
    revision: int
    title: str
    body: str
    author: str
    attached_entity_ids: tuple[KnowledgeEntityId, ...]
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, NoteId, field_name="id")
        _require_positive_int(self, self.revision, field_name="revision")
        title = _canonical_nonblank(self.title, type_name=type(self).__name__, field_name="title")
        body = _canonical_nonblank(self.body, type_name=type(self).__name__, field_name="body")
        author = _canonical_nonblank(
            self.author, type_name=type(self).__name__, field_name="author"
        )
        attached_entity_ids = _normalize_entity_id_tuple(
            self.attached_entity_ids,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="attached_entity_ids",
        )
        if not attached_entity_ids:
            raise DomainError(
                code="structural_cardinality_violation",
                message=f"Note {self.id.text} requires at least one attached entity",
                context={
                    "predicate": StructuralPredicate.NOTE_ATTACHED_TO.value,
                    "entity_id": self.id.text,
                    "expected": ">=1",
                    "actual": "0",
                },
            )
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "author", author)
        object.__setattr__(self, "attached_entity_ids", attached_entity_ids)


@dataclass(frozen=True, slots=True)
class TechnicalLineage:
    id: TechnicalLineageId
    name: str
    member_ids: tuple[KnowledgeEntityId, ...]
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, TechnicalLineageId, field_name="id")
        name = _canonical_nonblank(self.name, type_name=type(self).__name__, field_name="name")
        member_ids = _normalize_entity_id_tuple(
            self.member_ids,
            id_set=_ID_TYPE_SETS["knowledge_entity"],
            field_name="member_ids",
        )
        if not member_ids:
            raise DomainError(
                code="structural_cardinality_violation",
                message=f"TechnicalLineage {self.id.text} requires at least one member",
                context={
                    "predicate": StructuralPredicate.LINEAGE_CONTAINS.value,
                    "entity_id": self.id.text,
                    "expected": ">=1",
                    "actual": "0",
                },
            )
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "member_ids", member_ids)


@dataclass(frozen=True, slots=True)
class LineageSynthesis:
    id: LineageSynthesisId
    revision: int
    lineage_id: TechnicalLineageId
    graph_snapshot_digest: ContentDigest
    body: str
    language: LanguageTag
    claim_ids: tuple[ClaimId, ...]
    evidence_ids: tuple[EvidencePassageId, ...]
    created_at: UtcInstant
    lifecycle: EntityLifecycle

    def __post_init__(self) -> None:
        _require_field_type(self, self.id, LineageSynthesisId, field_name="id")
        _require_positive_int(self, self.revision, field_name="revision")
        _require_field_type(self, self.lineage_id, TechnicalLineageId, field_name="lineage_id")
        _require_field_type(
            self,
            self.graph_snapshot_digest,
            ContentDigest,
            field_name="graph_snapshot_digest",
        )
        body = _canonical_nonblank(self.body, type_name=type(self).__name__, field_name="body")
        _require_field_type(self, self.language, LanguageTag, field_name="language")
        claim_ids = _sorted_unique_typed_ids(self.claim_ids, ClaimId)
        evidence_ids = _sorted_unique_typed_ids(self.evidence_ids, EvidencePassageId)
        citation_total = len(claim_ids) + len(evidence_ids)
        if citation_total < 1:
            raise DomainError(
                code="structural_cardinality_violation",
                message=(
                    f"LineageSynthesis {self.id.text} requires at least one cited "
                    "claim or evidence passage"
                ),
                context={
                    "predicate": (
                        StructuralPredicate.SYNTHESIS_CITES_CLAIM.value,
                        StructuralPredicate.SYNTHESIS_CITES_EVIDENCE.value,
                    ),
                    "entity_id": self.id.text,
                    "expected": ">=1",
                    "actual": str(citation_total),
                },
            )
        _require_field_type(self, self.created_at, UtcInstant, field_name="created_at")
        _require_lifecycle(self.lifecycle, type_name=type(self).__name__)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "claim_ids", claim_ids)
        object.__setattr__(self, "evidence_ids", evidence_ids)


LifecycleEntitySnapshot: TypeAlias = (
    Work
    | Publication
    | Document
    | Identifier
    | Person
    | Venue
    | Topic
    | Method
    | ResearchTask
    | Dataset
    | EvidencePassage
    | Claim
    | Collection
    | Note
    | TechnicalLineage
    | LineageSynthesis
)

MergeableEntitySnapshot: TypeAlias = (
    Work | Publication | Identifier | Person | Venue | Topic | Method | ResearchTask | Dataset
)


_SNAPSHOT_ID_TYPES: Mapping[type[LifecycleEntitySnapshot], type[TypedId]] = MappingProxyType(
    {
        Work: WorkId,
        Publication: PublicationId,
        Document: DocumentId,
        Identifier: IdentifierId,
        Person: PersonId,
        Venue: VenueId,
        Topic: TopicId,
        Method: MethodId,
        ResearchTask: ResearchTaskId,
        Dataset: DatasetId,
        EvidencePassage: EvidencePassageId,
        Claim: ClaimId,
        Collection: CollectionId,
        Note: NoteId,
        TechnicalLineage: TechnicalLineageId,
        LineageSynthesis: LineageSynthesisId,
    }
)

_SNAPSHOT_KINDS: Mapping[type[LifecycleEntitySnapshot], EndpointKind] = MappingProxyType(
    {
        Work: EndpointKind.WORK,
        Publication: EndpointKind.PUBLICATION,
        Document: EndpointKind.DOCUMENT,
        Identifier: EndpointKind.IDENTIFIER,
        Person: EndpointKind.PERSON,
        Venue: EndpointKind.VENUE,
        Topic: EndpointKind.TOPIC,
        Method: EndpointKind.METHOD,
        ResearchTask: EndpointKind.RESEARCH_TASK,
        Dataset: EndpointKind.DATASET,
        EvidencePassage: EndpointKind.EVIDENCE_PASSAGE,
        Claim: EndpointKind.CLAIM,
        Collection: EndpointKind.COLLECTION,
        Note: EndpointKind.NOTE,
        TechnicalLineage: EndpointKind.TECHNICAL_LINEAGE,
        LineageSynthesis: EndpointKind.LINEAGE_SYNTHESIS,
    }
)

_MERGEABLE_SNAPSHOT_TYPES: frozenset[type[MergeableEntitySnapshot]] = frozenset(
    {
        Work,
        Publication,
        Identifier,
        Person,
        Venue,
        Topic,
        Method,
        ResearchTask,
        Dataset,
    }
)


@dataclass(frozen=True, slots=True)
class TerminalResolution:
    terminal_id: LifecycleEntityId
    terminal_lifecycle: EntityLifecycle
    path: tuple[LifecycleEntityId, ...]


def _resolve_terminal(
    entity_id: LifecycleEntityId,
    lookup: Mapping[LifecycleEntityId, LifecycleEntitySnapshot],
) -> TerminalResolution:
    path: list[LifecycleEntityId] = [entity_id]
    seen_texts = {entity_id.text}
    current: LifecycleEntityId = entity_id
    while True:
        snapshot = lookup.get(current)
        if snapshot is None:
            raise DomainError(
                code="dangling_redirect",
                message=f"Redirect target {current.text!r} does not exist in the entity index",
                context={"entity_id": current.text, "target_id": current.text},
            )
        lifecycle = snapshot.lifecycle
        if not isinstance(lifecycle, RedirectLifecycle):
            return TerminalResolution(
                terminal_id=current,
                terminal_lifecycle=lifecycle,
                path=tuple(path),
            )
        target = lifecycle.target_id
        if type(target) is not type(current):
            raise DomainError(
                code="redirect_type_mismatch",
                message=(f"Redirect from {current.text!r} changes entity type to {target.text!r}"),
                context={"entity_id": current.text, "target_id": target.text},
            )
        if target.text in seen_texts:
            raise DomainError(
                code="redirect_cycle",
                message=f"Redirect chain revisits {target.text!r}",
                context={"path": tuple(item.text for item in (*path, target))},
            )
        path.append(target)
        seen_texts.add(target.text)
        current = target


def resolve_terminal(
    entity_id: LifecycleEntityId,
    entity_index: EntitySnapshotIndex,
) -> TerminalResolution:
    return _resolve_terminal(entity_id, entity_index.by_id)


@dataclass(frozen=True, slots=True)
class EntitySnapshotIndex:
    by_id: Mapping[LifecycleEntityId, LifecycleEntitySnapshot]


def _verify_document_digests(
    snapshots: Iterable[LifecycleEntitySnapshot],
    lookup: Mapping[LifecycleEntityId, LifecycleEntitySnapshot],
) -> None:
    groups: dict[str, list[Document]] = {}
    for snapshot in snapshots:
        if type(snapshot) is Document:
            groups.setdefault(snapshot.content_digest.text, []).append(snapshot)
    for digest_text in sorted(groups):
        documents = groups[digest_text]
        if len(documents) < 2:
            continue
        ordered = sorted(documents, key=lambda document: document.id.text)
        first, second = ordered[0], ordered[1]
        first_terminal = _resolve_terminal(first.publication_id, lookup)
        second_terminal = _resolve_terminal(second.publication_id, lookup)
        tombstoned = any(isinstance(document.lifecycle, TombstoneLifecycle) for document in ordered)
        if tombstoned or first_terminal.terminal_id == second_terminal.terminal_id:
            raise DomainError(
                code="duplicate_document_digest",
                message=f"Content digest {digest_text!r} is already claimed by another document",
                context={
                    "content_digest": digest_text,
                    "existing_document_id": first.id.text,
                    "requested_document_id": second.id.text,
                    "publication_id": first_terminal.terminal_id.text,
                },
            )
        raise DomainError(
            code="document_publication_conflict",
            message=f"Content digest {digest_text!r} is claimed under different publications",
            context={
                "content_digest": digest_text,
                "existing_document_id": first.id.text,
                "requested_document_id": second.id.text,
                "existing_publication_id": first_terminal.terminal_id.text,
                "requested_publication_id": second_terminal.terminal_id.text,
            },
        )


def build_entity_snapshot_index(
    snapshots: Iterable[LifecycleEntitySnapshot],
) -> EntitySnapshotIndex:
    by_text: dict[str, LifecycleEntitySnapshot] = {}
    for snapshot in snapshots:
        snapshot_type = type(snapshot)
        id_type = _SNAPSHOT_ID_TYPES.get(snapshot_type)
        if id_type is None or type(snapshot.id) is not id_type:
            raise _invalid_value_object(
                type_name=snapshot_type.__name__,
                field_name="id",
                reason="snapshot concrete class does not match its identifier type",
            )
        kind = _SNAPSHOT_KINDS[snapshot_type].value
        lifecycle = snapshot.lifecycle
        if isinstance(lifecycle, RedirectLifecycle):
            if snapshot_type not in _MERGEABLE_SNAPSHOT_TYPES:
                raise DomainError(
                    code="merge_not_supported",
                    message=f"Entity kind {kind!r} does not support redirects",
                    context={"entity_kind": kind},
                )
            if type(lifecycle.target_id) is not id_type:
                raise DomainError(
                    code="redirect_type_mismatch",
                    message=(
                        f"Redirect target {lifecycle.target_id.text!r} does not match "
                        f"entity {snapshot.id.text!r}"
                    ),
                    context={
                        "entity_id": snapshot.id.text,
                        "target_id": lifecycle.target_id.text,
                    },
                )
        key = snapshot.id.text
        if key in by_text:
            raise DomainError(
                code="duplicate_entity_snapshot",
                message=f"Entity ID {key!r} appears more than once in the input",
                context={"entity_id": key, "entity_kind": kind},
            )
        by_text[key] = snapshot
    lookup: dict[LifecycleEntityId, LifecycleEntitySnapshot] = {
        snapshot.id: snapshot for snapshot in by_text.values()
    }
    frozen_lookup = MappingProxyType(lookup)
    for snapshot in lookup.values():
        if isinstance(snapshot.lifecycle, RedirectLifecycle):
            _resolve_terminal(snapshot.id, frozen_lookup)
    _verify_document_digests(lookup.values(), frozen_lookup)
    return EntitySnapshotIndex(by_id=frozen_lookup)


@dataclass(frozen=True, slots=True)
class SourceRecordIndex:
    by_id: Mapping[SourceRecordId, SourceRecord]


def build_source_record_index(records: Iterable[SourceRecord]) -> SourceRecordIndex:
    lookup: dict[SourceRecordId, SourceRecord] = {}
    for record in records:
        if type(record) is not SourceRecord:
            raise _invalid_value_object(
                type_name=type(record).__name__,
                field_name="record",
                reason="value must be a SourceRecord",
            )
        key = record.id.text
        if record.id in lookup:
            raise DomainError(
                code="duplicate_record_id",
                message=f"SourceRecord ID {key!r} appears more than once in the input",
                context={"record_id": key, "record_kind": "source_record"},
            )
        lookup[record.id] = record
    return SourceRecordIndex(by_id=MappingProxyType(lookup))


def _require_entity_index(value: object) -> None:
    if type(value) is not EntitySnapshotIndex:
        raise _invalid_value_object(
            type_name="EntitySnapshotIndex",
            field_name="entity_index",
            reason="value must be an EntitySnapshotIndex",
        )


def _require_source_record_index(value: object) -> None:
    if type(value) is not SourceRecordIndex:
        raise _invalid_value_object(
            type_name="SourceRecordIndex",
            field_name="source_record_index",
            reason="value must be a SourceRecordIndex",
        )


def _require_active_target(
    target_id: LifecycleEntityId,
    predicate: StructuralPredicate,
    subject_id: TypedId,
    entity_index: EntitySnapshotIndex,
    *,
    record_kind: str,
) -> None:
    if target_id not in entity_index.by_id:
        raise DomainError(
            code="dangling_structural_reference",
            message=(
                f"Structural predicate {predicate.value!r} on {subject_id.text!r} references "
                f"missing entity {target_id.text!r}"
            ),
            context={
                "predicate": predicate.value,
                "subject_id": subject_id.text,
                "target_id": target_id.text,
            },
        )
    resolution = resolve_terminal(target_id, entity_index)
    if len(resolution.path) > 1:
        raise DomainError(
            code="noncanonical_write_endpoint",
            message=(
                f"Write endpoints must use active terminal {resolution.terminal_id.text!r} "
                f"instead of redirect loser {target_id.text!r}"
            ),
            context={
                "endpoint_id": target_id.text,
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


def _semantic_relation_lookup(
    semantic_relations: Iterable[SemanticRelation],
) -> dict[str, SemanticRelation]:
    lookup: dict[str, SemanticRelation] = {}
    for relation in semantic_relations:
        if type(relation) is not SemanticRelation:
            raise _invalid_value_object(
                type_name=type(relation).__name__,
                field_name="semantic_relations",
                reason="value must be a SemanticRelation",
            )
        key = relation.id.text
        if key in lookup:
            raise DomainError(
                code="duplicate_record_id",
                message=f"SemanticRelation ID {key!r} appears more than once in the input",
                context={"record_id": key, "record_kind": "semantic_relation"},
            )
        lookup[key] = relation
    return lookup


def _require_member_targets(
    member_ids: tuple[KnowledgeEntityId, ...],
    *,
    predicate: StructuralPredicate,
    subject_id: TypedId,
    entity_index: EntitySnapshotIndex,
    semantic_lookup: Mapping[str, SemanticRelation],
    record_kind: str,
) -> None:
    for member_id in member_ids:
        if isinstance(member_id, SemanticRelationId):
            if member_id.text not in semantic_lookup:
                raise DomainError(
                    code="dangling_structural_reference",
                    message=(
                        f"Structural predicate {predicate.value!r} on {subject_id.text!r} "
                        f"references missing semantic relation {member_id.text!r}"
                    ),
                    context={
                        "predicate": predicate.value,
                        "subject_id": subject_id.text,
                        "target_id": member_id.text,
                    },
                )
            continue
        _require_active_target(
            member_id,
            predicate,
            subject_id,
            entity_index,
            record_kind=record_kind,
        )


def validate_structural_entity(
    entity: LifecycleEntitySnapshot,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> None:
    semantic_lookup = _semantic_relation_lookup(semantic_relations)
    _require_entity_index(entity_index)
    _require_source_record_index(source_record_index)
    if isinstance(entity, Publication):
        _require_active_target(
            entity.work_id,
            StructuralPredicate.PUBLICATION_OF,
            entity.id,
            entity_index,
            record_kind="publication",
        )
    elif isinstance(entity, Document):
        _require_active_target(
            entity.publication_id,
            StructuralPredicate.DOCUMENT_OF,
            entity.id,
            entity_index,
            record_kind="document",
        )
    elif isinstance(entity, EvidencePassage):
        source_id = entity.source_id
        if isinstance(source_id, DocumentId):
            _require_active_target(
                source_id,
                StructuralPredicate.EVIDENCE_FROM,
                entity.id,
                entity_index,
                record_kind="evidence_passage",
            )
        else:
            record = source_record_index.by_id.get(source_id)
            if record is None:
                raise DomainError(
                    code="source_record_not_found",
                    message=(
                        f"EvidencePassage {entity.id.text!r} references missing "
                        f"SourceRecord {source_id.text!r}"
                    ),
                    context={
                        "source_record_id": source_id.text,
                        "record_kind": "evidence_passage",
                        "record_id": entity.id.text,
                    },
                )
            if entity.recorded_at < record.retrieved_at:
                raise DomainError(
                    code="source_asserted_before_retrieval",
                    message=(
                        f"EvidencePassage {entity.id.text!r} was recorded before its "
                        "source record was retrieved"
                    ),
                    context={
                        "source_record_id": source_id.text,
                        "record_id": entity.id.text,
                        "recorded_at": entity.recorded_at.text,
                        "retrieved_at": record.retrieved_at.text,
                    },
                )
    elif isinstance(entity, Claim):
        _require_active_target(
            entity.work_id,
            StructuralPredicate.CLAIM_OF,
            entity.id,
            entity_index,
            record_kind="claim",
        )
        for evidence_id in entity.evidence_ids:
            _require_active_target(
                evidence_id,
                StructuralPredicate.CLAIM_SUPPORTED_BY,
                entity.id,
                entity_index,
                record_kind="claim",
            )
    elif isinstance(entity, Collection):
        _require_member_targets(
            entity.member_ids,
            predicate=StructuralPredicate.COLLECTION_CONTAINS,
            subject_id=entity.id,
            entity_index=entity_index,
            semantic_lookup=semantic_lookup,
            record_kind="collection",
        )
    elif isinstance(entity, Note):
        _require_member_targets(
            entity.attached_entity_ids,
            predicate=StructuralPredicate.NOTE_ATTACHED_TO,
            subject_id=entity.id,
            entity_index=entity_index,
            semantic_lookup=semantic_lookup,
            record_kind="note",
        )
    elif isinstance(entity, TechnicalLineage):
        _require_member_targets(
            entity.member_ids,
            predicate=StructuralPredicate.LINEAGE_CONTAINS,
            subject_id=entity.id,
            entity_index=entity_index,
            semantic_lookup=semantic_lookup,
            record_kind="technical_lineage",
        )
    elif isinstance(entity, LineageSynthesis):
        _require_active_target(
            entity.lineage_id,
            StructuralPredicate.SYNTHESIS_OF,
            entity.id,
            entity_index,
            record_kind="lineage_synthesis",
        )
        for claim_id in entity.claim_ids:
            _require_active_target(
                claim_id,
                StructuralPredicate.SYNTHESIS_CITES_CLAIM,
                entity.id,
                entity_index,
                record_kind="lineage_synthesis",
            )
        for evidence_id in entity.evidence_ids:
            _require_active_target(
                evidence_id,
                StructuralPredicate.SYNTHESIS_CITES_EVIDENCE,
                entity.id,
                entity_index,
                record_kind="lineage_synthesis",
            )


def create_work(work_id: WorkId) -> Work:
    _require_field_type(work_id, work_id, WorkId, field_name="work_id")
    return Work(id=work_id, lifecycle=ActiveLifecycle())


def create_publication(
    publication_id: PublicationId,
    work_id: WorkId,
    entity_index: EntitySnapshotIndex,
) -> Publication:
    _require_field_type(publication_id, publication_id, PublicationId, field_name="publication_id")
    _require_field_type(work_id, work_id, WorkId, field_name="work_id")
    _require_entity_index(entity_index)
    _require_active_target(
        work_id,
        StructuralPredicate.PUBLICATION_OF,
        publication_id,
        entity_index,
        record_kind="publication",
    )
    return Publication(id=publication_id, work_id=work_id, lifecycle=ActiveLifecycle())


def _find_document_by_digest(
    entity_index: EntitySnapshotIndex,
    content_digest: ContentDigest,
) -> Document | None:
    for snapshot in entity_index.by_id.values():
        if type(snapshot) is Document and snapshot.content_digest == content_digest:
            return snapshot
    return None


def create_document(
    document_id: DocumentId,
    publication_id: PublicationId,
    content_digest: ContentDigest,
    media_type: str,
    entity_index: EntitySnapshotIndex,
) -> Document:
    _require_field_type(document_id, document_id, DocumentId, field_name="document_id")
    _require_field_type(publication_id, publication_id, PublicationId, field_name="publication_id")
    _require_field_type(content_digest, content_digest, ContentDigest, field_name="content_digest")
    _canonical_media_type(document_id, media_type)
    _require_entity_index(entity_index)
    _require_active_target(
        publication_id,
        StructuralPredicate.DOCUMENT_OF,
        document_id,
        entity_index,
        record_kind="document",
    )
    existing = _find_document_by_digest(entity_index, content_digest)
    if existing is not None:
        requested_terminal = resolve_terminal(publication_id, entity_index)
        existing_terminal = resolve_terminal(existing.publication_id, entity_index)
        if isinstance(existing.lifecycle, TombstoneLifecycle) or (
            existing_terminal.terminal_id == requested_terminal.terminal_id
        ):
            raise DomainError(
                code="duplicate_document_digest",
                message=(
                    f"Content digest {content_digest.text!r} is already claimed by "
                    f"document {existing.id.text!r}"
                ),
                context={
                    "content_digest": content_digest.text,
                    "existing_document_id": existing.id.text,
                    "requested_document_id": document_id.text,
                    "publication_id": existing_terminal.terminal_id.text,
                },
            )
        raise DomainError(
            code="document_publication_conflict",
            message=(
                f"Content digest {content_digest.text!r} is claimed under a different "
                "publication terminal"
            ),
            context={
                "content_digest": content_digest.text,
                "existing_document_id": existing.id.text,
                "requested_document_id": document_id.text,
                "existing_publication_id": existing_terminal.terminal_id.text,
                "requested_publication_id": requested_terminal.terminal_id.text,
            },
        )
    return Document(
        id=document_id,
        publication_id=publication_id,
        content_digest=content_digest,
        media_type=media_type,
        lifecycle=ActiveLifecycle(),
    )


def create_identifier(identifier_id: IdentifierId, key: IdentifierKey) -> Identifier:
    _require_field_type(identifier_id, identifier_id, IdentifierId, field_name="identifier_id")
    _require_field_type(key, key, IdentifierKey, field_name="key")
    return Identifier(id=identifier_id, key=key, lifecycle=ActiveLifecycle())


def create_person(person_id: PersonId) -> Person:
    _require_field_type(person_id, person_id, PersonId, field_name="person_id")
    return Person(id=person_id, lifecycle=ActiveLifecycle())


def create_venue(venue_id: VenueId) -> Venue:
    _require_field_type(venue_id, venue_id, VenueId, field_name="venue_id")
    return Venue(id=venue_id, lifecycle=ActiveLifecycle())


def create_topic(topic_id: TopicId) -> Topic:
    _require_field_type(topic_id, topic_id, TopicId, field_name="topic_id")
    return Topic(id=topic_id, lifecycle=ActiveLifecycle())


def create_method(method_id: MethodId) -> Method:
    _require_field_type(method_id, method_id, MethodId, field_name="method_id")
    return Method(id=method_id, lifecycle=ActiveLifecycle())


def create_research_task(research_task_id: ResearchTaskId) -> ResearchTask:
    _require_field_type(
        research_task_id, research_task_id, ResearchTaskId, field_name="research_task_id"
    )
    return ResearchTask(id=research_task_id, lifecycle=ActiveLifecycle())


def create_dataset(dataset_id: DatasetId) -> Dataset:
    _require_field_type(dataset_id, dataset_id, DatasetId, field_name="dataset_id")
    return Dataset(id=dataset_id, lifecycle=ActiveLifecycle())


def create_evidence_passage(
    evidence_id: EvidencePassageId,
    source_id: DocumentId | SourceRecordId,
    locator: EvidenceLocator,
    text: str,
    source_language: LanguageTag,
    recorded_at: UtcInstant,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
) -> EvidencePassage:
    _require_field_type(evidence_id, evidence_id, EvidencePassageId, field_name="evidence_id")
    if type(source_id) not in (DocumentId, SourceRecordId):
        raise _invalid_value_object(
            type_name="EvidencePassage",
            field_name="source_id",
            reason="value must be a DocumentId or SourceRecordId",
        )
    _require_field_type(locator, locator, EvidenceLocator, field_name="locator")
    _require_field_type(source_language, source_language, LanguageTag, field_name="source_language")
    _require_field_type(recorded_at, recorded_at, UtcInstant, field_name="recorded_at")
    _require_entity_index(entity_index)
    _require_source_record_index(source_record_index)
    if isinstance(source_id, DocumentId):
        _require_active_target(
            source_id,
            StructuralPredicate.EVIDENCE_FROM,
            evidence_id,
            entity_index,
            record_kind="evidence_passage",
        )
    else:
        record = source_record_index.by_id.get(source_id)
        if record is None:
            raise DomainError(
                code="source_record_not_found",
                message=(
                    f"EvidencePassage {evidence_id.text!r} references missing "
                    f"SourceRecord {source_id.text!r}"
                ),
                context={
                    "source_record_id": source_id.text,
                    "record_kind": "evidence_passage",
                    "record_id": evidence_id.text,
                },
            )
        if recorded_at < record.retrieved_at:
            raise DomainError(
                code="source_asserted_before_retrieval",
                message=(
                    f"EvidencePassage {evidence_id.text!r} was recorded before its "
                    "source record was retrieved"
                ),
                context={
                    "source_record_id": source_id.text,
                    "record_id": evidence_id.text,
                    "recorded_at": recorded_at.text,
                    "retrieved_at": record.retrieved_at.text,
                },
            )
    return EvidencePassage(
        id=evidence_id,
        source_id=source_id,
        locator=locator,
        text=text,
        source_language=source_language,
        recorded_at=recorded_at,
        lifecycle=ActiveLifecycle(),
    )


def create_collection(
    collection_id: CollectionId,
    name: str,
    member_ids: Iterable[KnowledgeEntityId],
    entity_index: EntitySnapshotIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> Collection:
    _require_field_type(collection_id, collection_id, CollectionId, field_name="collection_id")
    _canonical_nonblank(name, type_name="Collection", field_name="name")
    _require_entity_index(entity_index)
    members = tuple(member_ids)
    _require_member_targets(
        members,
        predicate=StructuralPredicate.COLLECTION_CONTAINS,
        subject_id=collection_id,
        entity_index=entity_index,
        semantic_lookup=_semantic_relation_lookup(semantic_relations),
        record_kind="collection",
    )
    return Collection(id=collection_id, name=name, member_ids=members, lifecycle=ActiveLifecycle())


def create_note(
    note_id: NoteId,
    title: str,
    body: str,
    author: str,
    attached_entity_ids: Iterable[KnowledgeEntityId],
    entity_index: EntitySnapshotIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> Note:
    _require_field_type(note_id, note_id, NoteId, field_name="note_id")
    _require_entity_index(entity_index)
    attached = tuple(attached_entity_ids)
    _require_member_targets(
        attached,
        predicate=StructuralPredicate.NOTE_ATTACHED_TO,
        subject_id=note_id,
        entity_index=entity_index,
        semantic_lookup=_semantic_relation_lookup(semantic_relations),
        record_kind="note",
    )
    return Note(
        id=note_id,
        revision=1,
        title=title,
        body=body,
        author=author,
        attached_entity_ids=attached,
        lifecycle=ActiveLifecycle(),
    )


def create_technical_lineage(
    lineage_id: TechnicalLineageId,
    name: str,
    member_ids: Iterable[KnowledgeEntityId],
    entity_index: EntitySnapshotIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> TechnicalLineage:
    _require_field_type(lineage_id, lineage_id, TechnicalLineageId, field_name="lineage_id")
    _require_entity_index(entity_index)
    members = tuple(member_ids)
    _require_member_targets(
        members,
        predicate=StructuralPredicate.LINEAGE_CONTAINS,
        subject_id=lineage_id,
        entity_index=entity_index,
        semantic_lookup=_semantic_relation_lookup(semantic_relations),
        record_kind="technical_lineage",
    )
    return TechnicalLineage(
        id=lineage_id,
        name=name,
        member_ids=members,
        lifecycle=ActiveLifecycle(),
    )


def create_initial_lineage_synthesis(
    synthesis_id: LineageSynthesisId,
    lineage_id: TechnicalLineageId,
    graph_snapshot_digest: ContentDigest,
    body: str,
    language: LanguageTag,
    claim_ids: Iterable[ClaimId],
    evidence_ids: Iterable[EvidencePassageId],
    created_at: UtcInstant,
    entity_index: EntitySnapshotIndex,
) -> LineageSynthesis:
    _require_field_type(synthesis_id, synthesis_id, LineageSynthesisId, field_name="synthesis_id")
    _require_field_type(lineage_id, lineage_id, TechnicalLineageId, field_name="lineage_id")
    _require_field_type(
        graph_snapshot_digest,
        graph_snapshot_digest,
        ContentDigest,
        field_name="graph_snapshot_digest",
    )
    _require_field_type(language, language, LanguageTag, field_name="language")
    _require_field_type(created_at, created_at, UtcInstant, field_name="created_at")
    _require_entity_index(entity_index)
    claims = tuple(claim_ids)
    evidences = tuple(evidence_ids)
    _require_active_target(
        lineage_id,
        StructuralPredicate.SYNTHESIS_OF,
        synthesis_id,
        entity_index,
        record_kind="lineage_synthesis",
    )
    for claim_id in claims:
        _require_active_target(
            claim_id,
            StructuralPredicate.SYNTHESIS_CITES_CLAIM,
            synthesis_id,
            entity_index,
            record_kind="lineage_synthesis",
        )
    for evidence_id in evidences:
        _require_active_target(
            evidence_id,
            StructuralPredicate.SYNTHESIS_CITES_EVIDENCE,
            synthesis_id,
            entity_index,
            record_kind="lineage_synthesis",
        )
    return LineageSynthesis(
        id=synthesis_id,
        revision=1,
        lineage_id=lineage_id,
        graph_snapshot_digest=graph_snapshot_digest,
        body=body,
        language=language,
        claim_ids=claims,
        evidence_ids=evidences,
        created_at=created_at,
        lifecycle=ActiveLifecycle(),
    )


@dataclass(frozen=True, slots=True)
class TombstoneResult:
    snapshot: LifecycleEntitySnapshot
    accepted_operation: AcceptedOperationAttestation
    tombstoned_at: UtcInstant


def replace_entity_snapshot(
    entity_index: EntitySnapshotIndex,
    snapshot: LifecycleEntitySnapshot,
) -> EntitySnapshotIndex:
    old = entity_index.by_id.get(snapshot.id)
    if old is None:
        raise DomainError(
            code="record_input_mismatch",
            message=f"Entity {snapshot.id.text!r} does not exist in the index",
            context={
                "record_id": snapshot.id.text,
                "record_kind": _SNAPSHOT_KINDS[type(snapshot)].value,
            },
        )
    if not isinstance(old.lifecycle, ActiveLifecycle):
        raise DomainError(
            code="invalid_lifecycle_transition",
            message=(
                f"Entity {snapshot.id.text!r} cannot transition from "
                f"{old.lifecycle.tag!r} to {snapshot.lifecycle.tag!r}"
            ),
            context={
                "entity_id": snapshot.id.text,
                "from_lifecycle": old.lifecycle.tag,
                "to_lifecycle": snapshot.lifecycle.tag,
            },
        )
    if not isinstance(snapshot.lifecycle, (RedirectLifecycle, TombstoneLifecycle)):
        raise DomainError(
            code="invalid_lifecycle_transition",
            message=(
                f"Entity {snapshot.id.text!r} only supports active to redirect/tombstone "
                f"transitions, got {snapshot.lifecycle.tag!r}"
            ),
            context={
                "entity_id": snapshot.id.text,
                "from_lifecycle": old.lifecycle.tag,
                "to_lifecycle": snapshot.lifecycle.tag,
            },
        )
    if replace(snapshot, lifecycle=old.lifecycle) != old:
        raise DomainError(
            code="record_input_mismatch",
            message=(
                f"Replacement for {snapshot.id.text!r} differs from the indexed snapshot "
                "beyond its lifecycle"
            ),
            context={
                "record_id": snapshot.id.text,
                "record_kind": _SNAPSHOT_KINDS[type(snapshot)].value,
            },
        )
    updated: dict[LifecycleEntityId, LifecycleEntitySnapshot] = dict(entity_index.by_id)
    updated[snapshot.id] = snapshot
    return build_entity_snapshot_index(updated.values())


def tombstone_entity(
    entity: LifecycleEntitySnapshot,
    accepted_operation: AcceptedOperationAttestation,
    tombstoned_at: UtcInstant,
    entity_index: EntitySnapshotIndex,
) -> TombstoneResult:
    if type(entity) not in _SNAPSHOT_ID_TYPES:
        raise _invalid_value_object(
            type_name=type(entity).__name__,
            field_name="entity",
            reason="value must be a lifecycle entity snapshot",
        )
    _require_field_type(
        accepted_operation,
        accepted_operation,
        AcceptedOperationAttestation,
        field_name="accepted_operation",
    )
    _require_field_type(tombstoned_at, tombstoned_at, UtcInstant, field_name="tombstoned_at")
    _require_entity_index(entity_index)
    old = entity_index.by_id.get(entity.id)
    if old is None or old != entity:
        raise DomainError(
            code="record_input_mismatch",
            message=(
                f"Tombstone target {entity.id.text!r} does not match the unique indexed snapshot"
            ),
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
    if accepted_operation.action is not OperationAction.TOMBSTONE_ENTITY:
        raise _attestation_action_mismatch(
            "tombstone",
            (entity.id.text,),
            OperationAction.TOMBSTONE_ENTITY.value,
            accepted_operation.action.value,
        )
    if accepted_operation.principal_kind is not AttestationPrincipalKind.HUMAN:
        raise _invalid_attestation(
            attestation_kind="operation",
            reason="tombstone requires a named human principal",
        )
    if tombstoned_at < accepted_operation.accepted_at:
        raise _attestation_time_invalid(
            "tombstone",
            (entity.id.text,),
            accepted_operation.accepted_at.text,
            tombstoned_at.text,
        )
    binding = TombstoneOperationBinding(entity_id=entity.id, tombstoned_at=tombstoned_at)
    computed = compute_operation_payload_digest(binding)
    if not _content_digests_equal(computed, accepted_operation.payload_digest):
        raise _attestation_payload_mismatch(
            "tombstone",
            (entity.id.text,),
            accepted_operation.payload_digest.text,
            computed.text,
        )
    replacement = replace(
        entity,
        lifecycle=TombstoneLifecycle(
            accepted_operation=accepted_operation,
            tombstoned_at=tombstoned_at,
        ),
    )
    return TombstoneResult(
        snapshot=replacement,
        accepted_operation=accepted_operation,
        tombstoned_at=tombstoned_at,
    )


__all__ = [
    "METADATA_FIELD_REGISTRY",
    "PREDICATE_REGISTRY",
    "STRUCTURAL_PREDICATE_SOURCE_FIELDS",
    "ActiveLifecycle",
    "Cardinality",
    "Claim",
    "ClaimReviewBinding",
    "Collection",
    "Dataset",
    "Document",
    "EndpointKind",
    "EntityLifecycle",
    "EntitySnapshotIndex",
    "EvidencePassage",
    "ExactMergeOperationBinding",
    "FactualPredicate",
    "FuzzyMergeReviewBinding",
    "HumanMetadataCorrectionBinding",
    "HumanRelationshipCorrectionBinding",
    "HumanRetractionBinding",
    "Identifier",
    "LifecycleEntitySnapshot",
    "LineageSynthesis",
    "MergeableEntitySnapshot",
    "MetadataFieldKey",
    "MetadataFieldSpec",
    "Method",
    "Note",
    "OperationPayloadBinding",
    "Person",
    "Predicate",
    "PredicateKind",
    "PredicateSpec",
    "Publication",
    "RedirectLifecycle",
    "RelationshipKey",
    "ReviewPayloadBinding",
    "ReviewedSemanticPredicate",
    "SemanticRelation",
    "SemanticRelationReviewBinding",
    "SourceRecord",
    "SourceRecordIndex",
    "SourceWriteOperationBinding",
    "StructuralPredicate",
    "TechnicalLineage",
    "TerminalResolution",
    "TombstoneLifecycle",
    "TombstoneOperationBinding",
    "TombstoneResult",
    "Topic",
    "Venue",
    "Work",
    "build_entity_snapshot_index",
    "build_source_record_index",
    "canonicalize_relationship",
    "compute_operation_payload_digest",
    "compute_review_payload_digest",
    "create_collection",
    "create_dataset",
    "create_document",
    "create_evidence_passage",
    "create_identifier",
    "create_initial_lineage_synthesis",
    "create_method",
    "create_note",
    "create_person",
    "create_publication",
    "create_research_task",
    "create_technical_lineage",
    "create_topic",
    "create_venue",
    "create_work",
    "replace_entity_snapshot",
    "resolve_terminal",
    "tombstone_entity",
    "validate_structural_entity",
]
