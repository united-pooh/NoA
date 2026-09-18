from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import ladybug as lb

from noa.compat.models import CheckResult, CheckStatus

SCHEMA = "CREATE NODE TABLE Probe(id STRING PRIMARY KEY, value STRING)"
_QUERY_ROWS = "MATCH (p:Probe) RETURN p.id, p.value ORDER BY p.id"
_EXPECTED_COMMITTED_ROWS = [["committed", "ok"]]


class _Closeable(Protocol):
    def close(self) -> None: ...


def _close_resources(resources: Sequence[_Closeable]) -> list[dict[str, str]]:
    cleanup_errors: list[dict[str, str]] = []
    interrupt: BaseException | None = None
    for resource in reversed(resources):
        try:
            resource.close()
        except BaseException as exc:
            if isinstance(exc, Exception):
                cleanup_errors.append(
                    {
                        "resource_type": type(resource).__name__,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            elif interrupt is None:
                interrupt = exc
    if interrupt is not None:
        raise interrupt
    return cleanup_errors


def _execute(
    connection: lb.Connection,
    statement: str,
    resources: list[_Closeable],
) -> list[list[object]]:
    result = connection.execute(statement)
    if isinstance(result, list):
        resources.extend(result)
        raise TypeError("LadybugDB returned multiple query results for one statement.")
    resources.append(result)
    return cast(list[list[object]], result.get_all())


def _run_write_probe(
    database_path: Path,
) -> tuple[
    list[list[object]],
    list[list[object]],
    Exception | None,
    list[dict[str, str]],
]:
    resources: list[_Closeable] = []
    rolled_back_rows: list[list[object]] = []
    committed_rows: list[list[object]] = []
    primary_error: Exception | None = None
    cleanup_errors: list[dict[str, str]] = []
    try:
        database = lb.Database(str(database_path))
        resources.append(database)
        connection = lb.Connection(database)
        resources.append(connection)
        _execute(connection, SCHEMA, resources)

        _execute(connection, "BEGIN TRANSACTION", resources)
        _execute(connection, "CREATE (:Probe {id: 'rolled-back', value: 'no'})", resources)
        _execute(connection, "ROLLBACK", resources)
        rolled_back_rows = _execute(connection, _QUERY_ROWS, resources)

        _execute(connection, "BEGIN TRANSACTION", resources)
        _execute(connection, "CREATE (:Probe {id: 'committed', value: 'ok'})", resources)
        _execute(connection, "COMMIT", resources)
        committed_rows = _execute(connection, _QUERY_ROWS, resources)
    except Exception as exc:
        primary_error = exc
    finally:
        cleanup_errors = _close_resources(resources)
    return rolled_back_rows, committed_rows, primary_error, cleanup_errors


def _run_read_only_probe(
    database_path: Path,
) -> tuple[list[list[object]], Exception | None, list[dict[str, str]]]:
    resources: list[_Closeable] = []
    reopened_rows: list[list[object]] = []
    primary_error: Exception | None = None
    cleanup_errors: list[dict[str, str]] = []
    try:
        database = lb.Database(str(database_path), read_only=True)
        resources.append(database)
        connection = lb.Connection(database)
        resources.append(connection)
        reopened_rows = _execute(connection, _QUERY_ROWS, resources)
    except Exception as exc:
        primary_error = exc
    finally:
        cleanup_errors = _close_resources(resources)
    return reopened_rows, primary_error, cleanup_errors


def run_ladybug_probe(root: Path) -> CheckResult:
    database_path = root / f"compatibility-{uuid4().hex}.lbdb"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return CheckResult(
            name="ladybug-transaction-persistence",
            status=CheckStatus.FAIL,
            summary="LadybugDB compatibility probe failed.",
            details={
                "database_path": str(database_path),
                "phase": "setup",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "cleanup_errors": [],
            },
        )

    rolled_back_rows, committed_rows, primary_error, cleanup_errors = _run_write_probe(
        database_path
    )
    if primary_error is not None or cleanup_errors:
        error_type = (
            type(primary_error).__name__
            if primary_error is not None
            else cleanup_errors[0]["error_type"]
        )
        error = str(primary_error) if primary_error is not None else cleanup_errors[0]["error"]
        return CheckResult(
            name="ladybug-transaction-persistence",
            status=CheckStatus.FAIL,
            summary="LadybugDB compatibility probe failed.",
            details={
                "database_path": str(database_path),
                "phase": "write",
                "error_type": error_type,
                "error": error,
                "cleanup_errors": cleanup_errors,
            },
        )

    reopened_rows, primary_error, cleanup_errors = _run_read_only_probe(database_path)
    if primary_error is not None or cleanup_errors:
        error_type = (
            type(primary_error).__name__
            if primary_error is not None
            else cleanup_errors[0]["error_type"]
        )
        error = str(primary_error) if primary_error is not None else cleanup_errors[0]["error"]
        return CheckResult(
            name="ladybug-transaction-persistence",
            status=CheckStatus.FAIL,
            summary="LadybugDB compatibility probe failed.",
            details={
                "database_path": str(database_path),
                "phase": "read_only_reopen",
                "error_type": error_type,
                "error": error,
                "cleanup_errors": cleanup_errors,
            },
        )

    status = (
        CheckStatus.PASS
        if rolled_back_rows == []
        and committed_rows == _EXPECTED_COMMITTED_ROWS
        and reopened_rows == _EXPECTED_COMMITTED_ROWS
        else CheckStatus.FAIL
    )
    return CheckResult(
        name="ladybug-transaction-persistence",
        status=status,
        summary="LadybugDB rollback, commit, and read-only reopen probe completed.",
        details={
            "database_path": str(database_path),
            "rolled_back_rows": rolled_back_rows,
            "committed_rows": committed_rows,
            "reopened_rows": reopened_rows,
        },
    )
