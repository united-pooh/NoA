"""Contract tests for endpoint/predicate registries, metadata fields, lifecycles,
relationship keys, and payload bindings (spec sections 7.6, 7.8, 7.10, and 10)."""

from datetime import datetime
from typing import get_args

import pytest

from noa.domain.entities import (
    _CANONICAL_BINDING_PREFIX,
    METADATA_FIELD_REGISTRY,
    PREDICATE_REGISTRY,
    STRUCTURAL_PREDICATE_SOURCE_FIELDS,
    ActiveLifecycle,
    Cardinality,
    ClaimReviewBinding,
    EndpointKind,
    EntityLifecycle,
    ExactMergeOperationBinding,
    FactualPredicate,
    FuzzyMergeReviewBinding,
    HumanMetadataCorrectionBinding,
    HumanRelationshipCorrectionBinding,
    HumanRetractionBinding,
    MetadataFieldKey,
    MetadataFieldSpec,
    OperationPayloadBinding,
    Predicate,
    PredicateKind,
    PredicateSpec,
    RedirectLifecycle,
    RelationshipKey,
    ReviewedSemanticPredicate,
    ReviewPayloadBinding,
    SemanticRelationReviewBinding,
    SourceWriteOperationBinding,
    StructuralPredicate,
    TombstoneLifecycle,
    TombstoneOperationBinding,
    _content_digests_equal,
    canonicalize_relationship,
    compute_operation_payload_digest,
    compute_review_payload_digest,
)
from noa.domain.errors import DomainError
from noa.domain.identifiers import (
    AcceptedOperationAttestation,
    AcceptedReviewAttestation,
    AssertionValueKind,
    AttestationPrincipalKind,
    ContentDigest,
    IdentifierScheme,
    LanguageTag,
    OperationAction,
    ReviewAction,
    TextAssertionValue,
    UtcInstant,
    create_accepted_operation_attestation,
    create_accepted_review_attestation,
    normalize_identifier,
)
from noa.domain.ids import (
    ClaimId,
    DocumentId,
    EvidencePassageId,
    PersonId,
    PublicationId,
    RelationshipAssertionId,
    ReviewCandidateId,
    SemanticRelationId,
    SourceRecordId,
    WorkId,
)

HEX_UPPER = "0123456789ABCDEF" * 4
HEX_LOWER = "0123456789abcdef" * 4
VALID_DIGEST = f"sha256:{HEX_LOWER}"

WORK_ID_TEXT = "wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a"
LOSER_WORK_ID_TEXT = "wrk_0198cd4d-0000-7a31-8f25-000000000004"
PERSON_ID_TEXT = "per_0198cd4c-0000-7a31-8f25-000000000003"
EVIDENCE_ID_TEXT = "evp_0198cd4b-0000-7a31-8f25-000000000001"
OTHER_EVIDENCE_ID_TEXT = "evp_0198cd4b-0000-7a31-8f25-000000000002"
PUBLICATION_ID_TEXT = "pub_0198cd53-0000-7a31-8f25-00000000000b"
DOCUMENT_ID_TEXT = "doc_0198cd59-0000-7a31-8f25-000000000011"
CLAIM_A_ID_TEXT = "clm_0198cd57-0000-7a31-8f25-00000000000f"
CLAIM_B_ID_TEXT = "clm_0198cd58-0000-7a31-8f25-000000000010"
COLLECTION_ID_TEXT = "col_0198cd5a-0000-7a31-8f25-000000000012"

GOLDEN_CLAIM_REVIEW_DIGEST = (
    "sha256:d73e6c5b88d5928767d00d7cb1b2af821b6af30f8788b9c4e8ac32f9b01870cc"
)
GOLDEN_TOMBSTONE_OPERATION_DIGEST = (
    "sha256:48c91d73e84840f6867360cfb08e3c500cba49fe271b27a2a1f1348445ee73fe"
)
GOLDEN_FUZZY_MERGE_REVIEW_DIGEST = (
    "sha256:d35ba95181fe2b29bad02f78d603fb5074e7b8ae9ae61c1e3cda0cfb056db2db"
)


def _instant(text: str) -> UtcInstant:
    return UtcInstant.from_datetime(datetime.fromisoformat(text))


def _digest() -> ContentDigest:
    return ContentDigest.parse(VALID_DIGEST)


def _operation_attestation(
    action: OperationAction,
    principal_kind: AttestationPrincipalKind = AttestationPrincipalKind.SERVICE,
    *,
    accepted_at: str = "2026-08-21T00:00:00+00:00",
    operation_reference: str = "op-0001",
    operation_revision: int = 1,
    principal: str | None = None,
    review_event_reference: str = "rev-0001",
) -> AcceptedOperationAttestation:
    if principal is None:
        principal = "svc:noa" if principal_kind is AttestationPrincipalKind.SERVICE else "alice"
    return create_accepted_operation_attestation(
        operation_reference=operation_reference,
        operation_revision=operation_revision,
        action=action,
        principal_kind=principal_kind,
        principal=principal,
        review_event_reference=review_event_reference,
        payload_digest=_digest(),
        accepted_at=_instant(accepted_at),
    )


