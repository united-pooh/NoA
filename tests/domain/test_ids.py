"""Contract tests for typed UUIDv7 identifiers (spec sections 6 and 15)."""

import importlib.metadata
import inspect
import uuid
from typing import get_args
from uuid import RFC_4122, UUID

import pytest
import uuid6

import noa.domain.ids as ids_module
from noa.domain.errors import DomainError
from noa.domain.ids import (
    ID_PREFIX_REGISTRY,
    AssertionRetractionId,
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
    MetadataAssertionId,
    MethodId,
    NoteId,
    PersonId,
    ProvenanceRecordId,
    PublicationId,
    RelationshipAssertionId,
    RelationshipEndpointId,
    ResearchRunId,
    ResearchTaskId,
    ReviewCandidateId,
    SemanticRelationId,
    SourceRecordId,
    TechnicalLineageId,
    TopicId,
    TypedId,
    VenueId,
    WorkId,
    generate_uuid7_value,
)

UUID_V7 = UUID("0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a")
UUID_V1 = UUID("cdbba890-2f4b-1a31-8f25-5f2ca3b77b3a")
UUID_V4 = UUID("0198cd4a-2f4b-4a31-8f25-5f2ca3b77b3a")
UUID_V6 = UUID("0198cd4a-2f4b-6a31-bf25-5f2ca3b77b3a")
UUID_V8 = UUID("0198cd4a-2f4b-8a31-8f25-5f2ca3b77b3a")

ID_TABLE: tuple[tuple[str, type[TypedId]], ...] = (
    ("wrk", WorkId),
    ("pub", PublicationId),
    ("doc", DocumentId),
    ("idn", IdentifierId),
    ("per", PersonId),
    ("ven", VenueId),
    ("top", TopicId),
    ("mth", MethodId),
    ("tsk", ResearchTaskId),
    ("dts", DatasetId),
    ("src", SourceRecordId),
    ("mas", MetadataAssertionId),
    ("ras", RelationshipAssertionId),
    ("ret", AssertionRetractionId),
    ("clm", ClaimId),
    ("evp", EvidencePassageId),
    ("sem", SemanticRelationId),
    ("rvc", ReviewCandidateId),
    ("col", CollectionId),
    ("nte", NoteId),
    ("lin", TechnicalLineageId),
    ("syn", LineageSynthesisId),
    ("run", ResearchRunId),
)


@pytest.mark.parametrize(("prefix", "id_class"), ID_TABLE, ids=[row[0] for row in ID_TABLE])
def test_from_uuid7_and_parse_round_trip_canonically(
    prefix: str,
    id_class: type[TypedId],
) -> None:
    instance = id_class.from_uuid7(UUID_V7)

    assert instance.uuid_value == UUID_V7
    assert instance.text == f"{prefix}_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a"
    assert str(instance) == instance.text

    parsed = id_class.parse(instance.text)

    assert parsed == instance
    assert hash(parsed) == hash(instance)
    assert parsed.sort_key() == instance.sort_key() == instance.text


@pytest.mark.parametrize(("prefix", "id_class"), ID_TABLE, ids=[row[0] for row in ID_TABLE])
def test_sort_key_is_stable_across_calls(prefix: str, id_class: type[TypedId]) -> None:
    del prefix

    instance = id_class.from_uuid7(UUID_V7)
    other = id_class.parse(f"{id_class.PREFIX}_0198cd4b-0000-7a31-8f25-000000000009")

    assert instance.sort_key() == instance.sort_key()
    assert other.sort_key() == other.sort_key()
    assert sorted([other, instance], key=lambda item: item.sort_key()) == [instance, other]


