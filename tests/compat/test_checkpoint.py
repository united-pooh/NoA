from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import NoReturn, cast

import pytest

from noa.compat.checkpoint import CheckpointStore, run_checkpoint_probe
from noa.compat.models import CheckStatus


def test_checkpoint_store_starts_at_zero_and_advances(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoint.sqlite3"

    with CheckpointStore(database_path) as store:
        store.start("run-1", total_steps=3)
        assert store.load("run-1") == (0, 3)

        store.advance("run-1")
        assert store.load("run-1") == (1, 3)


def test_checkpoint_store_recovers_after_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoint.sqlite3"

    with CheckpointStore(database_path) as store:
        store.start("run-1", total_steps=3)
        store.advance("run-1")

    with CheckpointStore(database_path) as store:
        assert store.load("run-1") == (1, 3)
        store.advance("run-1")
        assert store.load("run-1") == (2, 3)


def test_checkpoint_store_rejects_non_positive_total_steps(tmp_path: Path) -> None:
    with CheckpointStore(tmp_path / "checkpoint.sqlite3") as store:
        with pytest.raises(sqlite3.IntegrityError):
            store.start("zero", total_steps=0)
        with pytest.raises(sqlite3.IntegrityError):
            store.start("negative", total_steps=-1)

        with pytest.raises(KeyError, match="zero"):
            store.load("zero")
        with pytest.raises(KeyError, match="negative"):
            store.load("negative")


def test_checkpoint_store_rejects_unknown_run(tmp_path: Path) -> None:
    with CheckpointStore(tmp_path / "checkpoint.sqlite3") as store:
        with pytest.raises(KeyError, match="missing"):
            store.load("missing")
        with pytest.raises(ValueError, match="missing"):
            store.advance("missing")


def test_checkpoint_store_cannot_advance_beyond_total_steps(tmp_path: Path) -> None:
    with CheckpointStore(tmp_path / "checkpoint.sqlite3") as store:
        store.start("run-1", total_steps=1)
        store.advance("run-1")

        with pytest.raises(ValueError, match="run-1"):
            store.advance("run-1")

        assert store.load("run-1") == (1, 1)


def test_checkpoint_store_duplicate_start_does_not_overwrite(tmp_path: Path) -> None:
    with CheckpointStore(tmp_path / "checkpoint.sqlite3") as store:
        store.start("run-1", total_steps=3)
        store.advance("run-1")

        with pytest.raises(sqlite3.IntegrityError):
            store.start("run-1", total_steps=99)

        assert store.load("run-1") == (1, 3)


def test_checkpoint_store_close_is_idempotent(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.sqlite3")

    store.close()
    store.close()

    with pytest.raises(RuntimeError, match="closed"):
        store.load("run-1")


def test_checkpoint_probe_recovers_and_advances_after_reopen(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "nested"

    result = run_checkpoint_probe(root)

    assert result.name == "sqlite-checkpoint-recovery"
    assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)
    database_path = Path(cast(str, result.details["database_path"]))
    assert database_path.parent == root
    assert database_path.is_file()
    assert database_path.stat().st_size > 0
    assert result.details["resumed_step"] == 1
    assert result.details["final_step"] == 2
    assert result.details["total_steps"] == 3


def test_checkpoint_probe_can_run_twice_in_same_root(tmp_path: Path) -> None:
    results = [run_checkpoint_probe(tmp_path) for _ in range(2)]

    assert all(result.status is CheckStatus.PASS for result in results)
    database_paths = [Path(cast(str, result.details["database_path"])) for result in results]
    assert database_paths[0] != database_paths[1]
    assert all(database_path.is_file() for database_path in database_paths)


def test_checkpoint_probe_normalizes_ordinary_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_start(
        self: CheckpointStore,
        run_id: str,
        total_steps: int,
    ) -> NoReturn:
        raise PermissionError("checkpoint unavailable")

    monkeypatch.setattr(CheckpointStore, "start", unavailable_start)

    result = run_checkpoint_probe(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["phase"] == "start"
    assert result.details["error_type"] == "PermissionError"
    assert result.details["error"] == "checkpoint unavailable"


def test_checkpoint_probe_closes_connection_before_propagating_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_stores: list[CheckpointStore] = []
    original_init = CheckpointStore.__init__

    def recording_init(self: CheckpointStore, path: Path) -> None:
        original_init(self, path)
        created_stores.append(self)

    def interrupted_advance(self: CheckpointStore, run_id: str) -> NoReturn:
        raise KeyboardInterrupt("checkpoint interrupted")

    monkeypatch.setattr(CheckpointStore, "__init__", recording_init)
    monkeypatch.setattr(CheckpointStore, "advance", interrupted_advance)

    with pytest.raises(KeyboardInterrupt, match="checkpoint interrupted"):
        run_checkpoint_probe(tmp_path)

    assert len(created_stores) == 1
    with pytest.raises(RuntimeError, match="closed"):
        created_stores[0].load("slice-0")


def test_checkpoint_probe_preserves_keyboard_interrupt_when_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_close = CheckpointStore.close

    def interrupted_advance(self: CheckpointStore, run_id: str) -> NoReturn:
        raise KeyboardInterrupt("checkpoint interrupted")

    def failing_close(self: CheckpointStore) -> NoReturn:
        original_close(self)
        raise RuntimeError("close failed")

    monkeypatch.setattr(CheckpointStore, "advance", interrupted_advance)
    monkeypatch.setattr(CheckpointStore, "close", failing_close)

    with pytest.raises(KeyboardInterrupt, match="checkpoint interrupted"):
        run_checkpoint_probe(tmp_path)


def _patch_close_to_raise(
    monkeypatch: pytest.MonkeyPatch,
    cleanup_error: BaseException,
) -> None:
    original_close = CheckpointStore.close

    def close_then_raise(self: CheckpointStore) -> NoReturn:
        original_close(self)
        raise cleanup_error

    monkeypatch.setattr(CheckpointStore, "close", close_then_raise)


def test_context_body_keyboard_interrupt_outranks_close_runtime_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.sqlite3")
    _patch_close_to_raise(monkeypatch, RuntimeError("close failed"))

    with pytest.raises(KeyboardInterrupt, match="body interrupted"):
        with store:
            raise KeyboardInterrupt("body interrupted")


def test_context_first_keyboard_interrupt_outranks_close_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.sqlite3")
    _patch_close_to_raise(monkeypatch, SystemExit("close interrupted"))

    with pytest.raises(KeyboardInterrupt, match="body interrupted"):
        with store:
            raise KeyboardInterrupt("body interrupted")


def test_context_body_exception_outranks_close_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.sqlite3")
    _patch_close_to_raise(monkeypatch, RuntimeError("close failed"))

    with pytest.raises(ValueError, match="body failed"):
        with store:
            raise ValueError("body failed")


def test_context_close_interrupt_outranks_body_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.sqlite3")
    _patch_close_to_raise(monkeypatch, SystemExit("close interrupted"))

    with pytest.raises(SystemExit, match="close interrupted"):
        with store:
            raise ValueError("body failed")


def test_context_close_error_propagates_without_body_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CheckpointStore(tmp_path / "checkpoint.sqlite3")
    _patch_close_to_raise(monkeypatch, RuntimeError("close failed"))

    with pytest.raises(RuntimeError, match="close failed"):
        with store:
            pass


def test_constructor_interrupt_outranks_close_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InterruptingConnection:
        def __init__(self) -> None:
            self.closed = False

        def __enter__(self) -> InterruptingConnection:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, statement: str) -> NoReturn:
            raise KeyboardInterrupt("initialization interrupted")

        def close(self) -> NoReturn:
            self.closed = True
            raise SystemExit("close interrupted")

    connection = InterruptingConnection()
    monkeypatch.setattr(
        "noa.compat.checkpoint.sqlite3.connect",
        lambda path: connection,
    )

    with pytest.raises(KeyboardInterrupt, match="initialization interrupted"):
        CheckpointStore(tmp_path / "checkpoint.sqlite3")

    assert connection.closed is True