def _review_attestation(
    action: ReviewAction,
    *,
    accepted_at: str = "2026-08-21T00:00:00+00:00",
    actor: str = "alice",
    candidate_id: ReviewCandidateId | None = None,
    candidate_revision: int = 1,
    review_event_reference: str = "rev-0001",
) -> AcceptedReviewAttestation:
    if candidate_id is None:
        candidate_id = ReviewCandidateId.parse("rvc_0198cd4e-0000-7a31-8f25-000000000005")
    return create_accepted_review_attestation(
        candidate_id=candidate_id,
        candidate_revision=candidate_revision,
        action=action,
        actor=actor,
        review_event_reference=review_event_reference,
        payload_digest=_digest(),
        accepted_at=_instant(accepted_at),
    )


def _work() -> WorkId:
    return WorkId.parse(WORK_ID_TEXT)


# ---------------------------------------------------------------------------
# EndpointKind / PredicateKind / Cardinality display forms (spec 10.1)
# ---------------------------------------------------------------------------


def test_endpoint_kind_is_closed() -> None:
    assert {kind.value for kind in EndpointKind} == {
        "work",
        "publication",
        "document",
        "identifier",
        "person",
        "venue",
        "topic",
        "method",
        "research_task",
        "dataset",
        "source_record",
        "evidence_passage",
        "claim",
        "semantic_relation",
        "collection",
        "note",
        "technical_lineage",
        "lineage_synthesis",
    }

    with pytest.raises(ValueError):
        EndpointKind("organization")


def test_predicate_kind_display_forms() -> None:
    assert {kind.value for kind in PredicateKind} == {
        "structural",
        "factual",
        "reviewed_semantic",
    }

    with pytest.raises(ValueError):
        PredicateKind("semantic")


def test_cardinality_display_forms() -> None:
    assert {card.value for card in Cardinality} == {"1", "0..1", "1..*", "0..*"}
    assert Cardinality.EXACTLY_ONE.value == "1"
    assert Cardinality.ZERO_OR_ONE.value == "0..1"
    assert Cardinality.ONE_OR_MORE.value == "1..*"
    assert Cardinality.ZERO_OR_MORE.value == "0..*"

    with pytest.raises(ValueError):
        Cardinality("at_most_one")


# ---------------------------------------------------------------------------
# PREDICATE_REGISTRY matrix (spec 10.2 / 10.3 / 10.4)
# ---------------------------------------------------------------------------


