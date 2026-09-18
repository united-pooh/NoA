"""Contract tests for shared value objects, attestations, and identifier
normalization (spec sections 7 and 9)."""

import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import get_args

import pytest

from noa.domain.errors import DomainError
from noa.domain.identifiers import (
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
    IdentifierScheme,
    InstantAssertionValue,
    IntegerAssertionValue,
    LanguageAssertionValue,
    LanguageTag,
    OperationAction,
    ReviewAction,
    TextAssertionValue,
    UtcInstant,
    assert_identifier_target_compatible,
    create_accepted_operation_attestation,
    create_accepted_review_attestation,
    normalize_identifier,
)
from noa.domain.ids import (
    AssertionTargetId,
    DatasetId,
    KnowledgeEntityId,
    LifecycleEntityId,
    MergeableEntityId,
    PersonId,
    PublicationId,
    RelationshipEndpointId,
    ReviewCandidateId,
    TopicId,
    VenueId,
    WorkId,
)

HEX_UPPER = "0123456789ABCDEF" * 4
HEX_LOWER = "0123456789abcdef" * 4
VALID_DIGEST = f"sha256:{HEX_LOWER}"

WORK_ID_TEXT = "wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a"
PERSON_ID_TEXT = "per_0198cd4c-0000-7a31-8f25-000000000003"


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


# ---------------------------------------------------------------------------
# ContentDigest (spec 7.1)
# ---------------------------------------------------------------------------


def test_content_digest_accepts_sha256_and_normalizes_uppercase_hex() -> None:
    digest = ContentDigest.parse(f"sha256:{HEX_UPPER}")

    assert digest.text == VALID_DIGEST
    assert ContentDigest.parse(VALID_DIGEST) == digest
    assert hash(ContentDigest.parse(VALID_DIGEST)) == hash(digest)
    assert digest.sort_key() == digest.sort_key() == VALID_DIGEST


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sha256:",
        f"sha256:{HEX_LOWER}0",
        f"sha256:{HEX_LOWER[:-1]}",
        f"sha256:{'0123456789abcdeg' * 4}",
        f"md5:{HEX_LOWER}",
        HEX_LOWER,
        f" sha256:{HEX_LOWER}",
        f"sha256: {HEX_LOWER}",
        f"sha256:{HEX_LOWER[:-4]} {HEX_LOWER[-4:]}",
        "SHA256:" + HEX_LOWER,
        f"sha3_256:{HEX_LOWER}",
    ],
)
def test_content_digest_rejects_non_canonical_input(text: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        ContentDigest.parse(text)

    error = excinfo.value
    assert error.code == "invalid_value_object"
    assert set(error.context) == {"type", "field", "reason"}
    assert error.context["type"] == "ContentDigest"


# ---------------------------------------------------------------------------
# LanguageTag (spec 7.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("zh-Hans", "zh-hans"),
        ("en-US", "en-us"),
        ("EN", "en"),
        ("und", "und"),
        ("de-CH-1901", "de-ch-1901"),
        ("zh-hans", "zh-hans"),
    ],
)
def test_language_tag_canonicalizes_to_lowercase(raw: str, canonical: str) -> None:
    tag = LanguageTag.parse(raw)

    assert tag.text == canonical
    assert LanguageTag.parse(canonical) == tag
    assert hash(LanguageTag.parse(canonical)) == hash(tag)
    assert tag.sort_key() == tag.sort_key() == canonical


