from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from noa.compat.models import CheckResult, CheckStatus

_CHECK_NAME = "sqlite-checkpoint-recovery"
_RUN_ID = "slice-0"
_TOTAL_STEPS = 3
_SCHEMA = """
CREATE TABLE IF NOT EXISTS compatibility_run(
    run_id TEXT PRIMARY KEY,
    current_step INTEGER NOT NULL,
    total_steps INTEGER NOT NULL,
    CHECK (current_step >= 0),
    CHECK (total_steps > 0),
    CHECK (current_step <= total_steps)
)
"""


def _close_with_error_priority(
    close: Callable[[], None],
    primary_error: BaseException | None,
) -> None:
    try:
        close()
    except BaseException as cleanup_error:
        if primary_error is None:
            raise
        if not isinstance(primary_error, Exception):
            primary_error.add_note(
                f"Suppressed cleanup {type(cleanup_error).__name__}: {cleanup_error}"
            )
            return
        if not isinstance(cleanup_error, Exception):
            raise
        primary_error.add_note(
            f"Suppressed cleanup {type(cleanup_error).__name__}: {cleanup_error}"
        )


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        connection = sqlite3.connect(path)
        self._connection: sqlite3.Connection | None = connection
        try:
            with connection:
                connection.execute(_SCHEMA)
        except BaseException as primary_error:
            self._connection = None
            _close_with_error_priority(connection.close, primary_error)
            raise

    def start(self, run_id: str, total_steps: int) -> None:
        connection = self._require_connection()
        with connection:
            connection.execute(
                "INSERT INTO compatibility_run(run_id, current_step, total_steps) VALUES (?, 0, ?)",
                (run_id, total_steps),
            )

    def advance(self, run_id: str) -> None:
        connection = self._require_connection()
        with connection:
            cursor = connection.execute(
                """
                UPDATE compatibility_run
                SET current_step = current_step + 1
                WHERE run_id = ? AND current_step < total_steps
                """,
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Run cannot advance: {run_id}")

    def load(self, run_id: str) -> tuple[int, int]:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT current_step, total_steps FROM compatibility_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return int(row[0]), int(row[1])

    def close(self) -> None:
        connection = self._connection
        if connection is None:
            return
        self._connection = None
        connection.close()

    def __enter__(self) -> CheckpointStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _close_with_error_priority(self.close, exc_value)

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("CheckpointStore is closed.")
        return self._connection


def run_checkpoint_probe(root: Path) -> CheckResult:
    database_path = root / f"compatibility-{uuid4().hex}.sqlite3"
    phase = "setup"
    resumed_step: int | None = None
    final_step: int | None = None

    try:
        root.mkdir(parents=True, exist_ok=True)

        phase = "open_initial"
        with CheckpointStore(database_path) as initial_store:
            phase = "start"
            initial_store.start(_RUN_ID, total_steps=_TOTAL_STEPS)
            phase = "initial_advance"
            initial_store.advance(_RUN_ID)
            phase = "close_initial"

        phase = "reopen"
        with CheckpointStore(database_path) as resumed_store:
            phase = "resume_load"
            resumed_step, resumed_total_steps = resumed_store.load(_RUN_ID)
            phase = "resumed_advance"
            resumed_store.advance(_RUN_ID)
            phase = "final_load"
            final_step, final_total_steps = resumed_store.load(_RUN_ID)
            phase = "close_resumed"
    except Exception as exc:
        return CheckResult(
            name=_CHECK_NAME,
            status=CheckStatus.FAIL,
            summary="SQLite checkpoint recovery probe failed.",
            details={
                "database_path": str(database_path),
                "resumed_step": resumed_step,
                "final_step": final_step,
                "total_steps": _TOTAL_STEPS,
                "phase": phase,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

    status = (
        CheckStatus.PASS
        if resumed_step == 1
        and resumed_total_steps == _TOTAL_STEPS
        and final_step == 2
        and final_total_steps == _TOTAL_STEPS
        else CheckStatus.FAIL
    )
    return CheckResult(
        name=_CHECK_NAME,
        status=status,
        summary="SQLite checkpoint recovery probe completed.",
        details={
            "database_path": str(database_path),
            "resumed_step": resumed_step,
            "final_step": final_step,
            "total_steps": _TOTAL_STEPS,
        },
    )
