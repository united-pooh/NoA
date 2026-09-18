"""Persistence: CAS object store, LadybugDB graph store, SQLite control plane
with operation journal, and idempotent startup recovery (contract sections 5.4, 7.1, 7.2)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

import ladybug as lb


class StorageError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def _error(code: str, message: str, **context: str) -> StorageError:
    return StorageError(code=code, message=message, context=context)


def _utc_now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ObjectStore:
    """Content-addressed blob store: objects/sha256/<hex>, atomic publish."""

    def __init__(self, root: Path, *, max_object_bytes: int = 128 * 1024 * 1024) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_object_bytes

    def _path_for(self, digest_hex: str) -> Path:
        return self.root / "sha256" / digest_hex

    def put(self, payload: bytes) -> str:
        if len(payload) > self._max_bytes:
            raise _error(
                "object_too_large",
                f"Object of {len(payload)} bytes exceeds the budget",
                size=str(len(payload)),
            )
        digest = hashlib.sha256(payload).hexdigest()
        final = self._path_for(digest)
        if final.exists():
            return f"sha256:{digest}"
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.with_name(f".tmp-{digest[:16]}")
        tmp.write_bytes(payload)
        tmp.replace(final)
        return f"sha256:{digest}"

    def get(self, digest: str) -> bytes:
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise _error("invalid_digest", f"Digest {digest!r} is not a sha256 reference")
        path = self._path_for(digest.removeprefix("sha256:"))
        if not path.is_file():
            raise _error(
                "object_missing",
                f"Object {digest!r} is not present in the store",
                digest=digest,
            )
        return path.read_bytes()

    def exists(self, digest: str) -> bool:
        if not digest.startswith("sha256:"):
            return False
        return self._path_for(digest.removeprefix("sha256:")).is_file()


_GRAPH_SCHEMA = (
    "CREATE NODE TABLE IF NOT EXISTS Entity"
    " (id STRING, kind STRING, payload STRING, PRIMARY KEY (id))"
)


class _GraphTransaction:
    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def __enter__(self) -> None:
        self._store._begin()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self._store._commit()
        else:
            self._store._rollback()


class GraphStore:
    """LadybugDB-backed entity snapshot store with transactional upsert."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._database = lb.Database(str(database_path))
        self._connection = lb.Connection(self._database)
        self._connection.execute(_GRAPH_SCHEMA)

    def close(self) -> None:
        try:
            self._connection.close()
        finally:
            self._database.close()

    def _execute(self, statement: str) -> list[list[object]]:
        result = self._connection.execute(statement)
        if isinstance(result, list):
            raise _error("graph_multi_result", "LadybugDB returned multiple results")
        return cast("list[list[object]]", result.get_all())

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _begin(self) -> None:
        self._execute("BEGIN TRANSACTION")

    def _commit(self) -> None:
        self._execute("COMMIT")

    def _rollback(self) -> None:
        self._execute("ROLLBACK")

    def transaction(self) -> _GraphTransaction:
        return _GraphTransaction(self)

    def put_entity(self, entity_id: str, kind: str, payload_json: str) -> None:
        escaped_id = self._quote(entity_id)
        with self.transaction():
            rows = self._execute(f"MATCH (n:Entity {{id: {escaped_id}}}) RETURN n.id")
            if rows:
                self._execute(
                    f"MATCH (n:Entity {{id: {escaped_id}}}) "
                    f"SET n.kind = {self._quote(kind)}, n.payload = {self._quote(payload_json)}"
                )
            else:
                self._execute(
                    f"CREATE (:Entity {{id: {escaped_id}, kind: {self._quote(kind)}, "
                    f"payload: {self._quote(payload_json)}}})"
                )

    def get_entity_payload(self, entity_id: str) -> str | None:
        rows = self._execute(f"MATCH (n:Entity {{id: {self._quote(entity_id)}}}) RETURN n.payload")
        if not rows:
            return None
        return str(rows[0][0])

    def all_entities(self) -> list[tuple[str, str, str]]:
        rows = self._execute("MATCH (n:Entity) RETURN n.id, n.kind, n.payload ORDER BY n.id")
        return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


class OperationStage(StrEnum):
    PREPARED = "prepared"
    GRAPH_COMMITTED = "graph_committed"
    OBJECTS_PUBLISHED = "objects_published"
    CONTROL_COMMITTED = "control_committed"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    RETRYABLE_FAILED = "retryable_failed"
    MANUAL_REPAIR_REQUIRED = "manual_repair_required"


_TERMINAL_STAGES = frozenset(
    {
        OperationStage.COMPLETED,
        OperationStage.ROLLED_BACK,
        OperationStage.MANUAL_REPAIR_REQUIRED,
    }
)


