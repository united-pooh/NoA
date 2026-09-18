"""Research runs: resumable state machine on the control plane and the
bounded sampling runtime that wraps MCP sampling (contract sections 5.2, 6.3)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from fastmcp import Context

from .compat.sampling import resolve_sampling


class RunError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def _error(code: str, message: str, **context: str) -> RunError:
    return RunError(code=code, message=message, context=context)


def _utc_now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunStage(StrEnum):
    PREPARED = "prepared"
    COLLECTING = "collecting"
    ACQUIRING = "acquiring"
    ENRICHING = "enriching"
    REVIEW_PENDING = "review_pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TrajectoryRunStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    LEGACY_UNKNOWN = "legacy_unknown"


_ACTIVE_STAGES = frozenset(RunStage) - {RunStage.COMPLETED, RunStage.CANCELLED}
_TERMINAL_TRAJECTORY_STATUSES = frozenset(
    {TrajectoryRunStatus.COMPLETED, TrajectoryRunStatus.ABANDONED}
)

_RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL CHECK (stage IN (
        'prepared','collecting','acquiring','enriching','review_pending',
        'completed','cancelled')),
    current_step INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER NOT NULL CHECK (total_steps > 0),
    sampling_requests INTEGER NOT NULL DEFAULT 0,
    max_sampling_requests INTEGER NOT NULL,
    trajectory_status TEXT NOT NULL DEFAULT 'legacy_unknown',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    stage: RunStage
    current_step: int
    total_steps: int
    sampling_requests: int
    max_sampling_requests: int
    payload: dict[str, object]
    trajectory_status: TrajectoryRunStatus = TrajectoryRunStatus.LEGACY_UNKNOWN


class ResearchRunStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(_RUN_SCHEMA)
        columns = {
            str(row[1]) for row in self._connection.execute("PRAGMA table_info(research_runs)")
        }
        if "trajectory_status" not in columns:
            self._connection.execute(
                "ALTER TABLE research_runs ADD COLUMN trajectory_status TEXT NOT NULL "
                "DEFAULT 'legacy_unknown'"
            )

    def close(self) -> None:
        self._connection.close()

    def start_run(
        self,
        run_id: str,
        *,
        total_steps: int,
        max_sampling_requests: int,
        payload: dict[str, object] | None = None,
    ) -> ResearchRun:
        if total_steps <= 0:
            raise _error("invalid_run", "total_steps must be positive")
        if max_sampling_requests <= 0:
            raise _error("invalid_run", "max_sampling_requests must be positive")
        try:
            now = _utc_now_text()
            self._connection.execute(
                "INSERT INTO research_runs (run_id, stage, total_steps,"
                " max_sampling_requests, trajectory_status, payload, created_at, updated_at)"
                " VALUES (?, 'prepared', ?, ?, 'active', ?, ?, ?)",
                (
                    run_id,
                    total_steps,
                    max_sampling_requests,
                    "{}" if payload is None else _json(payload),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise _error(
                "duplicate_run",
                f"Run {run_id!r} already exists",
                run_id=run_id,
            ) from error
        return self.load_run(run_id)

    def load_run(self, run_id: str) -> ResearchRun:
        row = self._connection.execute(
            "SELECT run_id, stage, current_step, total_steps, sampling_requests,"
            " max_sampling_requests, payload, trajectory_status"
            " FROM research_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise _error("run_not_found", f"Run {run_id!r} does not exist", run_id=run_id)
        import json

        return ResearchRun(
            run_id=row[0],
            stage=RunStage(row[1]),
            current_step=int(row[2]),
            total_steps=int(row[3]),
            sampling_requests=int(row[4]),
            max_sampling_requests=int(row[5]),
            payload=json.loads(row[6]),
            trajectory_status=TrajectoryRunStatus(row[7]),
        )

    def advance(
        self,
        run_id: str,
        *,
        stage: RunStage | None = None,
        payload_delta: dict[str, object] | None = None,
    ) -> ResearchRun:

        run = self.load_run(run_id)
        if (
            run.stage not in _ACTIVE_STAGES
            or run.trajectory_status in _TERMINAL_TRAJECTORY_STATUSES
        ):
            raise _error(
                "run_not_active",
                f"Run {run_id!r} is {run.stage.value!r} and cannot advance",
                run_id=run_id,
            )
        next_step = min(run.current_step + 1, run.total_steps)
        merged_payload = dict(run.payload)
        if payload_delta:
            merged_payload.update(payload_delta)
        new_stage = stage if stage is not None else run.stage
        new_trajectory_status = run.trajectory_status
        if new_stage is RunStage.COMPLETED:
            new_trajectory_status = TrajectoryRunStatus.COMPLETED
        elif new_stage is RunStage.CANCELLED:
            new_trajectory_status = TrajectoryRunStatus.ABANDONED
        self._connection.execute(
            "UPDATE research_runs SET stage = ?, current_step = ?, sampling_requests = ?,"
            " trajectory_status = ?,"
            " payload = ?, updated_at = ? WHERE run_id = ?",
            (
                new_stage.value,
                next_step,
                run.sampling_requests,
                new_trajectory_status.value,
                _json(merged_payload),
                _utc_now_text(),
                run_id,
            ),
        )
        return self.load_run(run_id)

    def record_sampling(self, run_id: str) -> None:
        run = self.load_run(run_id)
        if (
            run.stage not in _ACTIVE_STAGES
            or run.trajectory_status in _TERMINAL_TRAJECTORY_STATUSES
        ):
            raise _error(
                "run_not_active",
                f"Run {run_id!r} is terminal and cannot sample",
                run_id=run_id,
            )
        if run.sampling_requests >= run.max_sampling_requests:
            raise _error(
                "sampling_budget_exhausted",
                f"Run {run_id!r} reached its sampling budget",
                run_id=run_id,
            )
        self._connection.execute(
            "UPDATE research_runs SET sampling_requests = sampling_requests + 1,"
            " updated_at = ? WHERE run_id = ?",
            (_utc_now_text(), run_id),
        )

    def cancel(self, run_id: str) -> ResearchRun:
        run = self.load_run(run_id)
        if (
            run.stage not in _ACTIVE_STAGES
            or run.trajectory_status in _TERMINAL_TRAJECTORY_STATUSES
        ):
            raise _error(
                "run_not_active",
                f"Run {run_id!r} is terminal and cannot be cancelled",
                run_id=run_id,
            )
        self._connection.execute(
            "UPDATE research_runs SET stage = 'cancelled', trajectory_status = 'abandoned',"
            " updated_at = ? WHERE run_id = ?",
            (_utc_now_text(), run_id),
        )
        return self.load_run(run_id)

    def set_trajectory_status(self, run_id: str, status: TrajectoryRunStatus) -> ResearchRun:
        run = self.load_run(run_id)
        status = TrajectoryRunStatus(status)
        allowed = {
            TrajectoryRunStatus.ACTIVE: {
                TrajectoryRunStatus.ACTIVE,
                TrajectoryRunStatus.PAUSED,
                TrajectoryRunStatus.COMPLETED,
                TrajectoryRunStatus.ABANDONED,
            },
            TrajectoryRunStatus.PAUSED: {
                TrajectoryRunStatus.ACTIVE,
                TrajectoryRunStatus.PAUSED,
                TrajectoryRunStatus.COMPLETED,
                TrajectoryRunStatus.ABANDONED,
            },
        }
        if status not in allowed.get(run.trajectory_status, set()):
            raise _error(
                "invalid_trajectory_transition",
                f"Cannot transition trajectory status from {run.trajectory_status.value!r}"
                f" to {status.value!r}",
                run_id=run_id,
            )
        self._connection.execute(
            "UPDATE research_runs SET trajectory_status = ?, updated_at = ? WHERE run_id = ?",
            (status.value, _utc_now_text(), run_id),
        )
        return self.load_run(run_id)

    def resumable_runs(self) -> list[ResearchRun]:
        rows = self._connection.execute(
            "SELECT run_id FROM research_runs WHERE stage NOT IN ('completed','cancelled')"
            " ORDER BY created_at, run_id"
        ).fetchall()
        return [self.load_run(row[0]) for row in rows]


def _json(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class SamplingRuntime:
    """Bounded server-side sampling wrapper around the compat dual-protocol helper."""

    def __init__(self, store: ResearchRunStore) -> None:
        self._store = store

    async def sample(self, ctx: object, *, question: str, run_id: str | None = None) -> object:
        if run_id is not None:
            self._store.record_sampling(run_id)
        return await resolve_sampling(question, cast("Context", ctx))


__all__ = [
    "ResearchRun",
    "ResearchRunStore",
    "RunError",
    "RunStage",
    "SamplingRuntime",
    "TrajectoryRunStatus",
]
