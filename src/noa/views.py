"""Search, notes, lineage views, and projection exports (contract slices 8)."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .domain import (
    DomainProjectionInput,
    FactualPredicate,
    KnowledgeEntityId,
    MetadataAssertion,
    Note,
    ProjectedRelationship,
    ProjectionStatus,
    ReviewedSemanticPredicate,
    project_relationships,
    project_structural_relationships,
    resolve_terminal,
)
from .workspace import WorkspaceError


def _error(code: str, message: str, **context: str) -> WorkspaceError:
    return WorkspaceError(code=code, message=message, context=context)


@dataclass(frozen=True)
class SearchHit:
    entity_id: str
    kind: str
    field: str
    value: str
    score: int


@dataclass(frozen=True)
class SearchIndex:
    """Deterministic keyword index over metadata values and note text."""

    entries: tuple[tuple[str, str, str, str], ...]

    @classmethod
    def build(
        cls,
        *,
        entities_by_text: dict[str, object],
        metadata_assertions: Sequence[MetadataAssertion],
        terminals: dict[str, str],
    ) -> SearchIndex:
        collected: list[tuple[str, str, str, str]] = []
        for assertion in metadata_assertions:
            subject_text = terminals.get(assertion.subject_id.text, assertion.subject_id.text)
            value = assertion.value
            text = getattr(value, "text", None)
            if isinstance(text, str) and text.strip():
                kind = _kind_of(entities_by_text.get(subject_text))
                collected.append(
                    (
                        subject_text,
                        kind,
                        assertion.field.value,
                        unicodedata.normalize("NFC", text.strip().lower()),
                    )
                )
        for snapshot in entities_by_text.values():
            if isinstance(snapshot, Note):
                for chunk in (snapshot.title, snapshot.body):
                    normalized = unicodedata.normalize("NFC", chunk.strip().lower())
                    if normalized:
                        collected.append((snapshot.id.text, "note", "note.body", normalized[:2000]))
        return cls(entries=tuple(sorted(set(collected))))

    def query(self, term: str, *, limit: int = 20) -> list[SearchHit]:
        needle = unicodedata.normalize("NFC", term.strip().lower())
        if not needle:
            return []
        hits: list[SearchHit] = []
        for entity_id, kind, field_name, value in self.entries:
            score = 0
            if value == needle:
                score = 3
            elif value.startswith(needle):
                score = 2
            elif needle in value:
                score = 1
            if score:
                hits.append(SearchHit(entity_id, kind, field_name, value, score))
        hits.sort(key=lambda hit: (-hit.score, hit.entity_id, hit.field))
        return hits[:limit]


def _kind_of(snapshot: object) -> str:
    return type(snapshot).__name__.lower() if snapshot is not None else "unknown"


_NOTE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    PRIMARY KEY (note_id, revision)
);
"""


class NoteStore:
    """Durable note revisions; the current Note snapshot stays authoritative in the graph."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        self._connection = sqlite3.connect(database_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(_NOTE_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def record_revision(self, note: Note) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO notes (note_id, revision, title, body, author)"
            " VALUES (?, ?, ?, ?, ?)",
            (note.id.text, note.revision, note.title, note.body, note.author),
        )

    def history(self, note_id: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT revision, title, body, author FROM notes WHERE note_id = ? ORDER BY revision",
            (note_id,),
        ).fetchall()
        return [
            {"revision": row[0], "title": row[1], "body": row[2], "author": row[3]} for row in rows
        ]


_LINEAGE_PREDICATES = (
    ReviewedSemanticPredicate.EXTENDS,
    ReviewedSemanticPredicate.IMPROVES_ON,
)


@dataclass(frozen=True)
class LineageEdgeView:
    predicate: str
    subject_id: str
    object_id: str
    status: str
    supporting_record_ids: tuple[str, ...]


@dataclass(frozen=True)
class LineageView:
    seed_id: str
    depth: int
    nodes: tuple[str, ...]
    edges: tuple[LineageEdgeView, ...]


def build_lineage_view(
    seed_id: KnowledgeEntityId,
    projection_input: DomainProjectionInput,
    *,
    depth: int = 2,
    include_factual_cites: bool = True,
) -> LineageView:
    if depth < 1 or depth > 5:
        raise _error("invalid_lineage_depth", "depth must be between 1 and 5")
    evaluation_terminals = {
        snapshot.id.text: resolve_terminal(
            snapshot.id, projection_input.entity_index
        ).terminal_id.text
        for snapshot in projection_input.entity_index.by_id.values()
    }
    seed_terminal = evaluation_terminals.get(seed_id.text, seed_id.text)

    edges: list[LineageEdgeView] = []
    adjacency: dict[str, set[str]] = {}
    predicates: tuple[object, ...] = (
        *_LINEAGE_PREDICATES,
        *([FactualPredicate.CITES] if include_factual_cites else ()),
    )
    projected: dict[str, tuple[ProjectedRelationship, ...]] = {}
    for predicate in predicates:
        typed_predicate = cast("FactualPredicate | ReviewedSemanticPredicate", predicate)
        results = project_relationships(typed_predicate, projection_input)
        projected[typed_predicate.value] = results
        for entry in results:
            subject_text = entry.key.subject_id.text
            object_text = entry.key.object_id.text
            edges.append(
                LineageEdgeView(
                    predicate=typed_predicate.value,
                    subject_id=subject_text,
                    object_id=object_text,
                    status=entry.status.value,
                    supporting_record_ids=tuple(item.text for item in entry.supporting_record_ids),
                )
            )
            if entry.status is not ProjectionStatus.RESOLVED:
                continue
            adjacency.setdefault(subject_text, set()).add(object_text)

    visited = {seed_terminal}
    frontier = [seed_terminal]
    for _ in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            for successor in sorted(adjacency.get(node, ())):
                if successor not in visited:
                    visited.add(successor)
                    next_frontier.append(successor)
        frontier = next_frontier
        if not frontier:
            break

    scoped_edges = tuple(
        edge
        for edge in sorted(
            edges, key=lambda item: (item.predicate, item.subject_id, item.object_id)
        )
        if edge.subject_id in visited or edge.object_id in visited
    )
    return LineageView(
        seed_id=seed_terminal, depth=depth, nodes=tuple(sorted(visited)), edges=scoped_edges
    )


def export_projection_view(
    projection_input: DomainProjectionInput,
    output_path: Path,
) -> Path:
    """Write the deterministic structural projection as a rebuildable JSON view."""
    projection = project_structural_relationships(projection_input)
    view = {
        "current_record_ids": [item.text for item in projection.current_record_ids],
        "relationships": [
            {
                "predicate": relationship.key.predicate.value,
                "subject_id": relationship.key.subject_id.text,
                "object_id": relationship.key.object_id.text,
                "supporting_subject_record_ids": [
                    item.text for item in relationship.supporting_subject_record_ids
                ],
            }
            for relationship in projection.relationships
        ],
        "excluded": [
            {
                "subject_id": item.subject_id.text,
                "reason": item.reason.value,
            }
            for item in projection.excluded
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(view, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(output_path)
    return output_path


__all__ = [
    "LineageEdgeView",
    "LineageView",
    "NoteStore",
    "SearchHit",
    "SearchIndex",
    "build_lineage_view",
    "export_projection_view",
]
