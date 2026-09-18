"""NoA MCP server: compatibility probes plus Slice 7-9 knowledge tools.

Read tools are stateless queries; write tools require explicit `confirm=True`.
Server-side confirmation is the authorization boundary (contract sections 8.4,
slice 9); client-side prompts are not authorization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import cast

from fastmcp import Context, FastMCP
from fastmcp.apps import AppConfig, ResourceCSP
from mcp.types import InputRequiredResult

from noa.acquisition import acquire_document, page_locator
from noa.adapters import BatchPlanEntry, crossref_draft, single_entry_proposal
from noa.compat.runtime import build_runtime_checks
from noa.compat.sampling import resolve_sampling
from noa.domain import (
    ID_PREFIX_REGISTRY,
    AcceptedReviewAttestation,
    ActiveLifecycle,
    AuthorityTier,
    Claim,
    ClaimId,
    ClaimReviewBinding,
    ContentDigest,
    Document,
    DocumentId,
    DomainError,
    EntitySnapshotIndex,
    EvidenceLocator,
    EvidencePassage,
    EvidencePassageId,
    KnowledgeEntityId,
    LanguageTag,
    LifecycleEntitySnapshot,
    MetadataAssertionId,
    Note,
    NoteId,
    Publication,
    PublicationId,
    ReviewAction,
    ReviewCandidateId,
    SourceRecordId,
    TypedId,
    UtcInstant,
    Work,
    WorkId,
    build_domain_projection_input,
    build_entity_snapshot_index,
    build_source_record_index,
    compute_review_payload_digest,
    create_accepted_review_attestation,
    create_document,
    create_evidence_passage,
    create_publication,
    create_work,
)
from noa.review import CandidateKind, CandidateStore, validate_candidate_payload
from noa.runtime import ResearchRunStore, RunStage
from noa.storage import GraphStore, ObjectStore, StorageError
from noa.trajectory import (
    BranchContext,
    CriterionRole,
    EvidenceScope,
    EvidenceStatus,
    ObjectiveFacet,
    ObjectiveStatus,
    ResearchObjective,
    SuccessCriterion,
    TrajectoryEvent,
    TrajectoryIntent,
    WorkClass,
    WorkSource,
)
from noa.trajectory_store import TrajectoryStore
from noa.views import NoteStore, SearchIndex, export_projection_view
from noa.workspace import Workspace, WorkspaceError

COMPATIBILITY_APP_URI = "ui://noa/compatibility.html"

mcp = FastMCP("NoA Compatibility", mask_error_details=True)


def _error_result(code: str, detail: str) -> dict[str, object]:
    return {"status": "error", "code": code, "detail": detail}


def _instant(text: str) -> UtcInstant:
    from noa.domain import UtcInstant

    return UtcInstant.from_datetime(datetime.fromisoformat(text))


def _now_instant() -> UtcInstant:
    return UtcInstant.from_datetime(datetime.now(UTC))


def _parse_entity_id(text: str) -> KnowledgeEntityId:

    prefix = text.split("_", 1)[0]
    id_type = ID_PREFIX_REGISTRY.get(prefix)
    if id_type is None:
        raise ValueError(f"unknown id prefix {prefix!r}")
    from typing import cast

    return cast("KnowledgeEntityId", id_type.parse(text))


@mcp.tool()
def compatibility_ping(value: str = "pong") -> dict[str, object]:
    """Verify that the NoA MCP server can execute a tool."""
    return {"status": "pass", "value": value}


@mcp.tool()
def compatibility_runtime() -> list[dict[str, object]]:
    """Return exact runtime and dependency compatibility checks."""
    return [check.model_dump(mode="json") for check in build_runtime_checks()]


@mcp.tool()
async def sampling_compatibility(
    question: str,
    ctx: Context,
) -> dict[str, str | None] | InputRequiredResult:
    """Verify caller-model Sampling on both the 2025 and 2026 MCP protocol eras."""
    return await resolve_sampling(question, ctx)


@mcp.tool(app=AppConfig(resource_uri=COMPATIBILITY_APP_URI))
def show_compatibility_app() -> dict[str, object]:
    """Render the bundled NoA MCP App compatibility probe."""
    return {"status": "pass", "resource_uri": COMPATIBILITY_APP_URI}


@mcp.resource(COMPATIBILITY_APP_URI, app=AppConfig(csp=ResourceCSP()))
def compatibility_app() -> str:
    """Return the bundled NoA MCP App compatibility probe."""
    return files("noa.compat.app").joinpath("index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Knowledge read tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_id_prefixes() -> dict[str, object]:
    """Expose every typed-id prefix so callers never have to guess one."""
    return {
        "status": "pass",
        "prefixes": {
            prefix: _snake_kind_name(id_type) for prefix, id_type in ID_PREFIX_REGISTRY.items()
        },
    }


def _snake_kind_name(id_type: type) -> str:
    base = id_type.__name__.removesuffix("Id")
    return "".join(f"_{char.lower()}" if char.isupper() else char for char in base).lstrip("_")


@mcp.tool()
def knowledge_search(workspace_root: str, query: str, limit: int = 10) -> dict[str, object]:
    """Deterministic keyword search over stored entity payloads and notes."""
    try:
        workspace = Workspace.open(Path(workspace_root), create=False)
        graph = GraphStore(workspace.graph_dir / "graph.lbdb")
        try:
            entries = []
            for entity_id, kind, payload in graph.all_entities():
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                for field_name, value in sorted(data.items()):
                    if isinstance(value, str) and value.strip():
                        normalized = value.strip().lower()
                        entries.append((entity_id, kind, f"payload.{field_name}", normalized))
            notes = NoteStore(workspace.control_dir / "notes.sqlite3")
            try:
                for row in notes._connection.execute(
                    "SELECT note_id, title, body FROM notes"
                ).fetchall():
                    for field_name, value in (("title", row[1]), ("body", row[2])):
                        entries.append(
                            (row[0], "note", f"note.{field_name}", value.strip().lower())
                        )
            finally:
                notes.close()
            index = SearchIndex(entries=tuple(sorted(set(entries))))
            hits = index.query(query, limit=max(1, min(limit, 50)))
            return {
                "status": "pass",
                "hits": [
                    {
                        "entity_id": hit.entity_id,
                        "kind": hit.kind,
                        "field": hit.field,
                        "value": hit.value,
                        "score": hit.score,
                    }
                    for hit in hits
                ],
            }
        finally:
            graph.close()
    except (WorkspaceError, StorageError) as error:
        return _error_result(error.code, error.args[0])


# ---------------------------------------------------------------------------
# Protected write tools: explicit confirmation required
# ---------------------------------------------------------------------------


@mcp.tool()
def add_note(
    workspace_root: str,
    note_id: str,
    title: str,
    body: str,
    author: str,
    attached_entity_ids: list[str],
    confirm: bool = False,
) -> dict[str, object]:
    """Attach a human-authored note; requires explicit confirmation."""
    if not confirm:
        return _error_result("confirmation_required", "Pass confirm=true to attach a note")
    try:
        from noa.domain import create_note

        workspace = Workspace.open(Path(workspace_root), create=False)
        graph = GraphStore(workspace.graph_dir / "graph.lbdb")
        try:
            index = build_entity_index_from_graph(graph)
            from noa.domain import NoteId

            note = create_note(
                note_id=NoteId.parse(note_id),
                title=title,
                body=body,
                author=author,
                attached_entity_ids=[_parse_entity_id(item) for item in attached_entity_ids],
                entity_index=index,
                semantic_relations=[],
            )
            graph.put_entity(
                note.id.text,
                "note",
                json.dumps(
                    {
                        "title": note.title,
                        "body": note.body,
                        "author": note.author,
                        "revision": str(note.revision),
                        "attached_entity_ids": [item.text for item in note.attached_entity_ids],
                    },
                    ensure_ascii=False,
                ),
            )
            notes = NoteStore(workspace.control_dir / "notes.sqlite3")
            try:
                notes.record_revision(note)
            finally:
                notes.close()
            return {"status": "pass", "note_id": note.id.text}
        finally:
            graph.close()
    except Exception as error:
        return _error_result(getattr(error, "code", "add_note_failed"), error.args[0])


_SNAPSHOT_FIELD_WHITELISTS: dict[str, frozenset[str]] = {
    "work": frozenset(),
    "publication": frozenset({"work_id"}),
    "document": frozenset({"publication_id", "content_digest", "media_type"}),
    "evidence_passage": frozenset({"source_id", "locator", "text", "source_language"}),
}

_SNAPSHOT_ID_TYPES: dict[str, type[TypedId]] = {
    "work": WorkId,
    "publication": PublicationId,
    "document": DocumentId,
    "evidence_passage": EvidencePassageId,
}


@mcp.tool()
def put_entity_snapshot(
    workspace_root: str,
    kind: str,
    entity_id: str,
    work_id: str | None = None,
    publication_id: str | None = None,
    content_digest: str | None = None,
    media_type: str | None = None,
    source_id: str | None = None,
    locator: str | None = None,
    text: str | None = None,
    source_language: str | None = None,
    confirm: bool = False,
) -> dict[str, object]:
    """Persist one structural entity snapshot into the graph; requires confirmation."""
    if not confirm:
        return _error_result("confirmation_required", "Pass confirm=true to write a snapshot")
    fields = {
        key: value
        for key, value in (
            ("work_id", work_id),
            ("publication_id", publication_id),
            ("content_digest", content_digest),
            ("media_type", media_type),
            ("source_id", source_id),
            ("locator", locator),
            ("text", text),
            ("source_language", source_language),
        )
        if value is not None
    }
    try:
        allowed = _SNAPSHOT_FIELD_WHITELISTS.get(kind)
        if allowed is None:
            return _error_result("unsupported_snapshot_kind", f"Unknown snapshot kind {kind!r}")
        unexpected = sorted(set(fields) - allowed)
        missing = sorted(allowed - set(fields))
        if unexpected or missing:
            detail = []
            if unexpected:
                detail.append(f"unexpected keys {unexpected}")
            if missing:
                detail.append(f"missing keys {missing}")
            return _error_result("invalid_snapshot_payload", "; ".join(detail))

        entity_key = _SNAPSHOT_ID_TYPES[kind].parse(entity_id)
        workspace = Workspace.open(Path(workspace_root), create=False)
        graph = GraphStore(workspace.graph_dir / "graph.lbdb")
        try:
            if graph.get_entity_payload(entity_key.text) is not None:
                return _error_result("entity_exists", f"Entity {entity_key.text!r} already exists")
            index = build_entity_index_from_graph(graph)
            payload = _stage_structural_snapshot(
                kind, cast("KnowledgeEntityId", entity_key), fields, index
            )
            graph.put_entity(
                entity_key.text,
                kind,
                json.dumps(payload, ensure_ascii=False),
            )
            return {"status": "pass", "entity_id": entity_key.text}
        finally:
            graph.close()
    except Exception as error:
        code = getattr(error, "code", "invalid_snapshot_payload")
        return _error_result(code, error.args[0] if error.args else str(error))


def _stage_structural_snapshot(
    kind: str,
    entity_key: KnowledgeEntityId,
    fields: dict[str, str],
    index: EntitySnapshotIndex,
) -> dict[str, str]:
    if kind == "work":
        create_work(cast("WorkId", entity_key))
        return {}
    if kind == "publication":
        publication = create_publication(
            cast("PublicationId", entity_key), WorkId.parse(fields["work_id"]), index
        )
        return {"work_id": publication.work_id.text}
    if kind == "document":
        document = create_document(
            cast("DocumentId", entity_key),
            PublicationId.parse(fields["publication_id"]),
            ContentDigest.parse(fields["content_digest"]),
            fields["media_type"],
            index,
        )
        return {
            "publication_id": document.publication_id.text,
            "content_digest": document.content_digest.text,
            "media_type": document.media_type,
        }
    source_text = fields["source_id"]
    if not source_text.startswith("doc_"):
        raise DomainError(
            code="unsupported_source_kind",
            message=(
                "evidence_passage requires a document-sourced source_id; "
                "source-record-backed evidence needs a committed record index"
            ),
            context={"source_id": source_text},
        )
    recorded_at = UtcInstant.from_datetime(datetime.now(UTC))
    passage = create_evidence_passage(
        cast("EvidencePassageId", entity_key),
        DocumentId.parse(source_text),
        EvidenceLocator(text=fields["locator"]),
        fields["text"],
        LanguageTag.parse(fields["source_language"]),
        recorded_at,
        index,
        build_source_record_index([]),
    )
    return {
        "source_id": passage.source_id.text,
        "locator": passage.locator.text,
        "text": passage.text,
        "source_language": passage.source_language.text,
        "recorded_at": passage.recorded_at.text,
    }


@mcp.tool()
def get_note(workspace_root: str, note_id: str) -> dict[str, object]:
    """Fetch one note with its attached entities and their kinds."""
    try:
        parsed = NoteId.parse(note_id)
        workspace = Workspace.open(Path(workspace_root), create=False)
        graph = GraphStore(workspace.graph_dir / "graph.lbdb")
        try:
            kinds: dict[str, str] = {}
            raw_payload: str | None = None
            for entity_id, kind, payload in graph.all_entities():
                kinds[entity_id] = kind
                if entity_id == parsed.text and kind == "note":
                    raw_payload = payload
            if raw_payload is None:
                return _error_result(
                    "note_not_found", f"Note {parsed.text!r} does not exist in the graph"
                )
            data = json.loads(raw_payload)
            attachments = [
                {"entity_id": item, "kind": kinds.get(item, "unknown")}
                for item in cast("list[str]", data.get("attached_entity_ids", []))
            ]
            return {
                "status": "pass",
                "note": {
                    "note_id": parsed.text,
                    "title": data.get("title"),
                    "body": data.get("body"),
                    "author": data.get("author"),
                    "revision": int(cast("str", data.get("revision", "1"))),
                    "attached_entities": attachments,
                },
            }
        finally:
            graph.close()
    except Exception as error:
        code = getattr(error, "code", "get_note_failed")
        return _error_result(code, error.args[0] if error.args else str(error))


@mcp.tool()
def export_graph_view(workspace_root: str) -> dict[str, object]:
    """Export the structural projection as a rebuildable JSON view file."""
    try:
        workspace = Workspace.open(Path(workspace_root), create=False)
        graph = GraphStore(workspace.graph_dir / "graph.lbdb")
        try:
            projection_input = build_domain_projection_input(
                build_entity_index_from_graph(graph),
                build_source_record_index([]),
                [],
                [],
                [],
                [],
            )
        finally:
            graph.close()
        output_path = workspace.runtime / "exports" / "graph-view.json"
        export_projection_view(projection_input, output_path)
        view = json.loads(output_path.read_text(encoding="utf-8"))
        return {
            "status": "pass",
            "path": str(output_path),
            "current_record_count": len(view["current_record_ids"]),
            "relationship_count": len(view["relationships"]),
        }
    except Exception as error:
        code = getattr(error, "code", "export_failed")
        return _error_result(code, error.args[0] if error.args else str(error))


def build_entity_index_from_graph(graph: GraphStore) -> EntitySnapshotIndex:

    snapshots = []
    for entity_id, kind, payload in graph.all_entities():
        try:
            snapshot = _snapshot_from_payload(entity_id, kind, json.loads(payload))
        except (json.JSONDecodeError, ValueError):
            continue
        if snapshot is not None:
            snapshots.append(snapshot)
    return build_entity_snapshot_index(cast("list[LifecycleEntitySnapshot]", snapshots))


def _snapshot_from_payload(entity_id: str, kind: str, data: object) -> object:
    """Reconstruct lifecycle snapshots from canonical flat graph payloads."""
    if not isinstance(data, dict):
        return None
    try:
        if kind == "work":
            return Work(id=WorkId.parse(entity_id), lifecycle=_active_lifecycle())
        if kind == "publication":
            return Publication(
                id=PublicationId.parse(entity_id),
                work_id=WorkId.parse(_payload_str(data, "work_id")),
                lifecycle=_active_lifecycle(),
            )
        if kind == "document":
            return Document(
                id=DocumentId.parse(entity_id),
                publication_id=PublicationId.parse(_payload_str(data, "publication_id")),
                content_digest=ContentDigest.parse(_payload_str(data, "content_digest")),
                media_type=_payload_str(data, "media_type"),
                lifecycle=_active_lifecycle(),
            )
        if kind == "evidence_passage":
            return EvidencePassage(
                id=EvidencePassageId.parse(entity_id),
                source_id=DocumentId.parse(_payload_str(data, "source_id")),
                locator=EvidenceLocator(text=_payload_str(data, "locator")),
                text=_payload_str(data, "text"),
                source_language=LanguageTag.parse(_payload_str(data, "source_language")),
                recorded_at=_utc_instant_from_text(_payload_str(data, "recorded_at")),
                lifecycle=_active_lifecycle(),
            )
        if kind == "claim":
            return Claim(
                id=ClaimId.parse(entity_id),
                work_id=WorkId.parse(_payload_str(data, "work_id")),
                statement=_payload_str(data, "statement"),
                language=LanguageTag.parse(_payload_str(data, "language")),
                evidence_ids=tuple(
                    EvidencePassageId.parse(item)
                    for item in _payload_str_list(data, "evidence_ids")
                ),
                accepted_review=_review_attestation_from_payload(data),
                confirmed_at=_utc_instant_from_text(_payload_str(data, "confirmed_at")),
                lifecycle=ActiveLifecycle(),
            )
        if kind == "note":
            return Note(
                id=NoteId.parse(entity_id),
                revision=int(_payload_str(data, "revision")),
                title=_payload_str(data, "title"),
                body=_payload_str(data, "body"),
                author=_payload_str(data, "author"),
                attached_entity_ids=tuple(
                    _parse_entity_id(item)
                    for item in _payload_str_list(data, "attached_entity_ids")
                ),
                lifecycle=ActiveLifecycle(),
            )
    except Exception:
        return None
    return None


_REVIEW_FIELDS = (
    "review_candidate_id",
    "review_candidate_revision",
    "review_action",
    "review_actor",
    "review_event_reference",
    "review_payload_digest",
    "review_accepted_at",
)


def _review_attestation_from_payload(data: dict[str, object]) -> AcceptedReviewAttestation:
    for field in _REVIEW_FIELDS:
        _payload_str(data, field)
    action = ReviewAction(_payload_str(data, "review_action"))
    if action is not ReviewAction.CONFIRM_CLAIM:
        raise ValueError("only confirm_claim attestations are serializable")
    computed_digest = compute_review_payload_digest(
        ClaimReviewBinding(
            work_id=WorkId.parse(_payload_str(data, "work_id")),
            statement=_payload_str(data, "statement"),
            language=LanguageTag.parse(_payload_str(data, "language")),
            evidence_ids=tuple(
                EvidencePassageId.parse(item) for item in _payload_str_list(data, "evidence_ids")
            ),
        )
    )
    stored_digest = ContentDigest.parse(_payload_str(data, "review_payload_digest"))
    if stored_digest.text != computed_digest.text:
        raise ValueError("claim payload does not match its recorded review digest")
    return create_accepted_review_attestation(
        candidate_id=ReviewCandidateId.parse(_payload_str(data, "review_candidate_id")),
        candidate_revision=int(cast("str", data["review_candidate_revision"])),
        action=action,
        actor=_payload_str(data, "review_actor"),
        review_event_reference=_payload_str(data, "review_event_reference"),
        payload_digest=computed_digest,
        accepted_at=_utc_instant_from_text(_payload_str(data, "review_accepted_at")),
    )


def _payload_str_list(data: dict[str, object], key: str) -> list[str]:
    value = data[key]
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(f"payload field {key!r} must be a nonempty string array")
    return value


def _active_lifecycle() -> ActiveLifecycle:
    return ActiveLifecycle()


def _payload_str(data: dict[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"payload field {key!r} must be a nonempty string")
    return value


def _utc_instant_from_text(text: str) -> UtcInstant:
    return UtcInstant.from_datetime(datetime.fromisoformat(text.replace("Z", "+00:00")))


@mcp.tool()
def submit_claim_candidate(
    workspace_root: str,
    candidate_id: str,
    work_id: str,
    statement: str,
    language: str,
    evidence_ids: list[str],
    run_id: str | None = None,
) -> dict[str, object]:
    """Register a model-produced claim candidate for human review."""
    try:
        payload = validate_candidate_payload(
            CandidateKind.CLAIM,
            {
                "work_id": work_id,
                "statement": statement,
                "language": language,
                "evidence_ids": evidence_ids,
            },
        )
        Workspace.open(Path(workspace_root), create=False)
        store = CandidateStore(_candidate_store_path(workspace_root))
        try:
            record = store.submit(
                candidate_id=candidate_id,
                kind=CandidateKind.CLAIM,
                payload=payload,
                source_run_id=run_id,
            )
            return {
                "status": "pass",
                "candidate_id": record.candidate_id,
                "digest": record.payload_digest,
            }
        finally:
            store.close()
    except Exception as error:
        return _error_result(getattr(error, "code", "submit_failed"), error.args[0])


def _candidate_store_path(workspace_root: str) -> Path:
    return Path(workspace_root) / ".noa" / "control" / "candidates.sqlite3"


@mcp.tool()
def approve_claim_candidate(
    workspace_root: str,
    candidate_id: str,
    claim_id: str,
    actor: str,
    review_event_reference: str,
    confirmed_at: str,
    confirm: bool = False,
) -> dict[str, object]:
    """Approve a pending claim candidate with an accepted review attestation."""
    if not confirm:
        return _error_result("confirmation_required", "Pass confirm=true to approve a candidate")
    try:
        from noa.review import ApprovalService, review_binding_digest

        store = CandidateStore(_candidate_store_path(workspace_root))
        try:
            record = store.load(candidate_id)
        finally:
            store.close()
        accepted_review = create_accepted_review_attestation(
            candidate_id=ReviewCandidateId.parse(candidate_id),
            candidate_revision=record.revision,
            action=ReviewAction.CONFIRM_CLAIM,
            actor=actor,
            review_event_reference=review_event_reference,
            payload_digest=review_binding_digest(CandidateKind.CLAIM, record.payload),
            accepted_at=_instant(confirmed_at),
        )
        workspace = Workspace.open(Path(workspace_root), create=False)
        graph = GraphStore(workspace.graph_dir / "graph.lbdb")
        try:
            from noa.review import ApprovalService

            projection_input = build_domain_projection_input(
                build_entity_index_from_graph(graph),
                build_source_record_index([]),
                [],
                [],
                [],
                [],
            )
            candidate_store = CandidateStore(_candidate_store_path(workspace_root))
            try:
                service = ApprovalService(candidate_store)
                claim = service.approve_claim(
                    candidate_id,
                    claim_id=ClaimId.parse(claim_id),
                    accepted_review=accepted_review,
                    confirmed_at=_instant(confirmed_at),
                    projection_input=projection_input,
                    approver=actor,
                )
                graph.put_entity(
                    claim.id.text,
                    "claim",
                    json.dumps(_claim_payload(claim), ensure_ascii=False),
                )
                return {"status": "pass", "claim_id": claim.id.text}
            finally:
                candidate_store.close()
        finally:
            graph.close()
    except Exception as error:
        return _error_result(getattr(error, "code", "approval_failed"), error.args[0])


def _claim_payload(claim: Claim) -> dict[str, object]:
    review = claim.accepted_review
    return {
        "work_id": claim.work_id.text,
        "statement": claim.statement,
        "language": claim.language.text,
        "evidence_ids": [item.text for item in claim.evidence_ids],
        "confirmed_at": claim.confirmed_at.text,
        "review_candidate_id": review.candidate_id.text,
        "review_candidate_revision": str(review.candidate_revision),
        "review_action": review.action.value,
        "review_actor": review.actor,
        "review_event_reference": review.review_event_reference,
        "review_payload_digest": review.payload_digest.text,
        "review_accepted_at": review.accepted_at.text,
    }


def _trajectory_store_path(workspace_root: str) -> Path:
    path = Path(workspace_root) / ".noa" / "control" / "trajectory.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _trajectory_parse_instant(value: str | None) -> UtcInstant:
    if value is None or not isinstance(value, str) or not value.strip():
        return UtcInstant.from_datetime(datetime.now(UTC))
    try:
        return UtcInstant.from_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid instant {value!r}") from exc


def _trajectory_enum(value: object, enum_type: type) -> object:
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


def _trajectory_facets(values: list[dict[str, object]] | None) -> tuple[ObjectiveFacet, ...]:
    return tuple(
        ObjectiveFacet(
            kind=str(item["kind"]),
            value=str(item["value"]),
            weight=float(cast(float | int | str, item.get("weight", 1.0))),
        )
        for item in (values or [])
    )


def _trajectory_criteria(
    values: list[dict[str, object]],
) -> tuple[SuccessCriterion, ...]:
    criteria: list[SuccessCriterion] = []
    for item in values:
        criteria.append(
            SuccessCriterion(
                criterion_id=str(item["criterion_id"]),
                metric=str(item["metric"]),
                target=str(item["target"]),
                role=cast(CriterionRole, _trajectory_enum(item["role"], CriterionRole)),
                depends_on=tuple(
                    str(value)
                    for value in cast(list[object] | tuple[object, ...], item.get("depends_on", ()))
                ),
                blocking=bool(item.get("blocking", True)),
                acceptance_scope=cast(
                    EvidenceScope,
                    _trajectory_enum(
                        item.get("acceptance_scope", EvidenceScope.FORMAL_EVALUATION.value),
                        EvidenceScope,
                    ),
                ),
            )
        )
    return tuple(criteria)


def _trajectory_objective(
    *,
    objective_id: str,
    version: int,
    statement: str,
    criteria: list[dict[str, object]],
    facets: list[dict[str, object]] | None = None,
    supersedes_version: int | None = None,
) -> ResearchObjective:
    return ResearchObjective(
        objective_id=objective_id,
        version=version,
        statement=statement,
        facets=_trajectory_facets(facets),
        criteria=_trajectory_criteria(criteria),
        supersedes_version=supersedes_version,
    )


def _trajectory_error(error: Exception, default_type: str) -> dict[str, object]:
    code = str(getattr(error, "code", default_type))
    message = str(error)
    return {
        "status": "error",
        "type": code,
        "code": code,
        "message": message,
        "detail": message,
        "retryable": code in {"sequence_conflict", "version_conflict"},
        "suggestion": (
            "refresh the current trajectory snapshot and retry"
            if code in {"sequence_conflict", "version_conflict"}
            else "inspect the objective and trajectory event contract"
        ),
    }


def _trajectory_intent(value: dict[str, object] | None) -> TrajectoryIntent | None:
    if value is None:
        return None
    return TrajectoryIntent(
        hypothesis_ids=tuple(
            str(item)
            for item in cast(list[object] | tuple[object, ...], value.get("hypothesis_ids", ()))
        ),
        criterion_ids=tuple(
            str(item)
            for item in cast(list[object] | tuple[object, ...], value.get("criterion_ids", ()))
        ),
        facets=_trajectory_facets(cast(list[dict[str, object]], value.get("facets", []))),
        action=str(value["action"]),
        work_class=cast(
            WorkClass,
            _trajectory_enum(value.get("work_class", WorkClass.EXPLORATION.value), WorkClass),
        ),
        work_source=cast(
            WorkSource,
            _trajectory_enum(value.get("work_source", WorkSource.HYPOTHESIS.value), WorkSource),
        ),
        blocks_criterion_ids=tuple(
            str(item)
            for item in cast(
                list[object] | tuple[object, ...], value.get("blocks_criterion_ids", ())
            )
        ),
        returns_to_criterion_ids=tuple(
            str(item)
            for item in cast(
                list[object] | tuple[object, ...], value.get("returns_to_criterion_ids", ())
            )
        ),
        exit_conditions=tuple(
            str(item)
            for item in cast(list[object] | tuple[object, ...], value.get("exit_conditions", ()))
        ),
        evidence_scope=cast(
            EvidenceScope,
            _trajectory_enum(value.get("evidence_scope", EvidenceScope.PILOT.value), EvidenceScope),
        ),
    )


def _trajectory_event_json(event: TrajectoryEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "seq": event.seq,
        "parent_event_id": event.parent_event_id,
        "branch_id": event.branch_id,
        "event_kind": event.event_kind,
        "occurred_at": event.occurred_at.text,
        "started_at": None if event.started_at is None else event.started_at.text,
        "ended_at": None if event.ended_at is None else event.ended_at.text,
        "intent": None
        if event.intent is None
        else {
            "hypothesis_ids": list(event.intent.hypothesis_ids),
            "criterion_ids": list(event.intent.criterion_ids),
            "facets": [
                {"kind": facet.kind, "value": facet.value, "weight": facet.weight}
                for facet in event.intent.facets
            ],
            "action": event.intent.action,
            "work_class": event.intent.work_class.value,
            "work_source": event.intent.work_source.value,
            "blocks_criterion_ids": list(event.intent.blocks_criterion_ids),
            "returns_to_criterion_ids": list(event.intent.returns_to_criterion_ids),
            "exit_conditions": list(event.intent.exit_conditions),
            "evidence_scope": event.intent.evidence_scope.value,
        },
        "result": dict(event.result),
        "metrics": dict(event.metrics),
        "artifacts": list(event.artifacts),
        "outcome": event.outcome,
        "source": event.source,
        "idempotency_key": event.idempotency_key,
        "supports_criterion_ids": list(event.supports_criterion_ids),
        "blocked_criterion_ids": list(event.blocked_criterion_ids),
        "evidence_scope": event.evidence_scope.value,
        "evidence_status": event.evidence_status.value,
    }


def _trajectory_branch_context(
    events: tuple[TrajectoryEvent, ...],
    run_id: str,
) -> BranchContext:
    run_events = tuple(event for event in events if event.run_id == run_id)
    if not run_events:
        return BranchContext(run_id, run_id, run_id, None, 0, 1, None)
    first = run_events[0]
    if first.parent_event_id is None:
        return BranchContext(run_id, run_id, run_id, None, 0, first.seq, None)
    parent = next(
        (event for event in events if event.event_id == first.parent_event_id),
        None,
    )
    if parent is None:
        raise ValueError("parent event is missing from trajectory")
    ancestor = _trajectory_branch_context(events, parent.run_id)
    return BranchContext(
        run_id=run_id,
        root_run_id=ancestor.root_run_id,
        mainline_run_id=ancestor.mainline_run_id,
        parent_run_id=parent.run_id,
        branch_depth=ancestor.branch_depth + 1,
        fork_seq=parent.seq,
        common_ancestor_seq=parent.seq,
    )


def _trajectory_snapshot_json(
    objective: ResearchObjective,
    snapshot: object,
    events: tuple[TrajectoryEvent, ...],
) -> dict[str, object]:
    from noa.trajectory import TrajectorySnapshot

    if not isinstance(snapshot, TrajectorySnapshot):
        raise TypeError("snapshot must be a TrajectorySnapshot")
    context = _trajectory_branch_context(events, snapshot.run_id)
    branch_event = next(
        (event for event in reversed(events) if event.run_id == snapshot.run_id), None
    )
    return {
        "status": "pass",
        "objective_id": objective.objective_id,
        "objective_version": objective.version,
        "objective_status": objective.status.value,
        "branch_id": branch_event.branch_id if branch_event else "main",
        "common_ancestor_seq": context.common_ancestor_seq,
        "branch_elapsed_ms": snapshot.branch_elapsed_ms,
        "path_elapsed_ms": snapshot.path_elapsed_ms,
        "root_progress": snapshot.drift.root_progress,
        "prerequisite_progress": snapshot.drift.prerequisite_progress,
        "path_distance": snapshot.drift.path_distance,
        "goal_drift": snapshot.drift.goal_drift,
        "validation_stagnation_events": snapshot.drift.validation_stagnation_events,
        "return_due": snapshot.drift.return_due,
        "objective": {
            "objective_id": objective.objective_id,
            "version": objective.version,
            "status": objective.status.value,
            "statement": objective.statement,
        },
        "run_id": snapshot.run_id,
        "stage": branch_event.event_kind if branch_event is not None else "prepared",
        "branch": {
            "branch_id": branch_event.branch_id if branch_event else "main",
            "run_id": context.run_id,
            "root_run_id": context.root_run_id,
            "mainline_run_id": context.mainline_run_id,
            "parent_run_id": context.parent_run_id,
            "branch_depth": context.branch_depth,
            "common_ancestor_seq": context.common_ancestor_seq,
        },
        "elapsed": {
            "branch_ms": snapshot.branch_elapsed_ms,
            "path_ms": snapshot.path_elapsed_ms,
            "duration_source": snapshot.duration_source,
        },
        "progress": {
            "verified_criterion_ids": list(snapshot.progress.verified_criterion_ids),
            "pending_criterion_ids": list(snapshot.progress.pending_criterion_ids),
            "fraction": snapshot.progress.fraction,
            "root_criterion_ids": list(snapshot.progress.root_criterion_ids),
            "prerequisite_criterion_ids": list(snapshot.progress.prerequisite_criterion_ids),
            "evidence_status_by_criterion": dict(snapshot.progress.evidence_status_by_criterion),
        },
        "drift": {
            "path_distance": snapshot.drift.path_distance,
            "goal_drift": snapshot.drift.goal_drift,
            "score": snapshot.drift.score,
            "root_progress": snapshot.drift.root_progress,
            "prerequisite_progress": snapshot.drift.prerequisite_progress,
            "validation_stagnation": snapshot.drift.validation_stagnation_events,
            "return_due": snapshot.drift.return_due,
            "basis_event_ids": list(snapshot.drift.basis_event_ids),
            "reasons": list(snapshot.drift.reasons),
        },
        "active_blockers": list(snapshot.active_blockers),
        "last_capability_evidence_seq": snapshot.last_capability_evidence_seq,
        "last_prerequisite_release_seq": snapshot.last_prerequisite_release_seq,
        "next_action": snapshot.next_action,
    }


@mcp.tool()
def start_research_run(
    workspace_root: str,
    run_id: str,
    total_steps: int = 1,
    max_sampling_requests: int = 16,
    objective_id: str | None = None,
    branch_id: str = "main",
) -> dict[str, object]:
    """Start a resumable research run on the control plane."""
    try:
        if objective_id is not None:
            trajectory_store = TrajectoryStore(_trajectory_store_path(workspace_root))
            try:
                objective = trajectory_store.load_objective(objective_id)
                if objective.status in {ObjectiveStatus.COMPLETED, ObjectiveStatus.SUPERSEDED}:
                    return _trajectory_error(
                        ValueError("terminal objective cannot start a new run"),
                        "objective_terminal",
                    )
                trajectory_store.register_run(objective_id, run_id, branch_id=branch_id)
                return {
                    "status": "pass",
                    "run_id": run_id,
                    "objective_id": objective.objective_id,
                    "objective_version": objective.version,
                    "branch_id": branch_id,
                    "trajectory_status": "active",
                }
            finally:
                trajectory_store.close()
        Workspace.open(Path(workspace_root), create=False)
        run_store = ResearchRunStore(Path(workspace_root) / ".noa" / "control" / "runs.sqlite3")
        try:
            run = run_store.start_run(
                run_id, total_steps=total_steps, max_sampling_requests=max_sampling_requests
            )
            return {"status": "pass", "run_id": run.run_id, "stage": run.stage.value}
        finally:
            run_store.close()
    except Exception as error:
        return _trajectory_error(error, "start_run_failed")


@mcp.tool()
def create_research_objective(
    workspace_root: str,
    objective_id: str,
    statement: str,
    criteria: list[dict[str, object]],
    facets: list[dict[str, object]] | None = None,
    version: int = 1,
) -> dict[str, object]:
    """Create a versioned research objective in the trajectory control plane."""
    try:
        objective = _trajectory_objective(
            objective_id=objective_id,
            version=version,
            statement=statement,
            criteria=criteria,
            facets=facets,
        )
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            store.create_objective(objective)
        finally:
            store.close()
        return {
            "status": "pass",
            "objective_id": objective.objective_id,
            "version": objective.version,
            "objective_status": objective.status.value,
        }
    except Exception as error:
        return _trajectory_error(error, "create_objective_failed")


@mcp.tool()
def revise_research_objective(
    workspace_root: str,
    objective_id: str,
    base_version: int,
    statement: str,
    criteria: list[dict[str, object]],
    facets: list[dict[str, object]] | None = None,
    version: int | None = None,
) -> dict[str, object]:
    """Create a new objective version while preserving the old immutable version."""
    try:
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            new_version = base_version + 1 if version is None else version
            objective = _trajectory_objective(
                objective_id=objective_id,
                version=new_version,
                statement=statement,
                criteria=criteria,
                facets=facets,
                supersedes_version=base_version,
            )
            store.revise_objective(objective_id, base_version, objective)
        finally:
            store.close()
        return {
            "status": "pass",
            "objective_id": objective.objective_id,
            "version": objective.version,
            "supersedes_version": objective.supersedes_version,
            "objective_status": objective.status.value,
        }
    except Exception as error:
        return _trajectory_error(error, "revise_objective_failed")


@mcp.tool()
def complete_research_objective(
    workspace_root: str,
    objective_id: str,
    evidence_event_ids: list[str],
    version: int | None = None,
) -> dict[str, object]:
    """Complete an objective only after replay verifies every root criterion."""
    try:
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            objective = store.load_objective(objective_id, version)
            completed = store.complete_objective(
                objective_id,
                objective.version,
                tuple(evidence_event_ids),
            )
        finally:
            store.close()
        return {
            "status": "pass",
            "objective_id": completed.objective_id,
            "version": completed.version,
            "objective_status": completed.status.value,
            "completed_at": completed.completed_at.text if completed.completed_at else None,
            "completion_evidence_event_ids": list(completed.completion_evidence_event_ids),
        }
    except Exception as error:
        return _trajectory_error(error, "complete_objective_failed")


@mcp.tool()
def append_trajectory_event(
    workspace_root: str,
    objective_id: str,
    run_id: str,
    event_id: str,
    event_kind: str,
    idempotency_key: str,
    branch_id: str = "main",
    seq: int | None = None,
    parent_event_id: str | None = None,
    occurred_at: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    intent: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
    artifacts: list[str] | None = None,
    outcome: str = "observed",
    source: str = "runner",
    supports_criterion_ids: list[str] | None = None,
    blocked_criterion_ids: list[str] | None = None,
    evidence_scope: str = EvidenceScope.PILOT.value,
    evidence_status: str = EvidenceStatus.OBSERVED.value,
    expected_seq: int | None = None,
) -> dict[str, object]:
    """Append one immutable runner event with idempotency and sequence checks."""
    try:
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            objective = store.load_objective(objective_id)
            history = store.load_events(objective_id)
            run_events = tuple(event for event in history if event.run_id == run_id)
            actual_seq = max((event.seq for event in run_events), default=0)
            event_seq = actual_seq + 1 if seq is None else seq
            parent = parent_event_id
            if parent is None and run_events:
                parent = max(run_events, key=lambda event: event.seq).event_id
            parsed_scope = cast(EvidenceScope, _trajectory_enum(evidence_scope, EvidenceScope))
            parsed_status = cast(EvidenceStatus, _trajectory_enum(evidence_status, EvidenceStatus))
            if parsed_status is EvidenceStatus.VERIFIED:
                criteria_by_id = objective.criteria_by_id
                for criterion_id in supports_criterion_ids or []:
                    criterion = criteria_by_id.get(criterion_id)
                    if criterion is not None and parsed_scope is not criterion.acceptance_scope:
                        parsed_status = EvidenceStatus.INSUFFICIENT
                        break
            event = TrajectoryEvent(
                event_id=event_id,
                run_id=run_id,
                seq=event_seq,
                parent_event_id=parent,
                branch_id=branch_id,
                event_kind=event_kind,
                occurred_at=_trajectory_parse_instant(occurred_at),
                started_at=None if started_at is None else _trajectory_parse_instant(started_at),
                ended_at=None if ended_at is None else _trajectory_parse_instant(ended_at),
                intent=_trajectory_intent(intent),
                result={} if result is None else result,
                metrics={} if metrics is None else metrics,
                artifacts=tuple(artifacts or ()),
                outcome=outcome,
                source=source,
                idempotency_key=idempotency_key,
                supports_criterion_ids=tuple(supports_criterion_ids or ()),
                blocked_criterion_ids=tuple(blocked_criterion_ids or ()),
                evidence_scope=parsed_scope,
                evidence_status=parsed_status,
            )
            persisted = store.append_event(objective_id, event, expected_seq=expected_seq)
        finally:
            store.close()
        return {"status": "pass", "event": _trajectory_event_json(persisted)}
    except Exception as error:
        return _trajectory_error(error, "append_trajectory_event_failed")


@mcp.tool()
def fork_research_path(
    workspace_root: str,
    objective_id: str,
    parent_run_id: str,
    parent_event_id: str,
    child_run_id: str,
    branch_id: str,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """Fork a child path from a persisted checkpoint."""
    try:
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            objective = store.load_objective(objective_id)
            history = store.load_events(objective_id)
            parent = next(
                (
                    event
                    for event in history
                    if event.event_id == parent_event_id and event.run_id == parent_run_id
                ),
                None,
            )
            if parent is None:
                raise ValueError("parent event does not belong to parent run")
            if any(event.run_id == child_run_id for event in history):
                raise ValueError("child run already exists")
            store.register_run(
                objective_id,
                child_run_id,
                branch_id=branch_id,
                parent_run_id=parent_run_id,
                parent_event_id=parent_event_id,
            )
            event = TrajectoryEvent(
                event_id=f"fork:{child_run_id}",
                run_id=child_run_id,
                seq=1,
                parent_event_id=parent_event_id,
                branch_id=branch_id,
                event_kind="branch_forked",
                occurred_at=parent.occurred_at,
                started_at=None,
                ended_at=None,
                intent=None,
                result={"parent_run_id": parent_run_id},
                metrics={},
                artifacts=(),
                outcome="forked",
                source="mcp",
                idempotency_key=idempotency_key or f"fork:{child_run_id}",
            )
            persisted = store.append_event(objective.objective_id, event, expected_seq=0)
        finally:
            store.close()
        return {
            "status": "pass",
            "run_id": child_run_id,
            "parent_run_id": parent_run_id,
            "parent_event_id": parent_event_id,
            "branch_id": branch_id,
            "event": _trajectory_event_json(persisted),
        }
    except Exception as error:
        return _trajectory_error(error, "fork_research_path_failed")


@mcp.tool()
def get_research_snapshot(
    workspace_root: str,
    objective_id: str,
    run_id: str,
) -> dict[str, object]:
    """Return a compact model-ready snapshot reconstructed from events."""
    try:
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            objective = store.load_objective(objective_id)
            events = store.load_events(objective_id)
            context = _trajectory_branch_context(events, run_id)
            snapshot = store.replay_snapshot(
                objective_id,
                run_id=run_id,
                path_context=context,
                dependency_context={},
            )
            return _trajectory_snapshot_json(objective, snapshot, events)
        finally:
            store.close()
    except Exception as error:
        return _trajectory_error(error, "get_snapshot_failed")


@mcp.tool()
def get_research_trajectory(
    workspace_root: str,
    objective_id: str,
    run_id: str | None = None,
    view: str = "events",
    after_seq: int = 0,
    limit: int = 100,
) -> dict[str, object]:
    """Read a replayable trajectory as events, a path, branches, or summary."""
    try:
        store = TrajectoryStore(_trajectory_store_path(workspace_root))
        try:
            objective = store.load_objective(objective_id)
            events = store.load_events(objective_id)
            if view not in {"summary", "path", "branches", "events"}:
                raise ValueError("view must be summary, path, branches, or events")
            if after_seq < 0:
                raise ValueError("after_seq must be non-negative")
            selected = tuple(
                event
                for event in events
                if (run_id is None or event.run_id == run_id) and event.seq > after_seq
            )[: max(1, min(limit, 1000))]
            if view == "summary":
                return {
                    "status": "pass",
                    "objective_id": objective.objective_id,
                    "version": objective.version,
                    "event_count": len(events),
                    "run_ids": sorted({event.run_id for event in events}),
                }
            if view == "branches":
                branches = {
                    event.run_id: {
                        "run_id": event.run_id,
                        "branch_id": event.branch_id,
                        "event_count": sum(item.run_id == event.run_id for item in events),
                    }
                    for event in events
                }
                return {"status": "pass", "branches": list(branches.values())}
            if view == "path" and run_id is None:
                raise ValueError("run_id is required for path view")
            return {
                "status": "pass",
                "objective_id": objective.objective_id,
                "run_id": run_id,
                "view": view,
                "after_seq": after_seq,
                "events": [_trajectory_event_json(event) for event in selected],
            }
        finally:
            store.close()
    except Exception as error:
        return _trajectory_error(error, "get_trajectory_failed")


@mcp.tool()
def pause_research_run(
    workspace_root: str,
    objective_id: str,
    run_id: str,
    event_id: str | None = None,
) -> dict[str, object]:
    """Record an explicit pause marker for a trajectory run."""
    return append_trajectory_event(
        workspace_root=workspace_root,
        objective_id=objective_id,
        run_id=run_id,
        event_id=event_id or f"pause:{run_id}",
        event_kind="run_paused",
        idempotency_key=event_id or f"pause:{run_id}",
        outcome="paused",
        source="mcp",
    )


@mcp.tool()
def abandon_research_branch(
    workspace_root: str,
    objective_id: str,
    run_id: str,
    event_id: str | None = None,
    reason: str = "abandoned by operator",
) -> dict[str, object]:
    """Record an explicit branch abandonment marker."""
    return append_trajectory_event(
        workspace_root=workspace_root,
        objective_id=objective_id,
        run_id=run_id,
        event_id=event_id or f"abandon:{run_id}",
        event_kind="branch_abandoned",
        idempotency_key=event_id or f"abandon:{run_id}",
        result={"reason": reason},
        outcome="abandoned",
        source="mcp",
    )


@mcp.tool()
def advance_research_run(workspace_root: str, run_id: str, stage: str = "") -> dict[str, object]:
    """Advance a research run one bounded step."""
    try:
        Workspace.open(Path(workspace_root), create=False)
        store = ResearchRunStore(Path(workspace_root) / ".noa" / "control" / "runs.sqlite3")
        try:
            stage_value = RunStage(stage) if stage else None
            run = store.advance(run_id, stage=stage_value)
            return {
                "status": "pass",
                "run_id": run.run_id,
                "stage": run.stage.value,
                "step": str(run.current_step),
            }
        finally:
            store.close()
    except Exception as error:
        return _error_result(getattr(error, "code", "advance_failed"), error.args[0])


@mcp.tool()
def acquire_and_stage_document(
    workspace_root: str,
    url: str,
    source_record_id: str,
    publication_id: str,
    work_id: str,
    title_assertion_id: str,
    doi_payload_json: str,
    confirm: bool = False,
) -> dict[str, object]:
    """Acquire one document under the network policy and stage a Crossref batch proposal."""
    if not confirm:
        return _error_result("confirmation_required", "Pass confirm=true to ingest")
    try:
        workspace = Workspace.open(Path(workspace_root), create=False)
        objects = ObjectStore(workspace.objects_dir)
        acquired = acquire_document(
            url,
            objects=objects,
            policy=workspace.network_policy,
            budgets=workspace.budgets,
        )
        entry = BatchPlanEntry(
            draft=crossref_draft(json.loads(doi_payload_json)),
            source_record_id=SourceRecordId.parse(source_record_id),
            work_id=WorkId.parse(work_id),
            publication_id=PublicationId.parse(publication_id),
            title_assertion_id=MetadataAssertionId.parse(title_assertion_id),
            year_assertion_id=None,
            relationship_assertion_id=None,
        )
        proposal, idem = single_entry_proposal(
            entry,
            source_system="crossref",
            retrieved_at=_now_instant(),
            media_type=acquired.media_type,
            authority_tier=AuthorityTier.AGGREGATOR,
        )
        return {
            "status": "staged",
            "digest": acquired.digest,
            "proposal_digest": proposal.canonical_digest().text,
            "idempotency_key": idem,
        }
    except Exception as error:
        return _error_result(getattr(error, "code", "ingest_failed"), error.args[0])


@mcp.tool()
def evidence_locator_for_page(page: int) -> dict[str, object]:
    """Build a canonical evidence locator string for a page number."""
    try:
        return {"status": "pass", "locator": page_locator(page)}
    except Exception as error:
        return _error_result(getattr(error, "code", "locator_failed"), error.args[0])


def run() -> None:
    mcp.run(transport="stdio")
