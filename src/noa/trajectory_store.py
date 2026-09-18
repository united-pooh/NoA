"""SQLite persistence for the append-only research trajectory kernel.

The store deliberately keeps persistence concerns separate from the pure domain
objects in :mod:`noa.trajectory`.  Events are immutable facts; snapshots are a
cache and can always be reconstructed by replaying events.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .domain import UtcInstant
from .domain.errors import DomainError
from .trajectory import (
    BranchContext,
    CriterionRole,
    DriftReport,
    EvidenceScope,
    EvidenceStatus,
    ObjectiveFacet,
    ObjectiveStatus,
    ProgressReport,
    ResearchObjective,
    SuccessCriterion,
    TrajectoryEvent,
    TrajectoryIntent,
    TrajectorySnapshot,
    WorkClass,
    WorkSource,
    evaluate_drift,
    evaluate_progress,
    validate_history,
)
from .trajectory import (
    complete_objective as complete_trajectory_objective,
)


class TrajectoryStoreError(Exception):
    """Structured persistence failure."""

    def __init__(self, code: str, message: str, **context: str) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_objectives (
    objective_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    objective_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (objective_id, version)
);
CREATE TABLE IF NOT EXISTS trajectory_events (
    objective_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    parent_event_id TEXT,
    branch_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (objective_id, event_id),
    UNIQUE (objective_id, idempotency_key),
    UNIQUE (objective_id, run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_trajectory_events_run
    ON trajectory_events(objective_id, run_id, seq);
CREATE TABLE IF NOT EXISTS trajectory_runs (
    objective_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    parent_run_id TEXT,
    parent_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    PRIMARY KEY (objective_id, run_id)
);
CREATE TABLE IF NOT EXISTS trajectory_snapshots (
    objective_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (objective_id, run_id)
);
"""


def _now() -> str:
    return UtcInstant.from_datetime(datetime.now().astimezone()).text


def _error(code: str, message: str, **context: str) -> TrajectoryStoreError:
    return TrajectoryStoreError(code, message, **context)


def _as_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise _error("corrupt_record", f"{field} must be an integer")
    return value