PREDICATE_TABLE = (
    # --- structural (spec 10.2, registry_order 1..12) ---
    (
        "publication_of",
        "structural",
        (EndpointKind.PUBLICATION,),
        (EndpointKind.WORK,),
        "1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "document_of",
        "structural",
        (EndpointKind.DOCUMENT,),
        (EndpointKind.PUBLICATION,),
        "1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "evidence_from",
        "structural",
        (EndpointKind.EVIDENCE_PASSAGE,),
        (EndpointKind.DOCUMENT, EndpointKind.SOURCE_RECORD),
        "1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "claim_of",
        "structural",
        (EndpointKind.CLAIM,),
        (EndpointKind.WORK,),
        "1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "claim_supported_by",
        "structural",
        (EndpointKind.CLAIM,),
        (EndpointKind.EVIDENCE_PASSAGE,),
        "1..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "semantic_supported_by",
        "structural",
        (EndpointKind.SEMANTIC_RELATION,),
        (EndpointKind.EVIDENCE_PASSAGE,),
        "1..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "collection_contains",
        "structural",
        (EndpointKind.COLLECTION,),
        (
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
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "note_attached_to",
        "structural",
        (EndpointKind.NOTE,),
        (
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
        "1..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "lineage_contains",
        "structural",
        (EndpointKind.TECHNICAL_LINEAGE,),
        (
            EndpointKind.WORK,
            EndpointKind.CLAIM,
            EndpointKind.METHOD,
            EndpointKind.RESEARCH_TASK,
            EndpointKind.DATASET,
            EndpointKind.SEMANTIC_RELATION,
        ),
        "1..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "synthesis_of",
        "structural",
        (EndpointKind.LINEAGE_SYNTHESIS,),
        (EndpointKind.TECHNICAL_LINEAGE,),
        "1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "synthesis_cites_claim",
        "structural",
        (EndpointKind.LINEAGE_SYNTHESIS,),
        (EndpointKind.CLAIM,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "synthesis_cites_evidence",
        "structural",
        (EndpointKind.LINEAGE_SYNTHESIS,),
        (EndpointKind.EVIDENCE_PASSAGE,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    # --- factual (spec 10.3, registry_order 13..20) ---
    (
        "has_identifier",
        "factual",
        (
            EndpointKind.PUBLICATION,
            EndpointKind.DATASET,
            EndpointKind.PERSON,
            EndpointKind.VENUE,
            EndpointKind.TOPIC,
        ),
        (EndpointKind.IDENTIFIER,),
        "0..*",
        "0..1",
        True,
        True,
        False,
    ),
    (
        "observed_identifier",
        "factual",
        (EndpointKind.SOURCE_RECORD,),
        (EndpointKind.IDENTIFIER,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "authored_by",
        "factual",
        (EndpointKind.PUBLICATION,),
        (EndpointKind.PERSON,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "published_in",
        "factual",
        (EndpointKind.PUBLICATION,),
        (EndpointKind.VENUE,),
        "0..1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "cites",
        "factual",
        (EndpointKind.PUBLICATION,),
        (EndpointKind.PUBLICATION,),
        "0..*",
        "0..*",
        True,
        False,
        False,
    ),
    (
        "is_version_of",
        "factual",
        (EndpointKind.PUBLICATION,),
        (EndpointKind.PUBLICATION,),
        "0..1",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "has_topic",
        "factual",
        (EndpointKind.WORK,),
        (EndpointKind.TOPIC,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "describes_dataset",
        "factual",
        (EndpointKind.PUBLICATION,),
        (EndpointKind.DATASET,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    # --- reviewed-semantic (spec 10.4, registry_order 21..30) ---
    (
        "supports",
        "reviewed_semantic",
        (EndpointKind.CLAIM,),
        (EndpointKind.CLAIM,),
        "0..*",
        "0..*",
        True,
        False,
        False,
    ),
    (
        "contradicts",
        "reviewed_semantic",
        (EndpointKind.CLAIM,),
        (EndpointKind.CLAIM,),
        "0..*",
        "0..*",
        True,
        False,
        True,
    ),
    (
        "extends",
        "reviewed_semantic",
        (EndpointKind.WORK,),
        (EndpointKind.WORK,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "improves_on",
        "reviewed_semantic",
        (EndpointKind.WORK,),
        (EndpointKind.WORK,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "compares_with",
        "reviewed_semantic",
        (EndpointKind.WORK,),
        (EndpointKind.WORK,),
        "0..*",
        "0..*",
        True,
        False,
        True,
    ),
    (
        "uses_method",
        "reviewed_semantic",
        (EndpointKind.WORK,),
        (EndpointKind.METHOD,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "addresses_task",
        "reviewed_semantic",
        (EndpointKind.WORK,),
        (EndpointKind.RESEARCH_TASK,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "uses_dataset",
        "reviewed_semantic",
        (EndpointKind.WORK,),
        (EndpointKind.DATASET,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "about_topic",
        "reviewed_semantic",
        (EndpointKind.WORK, EndpointKind.CLAIM),
        (EndpointKind.TOPIC,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
    (
        "derived_from",
        "reviewed_semantic",
        (EndpointKind.METHOD,),
        (EndpointKind.METHOD,),
        "0..*",
        "0..*",
        True,
        True,
        False,
    ),
)


def _resolve_predicate(canonical: str) -> Predicate:
    for enum_type in (StructuralPredicate, FactualPredicate, ReviewedSemanticPredicate):
        try:
            return enum_type(canonical)
        except ValueError:
            continue
    raise AssertionError(f"unknown predicate {canonical!r}")


@pytest.mark.parametrize(
    (
        "canonical",
        "kind",
        "subject_kinds",
        "object_kinds",
        "subject_cardinality",
        "object_cardinality",
        "irreflexive",
        "acyclic",
        "symmetric",
    ),
    PREDICATE_TABLE,
    ids=[row[0] for row in PREDICATE_TABLE],
)
def test_predicate_registry_rows_match_spec(
    canonical: str,
    kind: str,
    subject_kinds: tuple[EndpointKind, ...],
    object_kinds: tuple[EndpointKind, ...],
    subject_cardinality: str,
    object_cardinality: str,
    irreflexive: bool,
    acyclic: bool,
    symmetric: bool,
) -> None:
    predicate = _resolve_predicate(canonical)
    spec = PREDICATE_REGISTRY[predicate]

    assert isinstance(spec, PredicateSpec)
    assert predicate.value == canonical
    assert predicate.name == canonical.upper()
    assert spec.predicate is predicate
    assert spec.kind is PredicateKind(kind)
    assert spec.subject_kinds == subject_kinds
    assert spec.object_kinds == object_kinds
    assert spec.subject_cardinality.value == subject_cardinality
    assert spec.object_cardinality.value == object_cardinality
    assert spec.irreflexive is irreflexive
    assert spec.acyclic is acyclic
    assert spec.symmetric is symmetric
    assert type(spec.registry_order) is int


def test_predicate_registry_order_is_continuous_and_spec_ordered() -> None:
    ordered = sorted(PREDICATE_REGISTRY.values(), key=lambda spec: spec.registry_order)

    assert [spec.registry_order for spec in ordered] == list(range(1, 31))
    assert [spec.kind for spec in ordered] == (
        [PredicateKind.STRUCTURAL] * 12
        + [PredicateKind.FACTUAL] * 8
        + [PredicateKind.REVIEWED_SEMANTIC] * 10
    )
    assert [spec.predicate.value for spec in ordered] == [row[0] for row in PREDICATE_TABLE]


def test_predicate_registry_covers_exactly_the_declared_predicates() -> None:
    all_predicates = (
        set(StructuralPredicate) | set(FactualPredicate) | set(ReviewedSemanticPredicate)
    )

    assert len(PREDICATE_REGISTRY) == 30
    assert set(PREDICATE_REGISTRY) == all_predicates

    with pytest.raises(TypeError):
        PREDICATE_REGISTRY[StructuralPredicate.PUBLICATION_OF] = (  # type: ignore[index]
            PREDICATE_REGISTRY[StructuralPredicate.PUBLICATION_OF]
        )


def test_structural_predicate_is_closed() -> None:
    assert {predicate.value for predicate in StructuralPredicate} == {
        "publication_of",
        "document_of",
        "evidence_from",
        "claim_of",
        "claim_supported_by",
        "semantic_supported_by",
        "collection_contains",
        "note_attached_to",
        "lineage_contains",
        "synthesis_of",
        "synthesis_cites_claim",
        "synthesis_cites_evidence",
    }

    with pytest.raises(ValueError):
        StructuralPredicate("part_of")


# ---------------------------------------------------------------------------
# Structural predicate <-> source field unique mapping (spec 10.5)
# ---------------------------------------------------------------------------


EXPECTED_STRUCTURAL_SOURCES = {
    "publication_of": "work_id",
    "document_of": "publication_id",
    "evidence_from": "source_id",
    "claim_of": "work_id",
    "claim_supported_by": "evidence_ids",
    "semantic_supported_by": "evidence_ids",
    "collection_contains": "member_ids",
    "note_attached_to": "attached_entity_ids",
    "lineage_contains": "member_ids",
    "synthesis_of": "lineage_id",
    "synthesis_cites_claim": "claim_ids",
    "synthesis_cites_evidence": "evidence_ids",
}


def test_structural_predicate_source_fields_match_spec() -> None:
    assert set(STRUCTURAL_PREDICATE_SOURCE_FIELDS) == set(StructuralPredicate)

    for canonical, field_name in EXPECTED_STRUCTURAL_SOURCES.items():
        predicate = StructuralPredicate(canonical)
        assert STRUCTURAL_PREDICATE_SOURCE_FIELDS[predicate] == field_name


# ---------------------------------------------------------------------------
# RelationshipKey and canonicalize_relationship (spec 10.5)
# ---------------------------------------------------------------------------


def test_relationship_key_keeps_canonical_directional_endpoints() -> None:
    key = RelationshipKey(
        predicate=FactualPredicate.AUTHORED_BY,
        subject_id=PublicationId.parse(PUBLICATION_ID_TEXT),
        object_id=PersonId.parse(PERSON_ID_TEXT),
    )

    assert key.subject_id == PublicationId.parse(PUBLICATION_ID_TEXT)
    assert key.object_id == PersonId.parse(PERSON_ID_TEXT)
    assert key.sort_key() == key.sort_key()


def test_relationship_key_accepts_each_declared_object_kind() -> None:
    for object_id in (
        DocumentId.parse(DOCUMENT_ID_TEXT),
        SourceRecordId.parse("src_0198cd50-0000-7a31-8f25-000000000007"),
    ):
        key = RelationshipKey(
            predicate=StructuralPredicate.EVIDENCE_FROM,
            subject_id=EvidencePassageId.parse(EVIDENCE_ID_TEXT),
            object_id=object_id,
        )

        assert key.object_id == object_id


def test_relationship_key_rejects_reversed_directional_endpoints() -> None:
    with pytest.raises(DomainError) as excinfo:
        RelationshipKey(
            predicate=FactualPredicate.AUTHORED_BY,
            subject_id=PersonId.parse(PERSON_ID_TEXT),
            object_id=PublicationId.parse(PUBLICATION_ID_TEXT),
        )

    error = excinfo.value
    assert error.code == "predicate_endpoint_mismatch"
    assert set(error.context) == {"predicate", "subject_kind", "object_kind"}
    assert error.context["predicate"] == "authored_by"
    assert error.context["subject_kind"] == "person"
    assert error.context["object_kind"] == "publication"


def test_relationship_key_canonicalizes_symmetric_endpoints() -> None:
    first = ClaimId.parse(CLAIM_A_ID_TEXT)
    second = ClaimId.parse(CLAIM_B_ID_TEXT)

    forward = RelationshipKey(
        predicate=ReviewedSemanticPredicate.CONTRADICTS,
        subject_id=first,
        object_id=second,
    )
    backward = RelationshipKey(
        predicate=ReviewedSemanticPredicate.CONTRADICTS,
        subject_id=second,
        object_id=first,
    )

    assert forward == backward
    assert hash(forward) == hash(backward)
    assert forward.subject_id == first
    assert forward.object_id == second


def test_relationship_key_rejects_irreflexive_relationship() -> None:
    with pytest.raises(DomainError) as excinfo:
        RelationshipKey(
            predicate=FactualPredicate.CITES,
            subject_id=PublicationId.parse(PUBLICATION_ID_TEXT),
            object_id=PublicationId.parse(PUBLICATION_ID_TEXT),
        )

    error = excinfo.value
    assert error.code == "irreflexive_relationship"
    assert set(error.context) == {"predicate", "entity_id"}
    assert error.context["predicate"] == "cites"
    assert error.context["entity_id"] == PUBLICATION_ID_TEXT


def test_relationship_key_rejects_unknown_predicate() -> None:
    with pytest.raises(DomainError) as excinfo:
        RelationshipKey(
            predicate="author_of",  # type: ignore[arg-type]
            subject_id=PublicationId.parse(PUBLICATION_ID_TEXT),
            object_id=PersonId.parse(PERSON_ID_TEXT),
        )

    error = excinfo.value
    assert error.code == "unknown_predicate"
    assert error.context["predicate"] == "author_of"


def test_canonicalize_relationship_matches_key_construction() -> None:
    first = WorkId.parse(WORK_ID_TEXT)
    second = WorkId.parse(LOSER_WORK_ID_TEXT)

    assert canonicalize_relationship(ReviewedSemanticPredicate.COMPARES_WITH, second, first) == (
        first,
        second,
    )
    assert canonicalize_relationship(
        FactualPredicate.AUTHORED_BY,
        PublicationId.parse(PUBLICATION_ID_TEXT),
        PersonId.parse(PERSON_ID_TEXT),
    ) == (
        PublicationId.parse(PUBLICATION_ID_TEXT),
        PersonId.parse(PERSON_ID_TEXT),
    )


# ---------------------------------------------------------------------------
# MetadataFieldKey / MetadataFieldSpec / METADATA_FIELD_REGISTRY (spec 7.6)
# ---------------------------------------------------------------------------


FIELD_TABLE = (
    ("work.title", EndpointKind.WORK, AssertionValueKind.TEXT, True, None, ()),
    ("work.abstract", EndpointKind.WORK, AssertionValueKind.TEXT, True, None, ()),
    ("work.year", EndpointKind.WORK, AssertionValueKind.INTEGER, False, (0, 9999), ()),
    ("work.language", EndpointKind.WORK, AssertionValueKind.LANGUAGE, False, None, ()),
    ("publication.title", EndpointKind.PUBLICATION, AssertionValueKind.TEXT, True, None, ()),
    ("publication.abstract", EndpointKind.PUBLICATION, AssertionValueKind.TEXT, True, None, ()),
    (
        "publication.year",
        EndpointKind.PUBLICATION,
        AssertionValueKind.INTEGER,
        False,
        (0, 9999),
        (),
    ),
    (
        "publication.language",
        EndpointKind.PUBLICATION,
        AssertionValueKind.LANGUAGE,
        False,
        None,
        (),
    ),
    ("publication.volume", EndpointKind.PUBLICATION, AssertionValueKind.TEXT, False, None, ()),
    ("publication.issue", EndpointKind.PUBLICATION, AssertionValueKind.TEXT, False, None, ()),
    ("publication.pages", EndpointKind.PUBLICATION, AssertionValueKind.TEXT, False, None, ()),
    ("publication.publisher", EndpointKind.PUBLICATION, AssertionValueKind.TEXT, True, None, ()),
    ("document.language", EndpointKind.DOCUMENT, AssertionValueKind.LANGUAGE, False, None, ()),
    ("person.display_name", EndpointKind.PERSON, AssertionValueKind.TEXT, True, None, ()),
    ("person.given_name", EndpointKind.PERSON, AssertionValueKind.TEXT, True, None, ()),
    ("person.family_name", EndpointKind.PERSON, AssertionValueKind.TEXT, True, None, ()),
    ("venue.name", EndpointKind.VENUE, AssertionValueKind.TEXT, True, None, ()),
    ("venue.abbreviated_name", EndpointKind.VENUE, AssertionValueKind.TEXT, True, None, ()),
    ("venue.publisher", EndpointKind.VENUE, AssertionValueKind.TEXT, True, None, ()),
    (
        "venue.type",
        EndpointKind.VENUE,
        AssertionValueKind.TEXT,
        False,
        None,
        ("journal", "conference", "repository", "book_series", "ebook_platform", "other"),
    ),
    ("topic.label", EndpointKind.TOPIC, AssertionValueKind.TEXT, True, None, ()),
    ("topic.description", EndpointKind.TOPIC, AssertionValueKind.TEXT, True, None, ()),
    ("method.label", EndpointKind.METHOD, AssertionValueKind.TEXT, True, None, ()),
    ("method.description", EndpointKind.METHOD, AssertionValueKind.TEXT, True, None, ()),
    ("research_task.label", EndpointKind.RESEARCH_TASK, AssertionValueKind.TEXT, True, None, ()),
    (
        "research_task.description",
        EndpointKind.RESEARCH_TASK,
        AssertionValueKind.TEXT,
        True,
        None,
        (),
    ),
    ("dataset.name", EndpointKind.DATASET, AssertionValueKind.TEXT, True, None, ()),
    ("dataset.description", EndpointKind.DATASET, AssertionValueKind.TEXT, True, None, ()),
    ("dataset.version", EndpointKind.DATASET, AssertionValueKind.TEXT, False, None, ()),
)


@pytest.mark.parametrize(
    ("key_name", "target_kind", "value_kind", "language_scoped", "integer_range", "allowed"),
    FIELD_TABLE,
    ids=[row[0] for row in FIELD_TABLE],
)
def test_metadata_field_registry_rows_match_spec(
    key_name: str,
    target_kind: EndpointKind,
    value_kind: AssertionValueKind,
    language_scoped: bool,
    integer_range: tuple[int, int] | None,
    allowed: tuple[str, ...],
) -> None:
    key = MetadataFieldKey(key_name)
    spec = METADATA_FIELD_REGISTRY[key]

    assert isinstance(spec, MetadataFieldSpec)
    assert spec.key is key
    assert spec.target_kind is target_kind
    assert spec.value_kind is value_kind
    assert spec.language_scoped is language_scoped
    assert spec.integer_range == integer_range
    assert spec.allowed_text_values == allowed


def test_metadata_field_registry_covers_exactly_the_declared_fields() -> None:
    assert len(METADATA_FIELD_REGISTRY) == 29
    assert set(METADATA_FIELD_REGISTRY) == set(MetadataFieldKey)

    with pytest.raises(TypeError):
        METADATA_FIELD_REGISTRY[MetadataFieldKey.WORK_TITLE] = (  # type: ignore[index]
            METADATA_FIELD_REGISTRY[MetadataFieldKey.WORK_TITLE]
        )


def test_metadata_field_key_is_closed_to_declared_members() -> None:
    with pytest.raises(ValueError):
        MetadataFieldKey("work.subtitle")


# ---------------------------------------------------------------------------
# EntityLifecycle variants (spec 7.8)
# ---------------------------------------------------------------------------


def test_active_lifecycle_has_tag_and_no_fields() -> None:
    lifecycle = ActiveLifecycle()

    assert lifecycle.tag == "active"
    assert ActiveLifecycle() == lifecycle


def test_redirect_lifecycle_accepts_exact_merge_operation_attestation() -> None:
    lifecycle = RedirectLifecycle(
        target_id=_work(),
        transition_attestation=_operation_attestation(OperationAction.MERGE_EXACT_IDENTITY),
        redirected_at=_instant("2026-08-21T01:00:00+00:00"),
    )

    assert lifecycle.tag == "redirect"
    assert lifecycle.target_id == _work()


def test_redirect_lifecycle_accepts_fuzzy_merge_review_attestation() -> None:
    lifecycle = RedirectLifecycle(
        target_id=_work(),
        transition_attestation=_review_attestation(ReviewAction.MERGE_FUZZY),
        redirected_at=_instant("2026-08-21T01:00:00+00:00"),
    )

    assert lifecycle.tag == "redirect"


def test_redirect_lifecycle_allows_equal_timestamps() -> None:
    lifecycle = RedirectLifecycle(
        target_id=_work(),
        transition_attestation=_operation_attestation(OperationAction.MERGE_EXACT_IDENTITY),
        redirected_at=_instant("2026-08-21T00:00:00+00:00"),
    )

    assert lifecycle.redirected_at == _instant("2026-08-21T00:00:00+00:00")


@pytest.mark.parametrize(
    "attestation",
    [
        _operation_attestation(OperationAction.HUMAN_CORRECTION, AttestationPrincipalKind.HUMAN),
        _operation_attestation(OperationAction.SOURCE_INGEST),
        _review_attestation(ReviewAction.CONFIRM_CLAIM),
        _review_attestation(ReviewAction.CONFIRM_SEMANTIC_RELATION),
    ],
)
def test_redirect_lifecycle_rejects_mismatched_action(
    attestation: AcceptedOperationAttestation | AcceptedReviewAttestation,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        RedirectLifecycle(
            target_id=_work(),
            transition_attestation=attestation,
            redirected_at=_instant("2026-08-21T01:00:00+00:00"),
        )

    error = excinfo.value
    assert error.code == "attestation_action_mismatch"
    assert set(error.context) == {
        "operation_kind",
        "subject_ids",
        "expected_action",
        "actual_action",
    }
    assert error.context["operation_kind"] == "redirect"


def test_redirect_lifecycle_rejects_redirect_before_acceptance() -> None:
    with pytest.raises(DomainError) as excinfo:
        RedirectLifecycle(
            target_id=_work(),
            transition_attestation=_operation_attestation(
                OperationAction.MERGE_EXACT_IDENTITY,
                accepted_at="2026-08-21T02:00:00+00:00",
            ),
            redirected_at=_instant("2026-08-21T01:00:00+00:00"),
        )

    error = excinfo.value
    assert error.code == "attestation_time_invalid"
    assert set(error.context) == {"operation_kind", "subject_ids", "accepted_at", "recorded_at"}
    assert error.context["accepted_at"] == "2026-08-21T02:00:00Z"
    assert error.context["recorded_at"] == "2026-08-21T01:00:00Z"


@pytest.mark.parametrize(
    "target_id",
    [
        SemanticRelationId.parse("sem_0198cd4f-0000-7a31-8f25-000000000006"),
        SourceRecordId.parse("src_0198cd50-0000-7a31-8f25-000000000007"),
    ],
)
def test_redirect_lifecycle_rejects_non_lifecycle_target(target_id: object) -> None:
    with pytest.raises(DomainError) as excinfo:
        RedirectLifecycle(
            target_id=target_id,  # type: ignore[arg-type]
            transition_attestation=_operation_attestation(OperationAction.MERGE_EXACT_IDENTITY),
            redirected_at=_instant("2026-08-21T01:00:00+00:00"),
        )

    assert excinfo.value.code == "invalid_value_object"


def test_tombstone_lifecycle_accepts_human_tombstone_operation() -> None:
    operation = _operation_attestation(
        OperationAction.TOMBSTONE_ENTITY, AttestationPrincipalKind.HUMAN
    )
    lifecycle = TombstoneLifecycle(
        accepted_operation=operation,
        tombstoned_at=_instant("2026-08-21T01:00:00+00:00"),
    )

    assert lifecycle.tag == "tombstone"
    assert lifecycle.accepted_operation is operation


def test_tombstone_lifecycle_rejects_wrong_action() -> None:
    with pytest.raises(DomainError) as excinfo:
        TombstoneLifecycle(
            accepted_operation=_operation_attestation(
                OperationAction.RETRACT_RECORD, AttestationPrincipalKind.HUMAN
            ),
            tombstoned_at=_instant("2026-08-21T01:00:00+00:00"),
        )

    error = excinfo.value
    assert error.code == "attestation_action_mismatch"
    assert set(error.context) == {
        "operation_kind",
        "subject_ids",
        "expected_action",
        "actual_action",
    }
    assert error.context["operation_kind"] == "tombstone"
    assert error.context["expected_action"] == "tombstone_entity"


def test_tombstone_lifecycle_rejects_tombstone_before_acceptance() -> None:
    with pytest.raises(DomainError) as excinfo:
        TombstoneLifecycle(
            accepted_operation=_operation_attestation(
                OperationAction.TOMBSTONE_ENTITY,
                AttestationPrincipalKind.HUMAN,
                accepted_at="2026-08-21T02:00:00+00:00",
            ),
            tombstoned_at=_instant("2026-08-21T01:00:00+00:00"),
        )

    assert excinfo.value.code == "attestation_time_invalid"
    assert set(excinfo.value.context) == {
        "operation_kind",
        "subject_ids",
        "accepted_at",
        "recorded_at",
    }


def test_entity_lifecycle_union_has_exactly_three_variants() -> None:
    args = get_args(EntityLifecycle)

    assert set(args) == {ActiveLifecycle, RedirectLifecycle, TombstoneLifecycle}


# ---------------------------------------------------------------------------
# noa-binding-v1 encoder, payload bindings, and digest computation (spec 7.10)
# ---------------------------------------------------------------------------


def test_encoder_prefix_and_scalar_framing() -> None:
    assert _CANONICAL_BINDING_PREFIX == b"noa-binding-v1\0"
    assert callable(compute_review_payload_digest)
    assert callable(compute_operation_payload_digest)


def test_scalar_framing_uses_eight_hex_byte_length_and_ascii_colon() -> None:
    from noa.domain.entities import _encode_canonical_scalar

    assert _encode_canonical_scalar("hello") == b"00000005:hello"
    assert _encode_canonical_scalar("") == b"00000000:"
    assert _encode_canonical_scalar("é") == b"00000002:\xc3\xa9"
    assert _encode_canonical_scalar(True) == b"00000004:true"
    assert _encode_canonical_scalar(42) == b"00000002:42"
    assert _encode_canonical_scalar(-7) == b"00000002:-7"


def test_tuple_encoding_sorts_by_canonical_text_and_prefixes_the_count() -> None:
    from noa.domain.entities import _encode_canonical_tuple

    first = WorkId.parse(WORK_ID_TEXT)
    second = WorkId.parse(LOSER_WORK_ID_TEXT)
    first_frame = b"00000028:" + WORK_ID_TEXT.encode("ascii")
    second_frame = b"00000028:" + LOSER_WORK_ID_TEXT.encode("ascii")

    encoded = _encode_canonical_tuple((second, first))

    assert encoded == b"00000002:" + first_frame + second_frame


def test_claim_review_binding_golden_digest() -> None:
    binding = ClaimReviewBinding(
        work_id=WorkId.parse(WORK_ID_TEXT),
        statement="Cats sleep more than dogs",
        language=LanguageTag.parse("en"),
        evidence_ids=(
            EvidencePassageId.parse(OTHER_EVIDENCE_ID_TEXT),
            EvidencePassageId.parse(EVIDENCE_ID_TEXT),
        ),
    )

    assert compute_review_payload_digest(binding).text == GOLDEN_CLAIM_REVIEW_DIGEST


def test_claim_review_binding_digest_ignores_evidence_order_and_duplicates() -> None:
    evidence_a = EvidencePassageId.parse(EVIDENCE_ID_TEXT)
    evidence_b = EvidencePassageId.parse(OTHER_EVIDENCE_ID_TEXT)
    base = ClaimReviewBinding(
        work_id=WorkId.parse(WORK_ID_TEXT),
        statement="Cats sleep more than dogs",
        language=LanguageTag.parse("en"),
        evidence_ids=(evidence_a, evidence_b),
    )
    reordered = ClaimReviewBinding(
        work_id=WorkId.parse(WORK_ID_TEXT),
        statement="Cats sleep more than dogs",
        language=LanguageTag.parse("en"),
        evidence_ids=(evidence_b, evidence_a, evidence_a),
    )

    assert reordered.evidence_ids == (evidence_a, evidence_b)
    assert compute_review_payload_digest(reordered) == compute_review_payload_digest(base)
    assert compute_review_payload_digest(base).text == GOLDEN_CLAIM_REVIEW_DIGEST


def test_tombstone_operation_binding_golden_digest() -> None:
    binding = TombstoneOperationBinding(
        entity_id=PersonId.parse(PERSON_ID_TEXT),
        tombstoned_at=_instant("2026-08-21T12:30:45+00:00"),
    )

    assert compute_operation_payload_digest(binding).text == GOLDEN_TOMBSTONE_OPERATION_DIGEST


def test_fuzzy_merge_review_binding_golden_digest() -> None:
    binding = FuzzyMergeReviewBinding(
        survivor_id=WorkId.parse(WORK_ID_TEXT),
        loser_id=WorkId.parse(LOSER_WORK_ID_TEXT),
    )

    assert compute_review_payload_digest(binding).text == GOLDEN_FUZZY_MERGE_REVIEW_DIGEST


def test_source_write_operation_binding_round_trips_digest_text() -> None:
    binding = SourceWriteOperationBinding(proposal_digest=_digest())

    recomputed = compute_operation_payload_digest(
        SourceWriteOperationBinding(proposal_digest=_digest())
    )

    assert compute_operation_payload_digest(binding) == recomputed
    assert recomputed != _digest()


def test_symmetric_semantic_review_binding_canonicalizes_endpoints() -> None:
    subject = WorkId.parse(WORK_ID_TEXT)
    obj = WorkId.parse(LOSER_WORK_ID_TEXT)

    forward = SemanticRelationReviewBinding(
        predicate=ReviewedSemanticPredicate.COMPARES_WITH,
        subject_id=subject,
        object_id=obj,
        evidence_ids=(),
    )
    backward = SemanticRelationReviewBinding(
        predicate=ReviewedSemanticPredicate.COMPARES_WITH,
        subject_id=obj,
        object_id=subject,
        evidence_ids=(),
    )

    assert forward.subject_id == subject
    assert forward.object_id == obj
    assert compute_review_payload_digest(forward) == compute_review_payload_digest(backward)

    directional = SemanticRelationReviewBinding(
        predicate=ReviewedSemanticPredicate.EXTENDS,
        subject_id=obj,
        object_id=subject,
        evidence_ids=(),
    )
    assert directional.subject_id == obj
    assert directional.object_id == subject


def test_human_metadata_correction_binding_normalizes_fields() -> None:
    binding = HumanMetadataCorrectionBinding(
        subject_id=_work(),
        field=MetadataFieldKey.WORK_TITLE,
        value=TextAssertionValue.create("  A  title  ", LanguageTag.parse("EN")),
        asserted_at=_instant("2026-08-21T00:00:00+00:00"),
    )

    value = binding.value
    assert isinstance(value, TextAssertionValue)
    assert value.text == "A  title"
    assert value.language.text == "en"
    assert compute_operation_payload_digest(binding).text.startswith("sha256:")


def test_human_retraction_binding_requires_nonblank_reason() -> None:
    binding = HumanRetractionBinding(
        target_id=SemanticRelationId.parse("sem_0198cd4f-0000-7a31-8f25-000000000006"),
        reason="  duplicated  ",
        retracted_at=_instant("2026-08-21T00:00:00+00:00"),
    )

    assert binding.reason == "duplicated"

    with pytest.raises(DomainError):
        HumanRetractionBinding(
            target_id=SemanticRelationId.parse("sem_0198cd4f-0000-7a31-8f25-000000000006"),
            reason="   ",
            retracted_at=_instant("2026-08-21T00:00:00+00:00"),
        )


def test_exact_merge_operation_binding_sorts_supporting_assertions() -> None:
    first = RelationshipAssertionId.parse("ras_0198cd51-0000-7a31-8f25-000000000008")
    second = RelationshipAssertionId.parse("ras_0198cd51-0000-7a31-8f25-000000000009")
    binding = ExactMergeOperationBinding(
        survivor_id=PersonId.parse(PERSON_ID_TEXT),
        loser_id=PersonId.parse("per_0198cd52-0000-7a31-8f25-00000000000a"),
        identifier_key=normalize_identifier(IdentifierScheme.ORCID, "0000-0002-1825-0097"),
        supporting_assertion_ids=(second, first, second),
        merged_at=_instant("2026-08-21T00:00:00+00:00"),
    )

    assert binding.supporting_assertion_ids == (first, second)
    assert compute_operation_payload_digest(binding).text.startswith("sha256:")


def test_human_relationship_correction_binding_accepts_factual_predicates() -> None:
    binding = HumanRelationshipCorrectionBinding(
        predicate=FactualPredicate.AUTHORED_BY,
        subject_id=PublicationId.parse(PUBLICATION_ID_TEXT),
        object_id=PersonId.parse(PERSON_ID_TEXT),
        asserted_at=_instant("2026-08-21T00:00:00+00:00"),
    )

    assert compute_operation_payload_digest(binding).text.startswith("sha256:")


def test_binding_unions_have_exact_variants() -> None:
    assert set(get_args(ReviewPayloadBinding)) == {
        ClaimReviewBinding,
        SemanticRelationReviewBinding,
        FuzzyMergeReviewBinding,
    }
    assert set(get_args(OperationPayloadBinding)) == {
        SourceWriteOperationBinding,
        HumanMetadataCorrectionBinding,
        HumanRelationshipCorrectionBinding,
        HumanRetractionBinding,
        ExactMergeOperationBinding,
        TombstoneOperationBinding,
    }


def test_compute_functions_reject_unknown_binding_variants() -> None:
    with pytest.raises(DomainError):
        compute_review_payload_digest("not-a-binding")  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        compute_operation_payload_digest(None)  # type: ignore[arg-type]


def test_digest_comparison_helper_is_exact_and_type_safe() -> None:
    left = ContentDigest.parse(VALID_DIGEST)
    same = ContentDigest.parse(f"sha256:{HEX_UPPER}")
    other = ContentDigest.parse("sha256:" + "ff" * 32)

    assert _content_digests_equal(left, same) is True
    assert _content_digests_equal(left, other) is False
    assert _content_digests_equal(left, "sha256:") is False  # type: ignore[arg-type]
