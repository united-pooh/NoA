from __future__ import annotations

from pathlib import Path
from typing import NoReturn, cast

import pytest

import noa.compat.ladybug_probe as ladybug_probe
from noa.compat.ladybug_probe import run_ladybug_probe
from noa.compat.models import CheckStatus

_EXPECTED_ROWS: list[list[object]] = [["committed", "ok"]]


def test_ladybug_probe_verifies_rollback_commit_and_reopen(tmp_path: Path) -> None:
    result = run_ladybug_probe(tmp_path)

    assert result.name == "ladybug-transaction-persistence"
    assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)
    assert result.details["rolled_back_rows"] == []
    assert result.details["committed_rows"] == _EXPECTED_ROWS
    assert result.details["reopened_rows"] == _EXPECTED_ROWS


def test_ladybug_probe_creates_missing_root_and_persists_database(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "nested"

    result = run_ladybug_probe(root)

    assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)
    database_path = Path(cast(str, result.details["database_path"]))
    assert root.is_dir()
    assert database_path.parent == root
    assert database_path.is_file()
    assert database_path.stat().st_size > 0


def test_ladybug_probe_normalizes_database_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_database(*args: object, **kwargs: object) -> NoReturn:
        raise PermissionError("database unavailable")

    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Database", unavailable_database)

    result = run_ladybug_probe(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["phase"] == "write"
    assert result.details["error_type"] == "PermissionError"
    assert result.details["error"] == "database unavailable"
    assert result.details["cleanup_errors"] == []


def test_ladybug_probe_is_stable_across_independent_directories(tmp_path: Path) -> None:
    results = [run_ladybug_probe(tmp_path / f"run-{index}") for index in range(3)]

    for result in results:
        assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)
        assert result.details["rolled_back_rows"] == []
        assert result.details["committed_rows"] == _EXPECTED_ROWS
        assert result.details["reopened_rows"] == _EXPECTED_ROWS

    database_paths = {cast(str, result.details["database_path"]) for result in results}
    assert len(database_paths) == 3
    assert all(Path(database_path).is_file() for database_path in database_paths)


def test_ladybug_probe_can_run_twice_in_the_same_directory(tmp_path: Path) -> None:
    results = [run_ladybug_probe(tmp_path) for _ in range(2)]

    for result in results:
        assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)
        assert result.details["rolled_back_rows"] == []
        assert result.details["committed_rows"] == _EXPECTED_ROWS
        assert result.details["reopened_rows"] == _EXPECTED_ROWS

    database_paths = [Path(cast(str, result.details["database_path"])) for result in results]
    assert database_paths[0] != database_paths[1]
    assert all(database_path.is_file() for database_path in database_paths)


def test_close_resources_attempts_every_query_result_after_a_close_failure() -> None:
    events: list[str] = []

    class QueryResult:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        def close(self) -> None:
            events.append(self.name)
            if self.fail:
                raise RuntimeError(f"{self.name} close failed")

    resources = [
        QueryResult("first"),
        QueryResult("second", fail=True),
        QueryResult("third"),
    ]

    cleanup_errors = ladybug_probe._close_resources(resources)

    assert events == ["third", "second", "first"]
    assert cleanup_errors == [
        {
            "resource_type": "QueryResult",
            "error_type": "RuntimeError",
            "error": "second close failed",
        }
    ]