@pytest.mark.parametrize(
    "text",
    [
        "",
        "e",
        "aaaa",
        "en-",
        "-en",
        "en--us",
        "en_us",
        "en US",
        " en",
        "en ",
        "en-us.",
        "und-x",
        "en-1",
        "1234",
        "en\u2013us",
    ],
)
def test_language_tag_rejects_out_of_profile_input(text: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        LanguageTag.parse(text)

    error = excinfo.value
    assert error.code == "invalid_value_object"
    assert error.context["type"] == "LanguageTag"


# ---------------------------------------------------------------------------
# UtcInstant (spec 7.3)
# ---------------------------------------------------------------------------


def test_utc_instant_rejects_naive_datetime() -> None:
    with pytest.raises(DomainError) as excinfo:
        UtcInstant.from_datetime(datetime(2026, 8, 21, 12, 0, 0))

    error = excinfo.value
    assert error.code == "invalid_value_object"
    assert set(error.context) == {"type", "field", "reason"}
    assert error.context["type"] == "UtcInstant"


def test_utc_instant_converts_to_utc_preserving_microseconds() -> None:
    offset = timezone(timedelta(hours=2))
    instant = UtcInstant.from_datetime(datetime(2026, 8, 21, 12, 30, 45, 123456, tzinfo=offset))

    assert instant.value == datetime(2026, 8, 21, 10, 30, 45, 123456, tzinfo=UTC)
    assert instant.value.utcoffset() == timedelta(0)
    assert instant.text == "2026-08-21T10:30:45.123456Z"


def test_utc_instant_canonical_text_formats() -> None:
    assert _instant("2026-08-21T12:30:45+00:00").text == "2026-08-21T12:30:45Z"
    assert _instant("2026-08-21T12:30:45.000120+00:00").text == "2026-08-21T12:30:45.000120Z"
    assert _instant("2026-08-21T12:30:45.000001+00:00").text == "2026-08-21T12:30:45.000001Z"


def test_utc_instant_equality_and_ordering_follow_the_instant() -> None:
    same_instant_a = _instant("2026-08-21T12:30:45+02:00")
    same_instant_b = _instant("2026-08-21T10:30:45+00:00")
    later = _instant("2026-08-21T10:30:46+00:00")

    assert same_instant_a == same_instant_b
    assert hash(same_instant_a) == hash(same_instant_b)
    assert not same_instant_a < same_instant_b
    assert same_instant_a < later
    assert later > same_instant_a


def test_utc_instant_sort_key_is_deterministic() -> None:
    instant = _instant("2026-08-21T10:30:45.123456+00:00")

    assert instant.sort_key() == instant.sort_key() == "2026-08-21T10:30:45.123456Z"


# ---------------------------------------------------------------------------
# EvidenceLocator (spec 7.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("page 12", "page 12"),
        ("  page 12  ", "page 12"),
        ("\u00a0page\u00a012\u00a0", "page\u00a012"),
        ("p.1", "p.1"),
    ],
)
def test_evidence_locator_strips_unicode_whitespace(raw: str, canonical: str) -> None:
    locator = EvidenceLocator.parse(raw)

    assert locator.text == canonical
    assert EvidenceLocator.parse(canonical) == locator
    assert locator.sort_key() == locator.sort_key() == canonical


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "a\u0000b",
        "line\nbreak",
        "tab\there",
        "zero\u200bwidth",
        "rtl\u200fmark",
        "lrm\u200emark",
        "\ud800",
    ],
)
def test_evidence_locator_rejects_control_format_and_surrogate_points(text: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        EvidenceLocator.parse(text)

    error = excinfo.value
    assert error.code == "invalid_value_object"
    assert error.context["type"] == "EvidenceLocator"


@pytest.mark.parametrize(
    "text",
    [
        "\ue000private",
        "\u0378unassigned",
    ],
)
def test_evidence_locator_allows_private_use_and_unassigned_categories(text: str) -> None:
    assert unicodedata.category(text[0]) in {"Co", "Cn"}
    assert EvidenceLocator.parse(text).text == text


# ---------------------------------------------------------------------------
# IdentifierKey (spec 7.5)
# ---------------------------------------------------------------------------


def test_identifier_key_direct_construction_is_rejected() -> None:
    with pytest.raises(DomainError) as excinfo:
        IdentifierKey(IdentifierScheme.DOI, "10.1000/xyz", "https://doi.org/10.1000/xyz")

    error = excinfo.value
    assert error.code == "invalid_value_object"
    assert error.context["type"] == "IdentifierKey"


def test_identifier_key_equality_and_hashing_use_the_pair() -> None:
    via_uri = normalize_identifier(IdentifierScheme.DOI, "https://doi.org/10.1000/XYZ")
    via_bare = normalize_identifier(IdentifierScheme.DOI, "doi:10.1000/xyz")
    other = normalize_identifier(IdentifierScheme.DOI, "10.1000/other")

    assert via_uri == via_bare
    assert hash(via_uri) == hash(via_bare)
    assert (via_uri.scheme, via_uri.normalized_value) == (
        via_bare.scheme,
        via_bare.normalized_value,
    )
    assert len({via_uri, via_bare, other}) == 2
    assert via_uri != other


def test_identifier_key_exposes_uri_outside_the_key() -> None:
    key = normalize_identifier(IdentifierScheme.DOI, "https://dx.doi.org/10.1000/xyz")

    assert key.scheme is IdentifierScheme.DOI
    assert key.normalized_value == "10.1000/xyz"
    assert key.canonical_uri == "https://doi.org/10.1000/xyz"
    assert key.sort_key() == key.sort_key() == ("doi", "10.1000/xyz")


def test_identifier_scheme_is_closed() -> None:
    assert {scheme.value for scheme in IdentifierScheme} == {
        "doi",
        "arxiv",
        "openalex",
        "orcid",
        "ror",
        "issn",
    }

    with pytest.raises(ValueError):
        IdentifierScheme("pmid")


# ---------------------------------------------------------------------------
# AssertionValue variants (spec 7.7)
# ---------------------------------------------------------------------------


def test_text_assertion_value_applies_nfc_strip_and_requires_nonblank() -> None:
    language = LanguageTag.parse("en")
    value = TextAssertionValue.create("  Cafe\u0301  title  ", language)

    assert value.text == unicodedata.normalize("NFC", "Cafe\u0301  title").strip()
    assert value.text == "Caf\u00e9  title"
    assert value.language is language
    assert value.kind is AssertionValueKind.TEXT
    assert value.sort_key() == value.sort_key()

    with pytest.raises(DomainError):
        TextAssertionValue.create("   ", language)

    with pytest.raises(DomainError):
        TextAssertionValue.create(5, language)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_value", [True, False, 5.0, Decimal("5"), "5", None])
def test_integer_assertion_value_rejects_bool_and_non_int(bad_value: object) -> None:
    with pytest.raises(DomainError):
        IntegerAssertionValue.create(bad_value)  # type: ignore[arg-type]


def test_integer_assertion_value_accepts_int() -> None:
    value = IntegerAssertionValue.create(2026)

    assert value.value == 2026
    assert value.kind is AssertionValueKind.INTEGER
    assert value.sort_key() == value.sort_key()


@pytest.mark.parametrize("bad_value", [1, 0, "true", None, 1.0])
def test_boolean_assertion_value_rejects_non_bool(bad_value: object) -> None:
    with pytest.raises(DomainError):
        BooleanAssertionValue.create(bad_value)  # type: ignore[arg-type]


def test_boolean_assertion_value_accepts_bool() -> None:
    value = BooleanAssertionValue.create(True)

    assert value.value is True
    assert value.kind is AssertionValueKind.BOOLEAN
    assert value.sort_key() == value.sort_key()


def test_typed_wrapper_variants_require_exact_value_types() -> None:
    digest = ContentDigest.parse(VALID_DIGEST)
    language = LanguageTag.parse("en")
    instant = _instant("2026-08-21T00:00:00+00:00")
    key = normalize_identifier(IdentifierScheme.DOI, "10.1000/xyz")

    assert DigestAssertionValue.create(digest).value is digest
    assert LanguageAssertionValue.create(language).value is language
    assert InstantAssertionValue.create(instant).value is instant
    assert IdentifierAssertionValue.create(key).value is key

    with pytest.raises(DomainError):
        DigestAssertionValue.create(VALID_DIGEST)  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        LanguageAssertionValue.create("en")  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        InstantAssertionValue.create(instant.value)  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        IdentifierAssertionValue.create(("doi", "10.1000/xyz"))  # type: ignore[arg-type]

    for value in (
        DigestAssertionValue.create(digest),
        LanguageAssertionValue.create(language),
        InstantAssertionValue.create(instant),
        IdentifierAssertionValue.create(key),
    ):
        assert value.sort_key() == value.sort_key()


def test_assertion_value_union_has_exactly_seven_variants() -> None:
    args = get_args(AssertionValue)

    assert len(args) == 7
    assert set(args) == {
        TextAssertionValue,
        IntegerAssertionValue,
        BooleanAssertionValue,
        DigestAssertionValue,
        LanguageAssertionValue,
        InstantAssertionValue,
        IdentifierAssertionValue,
    }


# ---------------------------------------------------------------------------
# Review / operation attestation shape (spec 7.9)
# ---------------------------------------------------------------------------


def test_review_and_operation_action_enums_are_closed() -> None:
    assert {action.value for action in ReviewAction} == {
        "confirm_claim",
        "confirm_semantic_relation",
        "merge_fuzzy",
    }
    assert {action.value for action in OperationAction} == {
        "source_ingest",
        "source_refresh",
        "human_correction",
        "retract_record",
        "merge_exact_identity",
        "tombstone_entity",
    }
    assert {kind.value for kind in AttestationPrincipalKind} == {"human", "service"}

    with pytest.raises(ValueError):
        ReviewAction("delete_everything")
    with pytest.raises(ValueError):
        OperationAction("delete_everything")
    with pytest.raises(ValueError):
        AttestationPrincipalKind("robot")


def test_accepted_review_attestation_happy_path_shape() -> None:
    candidate = ReviewCandidateId.parse("rvc_0198cd4e-0000-7a31-8f25-000000000005")
    attestation = _review_attestation(
        ReviewAction.CONFIRM_CLAIM,
        candidate_id=candidate,
        candidate_revision=3,
        actor="  alice  ",
        accepted_at="2026-08-21T00:00:00+00:00",
    )

    assert attestation.candidate_id is candidate
    assert attestation.candidate_revision == 3
    assert attestation.action is ReviewAction.CONFIRM_CLAIM
    assert attestation.actor == "alice"
    assert attestation.review_event_reference == "rev-0001"
    assert attestation.payload_digest == _digest()
    assert attestation.accepted_at == _instant("2026-08-21T00:00:00+00:00")
    assert attestation.sort_key() == attestation.sort_key()


@pytest.mark.parametrize("bad_revision", [0, -1, True, False, 1.0, "1", None])
def test_accepted_review_attestation_rejects_invalid_revision(bad_revision: object) -> None:
    with pytest.raises(DomainError) as excinfo:
        create_accepted_review_attestation(
            candidate_id=_review_attestation(ReviewAction.MERGE_FUZZY).candidate_id,
            candidate_revision=bad_revision,  # type: ignore[arg-type]
            action=ReviewAction.MERGE_FUZZY,
            actor="alice",
            review_event_reference="rev-0001",
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )

    assert excinfo.value.code == "invalid_attestation"
    assert set(excinfo.value.context) == {"attestation_kind", "reason"}
    assert excinfo.value.context["attestation_kind"] == "review"


@pytest.mark.parametrize("blank_text", ["", "   ", "\t"])
def test_accepted_review_attestation_rejects_blank_actor_and_reference(
    blank_text: str,
) -> None:
    with pytest.raises(DomainError):
        create_accepted_review_attestation(
            candidate_id=_review_attestation(ReviewAction.MERGE_FUZZY).candidate_id,
            candidate_revision=1,
            action=ReviewAction.MERGE_FUZZY,
            actor=blank_text,
            review_event_reference="rev-0001",
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )

    with pytest.raises(DomainError):
        create_accepted_review_attestation(
            candidate_id=_review_attestation(ReviewAction.MERGE_FUZZY).candidate_id,
            candidate_revision=1,
            action=ReviewAction.MERGE_FUZZY,
            actor="alice",
            review_event_reference=blank_text,
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )


def test_accepted_operation_attestation_happy_path_shape() -> None:
    attestation = _operation_attestation(
        OperationAction.SOURCE_INGEST,
        AttestationPrincipalKind.SERVICE,
        principal="svc:crossref",
    )

    assert attestation.operation_reference == "op-0001"
    assert attestation.operation_revision == 1
    assert attestation.action is OperationAction.SOURCE_INGEST
    assert attestation.principal_kind is AttestationPrincipalKind.SERVICE
    assert attestation.principal == "svc:crossref"
    assert attestation.payload_digest == _digest()
    assert attestation.sort_key() == attestation.sort_key()


@pytest.mark.parametrize(
    "human_only_action",
    [
        OperationAction.HUMAN_CORRECTION,
        OperationAction.RETRACT_RECORD,
        OperationAction.TOMBSTONE_ENTITY,
    ],
)
def test_human_only_actions_require_human_principal(human_only_action: OperationAction) -> None:
    with pytest.raises(DomainError) as excinfo:
        _operation_attestation(human_only_action, AttestationPrincipalKind.SERVICE)

    assert excinfo.value.code == "invalid_attestation"
    assert excinfo.value.context["attestation_kind"] == "operation"


@pytest.mark.parametrize("bad_revision", [0, -1, True, 2.5])
def test_accepted_operation_attestation_rejects_invalid_revision(bad_revision: object) -> None:
    with pytest.raises(DomainError):
        create_accepted_operation_attestation(
            operation_reference="op-0001",
            operation_revision=bad_revision,  # type: ignore[arg-type]
            action=OperationAction.SOURCE_INGEST,
            principal_kind=AttestationPrincipalKind.SERVICE,
            principal="svc:noa",
            review_event_reference="rev-0001",
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )


def test_accepted_operation_attestation_rejects_blank_principal_and_reference() -> None:
    with pytest.raises(DomainError):
        create_accepted_operation_attestation(
            operation_reference="   ",
            operation_revision=1,
            action=OperationAction.SOURCE_INGEST,
            principal_kind=AttestationPrincipalKind.SERVICE,
            principal="svc:noa",
            review_event_reference="rev-0001",
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )

    with pytest.raises(DomainError):
        create_accepted_operation_attestation(
            operation_reference="op-0001",
            operation_revision=1,
            action=OperationAction.SOURCE_INGEST,
            principal_kind=AttestationPrincipalKind.SERVICE,
            principal="   ",
            review_event_reference="rev-0001",
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )

    with pytest.raises(DomainError):
        create_accepted_operation_attestation(
            operation_reference="op-0001",
            operation_revision=1,
            action=OperationAction.SOURCE_INGEST,
            principal_kind=AttestationPrincipalKind.SERVICE,
            principal="svc:noa",
            review_event_reference="  ",
            payload_digest=_digest(),
            accepted_at=_instant("2026-08-21T00:00:00+00:00"),
        )


# ---------------------------------------------------------------------------
# normalize_identifier (spec 9)
# ---------------------------------------------------------------------------


EQUIVALENCE_CASES = (
    (
        IdentifierScheme.DOI,
        "10.1000/xyz",
        (
            "10.1000/xyz",
            "DOI:10.1000/xyz",
            "doi:10.1000/xyz",
            "https://doi.org/10.1000/xyz",
            "https://doi.org/10.1000/Xyz",
            "http://dx.doi.org/10.1000/xyz",
            "https://dx.doi.org/10.1000/xyz",
        ),
        "https://doi.org/10.1000/xyz",
    ),
    (
        IdentifierScheme.ARXIV,
        "1501.00001v2",
        (
            "1501.00001v2",
            "arXiv:1501.00001v2",
            "ARXIV:1501.00001v2",
            "https://arxiv.org/abs/1501.00001v2",
            "https://arxiv.org/pdf/1501.00001v2",
            "https://arxiv.org/pdf/1501.00001v2.pdf",
        ),
        "https://arxiv.org/abs/1501.00001v2",
    ),
    (
        IdentifierScheme.ARXIV,
        "math.gt/0309136v2",
        (
            "math.GT/0309136v2",
            "arxiv:math.GT/0309136v2",
            "https://arxiv.org/abs/math.GT/0309136v2",
            "https://arxiv.org/pdf/math.GT/0309136v2.pdf",
        ),
        "https://arxiv.org/abs/math.gt/0309136v2",
    ),
    (
        IdentifierScheme.OPENALEX,
        "W2741809807",
        (
            "W2741809807",
            "openalex:w2741809807",
            "https://openalex.org/W2741809807",
            "https://openalex.org/works/W2741809807",
            "https://api.openalex.org/works/w2741809807",
            "https://OPENALEX.org/works/W2741809807",
        ),
        "https://openalex.org/W2741809807",
    ),
    (
        IdentifierScheme.ORCID,
        "0000-0002-1825-0097",
        (
            "0000-0002-1825-0097",
            "0000000218250097",
            "orcid:0000-0002-1825-0097",
            "ORCID:0000000218250097",
            "https://orcid.org/0000-0002-1825-0097",
            "http://orcid.org/0000-0002-1825-0097",
        ),
        "https://orcid.org/0000-0002-1825-0097",
    ),
    (
        IdentifierScheme.ROR,
        "02mhbdp94",
        (
            "02mhbdp94",
            "02MHBDP94",
            "ror:02mhbdp94",
            "ror.org/02mhbdp94",
            "https://ror.org/02mhbdp94",
            "http://ror.org/02mhbdp94",
        ),
        "https://ror.org/02mhbdp94",
    ),
    (
        IdentifierScheme.ISSN,
        "2049-3630",
        (
            "2049-3630",
            "20493630",
            "issn:2049-3630",
            "ISSN:20493630",
            "https://portal.issn.org/resource/ISSN/2049-3630",
        ),
        "https://portal.issn.org/resource/ISSN/2049-3630",
    ),
)


@pytest.mark.parametrize(
    ("scheme", "expected_value", "raw_inputs", "canonical_uri"), EQUIVALENCE_CASES
)
def test_equivalent_inputs_normalize_to_one_key(
    scheme: IdentifierScheme,
    expected_value: str,
    raw_inputs: tuple[str, ...],
    canonical_uri: str,
) -> None:
    keys = [normalize_identifier(scheme, raw) for raw in raw_inputs]

    assert len(set(keys)) == 1
    key = keys[0]
    assert key.scheme is scheme
    assert key.normalized_value == expected_value
    assert key.canonical_uri == canonical_uri


INVALID_IDENTIFIER_CASES = (
    # DOI profile and URI rules
    (IdentifierScheme.DOI, ""),
    (IdentifierScheme.DOI, "   "),
    (IdentifierScheme.DOI, "10.123/abc"),
    (IdentifierScheme.DOI, "10.1234567890/abc"),
    (IdentifierScheme.DOI, "11.1000/abc"),
    (IdentifierScheme.DOI, "10.1000/"),
    (IdentifierScheme.DOI, "10.1000"),
    (IdentifierScheme.DOI, "10.1000/abc def"),
    (IdentifierScheme.DOI, "10.1000/café"),
    (IdentifierScheme.DOI, "10.1000/abc|def"),
    (IdentifierScheme.DOI, "https://example.org/10.1000/xyz"),
    (IdentifierScheme.DOI, "https://doi.org.evil.com/10.1000/xyz"),
    (IdentifierScheme.DOI, "https://user@doi.org/10.1000/xyz"),
    (IdentifierScheme.DOI, "https://doi.org:443/10.1000/xyz"),
    (IdentifierScheme.DOI, "https://doi.org/10.1000/xyz?q=1"),
    (IdentifierScheme.DOI, "https://doi.org/10.1000/xyz#frag"),
    (IdentifierScheme.DOI, "ftp://doi.org/10.1000/xyz"),
    (IdentifierScheme.DOI, "https://doi.org/10.1000/a%2520b"),
    (IdentifierScheme.DOI, "https://doi.org"),
    # arXiv modern boundaries
    (IdentifierScheme.ARXIV, "0703.0001"),
    (IdentifierScheme.ARXIV, "1413.0001"),
    (IdentifierScheme.ARXIV, "1412.00001"),
    (IdentifierScheme.ARXIV, "1500.00001"),
    (IdentifierScheme.ARXIV, "1501.0001"),
    (IdentifierScheme.ARXIV, "1501.00000"),
    (IdentifierScheme.ARXIV, "0704.0000"),
    (IdentifierScheme.ARXIV, "1513.00001"),
    (IdentifierScheme.ARXIV, "1501.00001v0"),
    (IdentifierScheme.ARXIV, "1501.00001v01"),
    (IdentifierScheme.ARXIV, "1501.00001v"),
    (IdentifierScheme.ARXIV, "1501.00001v2x"),
    # arXiv legacy boundaries
    (IdentifierScheme.ARXIV, "math/9106001"),
    (IdentifierScheme.ARXIV, "math/0704001"),
    (IdentifierScheme.ARXIV, "math/0000001"),
    (IdentifierScheme.ARXIV, "math/9113001"),
    (IdentifierScheme.ARXIV, "math/0309136v0"),
    (IdentifierScheme.ARXIV, "math_gt/0309136"),
    (IdentifierScheme.ARXIV, "https://www.arxiv.org/abs/1501.00001"),
    (IdentifierScheme.ARXIV, "https://arxiv.org/export/abs/1501.00001"),
    (IdentifierScheme.ARXIV, "https://arxiv.org/pdf/1501.00001.txt"),
    (IdentifierScheme.ARXIV, "https://arxiv.org/abs/"),
    # OpenAlex prefix/plural rules
    (IdentifierScheme.OPENALEX, "X2741809807"),
    (IdentifierScheme.OPENALEX, "W"),
    (IdentifierScheme.OPENALEX, "W012345678"),
    (IdentifierScheme.OPENALEX, "W2741809807x"),
    (IdentifierScheme.OPENALEX, "https://openalex.org/works/A2741809807"),
    (IdentifierScheme.OPENALEX, "https://api.openalex.org/W2741809807"),
    (IdentifierScheme.OPENALEX, "http://openalex.org/W2741809807"),
    (IdentifierScheme.OPENALEX, "https://example.org/W2741809807"),
    (IdentifierScheme.OPENALEX, "https://openalex.org/works/W2741809807/extra"),
    # ORCID grammar
    (IdentifierScheme.ORCID, "0000-0002-1825-009"),
    (IdentifierScheme.ORCID, "0000-0002-1825-00970"),
    (IdentifierScheme.ORCID, "000018250097"),
    (IdentifierScheme.ORCID, "abcd-efgh-ijkl-mnop"),
    (IdentifierScheme.ORCID, "https://orcid.org/0000-0002-1825-0097/x"),
    (IdentifierScheme.ORCID, "https://example.com/0000-0002-1825-0097"),
    # ROR shape
    (IdentifierScheme.ROR, "12mhbdp94"),
    (IdentifierScheme.ROR, "0imhbdp94"),
    (IdentifierScheme.ROR, "0omhbdp94"),
    (IdentifierScheme.ROR, "0lmhbdp94"),
    (IdentifierScheme.ROR, "0umhbdp94"),
    (IdentifierScheme.ROR, "02mhbdp9"),
    (IdentifierScheme.ROR, "02mhbdp944"),
    (IdentifierScheme.ROR, "https://example.com/02mhbdp94"),
    # ISSN grammar and all-zero rejection
    (IdentifierScheme.ISSN, "0000-0000"),
    (IdentifierScheme.ISSN, "2049-363"),
    (IdentifierScheme.ISSN, "2049-36300"),
    (IdentifierScheme.ISSN, "2049_3630"),
    (IdentifierScheme.ISSN, "https://portal.issn.org/resource/issn/2049-3630"),
    (IdentifierScheme.ISSN, "http://portal.issn.org/resource/ISSN/2049-3630"),
    (IdentifierScheme.ISSN, "https://portal.issn.org/resource/ISSN/2049-3630/x"),
    (IdentifierScheme.ISSN, "https://example.org/resource/ISSN/2049-3630"),
)


@pytest.mark.parametrize(("scheme", "raw"), INVALID_IDENTIFIER_CASES)
def test_invalid_identifier_inputs_fail_with_stable_error(
    scheme: IdentifierScheme,
    raw: str,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        normalize_identifier(scheme, raw)

    error = excinfo.value
    assert error.code == "invalid_identifier"
    assert set(error.context) == {"scheme", "value", "reason"}
    assert error.context["scheme"] == scheme.value
    assert error.context["value"] == raw


def test_doi_percent_decoding_happens_exactly_once() -> None:
    key = normalize_identifier(IdentifierScheme.DOI, "https://doi.org/10.1000/ab%61c")

    assert key.normalized_value == "10.1000/abac"


CHECKSUM_MISMATCH_CASES = (
    (IdentifierScheme.ORCID, "0000-0002-1825-0098", "0000-0002-1825-0098"),
    (IdentifierScheme.ROR, "02mhbdp95", "02mhbdp95"),
    (IdentifierScheme.ISSN, "2049-3631", "2049-3631"),
    (IdentifierScheme.ORCID, "0000000218250098", "0000-0002-1825-0098"),
)


@pytest.mark.parametrize(("scheme", "raw", "normalized"), CHECKSUM_MISMATCH_CASES)
def test_single_character_tampering_fails_checksum(
    scheme: IdentifierScheme,
    raw: str,
    normalized: str,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        normalize_identifier(scheme, raw)

    error = excinfo.value
    assert error.code == "identifier_checksum_mismatch"
    assert set(error.context) == {"scheme", "normalized_value"}
    assert error.context["scheme"] == scheme.value
    assert error.context["normalized_value"] == normalized


OFFICIAL_SAMPLE_CASES = (
    (IdentifierScheme.ORCID, "0000-0002-1825-0097"),
    (IdentifierScheme.ORCID, "0000-0002-1694-233X"),
    (IdentifierScheme.ROR, "02mhbdp94"),
    (IdentifierScheme.ISSN, "2049-3630"),
    (IdentifierScheme.ISSN, "1234-5679"),
    (IdentifierScheme.ISSN, "2434-561X"),
    (IdentifierScheme.ISSN, "0378-5955"),
)


@pytest.mark.parametrize(("scheme", "raw"), OFFICIAL_SAMPLE_CASES)
def test_official_checksum_samples_are_accepted(scheme: IdentifierScheme, raw: str) -> None:
    key = normalize_identifier(scheme, raw)

    assert key.normalized_value.startswith(("0", "1", "2"))
    assert key.canonical_uri.startswith("https://")


def test_orcid_preserves_leading_zeros_and_uppercase_x() -> None:
    key = normalize_identifier(IdentifierScheme.ORCID, "000000021694233x")

    assert key.normalized_value == "0000-0002-1694-233X"


def test_openalex_ownerless_prefixes_normalize_without_target() -> None:
    for prefix in "WASICPFT":
        key = normalize_identifier(IdentifierScheme.OPENALEX, f"{prefix}12345")

        assert key.normalized_value[0] == prefix


# ---------------------------------------------------------------------------
# assert_identifier_target_compatible (spec 9.8)
# ---------------------------------------------------------------------------


def _doi_key() -> IdentifierKey:
    return normalize_identifier(IdentifierScheme.DOI, "10.1000/xyz")


def _arxiv_key() -> IdentifierKey:
    return normalize_identifier(IdentifierScheme.ARXIV, "1501.00001")


def _openalex_key(prefix: str) -> IdentifierKey:
    return normalize_identifier(IdentifierScheme.OPENALEX, f"{prefix}12345")


def _orcid_key() -> IdentifierKey:
    return normalize_identifier(IdentifierScheme.ORCID, "0000-0002-1825-0097")


def _ror_key() -> IdentifierKey:
    return normalize_identifier(IdentifierScheme.ROR, "02mhbdp94")


def _issn_key() -> IdentifierKey:
    return normalize_identifier(IdentifierScheme.ISSN, "2049-3630")


COMPATIBLE_CASES = (
    (_doi_key, PublicationId.parse("pub_0198cd53-0000-7a31-8f25-00000000000b")),
    (_doi_key, DatasetId.parse("dts_0198cd54-0000-7a31-8f25-00000000000c")),
    (_arxiv_key, PublicationId.parse("pub_0198cd53-0000-7a31-8f25-00000000000b")),
    (lambda: _openalex_key("W"), PublicationId.parse("pub_0198cd53-0000-7a31-8f25-00000000000b")),
    (lambda: _openalex_key("A"), PersonId.parse(PERSON_ID_TEXT)),
    (lambda: _openalex_key("S"), VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
    (lambda: _openalex_key("C"), TopicId.parse("top_0198cd56-0000-7a31-8f25-00000000000e")),
    (lambda: _openalex_key("T"), TopicId.parse("top_0198cd56-0000-7a31-8f25-00000000000e")),
    (_orcid_key, PersonId.parse(PERSON_ID_TEXT)),
    (_issn_key, VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
)

INCOMPATIBLE_CASES = (
    (_doi_key, WorkId.parse(WORK_ID_TEXT)),
    (_arxiv_key, PersonId.parse(PERSON_ID_TEXT)),
    (lambda: _openalex_key("I"), VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
    (lambda: _openalex_key("P"), VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
    (lambda: _openalex_key("F"), VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
    (lambda: _openalex_key("W"), PersonId.parse(PERSON_ID_TEXT)),
    (_orcid_key, VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
    (_ror_key, VenueId.parse("ven_0198cd55-0000-7a31-8f25-00000000000d")),
    (_ror_key, PersonId.parse(PERSON_ID_TEXT)),
    (_issn_key, PersonId.parse(PERSON_ID_TEXT)),
    (_issn_key, PublicationId.parse("pub_0198cd53-0000-7a31-8f25-00000000000b")),
)


@pytest.mark.parametrize(
    ("key_builder", "target_id"),
    [(case[0], case[1]) for case in COMPATIBLE_CASES],
)
def test_compatible_identifier_targets_pass(
    key_builder: Callable[[], IdentifierKey],
    target_id: KnowledgeEntityId,
) -> None:
    assert_identifier_target_compatible(key_builder(), target_id)


@pytest.mark.parametrize(
    ("key_builder", "target_id"),
    [(case[0], case[1]) for case in INCOMPATIBLE_CASES],
)
def test_incompatible_identifier_targets_fail_closed(
    key_builder: Callable[[], IdentifierKey],
    target_id: KnowledgeEntityId,
) -> None:
    key = key_builder()

    with pytest.raises(DomainError) as excinfo:
        assert_identifier_target_compatible(key, target_id)

    error = excinfo.value
    assert error.code == "identifier_target_incompatible"
    assert set(error.context) == {"scheme", "normalized_value", "target_kind"}
    assert error.context["scheme"] == key.scheme.value
    assert error.context["normalized_value"] == key.normalized_value


def test_identifier_target_compatibility_rejects_non_identifier_key() -> None:
    with pytest.raises(DomainError) as excinfo:
        assert_identifier_target_compatible(
            ("doi", "10.1000/xyz"),  # type: ignore[arg-type]
            PersonId.parse(PERSON_ID_TEXT),
        )

    assert excinfo.value.code == "invalid_value_object"


def test_union_aliases_used_by_bindings_are_importable() -> None:
    assert len(get_args(KnowledgeEntityId)) == 17
    assert len(get_args(LifecycleEntityId)) == 16
    assert len(get_args(RelationshipEndpointId)) == 18
    assert len(get_args(AssertionTargetId)) == 3
    assert len(get_args(MergeableEntityId)) == 9