@pytest.mark.parametrize(
    "text",
    [
        "wrk_0198CD4A-2F4B-7A31-8F25-5F2CA3B77B3A",
        "wrk_0198cd4a2f4b7a318f255f2ca3b77b3a",
        "wrk_{0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a}",
        "urn:uuid:0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a",
        " wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a",
        "wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a ",
        "wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3",
        "wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3aa",
        "wrk_",
        "wrk_0198cd4a-2f4b-1a31-8f25-5f2ca3b77b3a",
        "wrk_0198cd4a-2f4b-4a31-8f25-5f2ca3b77b3a",
        "wrk_0198cd4a-2f4b-6a31-bf25-5f2ca3b77b3a",
        "wrk_0198cd4a-2f4b-8a31-8f25-5f2ca3b77b3a",
        "wrk_0198cd4a-2f4b-7a31-cf25-5f2ca3b77b3a",
        "wrk_0198cd4a_2f4b_7a31_8f25_5f2ca3b77b3a",
    ],
)
def test_parse_rejects_malformed_or_non_v7_text_with_stable_error(text: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        WorkId.parse(text)

    error = excinfo.value
    assert error.code in {"invalid_typed_id", "id_prefix_mismatch"}
    if error.code == "invalid_typed_id":
        assert set(error.context) == {"expected_prefix", "value", "reason"}
        assert error.context["expected_prefix"] == "wrk"
    else:
        assert set(error.context) == {"expected_prefix", "actual_prefix"}
        assert error.context["expected_prefix"] == "wrk"


def test_parse_rejects_wrong_prefix_with_id_prefix_mismatch() -> None:
    with pytest.raises(DomainError) as excinfo:
        WorkId.parse(f"pub_{UUID_V7}")

    error = excinfo.value
    assert error.code == "id_prefix_mismatch"
    assert set(error.context) == {"expected_prefix", "actual_prefix"}
    assert error.context["expected_prefix"] == "wrk"
    assert error.context["actual_prefix"] == "pub"

    with pytest.raises(DomainError) as reverse_excinfo:
        PublicationId.parse(f"wrk_{UUID_V7}")

    assert reverse_excinfo.value.code == "id_prefix_mismatch"
    assert reverse_excinfo.value.context["expected_prefix"] == "pub"
    assert reverse_excinfo.value.context["actual_prefix"] == "wrk"


@pytest.mark.parametrize("bad_uuid", [UUID_V1, UUID_V4, UUID_V6, UUID_V8])
def test_from_uuid7_rejects_non_v7_uuid_objects(bad_uuid: UUID) -> None:
    with pytest.raises(DomainError) as excinfo:
        WorkId.from_uuid7(bad_uuid)

    error = excinfo.value
    assert error.code == "invalid_typed_id"
    assert set(error.context) == {"expected_prefix", "value", "reason"}
    assert error.context["expected_prefix"] == "wrk"


def test_from_uuid7_rejects_non_uuid_input() -> None:
    with pytest.raises(DomainError) as excinfo:
        WorkId.from_uuid7(f"wrk_{UUID_V7}")  # type: ignore[arg-type]

    error = excinfo.value
    assert error.code == "invalid_typed_id"
    assert set(error.context) == {"expected_prefix", "value", "reason"}


def test_generate_uuid7_value_returns_rfc9562_uuidv7() -> None:
    value = generate_uuid7_value()

    assert isinstance(value, UUID)
    assert value.version == 7
    assert value.variant == RFC_4122


def test_generate_uuid7_value_calls_uuid6_uuid7_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[UUID] = []

    def fake_uuid7() -> UUID:
        calls.append(UUID_V7)
        return UUID_V7

    monkeypatch.setattr(uuid6, "uuid7", fake_uuid7)

    assert generate_uuid7_value() == UUID_V7
    assert len(calls) == 1


def test_generate_uuid7_value_rejects_non_v7_entropy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uuid6, "uuid7", lambda: UUID_V4)

    with pytest.raises(DomainError) as excinfo:
        generate_uuid7_value()

    assert excinfo.value.code == "invalid_typed_id"