def test_connection_close_failure_still_closes_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class QueryResult:
        def __init__(self, rows: list[list[object]]) -> None:
            self.rows = rows

        def get_all(self) -> list[list[object]]:
            return self.rows

        def close(self) -> None:
            events.append("query-result-close")

    class Database:
        def __init__(self, path: str, *, read_only: bool = False) -> None:
            self.path = path
            self.read_only = read_only

        def close(self) -> None:
            events.append("database-close")

    class Connection:
        def __init__(self, database: Database) -> None:
            self.match_count = 0

        def execute(self, statement: str) -> QueryResult:
            rows: list[list[object]] = []
            if statement.startswith("MATCH"):
                rows = [] if self.match_count == 0 else _EXPECTED_ROWS
                self.match_count += 1
            return QueryResult(rows)

        def close(self) -> None:
            events.append("connection-close")
            raise RuntimeError("connection close failed")

    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Database", Database)
    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Connection", Connection)

    result = run_ladybug_probe(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["phase"] == "write"
    assert result.details["error_type"] == "RuntimeError"
    assert result.details["error"] == "connection close failed"
    assert result.details["cleanup_errors"] == [
        {
            "resource_type": "Connection",
            "error_type": "RuntimeError",
            "error": "connection close failed",
        }
    ]
    assert events[-2:] == ["connection-close", "database-close"]


def test_query_error_remains_primary_when_query_result_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class QueryResult:
        def get_all(self) -> list[list[object]]:
            raise ValueError("query execution failed")

        def close(self) -> None:
            events.append("query-result-close")
            raise RuntimeError("query result close failed")

    class Database:
        def __init__(self, path: str, *, read_only: bool = False) -> None:
            self.path = path
            self.read_only = read_only

        def close(self) -> None:
            events.append("database-close")

    class Connection:
        def __init__(self, database: Database) -> None:
            self.database = database

        def execute(self, statement: str) -> QueryResult:
            return QueryResult()

        def close(self) -> None:
            events.append("connection-close")

    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Database", Database)
    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Connection", Connection)

    result = run_ladybug_probe(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["phase"] == "write"
    assert result.details["error_type"] == "ValueError"
    assert result.details["error"] == "query execution failed"
    assert result.details["cleanup_errors"] == [
        {
            "resource_type": "QueryResult",
            "error_type": "RuntimeError",
            "error": "query result close failed",
        }
    ]
    assert events == ["query-result-close", "connection-close", "database-close"]


def test_read_only_reopen_failure_reports_its_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class QueryResult:
        def __init__(
            self,
            rows: list[list[object]],
            error: Exception | None = None,
        ) -> None:
            self.rows = rows
            self.error = error

        def get_all(self) -> list[list[object]]:
            if self.error is not None:
                raise self.error
            return self.rows

        def close(self) -> None:
            pass

    class Database:
        def __init__(self, path: str, *, read_only: bool = False) -> None:
            self.path = path
            self.read_only = read_only

        def close(self) -> None:
            pass

    class Connection:
        def __init__(self, database: Database) -> None:
            self.database = database
            self.match_count = 0

        def execute(self, statement: str) -> QueryResult:
            if self.database.read_only:
                return QueryResult([], ValueError("read-only query failed"))
            if statement.startswith("MATCH"):
                rows = [] if self.match_count == 0 else _EXPECTED_ROWS
                self.match_count += 1
                return QueryResult(rows)
            return QueryResult([])

        def close(self) -> None:
            pass

    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Database", Database)
    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Connection", Connection)

    result = run_ladybug_probe(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["phase"] == "read_only_reopen"
    assert result.details["error_type"] == "ValueError"
    assert result.details["error"] == "read-only query failed"
    assert result.details["cleanup_errors"] == []


def test_execute_keyboard_interrupt_closes_resources_before_propagating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Database:
        def __init__(self, path: str, *, read_only: bool = False) -> None:
            self.path = path
            self.read_only = read_only

        def close(self) -> None:
            events.append("database-close")

    class Connection:
        def __init__(self, database: Database) -> None:
            self.database = database

        def execute(self, statement: str) -> NoReturn:
            raise KeyboardInterrupt("execution interrupted")

        def close(self) -> None:
            events.append("connection-close")

    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Database", Database)
    monkeypatch.setattr("noa.compat.ladybug_probe.lb.Connection", Connection)

    with pytest.raises(KeyboardInterrupt, match="execution interrupted"):
        run_ladybug_probe(tmp_path)

    assert events == ["connection-close", "database-close"]


def test_close_keyboard_interrupt_attempts_remaining_resources_then_propagates() -> None:
    events: list[str] = []

    class QueryResult:
        def __init__(self, name: str, *, interrupt: bool = False) -> None:
            self.name = name
            self.interrupt = interrupt

        def close(self) -> None:
            events.append(self.name)
            if self.interrupt:
                raise KeyboardInterrupt("cleanup interrupted")

    resources = [
        QueryResult("first"),
        QueryResult("second", interrupt=True),
        QueryResult("third"),
    ]

    with pytest.raises(KeyboardInterrupt, match="cleanup interrupted"):
        ladybug_probe._close_resources(resources)

    assert events == ["third", "second", "first"]
