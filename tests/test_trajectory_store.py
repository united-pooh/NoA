from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from noa.domain import UtcInstant
from noa.trajectory import (
    BranchContext,
    CriterionRole,
    EvidenceScope,
    EvidenceStatus,
    ObjectiveStatus,
    ResearchObjective,
    SuccessCriterion,
    TrajectoryEvent,
)
from noa.trajectory_store import TrajectoryStore, TrajectoryStoreError

BASE_TIME = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _instant(offset: int = 0) -> UtcInstant:
    return UtcInstant.from_datetime(BASE_TIME + timedelta(minutes=offset))


def _objective(*, status: ObjectiveStatus = ObjectiveStatus.ACTIVE) -> ResearchObjective:
    arguments: dict[str, object] = {
        "objective_id": "objective-1",
        "version": 1,
        "statement": "validate trajectory persistence",
        "facets": (),
        "criteria": (
            SuccessCriterion(
                "root",
                "root_metric",
                "exists",
                CriterionRole.ROOT_CAPABILITY,
                acceptance_scope=EvidenceScope.PILOT,
            ),
        ),
        "status": status,
    }
    if status is ObjectiveStatus.COMPLETED:
        arguments.update(
            completed_at=_instant(5),
            completion_evidence_event_ids=("e1",),
        )
    return ResearchObjective(**arguments)  # type: ignore[arg-type]


def _event(
    event_id: str,
    run_id: str = "run-main",
    seq: int = 1,
    *,
    parent_event_id: str | None = None,
    branch_id: str = "main",
) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_id=event_id,
        run_id=run_id,
        seq=seq,
        parent_event_id=parent_event_id,
        branch_id=branch_id,
        event_kind="experiment_finished",
        occurred_at=_instant(seq),
        started_at=_instant(seq),
        ended_at=_instant(seq + 1),
        intent=None,
        result={},
        metrics={},
        artifacts=(),
        outcome="observed",
        source="test",
        idempotency_key=event_id,
        evidence_scope=EvidenceScope.PILOT,
        evidence_status=EvidenceStatus.OBSERVED,
    )


def _context() -> BranchContext:
    return BranchContext(
        run_id="run-main",
        root_run_id="run-main",
        mainline_run_id="run-main",
        parent_run_id=None,
        branch_depth=0,
        fork_seq=1,
        common_ancestor_seq=None,
    )


def test_event_roundtrip_wal_reopen_and_idempotency(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.sqlite3"
    event = _event("e1")
    store = TrajectoryStore(path)
    store.create_objective(_objective())
    assert store.load_objective("objective-1") == _objective()
    assert store.append_event("objective-1", event, expected_seq=0) == event
    assert store.append_event("objective-1", event, expected_seq=1) == event
    store.close()

    reopened = TrajectoryStore(path)
    assert reopened.load_events("objective-1") == (event,)
    with pytest.raises(TrajectoryStoreError, match="expected sequence"):
        reopened.append_event("objective-1", _event("e2", seq=2), expected_seq=0)
    reopened.close()


def test_child_branch_requires_persisted_parent_and_sequence(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path / "trajectory.sqlite3")
    store.create_objective(_objective())
    store.append_event("objective-1", _event("e1"), expected_seq=0)
    child = _event("child-1", "run-child", parent_event_id="e1", branch_id="child")
    assert store.append_event("objective-1", child, expected_seq=0) == child

    with pytest.raises(TrajectoryStoreError, match="sequence"):
        store.append_event(
            "objective-1",
            _event("child-3", "run-child", seq=3, parent_event_id="child-1", branch_id="child"),
            expected_seq=1,
        )
    with pytest.raises(TrajectoryStoreError, match="parent"):
        store.append_event(
            "objective-1",
            _event("bad-parent", "run-other", parent_event_id="missing", branch_id="other"),
            expected_seq=0,
        )
    store.close()


def test_terminal_objective_rejects_append(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path / "trajectory.sqlite3")
    store.create_objective(_objective(status=ObjectiveStatus.COMPLETED))
    with pytest.raises(TrajectoryStoreError, match="terminal"):
        store.append_event("objective-1", _event("late"), expected_seq=0)
    store.close()


def test_snapshot_hash_corruption_returns_none_then_replays(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.sqlite3"
    store = TrajectoryStore(path)
    store.create_objective(_objective())
    event = _event("e1")
    store.append_event("objective-1", event, expected_seq=0)
    snapshot = store.replay_snapshot("objective-1", run_id="run-main", path_context=_context())
    assert store.load_snapshot("objective-1", "run-main") == snapshot
    store._connection.execute(
        "UPDATE trajectory_snapshots SET snapshot_json = '{broken}' "
        "WHERE objective_id = 'objective-1' AND run_id = 'run-main'"
    )
    assert store.load_snapshot("objective-1", "run-main") is None
    replayed = store.replay_snapshot("objective-1", run_id="run-main", path_context=_context())
    assert replayed.progress == snapshot.progress
    assert store.load_snapshot("objective-1", "run-main") == replayed
    store.close()


def test_legacy_runs_are_marked_unknown_without_synthetic_history(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE research_runs (run_id TEXT PRIMARY KEY, stage TEXT NOT NULL, "
        "current_step INTEGER NOT NULL, total_steps INTEGER NOT NULL, "
        "sampling_requests INTEGER NOT NULL, max_sampling_requests INTEGER NOT NULL, "
        "payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO research_runs VALUES ('legacy-1','completed',1,1,0,1,'{}',?,?)",
        (_instant().text, _instant().text),
    )
    connection.commit()
    connection.close()

    store = TrajectoryStore(path)
    status = store._connection.execute(
        "SELECT trajectory_status FROM research_runs WHERE run_id = 'legacy-1'"
    ).fetchone()
    assert status == ("legacy_unknown",)
    assert store.load_events("legacy-1") == ()
    store.close()