@dataclass(frozen=True)
class JournalOperation:
    operation_id: str
    operation_type: str
    stage: OperationStage
    staged_hashes: tuple[str, ...]
    attempts: int
    last_error: str | None


_JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_journal (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    stage TEXT NOT NULL CHECK (stage IN (
        'prepared','graph_committed','objects_published','control_committed',
        'completed','rolled_back','retryable_failed','manual_repair_required')),
    staged_hashes TEXT NOT NULL DEFAULT '[]',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_stage ON operation_journal(stage);
"""


class ControlStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(_JOURNAL_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    def begin_operation(
        self,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        staged_hashes: tuple[str, ...],
        actor: str,
    ) -> None:
        try:
            self._connection.execute(
                "INSERT INTO operation_journal"
                "(operation_id, operation_type, idempotency_key, stage, staged_hashes,"
                " attempts, actor, created_at, updated_at)"
                " VALUES (?, ?, ?, 'prepared', ?, 0, ?, ?, ?)",
                (
                    operation_id,
                    operation_type,
                    idempotency_key,
                    json.dumps(list(staged_hashes)),
                    actor,
                    _utc_now_text(),
                    _utc_now_text(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise _error(
                "duplicate_operation",
                f"Operation {operation_id!r} or idempotency key already exists",
                operation_id=operation_id,
            ) from error

    def set_stage(
        self, operation_id: str, stage: OperationStage, *, last_error: str | None = None
    ) -> None:
        cursor = self._connection.execute(
            "UPDATE operation_journal SET stage = ?, last_error = ?, updated_at = ?,"
            " attempts = attempts + 1 WHERE operation_id = ?",
            (stage.value, last_error, _utc_now_text(), operation_id),
        )
        if cursor.rowcount == 0:
            raise _error(
                "operation_not_found",
                f"Operation {operation_id!r} is not in the journal",
                operation_id=operation_id,
            )

    def load_operation(self, operation_id: str) -> JournalOperation:
        row = self._connection.execute(
            "SELECT operation_id, operation_type, stage, staged_hashes, attempts, last_error"
            " FROM operation_journal WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise _error(
                "operation_not_found",
                f"Operation {operation_id!r} is not in the journal",
                operation_id=operation_id,
            )
        return JournalOperation(
            operation_id=row[0],
            operation_type=row[1],
            stage=OperationStage(row[2]),
            staged_hashes=tuple(json.loads(row[3])),
            attempts=int(row[4]),
            last_error=row[5],
        )

    def unfinished_operations(self) -> list[JournalOperation]:
        rows = self._connection.execute(
            "SELECT operation_id, operation_type, stage, staged_hashes, attempts, last_error"
            " FROM operation_journal WHERE stage NOT IN ('completed','rolled_back',"
            "'manual_repair_required') ORDER BY created_at, operation_id"
        ).fetchall()
        return [
            JournalOperation(
                operation_id=row[0],
                operation_type=row[1],
                stage=OperationStage(row[2]),
                staged_hashes=tuple(json.loads(row[3])),
                attempts=int(row[4]),
                last_error=row[5],
            )
            for row in rows
        ]


@dataclass(frozen=True)
class RecoveryAction:
    operation_id: str
    action: str
    detail: str


def recover_stores(
    control: ControlStore,
    graph_has_operation: Callable[[str], bool],
) -> list[RecoveryAction]:
    """Idempotent startup recovery per contract section 7.2."""
    actions: list[RecoveryAction] = []
    for operation in control.unfinished_operations():
        if operation.stage is OperationStage.PREPARED and not graph_has_operation(
            operation.operation_id
        ):
            control.set_stage(operation.operation_id, OperationStage.ROLLED_BACK)
            actions.append(
                RecoveryAction(operation.operation_id, "rolled_back", "no committed graph writes")
            )
        elif operation.stage in (
            OperationStage.GRAPH_COMMITTED,
            OperationStage.OBJECTS_PUBLISHED,
            OperationStage.CONTROL_COMMITTED,
        ):
            control.set_stage(operation.operation_id, OperationStage.COMPLETED)
            actions.append(
                RecoveryAction(
                    operation.operation_id,
                    "rolled_forward",
                    "graph write set committed; control plane finalized",
                )
            )
        else:
            control.set_stage(
                operation.operation_id,
                OperationStage.MANUAL_REPAIR_REQUIRED,
                last_error=operation.last_error or "unrecoverable journal state",
            )
            actions.append(RecoveryAction(operation.operation_id, "manual_repair_required", ""))
    return actions


__all__ = [
    "ControlStore",
    "GraphStore",
    "JournalOperation",
    "ObjectStore",
    "OperationStage",
    "RecoveryAction",
    "StorageError",
    "recover_stores",
]
