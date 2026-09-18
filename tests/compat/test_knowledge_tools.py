"""Regression tests for the knowledge tool surface: entity snapshots,
prefix discovery, and the end-to-end claim approval loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastmcp import Client

import noa.domain as d


def _uid() -> str:
    return str(d.generate_uuid7_value())


def _seed_work(root: Path, work_id: str) -> None:
    from noa.storage import GraphStore
    from noa.workspace import Workspace

    workspace = Workspace.open(root)
    graph = GraphStore(workspace.graph_dir / "graph.lbdb")
    try:
        graph.put_entity(work_id, "work", json.dumps({"title": "Attention Is All You Need"}))
    finally:
        graph.close()


def _tool_data(result: object) -> dict[str, object]:
    return cast(dict[str, object], result.data)


def _tool_error(result: object) -> tuple[str, str | None]:
    payload = _tool_data(result)
    assert payload["status"] == "error", payload
    detail = cast(str | None, payload.get("detail"))
    return str(payload["code"]), detail


async def test_list_id_prefixes_exposes_full_registry() -> None:
    from noa.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("list_id_prefixes")

    payload = _tool_data(result)
    assert payload["status"] == "pass"
    prefixes = cast(dict[str, str], payload["prefixes"])
    assert len(prefixes) == 23
    assert prefixes["wrk"] == "work"
    assert prefixes["evp"] == "evidence_passage"


async def test_put_entity_snapshot_requires_confirmation(tmp_path: Path) -> None:
    from noa.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": str(tmp_path),
                "kind": "work",
                "entity_id": f"wrk_{_uid()}",
            },
        )

    code, detail = _tool_error(result)
    assert code == "confirmation_required"
    assert detail is not None


async def test_put_entity_snapshot_rejects_unknown_kind_and_duplicate(
    tmp_path: Path,
) -> None:
    from noa.server import mcp

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    async with Client(mcp) as client:
        unconfirmed = await client.call_tool(
            "put_entity_snapshot",
            {"workspace_root": root, "kind": "person", "entity_id": f"per_{_uid()}"},
        )
        assert _tool_error(unconfirmed)[0] == "confirmation_required"

        rejected = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": root,
                "kind": "person",
                "entity_id": f"per_{_uid()}",
                "confirm": True,
            },
        )
        assert _tool_error(rejected)[0] == "unsupported_snapshot_kind"

        first = await client.call_tool(
            "put_entity_snapshot",
            {"workspace_root": root, "kind": "work", "entity_id": work_id, "confirm": True},
        )
        assert _tool_data(first) == {"status": "pass", "entity_id": work_id}

        duplicate = await client.call_tool(
            "put_entity_snapshot",
            {"workspace_root": root, "kind": "work", "entity_id": work_id, "confirm": True},
        )
        assert _tool_error(duplicate)[0] == "entity_exists"


async def test_structural_chain_rejects_missing_parent(tmp_path: Path) -> None:
    from noa.server import mcp

    async with Client(mcp) as client:
        orphan = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": str(tmp_path),
                "kind": "publication",
                "entity_id": f"pub_{_uid()}",
                "work_id": f"wrk_{_uid()}",
                "confirm": True,
            },
        )
    assert _tool_error(orphan)[0] == "dangling_structural_reference"


async def test_approved_claim_persists_and_note_can_attach(tmp_path: Path) -> None:
    from noa.server import build_entity_index_from_graph, mcp
    from noa.storage import GraphStore

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    doc_id = f"doc_{_uid()}"
    evidence_id = f"evp_{_uid()}"
    candidate_id = f"rvc_{_uid()}"
    claim_id = f"clm_{_uid()}"
    note_id = f"nte_{_uid()}"

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("work", work_id, {}),
            ("publication", pub_id, {"work_id": work_id}),
            (
                "document",
                doc_id,
                {
                    "publication_id": pub_id,
                    "content_digest": f"sha256:{'12' * 32}",
                    "media_type": "application/pdf",
                },
            ),
            (
                "evidence_passage",
                evidence_id,
                {
                    "source_id": doc_id,
                    "locator": "p. 3",
                    "text": "Attention is all you need.",
                    "source_language": "en",
                },
            ),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass"

        submitted = await client.call_tool(
            "submit_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": candidate_id,
                "work_id": work_id,
                "statement": "Self-attention beats recurrence on WMT14.",
                "language": "en",
                "evidence_ids": [evidence_id],
            },
        )
        assert _tool_data(submitted)["status"] == "pass"

        approved = await client.call_tool(
            "approve_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": candidate_id,
                "claim_id": claim_id,
                "actor": "human-reviewer",
                "review_event_reference": "review-1",
                "confirmed_at": "2026-08-24T00:00:00+00:00",
                "confirm": True,
            },
        )
        assert _tool_data(approved)["status"] == "pass"

        noted = await client.call_tool(
            "add_note",
            {
                "workspace_root": root,
                "note_id": note_id,
                "title": "sweep A decision",
                "body": "Drop the RNN baseline based on the cited evidence.",
                "author": "human",
                "attached_entity_ids": [claim_id],
                "confirm": True,
            },
        )
        assert _tool_data(noted)["status"] == "pass"

    graph = GraphStore(Path(root) / ".noa" / "graph" / "graph.lbdb")
    try:
        kinds_by_id = {row_id: kind for row_id, kind, _ in graph.all_entities()}
        index = build_entity_index_from_graph(graph)
    finally:
        graph.close()

    assert kinds_by_id[claim_id] == "claim"
    claim_snapshot = index.by_id[d.ClaimId.parse(claim_id)]
    assert isinstance(claim_snapshot, d.Claim)
    assert claim_snapshot.evidence_ids == (d.EvidencePassageId.parse(evidence_id),)


async def test_note_attachments_survive_round_trip_and_project(tmp_path: Path) -> None:
    from noa.server import build_entity_index_from_graph, mcp
    from noa.storage import GraphStore

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    doc_id = f"doc_{_uid()}"
    evidence_id = f"evp_{_uid()}"
    candidate_id = f"rvc_{_uid()}"
    claim_id = f"clm_{_uid()}"
    note_id = f"nte_{_uid()}"

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("work", work_id, {}),
            ("publication", pub_id, {"work_id": work_id}),
            (
                "document",
                doc_id,
                {
                    "publication_id": pub_id,
                    "content_digest": f"sha256:{'34' * 32}",
                    "media_type": "application/pdf",
                },
            ),
            (
                "evidence_passage",
                evidence_id,
                {
                    "source_id": doc_id,
                    "locator": "p. 5",
                    "text": "Attachment projection smoke.",
                    "source_language": "en",
                },
            ),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass"

        await client.call_tool(
            "submit_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": candidate_id,
                "work_id": work_id,
                "statement": "Projection smoke claim.",
                "language": "en",
                "evidence_ids": [evidence_id],
            },
        )
        approved = await client.call_tool(
            "approve_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": candidate_id,
                "claim_id": claim_id,
                "actor": "human-reviewer",
                "review_event_reference": "review-1",
                "confirmed_at": "2026-08-24T00:00:00+00:00",
                "confirm": True,
            },
        )
        assert _tool_data(approved)["status"] == "pass"

        noted = await client.call_tool(
            "add_note",
            {
                "workspace_root": root,
                "note_id": note_id,
                "title": "sweep A decision",
                "body": "Drop the RNN baseline based on the cited evidence.",
                "author": "human",
                "attached_entity_ids": [claim_id, work_id],
                "confirm": True,
            },
        )
        assert _tool_data(noted)["status"] == "pass"

    graph = GraphStore(Path(root) / ".noa" / "graph" / "graph.lbdb")
    try:
        stored = json.loads(graph.get_entity_payload(note_id) or "{}")
        index = build_entity_index_from_graph(graph)
    finally:
        graph.close()

    assert stored["attached_entity_ids"] == [claim_id, work_id]

    note_snapshot = index.by_id[d.NoteId.parse(note_id)]
    assert isinstance(note_snapshot, d.Note)
    assert [item.text for item in note_snapshot.attached_entity_ids] == [claim_id, work_id]

    import noa.domain as domain

    projection_input = domain.build_domain_projection_input(
        index, domain.build_source_record_index([]), [], [], [], []
    )
    projection = domain.project_structural_relationships(projection_input)
    note_edges = [
        rel
        for rel in projection.relationships
        if rel.key.subject_id.text == note_id and rel.key.predicate.value == "note_attached_to"
    ]
    assert {rel.key.object_id.text for rel in note_edges} == {claim_id, work_id}


async def test_get_note_returns_attachments_with_kinds(tmp_path: Path) -> None:
    from noa.server import mcp

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    doc_id = f"doc_{_uid()}"
    evidence_id = f"evp_{_uid()}"
    candidate_id = f"rvc_{_uid()}"
    claim_id = f"clm_{_uid()}"
    note_id = f"nte_{_uid()}"

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("work", work_id, {}),
            ("publication", pub_id, {"work_id": work_id}),
            (
                "document",
                doc_id,
                {
                    "publication_id": pub_id,
                    "content_digest": f"sha256:{'56' * 32}",
                    "media_type": "text/html",
                },
            ),
            (
                "evidence_passage",
                evidence_id,
                {
                    "source_id": doc_id,
                    "locator": "p. 1",
                    "text": "Get-note evidence.",
                    "source_language": "en",
                },
            ),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass"

        submitted = await client.call_tool(
            "submit_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": candidate_id,
                "work_id": work_id,
                "statement": "Get-note smoke claim.",
                "language": "en",
                "evidence_ids": [evidence_id],
            },
        )
        assert _tool_data(submitted)["status"] == "pass"

        approved = await client.call_tool(
            "approve_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": candidate_id,
                "claim_id": claim_id,
                "actor": "human-reviewer",
                "review_event_reference": "review-1",
                "confirmed_at": "2026-08-24T00:00:00+00:00",
                "confirm": True,
            },
        )
        assert _tool_data(approved)["status"] == "pass"

        noted = await client.call_tool(
            "add_note",
            {
                "workspace_root": root,
                "note_id": note_id,
                "title": "reading notes",
                "body": "Claim reviewed against the cited paper.",
                "author": "human",
                "attached_entity_ids": [claim_id],
                "confirm": True,
            },
        )
        assert _tool_data(noted)["status"] == "pass"

        fetched = await client.call_tool("get_note", {"workspace_root": root, "note_id": note_id})
        payload = _tool_data(fetched)
        assert payload["status"] == "pass"
        note = cast(dict[str, object], payload["note"])
        assert note["note_id"] == note_id
        assert note["title"] == "reading notes"
        attachments = cast(list[dict[str, object]], note["attached_entities"])
        assert [entry["entity_id"] for entry in attachments] == [claim_id]
        assert attachments[0]["kind"] == "claim"

        missing = await client.call_tool(
            "get_note", {"workspace_root": root, "note_id": f"nte_{_uid()}"}
        )
        assert _tool_error(missing)[0] == "note_not_found"


async def test_export_graph_view_writes_readable_json(tmp_path: Path) -> None:
    from noa.server import mcp

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("work", work_id, {}),
            ("publication", pub_id, {"work_id": work_id}),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass"

        exported = await client.call_tool("export_graph_view", {"workspace_root": root})

    payload = _tool_data(exported)
    assert payload["status"] == "pass"
    view_path = Path(cast(str, payload["path"]))
    assert view_path.is_file()

    view = json.loads(view_path.read_text(encoding="utf-8"))
    relationships = cast(list[dict[str, object]], view["relationships"])
    assert any(
        rel["predicate"] == "publication_of"
        and rel["subject_id"] == pub_id
        and rel["object_id"] == work_id
        for rel in relationships
    )


async def test_claim_approval_end_to_end_over_mcp(tmp_path: Path) -> None:
    from noa.server import mcp

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    doc_id = f"doc_{_uid()}"
    evidence_id = f"evp_{_uid()}"

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("work", work_id, {}),
            ("publication", pub_id, {"work_id": work_id}),
            (
                "document",
                doc_id,
                {
                    "publication_id": pub_id,
                    "content_digest": f"sha256:{'ab' * 32}",
                    "media_type": "application/pdf",
                },
            ),
            (
                "evidence_passage",
                evidence_id,
                {
                    "source_id": doc_id,
                    "locator": "p. 3",
                    "text": "Attention is all you need.",
                    "source_language": "en",
                },
            ),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass", staged.data

        submitted = await client.call_tool(
            "submit_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": f"rvc_{_uid()}",
                "work_id": work_id,
                "statement": "Scaled-up runs keep loss curves stable.",
                "language": "en",
                "evidence_ids": [evidence_id],
            },
        )
        candidate = _tool_data(submitted)
        assert candidate["status"] == "pass"

        approved = await client.call_tool(
            "approve_claim_candidate",
            {
                "workspace_root": root,
                "candidate_id": cast(str, candidate["candidate_id"]),
                "claim_id": f"clm_{_uid()}",
                "actor": "human-reviewer",
                "review_event_reference": "review-1",
                "confirmed_at": "2026-08-24T00:00:00+00:00",
                "confirm": True,
            },
        )
        approved_payload = _tool_data(approved)
        assert approved_payload["status"] == "pass"
        assert cast(str, approved_payload["claim_id"]).startswith("clm_")

        search = await client.call_tool(
            "knowledge_search",
            {"workspace_root": root, "query": "attention"},
        )
        hits = cast(list[dict[str, object]], _tool_data(search)["hits"])
        indexed_ids = {str(hit["entity_id"]) for hit in hits}
        assert evidence_id in indexed_ids


async def test_evidence_passage_payload_survives_graph_round_trip(
    tmp_path: Path,
) -> None:
    from noa.server import mcp
    from noa.storage import GraphStore

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    doc_id = f"doc_{_uid()}"
    evidence_id = f"evp_{_uid()}"
    _seed_work(tmp_path, work_id)

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("publication", pub_id, {"work_id": work_id}),
            (
                "document",
                doc_id,
                {
                    "publication_id": pub_id,
                    "content_digest": f"sha256:{'cd' * 32}",
                    "media_type": "application/pdf",
                },
            ),
            (
                "evidence_passage",
                evidence_id,
                {
                    "source_id": doc_id,
                    "locator": "p. 7",
                    "text": "Smoke text for the round trip.",
                    "source_language": "en",
                },
            ),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass", staged.data

    graph = GraphStore(Path(root) / ".noa" / "graph" / "graph.lbdb")
    try:
        rows = {
            row_id: (kind, json.loads(payload)) for row_id, kind, payload in graph.all_entities()
        }
    finally:
        graph.close()

    stored_kind, stored_payload = rows[evidence_id]
    assert stored_kind == "evidence_passage"
    assert stored_payload["text"] == "Smoke text for the round trip."
    assert stored_payload["source_id"] == doc_id
    assert stored_payload["recorded_at"].endswith("Z")


async def test_reconstructed_index_contains_all_chain_kinds(tmp_path: Path) -> None:
    from noa.server import build_entity_index_from_graph, mcp
    from noa.storage import GraphStore

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    doc_id = f"doc_{_uid()}"
    evidence_id = f"evp_{_uid()}"
    _seed_work(tmp_path, work_id)

    async with Client(mcp) as client:
        for kind, entity_id, extra in (
            ("publication", pub_id, {"work_id": work_id}),
            (
                "document",
                doc_id,
                {
                    "publication_id": pub_id,
                    "content_digest": f"sha256:{'ef' * 32}",
                    "media_type": "text/html",
                },
            ),
            (
                "evidence_passage",
                evidence_id,
                {
                    "source_id": doc_id,
                    "locator": "p. 1",
                    "text": "Terminal resolution smoke.",
                    "source_language": "en",
                },
            ),
        ):
            staged = await client.call_tool(
                "put_entity_snapshot",
                {
                    "workspace_root": root,
                    "kind": kind,
                    "entity_id": entity_id,
                    **extra,
                    "confirm": True,
                },
            )
            assert _tool_data(staged)["status"] == "pass", staged.data

    graph = GraphStore(Path(root) / ".noa" / "graph" / "graph.lbdb")
    try:
        index = build_entity_index_from_graph(graph)
    finally:
        graph.close()

    kinds = {type(snapshot).__name__ for snapshot in index.by_id.values()}
    assert {"Work", "Publication", "Document", "EvidencePassage"} <= kinds


async def test_put_entity_snapshot_validates_field_values(tmp_path: Path) -> None:
    from noa.server import mcp

    root = str(tmp_path)
    work_id = f"wrk_{_uid()}"
    pub_id = f"pub_{_uid()}"
    _seed_work(tmp_path, work_id)

    async with Client(mcp) as client:
        bad_digest = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": root,
                "kind": "document",
                "entity_id": f"doc_{_uid()}",
                "publication_id": pub_id,
                "content_digest": "md5:nope",
                "media_type": "application/pdf",
                "confirm": True,
            },
        )
        code, _ = _tool_error(bad_digest)
        assert code == "invalid_value_object"

        bad_media = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": root,
                "kind": "document",
                "entity_id": f"doc_{_uid()}",
                "publication_id": pub_id,
                "content_digest": f"sha256:{'ab' * 32}",
                "media_type": "Application/PDF",
                "confirm": True,
            },
        )
        code, _ = _tool_error(bad_media)
        assert code == "invalid_value_object"


async def test_evidence_source_record_kind_is_rejected(tmp_path: Path) -> None:
    from noa.server import mcp

    root = str(tmp_path)
    async with Client(mcp) as client:
        rejected = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": root,
                "kind": "evidence_passage",
                "entity_id": f"evp_{_uid()}",
                "source_id": f"src_{_uid()}",
                "locator": "p. 2",
                "text": "Source-record-backed evidence needs a committed record index.",
                "source_language": "en",
                "confirm": True,
            },
        )
    assert _tool_error(rejected)[0] == "unsupported_source_kind"


@pytest.mark.parametrize(
    ("kind", "entity_prefix"),
    [("publication", "pub"), ("document", "doc"), ("evidence_passage", "evp")],
)
async def test_entity_id_prefix_must_match_kind(
    tmp_path: Path, kind: str, entity_prefix: str
) -> None:
    from noa.server import mcp

    mismatched = {"publication": "doc_", "document": "pub_", "evidence_passage": "pub_"}[kind]

    async with Client(mcp) as client:
        result = await client.call_tool(
            "put_entity_snapshot",
            {
                "workspace_root": str(tmp_path),
                "kind": kind,
                "entity_id": f"{mismatched}{_uid().removeprefix('wrk_')}",
                "confirm": True,
            },
        )
    code, _ = _tool_error(result)
    assert code == "invalid_snapshot_payload" or code == "id_prefix_mismatch"
    del entity_prefix