def test_no_uuid4_fallback_in_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> UUID:
        raise AssertionError("uuid.uuid4 must never be used as an entropy source")

    monkeypatch.setattr(uuid, "uuid4", explode)
    value = generate_uuid7_value()

    assert value.version == 7


def test_typed_id_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        TypedId(uuid_value=UUID_V7)

    with pytest.raises(TypeError):
        TypedId.from_uuid7(UUID_V7)

    with pytest.raises(TypeError):
        TypedId.parse(f"wrk_{UUID_V7}")


@pytest.mark.parametrize(("prefix", "id_class"), ID_TABLE, ids=[row[0] for row in ID_TABLE])
def test_concrete_ids_have_no_zero_argument_factory(
    prefix: str,
    id_class: type[TypedId],
) -> None:
    del prefix

    with pytest.raises(TypeError):
        id_class()  # type: ignore[call-arg]

    for forbidden_factory_name in ("create", "generate", "new", "random", "now", "from_text"):
        assert not hasattr(id_class, forbidden_factory_name)


def test_ids_module_exposes_exactly_one_public_entropy_function() -> None:
    module_defined_functions = {
        name
        for name, value in vars(ids_module).items()
        if inspect.isfunction(value)
        and not name.startswith("_")
        and value.__module__ == ids_module.__name__
    }

    assert module_defined_functions == {"generate_uuid7_value"}


def _alias_members(alias: object) -> frozenset[type[TypedId]]:
    args = get_args(alias)
    assert args, "expected a union type alias"
    return frozenset(args)


KNOWLEDGE_ENTITY_MEMBERS = frozenset(
    {
        WorkId,
        PublicationId,
        DocumentId,
        IdentifierId,
        PersonId,
        VenueId,
        TopicId,
        MethodId,
        ResearchTaskId,
        DatasetId,
        ClaimId,
        EvidencePassageId,
        SemanticRelationId,
        CollectionId,
        NoteId,
        TechnicalLineageId,
        LineageSynthesisId,
    }
)


def test_knowledge_entity_id_union_members_are_exact() -> None:
    assert _alias_members(KnowledgeEntityId) == KNOWLEDGE_ENTITY_MEMBERS


def test_relationship_endpoint_id_union_members_are_exact() -> None:
    assert _alias_members(RelationshipEndpointId) == KNOWLEDGE_ENTITY_MEMBERS | {SourceRecordId}


def test_lifecycle_entity_id_union_members_are_exact() -> None:
    expected = KNOWLEDGE_ENTITY_MEMBERS - {SemanticRelationId}

    assert _alias_members(LifecycleEntityId) == expected


def test_mergeable_entity_id_union_members_are_exact() -> None:
    expected = frozenset(
        {
            WorkId,
            PublicationId,
            IdentifierId,
            PersonId,
            VenueId,
            TopicId,
            MethodId,
            ResearchTaskId,
            DatasetId,
        }
    )

    assert _alias_members(MergeableEntityId) == expected


def test_assertion_target_id_union_members_are_exact() -> None:
    expected = frozenset({MetadataAssertionId, RelationshipAssertionId, SemanticRelationId})

    assert _alias_members(AssertionTargetId) == expected


def test_provenance_record_id_union_members_are_exact() -> None:
    expected = frozenset(
        {SourceRecordId, MetadataAssertionId, RelationshipAssertionId, AssertionRetractionId}
    )

    assert _alias_members(ProvenanceRecordId) == expected


def test_prefix_registry_is_complete_bidirectional_and_readonly() -> None:
    assert len(ID_PREFIX_REGISTRY) == 23

    for prefix, id_class in ID_TABLE:
        assert ID_PREFIX_REGISTRY[prefix] is id_class
        assert id_class.PREFIX == prefix

    with pytest.raises(TypeError):
        ID_PREFIX_REGISTRY["wrk"] = PublicationId  # type: ignore[index]


def test_uuid6_dependency_pin_is_exact() -> None:
    assert importlib.metadata.version("uuid6") == "2025.0.1"