def _as_float(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise _error("corrupt_record", f"{field} must be numeric")
    return float(cast(int | float, value))


def _as_items(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise _error("corrupt_record", f"{field} must be an array")
    return value


def _plain(value: object) -> object:
    """Convert frozen JSON and enums to values accepted by json.dumps."""

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "value") and value.__class__.__module__ == "enum":
        return cast(Any, value).value
    return value


def _instant(value: UtcInstant | None) -> str | None:
    return None if value is None else value.text


def _parse_instant(value: object) -> UtcInstant | None:
    if value is None:
        return None
    if type(value) is not str:
        raise _error("corrupt_record", "instant is not text")
    try:
        return UtcInstant.from_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (TypeError, ValueError) as exc:
        raise _error("corrupt_record", "invalid instant", value=value) from exc


def _facet_to_json(facet: ObjectiveFacet) -> dict[str, object]:
    return {"kind": facet.kind, "value": facet.value, "weight": facet.weight}


def _facet_from_json(value: object) -> ObjectiveFacet:
    if not isinstance(value, Mapping):
        raise _error("corrupt_record", "facet must be an object")
    try:
        return ObjectiveFacet(
            str(value["kind"]), str(value["value"]), _as_float(value["weight"], "weight")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _error("corrupt_record", "invalid facet") from exc


def _criterion_to_json(criterion: SuccessCriterion) -> dict[str, object]:
    return {
        "criterion_id": criterion.criterion_id,
        "metric": criterion.metric,
        "target": criterion.target,
        "role": criterion.role.value,
        "depends_on": list(criterion.depends_on),
        "blocking": criterion.blocking,
        "acceptance_scope": criterion.acceptance_scope.value,
    }


def _criterion_from_json(value: object) -> SuccessCriterion:
    if not isinstance(value, Mapping):
        raise _error("corrupt_record", "criterion must be an object")
    try:
        return SuccessCriterion(
            criterion_id=str(value["criterion_id"]),
            metric=str(value["metric"]),
            target=str(value["target"]),
            role=CriterionRole(str(value["role"])),
            depends_on=tuple(str(item) for item in cast(Sequence[object], value["depends_on"])),
            blocking=bool(value["blocking"]),
            acceptance_scope=EvidenceScope(str(value["acceptance_scope"])),
        )
    except (KeyError, TypeError, ValueError, DomainError) as exc:
        raise _error("corrupt_record", "invalid criterion") from exc


def _objective_to_json(objective: ResearchObjective) -> str:
    payload = {
        "objective_id": objective.objective_id,
        "version": objective.version,
        "statement": objective.statement,
        "facets": [_facet_to_json(facet) for facet in objective.facets],
        "criteria": [_criterion_to_json(criterion) for criterion in objective.criteria],
        "status": objective.status.value,
        "supersedes_version": objective.supersedes_version,
        "completed_at": _instant(objective.completed_at),
        "completion_evidence_event_ids": list(objective.completion_evidence_event_ids),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _objective_from_json(value: str) -> ResearchObjective:
    try:
        payload = cast(dict[str, object], json.loads(value))
        return ResearchObjective(
            objective_id=str(payload["objective_id"]),
            version=_as_int(payload["version"], "version"),
            statement=str(payload["statement"]),
            facets=tuple(
                _facet_from_json(item) for item in cast(Sequence[object], payload["facets"])
            ),
            criteria=tuple(
                _criterion_from_json(item) for item in cast(Sequence[object], payload["criteria"])
            ),
            status=ObjectiveStatus(str(payload["status"])),
            supersedes_version=(
                None
                if payload.get("supersedes_version") is None
                else _as_int(payload["supersedes_version"], "supersedes_version")
            ),
            completed_at=_parse_instant(payload.get("completed_at")),
            completion_evidence_event_ids=tuple(
                str(item)
                for item in cast(Sequence[object], payload.get("completion_evidence_event_ids", ()))
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, DomainError) as exc:
        raise _error("corrupt_record", "invalid objective record") from exc


def _intent_to_json(intent: TrajectoryIntent | None) -> object:
    if intent is None:
        return None
    return {
        "hypothesis_ids": list(intent.hypothesis_ids),
        "criterion_ids": list(intent.criterion_ids),
        "facets": [_facet_to_json(facet) for facet in intent.facets],
        "action": intent.action,
        "work_class": intent.work_class.value,
        "work_source": intent.work_source.value,
        "blocks_criterion_ids": list(intent.blocks_criterion_ids),
        "returns_to_criterion_ids": list(intent.returns_to_criterion_ids),
        "exit_conditions": list(intent.exit_conditions),
        "evidence_scope": intent.evidence_scope.value,
    }


def _intent_from_json(value: object) -> TrajectoryIntent | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _error("corrupt_record", "intent must be an object")
    try:
        return TrajectoryIntent(
            hypothesis_ids=tuple(
                str(item) for item in cast(Sequence[object], value["hypothesis_ids"])
            ),
            criterion_ids=tuple(
                str(item) for item in cast(Sequence[object], value["criterion_ids"])
            ),
            facets=tuple(
                _facet_from_json(item) for item in cast(Sequence[object], value["facets"])
            ),
            action=str(value["action"]),
            work_class=WorkClass(str(value["work_class"])),
            work_source=WorkSource(str(value["work_source"])),
            blocks_criterion_ids=tuple(
                str(item) for item in cast(Sequence[object], value.get("blocks_criterion_ids", ()))
            ),
            returns_to_criterion_ids=tuple(
                str(item)
                for item in cast(Sequence[object], value.get("returns_to_criterion_ids", ()))
            ),
            exit_conditions=tuple(
                str(item) for item in cast(Sequence[object], value.get("exit_conditions", ()))
            ),
            evidence_scope=EvidenceScope(str(value["evidence_scope"])),
        )
    except (KeyError, TypeError, ValueError, DomainError) as exc:
        raise _error("corrupt_record", "invalid intent") from exc


def _event_to_json(event: TrajectoryEvent) -> str:
    payload = {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "seq": event.seq,
        "parent_event_id": event.parent_event_id,
        "branch_id": event.branch_id,
        "event_kind": event.event_kind,
        "occurred_at": event.occurred_at.text,
        "started_at": _instant(event.started_at),
        "ended_at": _instant(event.ended_at),
        "intent": _intent_to_json(event.intent),
        "result": _plain(event.result),
        "metrics": _plain(event.metrics),
        "artifacts": list(event.artifacts),
        "outcome": event.outcome,
        "source": event.source,
        "idempotency_key": event.idempotency_key,
        "supports_criterion_ids": list(event.supports_criterion_ids),
        "blocked_criterion_ids": list(event.blocked_criterion_ids),
        "evidence_scope": event.evidence_scope.value,
        "evidence_status": event.evidence_status.value,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_from_json(value: str) -> TrajectoryEvent:
    try:
        payload = cast(dict[str, object], json.loads(value))
        occurred = _parse_instant(payload["occurred_at"])
        if occurred is None:
            raise _error("corrupt_record", "event occurred_at is required")
        return TrajectoryEvent(
            event_id=str(payload["event_id"]),
            run_id=str(payload["run_id"]),
            seq=_as_int(payload["seq"], "seq"),
            parent_event_id=(
                None if payload.get("parent_event_id") is None else str(payload["parent_event_id"])
            ),
            branch_id=str(payload["branch_id"]),
            event_kind=str(payload["event_kind"]),
            occurred_at=occurred,
            started_at=_parse_instant(payload.get("started_at")),
            ended_at=_parse_instant(payload.get("ended_at")),
            intent=_intent_from_json(payload.get("intent")),
            result=cast(Mapping[str, object], payload.get("result", {})),
            metrics=cast(Mapping[str, object], payload.get("metrics", {})),
            artifacts=tuple(
                str(item) for item in cast(Sequence[object], payload.get("artifacts", ()))
            ),
            outcome=str(payload["outcome"]),
            source=str(payload["source"]),
            idempotency_key=str(payload["idempotency_key"]),
            supports_criterion_ids=tuple(
                str(item)
                for item in cast(Sequence[object], payload.get("supports_criterion_ids", ()))
            ),
            blocked_criterion_ids=tuple(
                str(item)
                for item in cast(Sequence[object], payload.get("blocked_criterion_ids", ()))
            ),
            evidence_scope=EvidenceScope(str(payload["evidence_scope"])),
            evidence_status=EvidenceStatus(str(payload["evidence_status"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, DomainError) as exc:
        if isinstance(exc, TrajectoryStoreError):
            raise
        raise _error("corrupt_record", "invalid event record") from exc


def _snapshot_to_json(snapshot: TrajectorySnapshot) -> str:
    payload = {
        "run_id": snapshot.run_id,
        "objective_status": snapshot.objective_status.value,
        "branch_elapsed_ms": snapshot.branch_elapsed_ms,
        "path_elapsed_ms": snapshot.path_elapsed_ms,
        "duration_source": snapshot.duration_source,
        "progress": {
            "verified_criterion_ids": list(snapshot.progress.verified_criterion_ids),
            "pending_criterion_ids": list(snapshot.progress.pending_criterion_ids),
            "fraction": snapshot.progress.fraction,
            "root_criterion_ids": list(snapshot.progress.root_criterion_ids),
            "prerequisite_criterion_ids": list(snapshot.progress.prerequisite_criterion_ids),
            "evidence_status_by_criterion": _plain(snapshot.progress.evidence_status_by_criterion),
        },
        "drift": {
            "path_distance": snapshot.drift.path_distance,
            "goal_drift": snapshot.drift.goal_drift,
            "score": snapshot.drift.score,
            "root_progress": snapshot.drift.root_progress,
            "prerequisite_progress": snapshot.drift.prerequisite_progress,
            "validation_stagnation_events": snapshot.drift.validation_stagnation_events,
            "return_due": snapshot.drift.return_due,
            "basis_event_ids": list(snapshot.drift.basis_event_ids),
            "reasons": list(snapshot.drift.reasons),
        },
        "next_action": snapshot.next_action,
        "active_blockers": list(snapshot.active_blockers),
        "last_capability_evidence_seq": snapshot.last_capability_evidence_seq,
        "last_prerequisite_release_seq": snapshot.last_prerequisite_release_seq,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class TrajectoryStore:
    """Append-only trajectory facts and rebuildable snapshot cache."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(_SCHEMA)
        self.migrate_legacy_runs()

    def close(self) -> None:
        self._connection.close()

    def create_objective(self, objective: ResearchObjective) -> ResearchObjective:
        payload = _objective_to_json(objective)
        try:
            self._connection.execute(
                "INSERT INTO research_objectives("
                "objective_id,version,status,objective_json,created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    objective.objective_id,
                    objective.version,
                    objective.status.value,
                    payload,
                    _now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _error(
                "duplicate_objective",
                "objective version already exists",
                objective_id=objective.objective_id,
                version=str(objective.version),
            ) from exc
        return objective

    def revise_objective(
        self,
        objective_id: str,
        base_version: int,
        objective: ResearchObjective,
    ) -> ResearchObjective:
        """Create an immutable objective version after an explicit revision."""
        current = self.load_objective(objective_id)
        if current.version != base_version:
            raise _error(
                "version_conflict",
                "base objective version is stale",
                expected_version=str(current.version),
                actual_version=str(base_version),
            )
        if objective.objective_id != objective_id:
            raise _error("objective_mismatch", "revised objective ID does not match")
        if objective.version <= base_version:
            raise _error("invalid_version", "revised objective version must increase")
        if objective.supersedes_version != base_version:
            raise _error("invalid_version", "revised objective must supersede base version")
        return self.create_objective(objective)

    def complete_objective(
        self,
        objective_id: str,
        version: int,
        evidence_event_ids: Sequence[str],
    ) -> ResearchObjective:
        """Transition one active objective version to completed after replay."""
        objective = self.load_objective(objective_id, version)
        events = self.load_events(objective_id)
        completed = complete_trajectory_objective(
            objective,
            events,
            completed_at=events[-1].occurred_at if events else None,
        )
        expected = tuple(str(item) for item in evidence_event_ids)
        if expected and set(expected) != set(completed.completion_evidence_event_ids):
            raise _error("invalid_completion_evidence", "evidence IDs do not match replayed proof")
        payload = _objective_to_json(completed)
        self._connection.execute(
            "UPDATE research_objectives SET status = ?, objective_json = ? "
            "WHERE objective_id = ? AND version = ?",
            (completed.status.value, payload, objective_id, version),
        )
        return completed

    def load_objective(self, objective_id: str, version: int | None = None) -> ResearchObjective:
        query = (
            "SELECT objective_json FROM research_objectives WHERE objective_id = ?"
            if version is None
            else (
                "SELECT objective_json FROM research_objectives "
                "WHERE objective_id = ? AND version = ?"
            )
        )
        params: tuple[object, ...] = (objective_id,) if version is None else (objective_id, version)
        if version is None:
            query += " ORDER BY version DESC LIMIT 1"
        row = self._connection.execute(query, params).fetchone()
        if row is None:
            raise _error(
                "objective_not_found", "objective does not exist", objective_id=objective_id
            )
        return _objective_from_json(str(row[0]))

    def list_objectives(self, objective_id: str | None = None) -> tuple[ResearchObjective, ...]:
        if objective_id is None:
            rows = self._connection.execute(
                "SELECT objective_json FROM research_objectives ORDER BY objective_id, version"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT objective_json FROM research_objectives "
                "WHERE objective_id = ? ORDER BY version",
                (objective_id,),
            ).fetchall()
        return tuple(_objective_from_json(str(row[0])) for row in rows)

    def register_run(
        self,
        objective_id: str,
        run_id: str,
        *,
        branch_id: str = "main",
        parent_run_id: str | None = None,
        parent_event_id: str | None = None,
    ) -> None:
        """Persist run metadata without inventing a trajectory event."""

        self.load_objective(objective_id)
        try:
            self._connection.execute(
                "INSERT INTO trajectory_runs(objective_id,run_id,branch_id,parent_run_id,"
                "parent_event_id,status,created_at) VALUES(?,?,?,?,?,'active',?)",
                (
                    objective_id,
                    run_id,
                    branch_id,
                    parent_run_id,
                    parent_event_id,
                    _now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _error("duplicate_run", "trajectory run already exists", run_id=run_id) from exc

    def append_event(
        self,
        objective_id: str,
        event: TrajectoryEvent,
        *,
        expected_seq: int | None = None,
    ) -> TrajectoryEvent:
        objective = self.load_objective(objective_id)
        if objective.status in {ObjectiveStatus.COMPLETED, ObjectiveStatus.SUPERSEDED}:
            raise _error(
                "objective_terminal",
                "terminal objectives cannot accept events",
                objective_id=objective_id,
            )
        existing_by_key = self._connection.execute(
            "SELECT event_json FROM trajectory_events "
            "WHERE objective_id = ? AND idempotency_key = ?",
            (objective_id, event.idempotency_key),
        ).fetchone()
        if existing_by_key is not None:
            stored = _event_from_json(str(existing_by_key[0]))
            if _event_to_json(stored) == _event_to_json(event):
                return stored
            raise _error("idempotency_conflict", "idempotency key maps to another event")
        rows = self._connection.execute(
            "SELECT event_json FROM trajectory_events WHERE objective_id = ? ORDER BY rowid",
            (objective_id,),
        ).fetchall()
        history = tuple(_event_from_json(str(row[0])) for row in rows)
        run_events = tuple(item for item in history if item.run_id == event.run_id)
        current_seq = max((item.seq for item in run_events), default=0)
        if expected_seq is not None and (
            type(expected_seq) is not int or expected_seq != current_seq
        ):
            raise _error(
                "sequence_conflict",
                "expected sequence does not match persisted run sequence",
                expected_seq=str(expected_seq),
                actual_seq=str(current_seq),
            )
        if event.seq != current_seq + 1:
            raise _error(
                "invalid_sequence",
                "event sequence must append exactly one position in its run",
                expected_seq=str(current_seq + 1),
                actual_seq=str(event.seq),
            )
        if event.parent_event_id is not None and not any(
            item.event_id == event.parent_event_id for item in history
        ):
            raise _error("missing_parent", "parent event is not persisted")
        if event.parent_event_id is None and event.seq != 1:
            raise _error("invalid_parent", "non-root event requires a parent")
        try:
            validate_history((*history, event))
        except (DomainError, ValueError) as exc:
            raise _error("invalid_event", str(exc), event_id=event.event_id) from exc
        payload = _event_to_json(event)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "INSERT INTO trajectory_events(objective_id,event_id,run_id,seq,parent_event_id,"
                "branch_id,idempotency_key,event_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    objective_id,
                    event.event_id,
                    event.run_id,
                    event.seq,
                    event.parent_event_id,
                    event.branch_id,
                    event.idempotency_key,
                    payload,
                    _now(),
                ),
            )
            self._connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            self._connection.execute("ROLLBACK")
            raise _error("append_conflict", "event conflicts with persisted trajectory") from exc
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        return event

    def load_events(
        self,
        objective_id: str,
        *,
        run_id: str | None = None,
        branch_id: str | None = None,
    ) -> tuple[TrajectoryEvent, ...]:
        query = "SELECT event_json FROM trajectory_events WHERE objective_id = ?"
        params: list[object] = [objective_id]
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        if branch_id is not None:
            query += " AND branch_id = ?"
            params.append(branch_id)
        query += " ORDER BY rowid"
        rows = self._connection.execute(query, tuple(params)).fetchall()
        return tuple(_event_from_json(str(row[0])) for row in rows)

    def save_snapshot(self, objective_id: str, snapshot: TrajectorySnapshot) -> TrajectorySnapshot:
        payload = _snapshot_to_json(snapshot)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self._connection.execute(
            "INSERT INTO trajectory_snapshots("
            "objective_id,run_id,snapshot_json,snapshot_hash,updated_at)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(objective_id,run_id) DO UPDATE SET"
            " snapshot_json=excluded.snapshot_json, snapshot_hash=excluded.snapshot_hash,"
            " updated_at=excluded.updated_at",
            (objective_id, snapshot.run_id, payload, digest, _now()),
        )
        return snapshot

    def load_snapshot(self, objective_id: str, run_id: str) -> TrajectorySnapshot | None:
        row = self._connection.execute(
            "SELECT snapshot_json,snapshot_hash FROM trajectory_snapshots"
            " WHERE objective_id = ? AND run_id = ?",
            (objective_id, run_id),
        ).fetchone()
        if row is None:
            return None
        payload, digest = str(row[0]), str(row[1])
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
            return None
        try:
            return self._snapshot_from_json(payload)
        except (TrajectoryStoreError, DomainError, ValueError, TypeError, KeyError):
            return None

    def replay_snapshot(
        self,
        objective_id: str,
        *,
        run_id: str,
        path_context: BranchContext,
        dependency_context: Mapping[str, object] | None = None,
    ) -> TrajectorySnapshot:
        objective = self.load_objective(objective_id)
        all_events = self.load_events(objective_id)
        events = _events_for_path(all_events, run_id)
        progress = evaluate_progress(objective, events)
        drift = evaluate_drift(objective, events, path_context, dependency_context or {})
        snapshot = TrajectorySnapshot(
            run_id=run_id,
            objective_status=objective.status,
            branch_elapsed_ms=_elapsed_ms(events, run_id),
            path_elapsed_ms=_elapsed_ms(events, None),
            duration_source="event_timestamps" if events else "unknown",
            progress=progress,
            drift=drift,
            next_action="checkpoint_review" if drift.return_due else "continue",
            active_blockers=tuple(
                criterion_id
                for criterion_id, status in progress.evidence_status_by_criterion.items()
                if status == EvidenceStatus.BLOCKED.value
            ),
            last_capability_evidence_seq=_last_root_seq(objective, events),
            last_prerequisite_release_seq=_last_release_seq(events),
        )
        self.save_snapshot(objective_id, snapshot)
        return snapshot

    def migrate_legacy_runs(self) -> int:
        """Add an explicit unknown trajectory status to pre-kernel runs.

        No synthetic event, timestamp, parent, branch, or completion claim is
        generated.  The old ``stage`` column remains untouched for compatibility.
        """

        table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_runs'"
        ).fetchone()
        if table is None:
            return 0
        columns = {
            str(row[1])
            for row in self._connection.execute("PRAGMA table_info(research_runs)").fetchall()
        }
        if "trajectory_status" not in columns:
            self._connection.execute(
                "ALTER TABLE research_runs ADD COLUMN trajectory_status TEXT NOT NULL "
                "DEFAULT 'legacy_unknown'"
            )
        cursor = self._connection.execute(
            "UPDATE research_runs SET trajectory_status = 'legacy_unknown'"
            " WHERE trajectory_status IS NULL OR trajectory_status = ''"
        )
        return int(cursor.rowcount)

    def _snapshot_from_json(self, value: str) -> TrajectorySnapshot:
        payload = cast(dict[str, object], json.loads(value))
        progress_payload = cast(dict[str, object], payload["progress"])
        drift_payload = cast(dict[str, object], payload["drift"])
        progress = ProgressReport(
            verified_criterion_ids=tuple(
                str(item)
                for item in _as_items(progress_payload["verified_criterion_ids"], "verified")
            ),
            pending_criterion_ids=tuple(
                str(item)
                for item in _as_items(progress_payload["pending_criterion_ids"], "pending")
            ),
            fraction=(
                None
                if progress_payload["fraction"] is None
                else _as_float(progress_payload["fraction"], "fraction")
            ),
            root_criterion_ids=tuple(
                str(item) for item in _as_items(progress_payload["root_criterion_ids"], "root")
            ),
            prerequisite_criterion_ids=tuple(
                str(item)
                for item in _as_items(
                    progress_payload["prerequisite_criterion_ids"], "prerequisite"
                )
            ),
            evidence_status_by_criterion=cast(
                Mapping[str, str], progress_payload["evidence_status_by_criterion"]
            ),
        )
        drift = DriftReport(
            path_distance=(
                None
                if drift_payload["path_distance"] is None
                else _as_float(drift_payload["path_distance"], "path_distance")
            ),
            goal_drift=(
                None
                if drift_payload["goal_drift"] is None
                else _as_float(drift_payload["goal_drift"], "goal_drift")
            ),
            score=(
                None
                if drift_payload["score"] is None
                else _as_float(drift_payload["score"], "score")
            ),
            root_progress=(
                None
                if drift_payload["root_progress"] is None
                else _as_float(drift_payload["root_progress"], "root_progress")
            ),
            prerequisite_progress=(
                None
                if drift_payload["prerequisite_progress"] is None
                else _as_float(drift_payload["prerequisite_progress"], "prerequisite_progress")
            ),
            validation_stagnation_events=_as_int(
                drift_payload["validation_stagnation_events"], "validation_stagnation_events"
            ),
            return_due=bool(drift_payload["return_due"]),
            basis_event_ids=tuple(
                str(item) for item in _as_items(drift_payload["basis_event_ids"], "basis_event_ids")
            ),
            reasons=tuple(str(item) for item in _as_items(drift_payload["reasons"], "reasons")),
        )
        return TrajectorySnapshot(
            run_id=str(payload["run_id"]),
            objective_status=ObjectiveStatus(str(payload["objective_status"])),
            branch_elapsed_ms=(
                None
                if payload["branch_elapsed_ms"] is None
                else _as_int(payload["branch_elapsed_ms"], "branch_elapsed_ms")
            ),
            path_elapsed_ms=None
            if payload["path_elapsed_ms"] is None
            else _as_int(payload["path_elapsed_ms"], "path_elapsed_ms"),
            duration_source=str(payload["duration_source"]),
            progress=progress,
            drift=drift,
            next_action=str(payload["next_action"]),
            active_blockers=tuple(
                str(item) for item in _as_items(payload["active_blockers"], "active_blockers")
            ),
            last_capability_evidence_seq=(
                None
                if payload["last_capability_evidence_seq"] is None
                else _as_int(
                    payload["last_capability_evidence_seq"], "last_capability_evidence_seq"
                )
            ),
            last_prerequisite_release_seq=(
                None
                if payload["last_prerequisite_release_seq"] is None
                else _as_int(
                    payload["last_prerequisite_release_seq"], "last_prerequisite_release_seq"
                )
            ),
        )


def _events_for_path(events: Sequence[TrajectoryEvent], run_id: str) -> tuple[TrajectoryEvent, ...]:
    """Select the current run and its persisted ancestor chain only."""

    by_id = {event.event_id: event for event in events}
    selected: set[str] = set()
    for event in events:
        if event.run_id != run_id:
            continue
        current: TrajectoryEvent | None = event
        while current is not None and current.event_id not in selected:
            selected.add(current.event_id)
            current = (
                None if current.parent_event_id is None else by_id.get(current.parent_event_id)
            )
    return tuple(event for event in events if event.event_id in selected)


def _elapsed_ms(events: Sequence[TrajectoryEvent], run_id: str | None) -> int | None:
    selected = [event for event in events if run_id is None or event.run_id == run_id]
    starts = [event.started_at for event in selected if event.started_at is not None]
    ends = [event.ended_at for event in selected if event.ended_at is not None]
    if not starts or not ends:
        return None
    return max(0, int((max(ends).value - min(starts).value).total_seconds() * 1000))


def _last_root_seq(objective: ResearchObjective, events: Sequence[TrajectoryEvent]) -> int | None:
    roots = {criterion.criterion_id for criterion in objective.root_criteria}
    values = [event.seq for event in events if roots.intersection(event.supports_criterion_ids)]
    return max(values) if values else None


def _last_release_seq(events: Sequence[TrajectoryEvent]) -> int | None:
    values = [event.seq for event in events if event.event_kind == "prerequisite_unblocked"]
    return max(values) if values else None


__all__ = ["TrajectoryStore", "TrajectoryStoreError"]
