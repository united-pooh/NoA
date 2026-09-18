"""Enrichment and review: model-output candidates, structured validation,
human approval into confirmed records, invalidation, and audit (contract section 6.4, slice 7)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from .domain import (
    AcceptedReviewAttestation,
    Claim,
    ClaimId,
    ClaimReviewBinding,
    ContentDigest,
    DomainProjectionInput,
    EvidencePassageId,
    FuzzyMergeReviewBinding,
    KnowledgeEntityId,
    LanguageTag,
    MergeableEntityId,
    MergeableEntitySnapshot,
    MergeResult,
    ReviewAction,
    ReviewedFuzzyMergeBasis,
    ReviewedSemanticPredicate,
    SemanticRelationId,
    SemanticRelationReviewBinding,
    UtcInstant,
    WorkId,
    compute_review_payload_digest,
    confirm_claim,
    confirm_semantic_relation,
    merge_entities,
)


def _utc_now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReviewError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def _error(code: str, message: str, **context: str) -> ReviewError:
    return ReviewError(code=code, message=message, context=context)


class CandidateKind(StrEnum):
    CLAIM = "claim"
    SEMANTIC_RELATION = "semantic_relation"
    FUZZY_MERGE = "fuzzy_merge"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    kind: CandidateKind
    revision: int
    status: CandidateStatus
    payload: dict[str, object]
    payload_digest: str
    created_at: str
    decided_by: str | None
    decided_at: str | None


_CANDIDATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_candidates (
    candidate_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('claim','semantic_relation','fuzzy_merge')),
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','superseded')),
    payload TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""

_ALLOWED_KEYS: dict[CandidateKind, frozenset[str]] = {
    CandidateKind.CLAIM: frozenset({"work_id", "statement", "language", "evidence_ids"}),
    CandidateKind.SEMANTIC_RELATION: frozenset(
        {"predicate", "subject_id", "object_id", "evidence_ids"}
    ),
    CandidateKind.FUZZY_MERGE: frozenset({"survivor_id", "loser_id"}),
}


def _canonical_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def validate_candidate_payload(
    kind: CandidateKind, payload: dict[str, object]
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise _error("invalid_candidate", "Payload must be a JSON object")
    unexpected = set(payload) - set(_ALLOWED_KEYS[kind])
    if unexpected:
        raise _error(
            "invalid_candidate",
            f"Unexpected keys for {kind.value}: {sorted(unexpected)}",
            keys=",".join(sorted(unexpected)),
        )
    missing = set(_ALLOWED_KEYS[kind]) - set(payload)
    if missing:
        raise _error(
            "invalid_candidate",
            f"Missing keys for {kind.value}: {sorted(missing)}",
            keys=",".join(sorted(missing)),
        )
    if kind is CandidateKind.CLAIM:
        WorkId.parse(cast("str", payload["work_id"]))
        statement = payload["statement"]
        if not isinstance(statement, str) or not statement.strip():
            raise _error("invalid_candidate", "statement must be a nonempty string")
        LanguageTag.parse(cast("str", payload["language"]))
        _validate_evidence_ids(payload["evidence_ids"])
    elif kind is CandidateKind.SEMANTIC_RELATION:
        try:
            ReviewedSemanticPredicate(str(payload["predicate"]))
        except ValueError as error:
            raise _error(
                "invalid_candidate",
                f"Unknown reviewed-semantic predicate {payload['predicate']!r}",
            ) from error
        for key in ("subject_id", "object_id"):
            _validate_entity_id(payload[key])
        _validate_evidence_ids(payload["evidence_ids"])
    else:
        _validate_entity_id(payload["survivor_id"])
        _validate_entity_id(payload["loser_id"])
    return cast("dict[str, object]", json.loads(_canonical_payload(payload)))


def _validate_evidence_ids(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise _error("invalid_candidate", "evidence_ids must be a nonempty array")
    for item in value:
        EvidencePassageId.parse(cast("str", item))


def _validate_entity_id(value: object) -> None:
    from .domain import ID_PREFIX_REGISTRY

    if not isinstance(value, str) or "_" not in value:
        raise _error("invalid_candidate", f"Entity id {value!r} is not a typed id")
    prefix = value.split("_", 1)[0]
    if prefix not in ID_PREFIX_REGISTRY:
        raise _error("invalid_candidate", f"Unknown id prefix {prefix!r}")


class CandidateStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(_CANDIDATE_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def submit(
        self,
        *,
        candidate_id: str,
        kind: CandidateKind,
        payload: dict[str, object],
        source_run_id: str | None = None,
    ) -> CandidateRecord:
        validated = validate_candidate_payload(kind, payload)
        digest = hashlib.sha256(_canonical_payload(validated)).hexdigest()
        now = _utc_now_text()
        try:
            self._connection.execute(
                "INSERT INTO review_candidates (candidate_id, kind, revision, status,"
                " payload, payload_digest, created_at, updated_at)"
                " VALUES (?, ?, 1, 'pending', ?, ?, ?, ?)",
                (
                    candidate_id,
                    kind.value,
                    _canonical_payload(validated).decode("utf-8"),
                    f"sha256:{digest}",
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise _error(
                "duplicate_candidate",
                f"Candidate {candidate_id!r} already exists",
                candidate_id=candidate_id,
            ) from error
        if source_run_id is not None:
            self.audit("candidate_submitted", "model", candidate_id, {"run_id": source_run_id})
        return self.load(candidate_id)

    def load(self, candidate_id: str) -> CandidateRecord:
        row = self._connection.execute(
            "SELECT candidate_id, kind, revision, status, payload, payload_digest,"
            " created_at, decided_by, decided_at FROM review_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise _error(
                "candidate_not_found",
                f"Candidate {candidate_id!r} does not exist",
                candidate_id=candidate_id,
            )
        return CandidateRecord(
            candidate_id=row[0],
            kind=CandidateKind(row[1]),
            revision=int(row[2]),
            status=CandidateStatus(row[3]),
            payload=json.loads(row[4]),
            payload_digest=row[5],
            created_at=row[6],
            decided_by=row[7],
            decided_at=row[8],
        )

    def pending(self) -> list[CandidateRecord]:
        rows = self._connection.execute(
            "SELECT candidate_id FROM review_candidates WHERE status = 'pending'"
            " ORDER BY created_at, candidate_id"
        ).fetchall()
        return [self.load(row[0]) for row in rows]

    def _decide(
        self,
        candidate_id: str,
        status: CandidateStatus,
        *,
        decided_by: str,
        note: str | None,
    ) -> None:
        cursor = self._connection.execute(
            "UPDATE review_candidates SET status = ?, decided_by = ?, decided_at = ?,"
            " decision_note = ?, updated_at = ? WHERE candidate_id = ? AND status = 'pending'",
            (status.value, decided_by, _utc_now_text(), note, _utc_now_text(), candidate_id),
        )
        if cursor.rowcount == 0:
            raise _error(
                "candidate_not_pending",
                f"Candidate {candidate_id!r} is not pending",
                candidate_id=candidate_id,
            )

    def audit(
        self, event_type: str, actor: str, subject: str, detail: dict[str, object] | None = None
    ) -> None:
        self._connection.execute(
            "INSERT INTO audit_events (event_type, actor, subject, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                event_type,
                actor,
                subject,
                "{}" if detail is None else _canonical_payload(detail).decode("utf-8"),
                _utc_now_text(),
            ),
        )

    def audit_trail(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT event_type, actor, subject, detail, created_at FROM audit_events"
            " ORDER BY event_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "event_type": row[0],
                "actor": row[1],
                "subject": row[2],
                "detail": json.loads(row[3]),
                "created_at": row[4],
            }
            for row in reversed(rows)
        ]

    def supersede_stale(self, stale_entity_texts: set[str], *, reason: str) -> list[str]:
        superseded: list[str] = []
        for record in self.pending():
            referenced = _referenced_entities(record)
            if referenced & stale_entity_texts:
                self._decide(
                    record.candidate_id,
                    CandidateStatus.SUPERSEDED,
                    decided_by="system",
                    note=reason,
                )
                self.audit(
                    "candidate_superseded", "system", record.candidate_id, {"reason": reason}
                )
                superseded.append(record.candidate_id)
        return superseded


def _referenced_entities(record: CandidateRecord) -> set[str]:
    payload = record.payload
    keys = ("work_id", "subject_id", "object_id", "survivor_id", "loser_id")
    found = {cast("str", payload[key]) for key in keys if key in payload}
    for key in ("evidence_ids",):
        value = payload.get(key)
        if isinstance(value, list):
            found.update(item for item in value if isinstance(item, str))
    return found


@dataclass(frozen=True)
class ApprovalOutcome:
    candidate_id: str
    ok: bool
    detail: str
    error_code: str | None = None


def review_binding_digest(kind: CandidateKind, payload: dict[str, object]) -> ContentDigest:
    """Domain binding digest for a validated candidate payload."""
    evidence_ids = [
        EvidencePassageId.parse(item) for item in cast("list[str]", payload.get("evidence_ids", []))
    ]
    if kind is CandidateKind.CLAIM:
        return compute_review_payload_digest(
            ClaimReviewBinding(
                work_id=WorkId.parse(cast("str", payload["work_id"])),
                statement=cast("str", payload["statement"]),
                language=LanguageTag.parse(cast("str", payload["language"])),
                evidence_ids=tuple(evidence_ids),
            )
        )
    if kind is CandidateKind.SEMANTIC_RELATION:
        return compute_review_payload_digest(
            SemanticRelationReviewBinding(
                predicate=ReviewedSemanticPredicate(str(payload["predicate"])),
                subject_id=_entity_id_from_text(cast("str", payload["subject_id"])),
                object_id=_entity_id_from_text(cast("str", payload["object_id"])),
                evidence_ids=tuple(evidence_ids),
            )
        )
    return compute_review_payload_digest(
        FuzzyMergeReviewBinding(
            survivor_id=cast(
                "MergeableEntityId", _entity_id_from_text(cast("str", payload["survivor_id"]))
            ),
            loser_id=cast(
                "MergeableEntityId", _entity_id_from_text(cast("str", payload["loser_id"]))
            ),
        )
    )


class ApprovalService:
    """Human approval flow: candidate digest must equal the accepted review payload."""

    def __init__(self, store: CandidateStore) -> None:
        self._store = store

    def _require_pending(self, candidate_id: str, kind: CandidateKind) -> CandidateRecord:
        record = self._store.load(candidate_id)
        if record.status is not CandidateStatus.PENDING:
            raise _error(
                "candidate_not_pending",
                f"Candidate {candidate_id!r} is {record.status.value!r}",
                candidate_id=candidate_id,
            )
        if record.kind is not kind:
            raise _error(
                "candidate_kind_mismatch",
                f"Candidate {candidate_id!r} is {record.kind.value!r}, not {kind.value!r}",
                candidate_id=candidate_id,
            )
        recomputed = f"sha256:{hashlib.sha256(_canonical_payload(record.payload)).hexdigest()}"
        if recomputed != record.payload_digest:
            raise _error(
                "candidate_digest_mismatch",
                f"Candidate {candidate_id!r} payload does not match its stored digest",
                candidate_id=candidate_id,
            )
        return record

    @staticmethod
    def _require_review(
        record: CandidateRecord,
        accepted_review: AcceptedReviewAttestation,
        expected_action: ReviewAction,
        expected_binding_digest: ContentDigest,
    ) -> None:
        if type(accepted_review) is not AcceptedReviewAttestation:
            raise _error("review_required", "An accepted review attestation is required")
        if accepted_review.action is not expected_action:
            raise _error(
                "review_action_mismatch",
                f"Expected review action {expected_action.value!r}",
                expected_action=expected_action.value,
            )
        if accepted_review.candidate_id.text != record.candidate_id:
            raise _error(
                "review_candidate_mismatch",
                "Attestation candidate id does not match the candidate being approved",
            )
        if accepted_review.payload_digest != expected_binding_digest:
            raise _error(
                "attestation_payload_mismatch",
                "Review payload digest does not match the candidate binding digest",
            )

    @staticmethod
    def _binding_digest(kind: CandidateKind, payload: dict[str, object]) -> ContentDigest:
        return review_binding_digest(kind, payload)

    def approve_claim(
        self,
        candidate_id: str,
        *,
        claim_id: ClaimId,
        accepted_review: AcceptedReviewAttestation,
        confirmed_at: UtcInstant,
        projection_input: DomainProjectionInput,
        approver: str,
    ) -> Claim:
        record = self._require_pending(candidate_id, CandidateKind.CLAIM)
        self._require_review(
            record,
            accepted_review,
            ReviewAction.CONFIRM_CLAIM,
            self._binding_digest(CandidateKind.CLAIM, record.payload),
        )
        try:
            claim = confirm_claim(
                claim_id=claim_id,
                work_id=WorkId.parse(cast("str", record.payload["work_id"])),
                statement=cast("str", record.payload["statement"]),
                language=LanguageTag.parse(cast("str", record.payload["language"])),
                evidence_ids=[
                    EvidencePassageId.parse(item)
                    for item in cast("list[str]", record.payload["evidence_ids"])
                ],
                accepted_review=accepted_review,
                confirmed_at=confirmed_at,
                projection_input=projection_input,
            )
        except Exception as error:
            code = getattr(error, "code", "confirmation_failed")
            self._store.audit("approval_failed", approver, candidate_id, {"code": str(code)})
            raise
        self._store._decide(candidate_id, CandidateStatus.APPROVED, decided_by=approver, note=None)
        self._store.audit("candidate_approved", approver, candidate_id, {"claim_id": claim.id.text})
        return claim

    def approve_semantic_relation(
        self,
        candidate_id: str,
        *,
        relation_id: SemanticRelationId,
        accepted_review: AcceptedReviewAttestation,
        confirmed_at: UtcInstant,
        projection_input: DomainProjectionInput,
        approver: str,
    ) -> object:
        record = self._require_pending(candidate_id, CandidateKind.SEMANTIC_RELATION)
        self._require_review(
            record,
            accepted_review,
            ReviewAction.CONFIRM_SEMANTIC_RELATION,
            self._binding_digest(CandidateKind.SEMANTIC_RELATION, record.payload),
        )
        relation = confirm_semantic_relation(
            relation_id=relation_id,
            predicate=ReviewedSemanticPredicate(cast("str", record.payload["predicate"])),
            subject_id=_entity_id_from_text(cast("str", record.payload["subject_id"])),
            object_id=_entity_id_from_text(cast("str", record.payload["object_id"])),
            evidence_ids=[
                EvidencePassageId.parse(item)
                for item in cast("list[str]", record.payload["evidence_ids"])
            ],
            accepted_review=accepted_review,
            confirmed_at=confirmed_at,
            projection_input=projection_input,
        )
        self._store._decide(candidate_id, CandidateStatus.APPROVED, decided_by=approver, note=None)
        self._store.audit(
            "candidate_approved", approver, candidate_id, {"relation_id": relation.id.text}
        )
        return relation

    def approve_fuzzy_merge(
        self,
        candidate_id: str,
        *,
        survivor: MergeableEntitySnapshot,
        loser: MergeableEntitySnapshot,
        accepted_review: AcceptedReviewAttestation,
        merged_at: UtcInstant,
        projection_input: DomainProjectionInput,
        approver: str,
    ) -> MergeResult:
        record = self._require_pending(candidate_id, CandidateKind.FUZZY_MERGE)
        self._require_review(
            record,
            accepted_review,
            ReviewAction.MERGE_FUZZY,
            self._binding_digest(CandidateKind.FUZZY_MERGE, record.payload),
        )
        basis = ReviewedFuzzyMergeBasis.create(survivor.id, loser.id, accepted_review)
        result = merge_entities(survivor, loser, basis, merged_at, projection_input)
        self._store._decide(candidate_id, CandidateStatus.APPROVED, decided_by=approver, note=None)
        self._store.audit(
            "candidate_approved",
            approver,
            candidate_id,
            {"survivor": survivor.id.text, "loser": loser.id.text},
        )
        return result

    def reject(self, candidate_id: str, *, approver: str, note: str | None = None) -> None:
        self._store._decide(candidate_id, CandidateStatus.REJECTED, decided_by=approver, note=note)
        self._store.audit("candidate_rejected", approver, candidate_id, {})

    def batch_decide(
        self,
        decisions: Iterable[tuple[str, bool]],
        *,
        approver: str,
        note: str | None = None,
    ) -> list[ApprovalOutcome]:
        outcomes: list[ApprovalOutcome] = []
        for candidate_id, approve in decisions:
            try:
                if approve:
                    raise _error(
                        "batch_approval_requires_attestation",
                        "Batch flow supports rejection only; approvals need per-item attestations",
                    )
                self.reject(candidate_id, approver=approver, note=note)
                outcomes.append(ApprovalOutcome(candidate_id, True, "rejected"))
            except ReviewError as error:
                outcomes.append(ApprovalOutcome(candidate_id, False, error.args[0], error.code))
        return outcomes


def _entity_id_from_text(text: str) -> KnowledgeEntityId:
    from .domain import ID_PREFIX_REGISTRY

    prefix = text.split("_", 1)[0]
    id_type = ID_PREFIX_REGISTRY.get(prefix)
    if id_type is None:
        raise _error("invalid_candidate", f"Unknown id prefix {prefix!r}")
    return cast("KnowledgeEntityId", id_type.parse(text))


__all__ = [
    "ApprovalOutcome",
    "ApprovalService",
    "CandidateKind",
    "CandidateRecord",
    "CandidateStatus",
    "CandidateStore",
    "ReviewError",
    "review_binding_digest",
    "validate_candidate_payload",
]
