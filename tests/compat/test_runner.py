from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import struct
import subprocess
import sys
import tomllib
import zlib
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from time import monotonic, sleep
from types import TracebackType
from typing import NoReturn, cast

import pytest

import noa.compat.runner as runner
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport, GateDecision
from noa.compat.runner import write_report


def _report(*checks: CheckResult) -> CompatibilityReport:
    return CompatibilityReport.from_checks(checks)


def test_write_report_writes_valid_machine_and_human_reports(tmp_path: Path) -> None:
    report = _report(
        CheckResult(
            name="sample",
            status=CheckStatus.PASS,
            summary="Sample check passed.",
            details={"path": tmp_path, "at": datetime(2026, 8, 21, tzinfo=UTC)},
        )
    )
    json_path = tmp_path / "reports" / "compatibility.json"
    markdown_path = tmp_path / "docs" / "compatibility.md"

    write_report(report, json_path=json_path, markdown_path=markdown_path)

    json_text = json_path.read_text(encoding="utf-8")
    restored = CompatibilityReport.model_validate_json(json_text)
    generation = json.loads(json_text)["generated_at"]
    assert restored.decision == report.decision
    assert [(check.name, check.status) for check in restored.checks] == [
        ("sample", CheckStatus.PASS)
    ]
    assert restored.checks[0].details == {
        "path": str(tmp_path),
        "at": "2026-08-21T00:00:00Z",
    }
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# NoA Slice 0 Compatibility Report" in markdown
    assert f"- Generated: `{generation}`" in markdown
    assert "| Check | Status | Required | Summary |" in markdown
    assert "## Details" in markdown
    assert '"path"' in markdown
    assert '"at": "2026-08-21T00:00:00Z"' in markdown
    assert not json_path.is_symlink()
    assert not markdown_path.is_symlink()


def test_write_report_renders_both_reports_before_filesystem_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "machine" / "compatibility.json"
    markdown_path = tmp_path / "human" / "compatibility.md"
    report = _report(CheckResult(name="sample", status=CheckStatus.PASS))

    def fail_markdown(payload: dict[str, object]) -> NoReturn:
        raise RuntimeError("markdown rendering failed")

    monkeypatch.setattr(runner, "_markdown", fail_markdown)

    with pytest.raises(RuntimeError, match="markdown rendering failed"):
        write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert not json_path.parent.exists()
    assert not markdown_path.parent.exists()


def test_write_report_fsyncs_both_temps_before_first_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    report = _report(CheckResult(name="sample", status=CheckStatus.PASS))
    events: list[str] = []
    original_fsync = os.fsync
    original_replace = Path.replace

    def record_fsync(file_descriptor: int) -> None:
        events.append("fsync")
        original_fsync(file_descriptor)

    def record_replace(source: Path, target: Path) -> Path:
        if target == json_path:
            events.append("replace-json")
        elif target == markdown_path:
            events.append("replace-markdown")
        return original_replace(source, target)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(Path, "replace", record_replace)

    write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert events == ["fsync", "fsync", "replace-json", "replace-markdown"]


def test_write_report_escapes_pipe_and_newline_in_markdown_table(tmp_path: Path) -> None:
    report = _report(
        CheckResult(
            name="table-safe",
            status=CheckStatus.PASS,
            summary="first | second\nthird\r\nfourth",
        )
    )
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"

    write_report(report, json_path=json_path, markdown_path=markdown_path)

    table_row = next(
        line
        for line in markdown_path.read_text(encoding="utf-8").splitlines()
        if "table-safe" in line
    )
    assert "first \\| second<br>third<br>fourth" in table_row
    assert table_row.count("|") == 6


def test_write_report_replace_failure_preserves_existing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(CheckResult(name="sample", status=CheckStatus.PASS))
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    json_path.write_text('{"existing":"json"}', encoding="utf-8")
    markdown_path.write_text("existing markdown", encoding="utf-8")
    original_replace = Path.replace

    def fail_json_replace(source: Path, target: Path) -> Path:
        if target == json_path:
            raise OSError("replace unavailable")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_json_replace)

    with pytest.raises(OSError, match="replace unavailable"):
        write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8")) == {"existing": "json"}
    assert markdown_path.read_text(encoding="utf-8") == "existing markdown"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "compatibility.json",
        "compatibility.md",
    ]


def test_write_report_rejects_same_resolved_path_before_side_effects(tmp_path: Path) -> None:
    parent = tmp_path / "missing"
    target = parent / "report"
    alias = parent / "." / "report"
    report = _report(CheckResult(name="sample", status=CheckStatus.PASS))

    with pytest.raises(ValueError, match="different paths"):
        write_report(report, json_path=target, markdown_path=alias)

    assert not parent.exists()


def test_write_report_rolls_back_json_when_markdown_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    old_json = b'{"generation":"old-json"}'
    old_markdown = b"old markdown"
    json_path.write_bytes(old_json)
    markdown_path.write_bytes(old_markdown)
    report = _report(CheckResult(name="new", status=CheckStatus.PASS))
    original_replace = Path.replace
    markdown_target = markdown_path.resolve(strict=False)

    def fail_markdown_replace(source: Path, target: Path) -> Path:
        if target.resolve(strict=False) == markdown_target:
            raise OSError("markdown replace failed")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_markdown_replace)

    with pytest.raises(OSError, match="markdown replace failed"):
        write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json_path.read_bytes() == old_json
    assert markdown_path.read_bytes() == old_markdown


def test_write_report_removes_new_json_when_markdown_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    report = _report(CheckResult(name="new", status=CheckStatus.PASS))
    original_replace = Path.replace

    def fail_markdown_replace(source: Path, target: Path) -> Path:
        if target == markdown_path:
            raise OSError("markdown replace failed")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_markdown_replace)

    with pytest.raises(OSError, match="markdown replace failed"):
        write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert not json_path.exists()
    assert not markdown_path.exists()


def test_write_report_preserves_second_replace_error_when_rollback_unlink_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    report = _report(CheckResult(name="new", status=CheckStatus.PASS))
    original_replace = Path.replace
    original_unlink = Path.unlink

    def fail_markdown_replace(source: Path, target: Path) -> Path:
        if target == markdown_path:
            raise OSError("markdown replace failed")
        return original_replace(source, target)

    def fail_json_rollback_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == json_path:
            raise OSError("json rollback unlink failed")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "replace", fail_markdown_replace)
    monkeypatch.setattr(Path, "unlink", fail_json_rollback_unlink)

    with pytest.raises(OSError, match="markdown replace failed") as captured:
        write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json_path.exists()
    assert any("json rollback unlink failed" in note for note in captured.value.__notes__)


def test_atomic_write_preserves_replace_error_when_temp_unlink_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"old")

    def fail_replace(source: Path, destination: Path) -> NoReturn:
        raise OSError("replace failed")

    def fail_unlink(path: Path, missing_ok: bool = False) -> NoReturn:
        raise OSError("unlink failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(OSError, match="replace failed") as captured:
        runner._atomic_write(target, b"new")

    assert target.read_bytes() == b"old"
    assert any("unlink failed" in note for note in captured.value.__notes__)


def test_concurrent_report_writers_leave_matching_generation_pair(tmp_path: Path) -> None:
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    script = """
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport
from noa.compat.runner import write_report

json_path = Path(sys.argv[1])
markdown_path = Path(sys.argv[2])
writer = int(sys.argv[3])
for iteration in range(4):
    report = CompatibilityReport.from_checks([
        CheckResult(
            name=f"writer-{writer}",
            status=CheckStatus.PASS,
            details={"payload": str(writer) * 200_000},
        )
    ]).model_copy(update={
        "generated_at": datetime(2026, 8, 21, tzinfo=UTC)
        + timedelta(microseconds=writer * 10 + iteration)
    })
    write_report(report, json_path=json_path, markdown_path=markdown_path)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(json_path), str(markdown_path), str(index)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(5)
    ]

    outputs = [process.communicate(timeout=60) for process in processes]

    for process, (_, stderr) in zip(processes, outputs, strict=True):
        assert process.returncode == 0, stderr
    machine_generation = json.loads(json_path.read_text(encoding="utf-8"))["generated_at"]
    markdown = markdown_path.read_text(encoding="utf-8")
    assert f"- Generated: `{machine_generation}`" in markdown


def _report_file_kind_and_generation(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        generation_line = next(
            line for line in text.splitlines() if line.startswith("- Generated:")
        )
        return "markdown", generation_line.split("`", maxsplit=2)[1]
    return "json", payload["generated_at"]


def test_swapped_report_destinations_are_serialized_without_corruption(tmp_path: Path) -> None:
    first = tmp_path / "first.report"
    second = tmp_path / "second.report"
    script = """
import sys
from datetime import UTC, datetime
from pathlib import Path
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport
from noa.compat.runner import write_report

report = CompatibilityReport.from_checks([
    CheckResult(name=sys.argv[3], status=CheckStatus.PASS)
]).model_copy(update={"generated_at": datetime.fromisoformat(sys.argv[4]).replace(tzinfo=UTC)})
write_report(report, json_path=Path(sys.argv[1]), markdown_path=Path(sys.argv[2]))
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(first),
                str(second),
                "normal",
                "2026-08-21T00:00:00",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ),
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(second),
                str(first),
                "swapped",
                "2026-08-21T00:00:01",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ),
    ]
    outputs = [process.communicate(timeout=30) for process in processes]

    for process, (_, stderr) in zip(processes, outputs, strict=True):
        assert process.returncode == 0, stderr
    first_kind, first_generation = _report_file_kind_and_generation(first)
    second_kind, second_generation = _report_file_kind_and_generation(second)
    assert {first_kind, second_kind} == {"json", "markdown"}
    assert first_generation == second_generation


def test_report_writers_sharing_one_destination_do_not_interleave(tmp_path: Path) -> None:
    shared_json = tmp_path / "shared.json"
    first_markdown = tmp_path / "first.md"
    second_markdown = tmp_path / "second.md"
    script = """
import sys
from datetime import UTC, datetime
from pathlib import Path
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport
from noa.compat.runner import write_report

report = CompatibilityReport.from_checks([
    CheckResult(name=sys.argv[3], status=CheckStatus.PASS)
]).model_copy(update={"generated_at": datetime.fromisoformat(sys.argv[4]).replace(tzinfo=UTC)})
write_report(report, json_path=Path(sys.argv[1]), markdown_path=Path(sys.argv[2]))
"""
    pairs = [
        (first_markdown, "first", "2026-08-21T00:00:00"),
        (second_markdown, "second", "2026-08-21T00:00:01"),
    ]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(shared_json),
                str(markdown),
                name,
                generated,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for markdown, name, generated in pairs
    ]
    outputs = [process.communicate(timeout=30) for process in processes]

    for process, (_, stderr) in zip(processes, outputs, strict=True):
        assert process.returncode == 0, stderr
    _, machine_generation = _report_file_kind_and_generation(shared_json)
    markdown_generations = {
        _report_file_kind_and_generation(first_markdown)[1],
        _report_file_kind_and_generation(second_markdown)[1],
    }
    assert machine_generation in markdown_generations


class _FakeLockStream:
    def __init__(self, file_descriptor: int) -> None:
        self.file_descriptor = file_descriptor
        self.closed = False

    def fileno(self) -> int:
        return self.file_descriptor

    def close(self) -> None:
        self.closed = True


def test_report_lock_cleanup_preserves_primary_and_releases_all_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = [_FakeLockStream(10), _FakeLockStream(11)]

    def open_lock(path: Path, mode: str) -> _FakeLockStream:
        return streams.pop(0)

    def failing_unlock(file_descriptor: int, operation: int) -> None:
        if operation == fcntl.LOCK_UN:
            raise OSError(f"unlock failed for {file_descriptor}")

    monkeypatch.setattr(Path, "open", open_lock)
    monkeypatch.setattr(fcntl, "flock", failing_unlock)
    created = [_FakeLockStream(10), _FakeLockStream(11)]
    streams[:] = created

    with pytest.raises(RuntimeError, match="primary report failure") as captured:
        with runner._report_destination_locks(Path("a"), Path("b")):
            raise RuntimeError("primary report failure")

    assert all(stream.closed for stream in created)
    assert len(captured.value.__notes__) == 2
    assert all("unlock failed" in note for note in captured.value.__notes__)


def test_report_lock_acquisition_failure_closes_current_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _FakeLockStream(12)

    def open_lock(path: Path, mode: str) -> _FakeLockStream:
        return stream

    def fail_acquire(file_descriptor: int, operation: int) -> None:
        raise OSError("lock acquisition failed")

    monkeypatch.setattr(Path, "open", open_lock)
    monkeypatch.setattr(fcntl, "flock", fail_acquire)

    with pytest.raises(OSError, match="lock acquisition failed"):
        with runner._report_destination_locks(Path("a"), Path("b")):
            raise AssertionError("unreachable")
    assert stream.closed is True


@pytest.mark.parametrize("overlap", ["shared", "swapped"])
def test_destination_locks_block_deterministic_overlapping_writers(
    tmp_path: Path,
    overlap: str,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    third = tmp_path / "third"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    entered = tmp_path / "entered"
    script = """
import sys
import time
from pathlib import Path
from noa.compat.runner import _report_destination_locks

mode = sys.argv[1]
left = Path(sys.argv[2])
right = Path(sys.argv[3])
ready = Path(sys.argv[4])
release = Path(sys.argv[5])
entered = Path(sys.argv[6])
if mode == "holder":
    with _report_destination_locks(left, right):
        ready.write_text("ready", encoding="utf-8")
        while not release.exists():
            time.sleep(0.01)
else:
    while not ready.exists():
        time.sleep(0.01)
    with _report_destination_locks(left, right):
        entered.write_text("entered", encoding="utf-8")
"""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            "holder",
            str(first),
            str(second),
            str(ready),
            str(release),
            str(entered),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = monotonic() + 10
    while not ready.exists() and monotonic() < deadline:
        sleep(0.01)
    assert ready.exists()
    waiter_paths = (first, third) if overlap == "shared" else (second, first)
    waiter = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            "waiter",
            str(waiter_paths[0]),
            str(waiter_paths[1]),
            str(ready),
            str(release),
            str(entered),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    sleep(0.2)
    assert not entered.exists()
    release.write_text("release", encoding="utf-8")
    holder_output = holder.communicate(timeout=10)
    waiter_output = waiter.communicate(timeout=10)
    assert holder.returncode == 0, holder_output[1]
    assert waiter.returncode == 0, waiter_output[1]
    assert entered.exists()


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


_TEST_ARTIFACT_WIDTH = 1280
_TEST_ARTIFACT_HEIGHT = 720
_TEST_LOGICAL_WIDTH = 1024
_TEST_LOGICAL_HEIGHT = 576
_NOTE_MANIFEST_START = "<!-- noa-host-evidence-manifest:start -->\n```json\n"
_NOTE_MANIFEST_END = "\n```\n<!-- noa-host-evidence-manifest:end -->"
_NOTE_PROSE_PREFIX = """# Slice 0 MCP App Visual Evidence

## Observed Result

- Ping, modern Sampling request/response visibility, and inline MCP App rendering passed.
- The validator manifest below is the only machine-verifiable metadata source in this note.

## Validator Manifest

"""
_NOTE_PROSE_SUFFIX = "\n"
_TEST_SEMANTIC_KINDS = {
    "app": "inline_mcp_app",
    "sampling": "sampling_request_response",
}
_TEST_OBSERVED_RESULTS = {
    "app": (
        "Inline NoA Compatibility App heading, card, and ui://noa/compatibility.html URI "
        "are visible."
    ),
    "sampling": "Sampling request and response are visible.",
}


def _valid_test_png(
    width: int = _TEST_ARTIFACT_WIDTH,
    height: int = _TEST_ARTIFACT_HEIGHT,
    *,
    scanline_filter: int = 0,
    compressed_suffix: bytes = b"",
    compression_method: int = 0,
    filter_method: int = 0,
    interlace: int = 0,
) -> bytes:
    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,
        2,
        compression_method,
        filter_method,
        interlace,
    )
    row = bytes([scanline_filter]) + b"\x80\x80\x80" * width
    compressed = zlib.compress(row * height) + compressed_suffix
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _test_png_with_chunks(
    width: int = 2,
    height: int = 1,
    *,
    bit_depth: int = 8,
    color_type: int = 2,
    before_idat: tuple[tuple[bytes, bytes], ...] = (),
    after_idat: tuple[tuple[bytes, bytes], ...] = (),
    iend_payload: bytes = b"",
) -> bytes:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    chunks = [
        _png_chunk(b"IHDR", ihdr),
        *(_png_chunk(chunk_type, payload) for chunk_type, payload in before_idat),
        _png_chunk(b"IDAT", zlib.compress((b"\x00" + b"\x80" * row_bytes) * height)),
        *(_png_chunk(chunk_type, payload) for chunk_type, payload in after_idat),
        _png_chunk(b"IEND", iend_payload),
    ]
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def _test_png_with_compressed_data(
    width: int,
    height: int,
    compressed: bytes,
    *,
    color_type: int = 2,
) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("field", ["compression", "filter", "interlace"])
def test_decode_png_rejects_unsupported_ihdr_methods(field: str) -> None:
    image = _valid_test_png(
        width=2,
        height=1,
        compression_method=1 if field == "compression" else 0,
        filter_method=1 if field == "filter" else 0,
        interlace=1 if field == "interlace" else 0,
    )

    with pytest.raises(ValueError, match="unsupported PNG encoding"):
        runner._decode_png(image)


def test_decode_png_requires_ihdr_before_idat() -> None:
    ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0)
    rows = b"\x00" + b"\x80\x80\x80" * 2
    image = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IDAT", zlib.compress(rows))
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IEND", b"")
    )

    with pytest.raises(ValueError, match="IHDR must be the first PNG chunk"):
        runner._decode_png(image)


def test_decode_png_requires_consecutive_idat_chunks() -> None:
    ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0)
    rows = b"\x00" + b"\x80\x80\x80" * 2
    compressed = zlib.compress(rows)
    split = len(compressed) // 2
    image = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed[:split])
        + _png_chunk(b"tEXt", b"key\x00value")
        + _png_chunk(b"IDAT", compressed[split:])
        + _png_chunk(b"IEND", b"")
    )

    with pytest.raises(ValueError, match="PNG IDAT chunks must be consecutive"):
        runner._decode_png(image)


@pytest.mark.parametrize(
    ("chunk_type", "expected_error"),
    [
        (b"ab1d", "invalid PNG chunk type"),
        (b"abcD", "invalid PNG chunk reserved bit"),
        (b"ABCD", "unsupported critical PNG chunk"),
    ],
)
def test_decode_png_rejects_invalid_or_unknown_chunk_types(
    chunk_type: bytes,
    expected_error: str,
) -> None:
    image = _test_png_with_chunks(before_idat=((chunk_type, b""),))

    with pytest.raises(ValueError, match=expected_error):
        runner._decode_png(image)


@pytest.mark.parametrize("payload_size", [0, 1, 4, 769])
def test_decode_png_rejects_invalid_plte_length(payload_size: int) -> None:
    image = _test_png_with_chunks(before_idat=((b"PLTE", b"\x00" * payload_size),))

    with pytest.raises(ValueError, match="invalid PNG PLTE length"):
        runner._decode_png(image)


@pytest.mark.parametrize("color_type", [0, 4])
def test_decode_png_rejects_plte_for_grayscale_color_types(color_type: int) -> None:
    image = _test_png_with_chunks(
        color_type=color_type,
        before_idat=((b"PLTE", b"\x00\x00\x00"),),
    )

    with pytest.raises(ValueError, match="PNG PLTE is forbidden for color type"):
        runner._decode_png(image)


def test_decode_png_requires_plte_for_indexed_color() -> None:
    image = _test_png_with_chunks(bit_depth=1, color_type=3)

    with pytest.raises(ValueError, match="indexed PNG requires PLTE"):
        runner._decode_png(image)


def test_decode_png_limits_indexed_palette_to_bit_depth() -> None:
    image = _test_png_with_chunks(
        bit_depth=1,
        color_type=3,
        before_idat=((b"PLTE", b"\x00\x00\x00" * 3),),
    )

    with pytest.raises(ValueError, match="indexed PNG PLTE has too many entries"):
        runner._decode_png(image)


@pytest.mark.parametrize("color_type", [2, 6])
def test_decode_png_accepts_optional_truecolor_plte(color_type: int) -> None:
    image = _test_png_with_chunks(
        color_type=color_type,
        before_idat=((b"PLTE", b"\x00\x00\x00"),),
    )

    assert runner._decode_png(image) == (2, 1)


@pytest.mark.parametrize(
    ("before_idat", "after_idat"),
    [
        (((b"PLTE", b"\x00\x00\x00"), (b"PLTE", b"\x00\x00\x00")), ()),
        ((), ((b"PLTE", b"\x00\x00\x00"),)),
    ],
)
def test_decode_png_rejects_invalid_plte_order(
    before_idat: tuple[tuple[bytes, bytes], ...],
    after_idat: tuple[tuple[bytes, bytes], ...],
) -> None:
    image = _test_png_with_chunks(before_idat=before_idat, after_idat=after_idat)

    with pytest.raises(ValueError, match="invalid PNG PLTE order"):
        runner._decode_png(image)


def test_decode_png_rejects_invalid_ihdr_length() -> None:
    image = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", b"\x00" * 12)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00"))
        + _png_chunk(b"IEND", b"")
    )

    with pytest.raises(ValueError, match="invalid PNG IHDR"):
        runner._decode_png(image)


def test_decode_png_rejects_nonempty_iend() -> None:
    image = _test_png_with_chunks(iend_payload=b"invalid")

    with pytest.raises(ValueError, match="invalid PNG IEND"):
        runner._decode_png(image)


def test_decode_png_rejects_oversized_ihdr_before_decompression() -> None:
    image = _test_png_with_compressed_data(4001, 4000, zlib.compress(b"\x00"))

    with pytest.raises(ValueError, match="PNG pixel count exceeds limit"):
        runner._decode_png(image)


def test_decode_png_rejects_high_compression_output_over_expected_size() -> None:
    image = _test_png_with_compressed_data(1, 1, zlib.compress(b"\x00" * (1024 * 1024)))

    with pytest.raises(ValueError, match="PNG decompressed data exceeds expected size"):
        runner._decode_png(image)


def _host_visual(evidence: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], evidence["visual"])


def _host_artifact(evidence: dict[str, object], name: str) -> dict[str, object]:
    return cast(dict[str, object], _host_visual(evidence)[name])


def _write_host_evidence(root: Path, evidence: dict[str, object]) -> None:
    (root / ".agent/visual/slice-0-host-evidence.json").write_text(
        json.dumps(evidence),
        encoding="utf-8",
    )


def _host_note_manifest(evidence: dict[str, object]) -> dict[str, object]:
    host = cast(dict[str, object], evidence["host"])
    visual = _host_visual(evidence)
    artifacts: dict[str, object] = {}
    for name in ("app", "sampling"):
        artifact = _host_artifact(evidence, name)
        dimensions = cast(dict[str, object], artifact["pixel_dimensions"])
        semantic_review = cast(dict[str, object], artifact["semantic_review"])
        artifacts[name] = {
            "path": artifact["artifact"],
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
            "pixel_dimensions": dict(dimensions),
            "semantic_kind": artifact["semantic_kind"],
            "semantic_review": dict(semantic_review),
        }
    logical_viewport = cast(dict[str, object], visual["logical_viewport"])
    return {
        "host": {
            "name": host["name"],
            "version": host["version"],
            "commit": host["commit"],
            "architecture": host["architecture"],
        },
        "captured_at": visual["captured_at"],
        "logical_viewport": dict(logical_viewport),
        "artifacts": artifacts,
    }


def _write_host_note(
    root: Path,
    evidence: dict[str, object],
    *,
    manifest: dict[str, object] | None = None,
) -> None:
    manifest = manifest or _host_note_manifest(evidence)
    note = (
        _NOTE_PROSE_PREFIX
        + _NOTE_MANIFEST_START
        + json.dumps(manifest, indent=2)
        + _NOTE_MANIFEST_END
        + _NOTE_PROSE_SUFFIX
    )
    (root / ".agent/visual/slice-0-app.md").write_text(note, encoding="utf-8")


def _write_test_artifact(
    root: Path,
    evidence: dict[str, object],
    name: str,
    image: bytes,
    *,
    width: int,
    height: int,
) -> None:
    artifact = _host_artifact(evidence, name)
    (root / cast(str, artifact["artifact"])).write_bytes(image)
    artifact["pixel_dimensions"] = {"width": width, "height": height}
    artifact["sha256"] = hashlib.sha256(image).hexdigest()
    artifact["bytes"] = len(image)
    semantic_review = cast(dict[str, object], artifact["semantic_review"])
    semantic_review["artifact_sha256"] = artifact["sha256"]


def _write_test_host_evidence(root: Path) -> dict[str, object]:
    visual = root / ".agent/visual"
    vscode = root / ".vscode"
    visual.mkdir(parents=True)
    vscode.mkdir(parents=True)
    captured_at = datetime.now(UTC)
    reviewed_at = captured_at + timedelta(seconds=1)
    app_image = _valid_test_png()
    sampling_image = _valid_test_png()
    (visual / "slice-0-app.png").write_bytes(app_image)
    (visual / "slice-0-sampling.png").write_bytes(sampling_image)
    evidence: dict[str, object] = {
        "schema_version": 2,
        "host": {
            "name": "VS Code Stable",
            "version": "1.133.0",
            "commit": "commit",
            "architecture": "arm64",
            "code_version_output": ["1.133.0", "commit", "arm64"],
        },
        "mcp_server": {
            "name": "noa",
            "status": "pass",
            "transport": "stdio",
            "config_path": ".vscode/mcp.json",
        },
        "checks": {
            "compatibility_ping": {
                "status": "pass",
                "result": {"status": "pass", "value": "vscode"},
            },
            "sampling": {
                "status": "pass",
                "protocol_path": "2026-07-28",
                "authorization_prompt_observed": False,
                "authorization_result": "sampling_succeeded_without_separate_prompt",
                "request_visible": True,
                "response_visible": True,
                "result_status": "pass",
            },
            "mcp_app": {
                "status": "pass",
                "inline_rendered": True,
                "title_visible": "NoA Compatibility",
                "uri_wrapped_inside_card": True,
                "text_contrast": "body-color-inherited",
            },
        },
        "visual": {
            "status": "pass",
            "captured_at": captured_at.isoformat(),
            "logical_viewport": {
                "width": _TEST_LOGICAL_WIDTH,
                "height": _TEST_LOGICAL_HEIGHT,
            },
            "app": {
                "artifact": ".agent/visual/slice-0-app.png",
                "pixel_dimensions": {
                    "width": _TEST_ARTIFACT_WIDTH,
                    "height": _TEST_ARTIFACT_HEIGHT,
                },
                "sha256": hashlib.sha256(app_image).hexdigest(),
                "bytes": len(app_image),
                "semantic_kind": _TEST_SEMANTIC_KINDS["app"],
                "semantic_review": {
                    "reviewer_type": "independent_agent",
                    "reviewed_at": reviewed_at.isoformat(),
                    "artifact_sha256": hashlib.sha256(app_image).hexdigest(),
                    "observed_result": _TEST_OBSERVED_RESULTS["app"],
                },
            },
            "sampling": {
                "artifact": ".agent/visual/slice-0-sampling.png",
                "pixel_dimensions": {
                    "width": _TEST_ARTIFACT_WIDTH,
                    "height": _TEST_ARTIFACT_HEIGHT,
                },
                "sha256": hashlib.sha256(sampling_image).hexdigest(),
                "bytes": len(sampling_image),
                "semantic_kind": _TEST_SEMANTIC_KINDS["sampling"],
                "semantic_review": {
                    "reviewer_type": "independent_agent",
                    "reviewed_at": reviewed_at.isoformat(),
                    "artifact_sha256": hashlib.sha256(sampling_image).hexdigest(),
                    "observed_result": _TEST_OBSERVED_RESULTS["sampling"],
                },
            },
        },
    }
    _write_host_evidence(root, evidence)
    (vscode / "mcp.json").write_text(
        json.dumps(
            {
                "inputs": [],
                "servers": {
                    "noa": {
                        "type": "stdio",
                        "command": "uv",
                        "args": ["run", "--frozen", "python", "-m", "noa"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _write_host_note(root, evidence)
    return evidence


def test_vs_code_host_evidence_can_complete_the_gate(tmp_path: Path) -> None:
    evidence = _write_test_host_evidence(tmp_path)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.PASS
    assert result.details["version"] == "1.133.0"
    assert result.details["protocol_path"] == "2026-07-28"
    assert result.details["evidence_is_fresh"] is True
    assert result.details["note_manifest_matches"] is True
    note_manifest = cast(dict[str, object], result.details["note_manifest"])
    assert note_manifest["logical_viewport"] == {
        "width": _TEST_LOGICAL_WIDTH,
        "height": _TEST_LOGICAL_HEIGHT,
    }
    artifacts = cast(dict[str, dict[str, object]], result.details["artifacts"])
    assert set(artifacts) == {"app", "sampling"}
    for name in artifacts:
        artifact = artifacts[name]
        declared = _host_artifact(evidence, name)
        expected = {
            "bytes": declared["bytes"],
            "sha256": declared["sha256"],
            "pixel_dimensions": declared["pixel_dimensions"],
        }
        assert artifact["artifact"] == declared["artifact"]
        assert artifact["claimed"] == expected
        assert artifact["actual"] == expected
        assert artifact["bytes_match"] is True
        assert artifact["sha256_match"] is True
        assert artifact["dimensions_match"] is True
        assert artifact["meets_minimum_dimensions"] is True
        assert artifact["aspect_ratio_matches"] is True
        assert artifact["semantic_kind"] == _TEST_SEMANTIC_KINDS[name]
        assert artifact["semantic_kind_matches"] is True
        semantic_review = cast(dict[str, object], artifact["semantic_review"])
        assert semantic_review["reviewer_type"] == "independent_agent"
        assert semantic_review["artifact_sha256"] == declared["sha256"]
        assert semantic_review["observed_result"] == _TEST_OBSERVED_RESULTS[name]
        assert artifact["semantic_review_sha256_matches_claim"] is True
        assert artifact["semantic_review_sha256_matches_actual"] is True
        assert artifact["semantic_review_observed_result_matches"] is True
        assert artifact["semantic_review_not_before_capture"] is True
        assert artifact["semantic_review_not_too_far_future"] is True


def test_vs_code_host_evidence_rejects_duplicate_markdown_metadata(tmp_path: Path) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    note_path = tmp_path / ".agent/visual/slice-0-app.md"
    note = note_path.read_text(encoding="utf-8")
    duplicate = f"- Captured at: `{_host_visual(evidence)['captured_at']}`\n\n"
    note_path.write_text(
        note.replace("## Validator Manifest\n\n", duplicate + "## Validator Manifest\n\n"),
        encoding="utf-8",
    )

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["error"] == (
        "host evidence note must use the canonical prose around its only metadata manifest"
    )


@pytest.mark.parametrize("level", ["top", "nested"])
@pytest.mark.parametrize("source", ["evidence", "config", "manifest"])
def test_vs_code_host_evidence_rejects_duplicate_json_keys(
    tmp_path: Path,
    source: str,
    level: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    if source == "evidence":
        path = tmp_path / ".agent/visual/slice-0-host-evidence.json"
        text = path.read_text(encoding="utf-8")
        if level == "top":
            key = "schema_version"
            target = '"schema_version": 2,'
        else:
            key = "name"
            target = '"name": "VS Code Stable",'
    elif source == "config":
        path = tmp_path / ".vscode/mcp.json"
        text = path.read_text(encoding="utf-8")
        if level == "top":
            key = "inputs"
            target = '"inputs": [],'
        else:
            key = "type"
            target = '"type": "stdio",'
    else:
        path = tmp_path / ".agent/visual/slice-0-app.md"
        text = path.read_text(encoding="utf-8")
        if level == "top":
            key = "captured_at"
            target = f'"captured_at": "{_host_visual(evidence)["captured_at"]}",'
        else:
            key = "name"
            target = '"name": "VS Code Stable",'
    assert text.count(target) == 1
    path.write_text(text.replace(target, f"{target}\n    {target}"), encoding="utf-8")

    result = runner._vs_code_check(tmp_path)

    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert result.details["error"] == f"duplicate JSON key: {key}"


@pytest.mark.parametrize("days_old", [1, 15, 29])
def test_vs_code_host_evidence_accepts_recent_capture_with_checkout_mtime(
    tmp_path: Path,
    days_old: int,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    captured_at = datetime.now(UTC) - timedelta(days=days_old)
    _host_visual(evidence)["captured_at"] = captured_at.isoformat()
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)
    image_mtime = datetime.fromtimestamp(
        (tmp_path / ".agent/visual/slice-0-app.png").stat().st_mtime,
        UTC,
    )
    assert abs((image_mtime - captured_at).total_seconds()) > 3600

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.PASS
    assert result.details["evidence_is_fresh"] is True


@pytest.mark.parametrize("age", [timedelta(days=31), timedelta(days=-1)])
def test_vs_code_host_evidence_rejects_stale_or_future_capture(
    tmp_path: Path,
    age: timedelta,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    captured_at = datetime.now(UTC) - age
    _host_visual(evidence)["captured_at"] = captured_at.isoformat()
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["evidence_is_fresh"] is False
    evidence_age_seconds = cast(float, result.details["evidence_age_seconds"])
    if age.total_seconds() > 0:
        assert evidence_age_seconds > timedelta(days=30).total_seconds()
    else:
        assert evidence_age_seconds < 0


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
def test_vs_code_host_evidence_rejects_corrupt_png(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    corrupted = bytearray(_valid_test_png())
    idat_offset = corrupted.index(b"IDAT")
    corrupted[idat_offset + 4] ^= 1
    image = bytes(corrupted)
    _write_test_artifact(
        tmp_path,
        evidence,
        artifact_name,
        image,
        width=_TEST_ARTIFACT_WIDTH,
        height=_TEST_ARTIFACT_HEIGHT,
    )
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    error = cast(str, result.details["error"])
    assert f"{artifact_name} visual artifact" in error
    assert "invalid PNG chunk CRC" in error


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("zlib-trailing-data", "PNG zlib stream has trailing data"),
        ("invalid-scanline-filter", "invalid PNG scanline filter"),
    ],
)
def test_vs_code_host_evidence_rejects_crc_valid_png_corruption(
    tmp_path: Path,
    artifact_name: str,
    corruption: str,
    expected_error: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    image = (
        _valid_test_png(compressed_suffix=b"trailing-data")
        if corruption == "zlib-trailing-data"
        else _valid_test_png(scanline_filter=5)
    )
    _write_test_artifact(
        tmp_path,
        evidence,
        artifact_name,
        image,
        width=_TEST_ARTIFACT_WIDTH,
        height=_TEST_ARTIFACT_HEIGHT,
    )
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert expected_error in cast(str, result.details["error"])


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize(
    ("invalid_chunk", "expected_error"),
    [
        ((b"ab1d", b""), "invalid PNG chunk type"),
        ((b"PLTE", b"\x00"), "invalid PNG PLTE length"),
    ],
)
def test_vs_code_host_evidence_rejects_crc_valid_invalid_png_chunks(
    tmp_path: Path,
    artifact_name: str,
    invalid_chunk: tuple[bytes, bytes],
    expected_error: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    image = _test_png_with_chunks(
        _TEST_ARTIFACT_WIDTH,
        _TEST_ARTIFACT_HEIGHT,
        before_idat=(invalid_chunk,),
    )
    _write_test_artifact(
        tmp_path,
        evidence,
        artifact_name,
        image,
        width=_TEST_ARTIFACT_WIDTH,
        height=_TEST_ARTIFACT_HEIGHT,
    )
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert expected_error in cast(str, result.details["error"])


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("oversized-ihdr", "PNG pixel count exceeds limit"),
        ("high-compression-output", "PNG decompressed data exceeds expected size"),
    ],
)
def test_vs_code_host_evidence_rejects_png_resource_budget_violations(
    tmp_path: Path,
    artifact_name: str,
    corruption: str,
    expected_error: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    if corruption == "oversized-ihdr":
        width, height = 4001, 4000
        image = _test_png_with_compressed_data(width, height, zlib.compress(b"\x00"))
    else:
        width = height = 1
        image = _test_png_with_compressed_data(
            width,
            height,
            zlib.compress(b"\x00" * (1024 * 1024)),
        )
    _write_test_artifact(
        tmp_path,
        evidence,
        artifact_name,
        image,
        width=width,
        height=height,
    )
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert expected_error in cast(str, result.details["error"])


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
def test_vs_code_host_evidence_rejects_png_file_over_size_limit(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    artifact_path = tmp_path / cast(str, _host_artifact(evidence, artifact_name)["artifact"])
    with artifact_path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)

    result = runner._vs_code_check(tmp_path)

    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert result.details["error"] == (
        f"visual artifact exceeds maximum file size of 16777216 bytes: {artifact_path}"
    )


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize("failure", ["declared-mismatch", "below-minimum"])
def test_vs_code_host_evidence_rejects_invalid_artifact_dimensions(
    tmp_path: Path,
    artifact_name: str,
    failure: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    artifact = _host_artifact(evidence, artifact_name)
    if failure == "declared-mismatch":
        artifact["pixel_dimensions"] = {
            "width": _TEST_ARTIFACT_WIDTH + 1,
            "height": _TEST_ARTIFACT_HEIGHT,
        }
    else:
        _write_test_artifact(
            tmp_path,
            evidence,
            artifact_name,
            _valid_test_png(width=_TEST_LOGICAL_WIDTH, height=_TEST_LOGICAL_HEIGHT),
            width=_TEST_LOGICAL_WIDTH,
            height=_TEST_LOGICAL_HEIGHT,
        )
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    artifacts = cast(dict[str, dict[str, object]], result.details["artifacts"])
    artifact_audit = artifacts[artifact_name]
    if failure == "declared-mismatch":
        assert artifact_audit["dimensions_match"] is False
    else:
        assert artifact_audit["dimensions_match"] is True
        assert artifact_audit["meets_logical_viewport"] is True
        assert artifact_audit["meets_minimum_dimensions"] is False


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize("field", ["bytes", "sha256"])
def test_vs_code_host_evidence_rejects_artifact_integrity_mismatch(
    tmp_path: Path,
    artifact_name: str,
    field: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    artifact = _host_artifact(evidence, artifact_name)
    if field == "bytes":
        artifact[field] = cast(int, artifact[field]) + 1
    else:
        artifact[field] = "0" * 64
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    artifacts = cast(dict[str, dict[str, object]], result.details["artifacts"])
    assert artifacts[artifact_name][f"{field}_match"] is False


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
def test_vs_code_host_evidence_rejects_missing_semantic_review(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    _host_artifact(evidence, artifact_name).pop("semantic_review")
    _write_host_evidence(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert "semantic_review" in cast(str, result.details["error"])


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
def test_vs_code_host_evidence_rejects_wrong_semantic_kind(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    artifact = _host_artifact(evidence, artifact_name)
    artifact["semantic_kind"] = "wrong_semantic_kind"
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    artifacts = cast(dict[str, dict[str, object]], result.details["artifacts"])
    assert artifacts[artifact_name]["semantic_kind_matches"] is False


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize(
    ("field", "value", "audit_field"),
    [
        ("reviewer_type", "human", "semantic_review_reviewer_matches"),
        ("artifact_sha256", "0" * 64, "semantic_review_sha256_matches_actual"),
        ("observed_result", "Unexpected observation.", "semantic_review_observed_result_matches"),
    ],
)
def test_vs_code_host_evidence_rejects_invalid_semantic_review_binding(
    tmp_path: Path,
    artifact_name: str,
    field: str,
    value: str,
    audit_field: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    review = cast(dict[str, object], _host_artifact(evidence, artifact_name)["semantic_review"])
    review[field] = value
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    artifacts = cast(dict[str, dict[str, object]], result.details["artifacts"])
    assert artifacts[artifact_name][audit_field] is False


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
def test_vs_code_host_evidence_rejects_empty_semantic_observed_result(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    review = cast(dict[str, object], _host_artifact(evidence, artifact_name)["semantic_review"])
    review["observed_result"] = "   "
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert "observed_result must be a non-empty string" in cast(str, result.details["error"])


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
@pytest.mark.parametrize("timing", ["before-capture", "too-far-future"])
def test_vs_code_host_evidence_rejects_invalid_semantic_review_time(
    tmp_path: Path,
    artifact_name: str,
    timing: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    visual = _host_visual(evidence)
    captured_at = datetime.fromisoformat(cast(str, visual["captured_at"]))
    review = cast(dict[str, object], _host_artifact(evidence, artifact_name)["semantic_review"])
    review["reviewed_at"] = (
        captured_at - timedelta(seconds=1)
        if timing == "before-capture"
        else datetime.now(UTC) + timedelta(minutes=6)
    ).isoformat()
    _write_host_evidence(tmp_path, evidence)
    _write_host_note(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    artifacts = cast(dict[str, dict[str, object]], result.details["artifacts"])
    audit_field = (
        "semantic_review_not_before_capture"
        if timing == "before-capture"
        else "semantic_review_not_too_far_future"
    )
    assert artifacts[artifact_name][audit_field] is False


@pytest.mark.parametrize(
    "field_path",
    [
        "host.name",
        "host.version",
        "host.commit",
        "host.architecture",
        "captured_at",
        "logical_viewport",
        "app.path",
        "app.sha256",
        "app.bytes",
        "app.pixel_dimensions",
        "app.semantic_kind",
        "app.semantic_review",
        "sampling.path",
        "sampling.sha256",
        "sampling.bytes",
        "sampling.pixel_dimensions",
        "sampling.semantic_kind",
        "sampling.semantic_review",
    ],
)
def test_vs_code_host_evidence_rejects_markdown_manifest_mismatch(
    tmp_path: Path,
    field_path: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    manifest = _host_note_manifest(evidence)
    if field_path.startswith("host."):
        host = cast(dict[str, object], manifest["host"])
        field = field_path.removeprefix("host.")
        host[field] = f"{host[field]}-mismatch"
    elif field_path == "captured_at":
        manifest["captured_at"] = "2026-08-20T00:00:00+00:00"
    elif field_path == "logical_viewport":
        logical_viewport = cast(dict[str, int], manifest["logical_viewport"])
        manifest["logical_viewport"] = {
            **logical_viewport,
            "width": logical_viewport["width"] + 1,
        }
    else:
        artifact_name, field = field_path.split(".", maxsplit=1)
        artifacts = cast(dict[str, dict[str, object]], manifest["artifacts"])
        artifact = artifacts[artifact_name]
        if field == "bytes":
            artifact[field] = cast(int, artifact[field]) + 1
        elif field == "sha256":
            artifact[field] = "0" * 64
        elif field == "pixel_dimensions":
            dimensions = cast(dict[str, int], artifact[field])
            artifact[field] = {**dimensions, "width": dimensions["width"] + 1}
        elif field == "semantic_review":
            semantic_review = cast(dict[str, object], artifact[field])
            artifact[field] = {
                **semantic_review,
                "observed_result": f"{semantic_review['observed_result']} mismatch",
            }
        else:
            artifact[field] = f"{artifact[field]}-mismatch"
    _write_host_note(tmp_path, evidence, manifest=manifest)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["note_manifest_matches"] is False


@pytest.mark.parametrize("artifact_name", ["app", "sampling"])
def test_vs_code_host_evidence_rejects_missing_declared_artifact(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    artifact = _host_artifact(evidence, artifact_name)
    artifact_path = tmp_path / cast(str, artifact["artifact"])
    artifact_path.unlink()

    result = runner._vs_code_check(tmp_path)

    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert result.details["missing_path"] == str(artifact_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        ".vscode/mcp.json",
        ".agent/visual/slice-0-host-evidence.json",
        ".agent/visual/slice-0-app.md",
        ".agent/visual/slice-0-app.png",
        ".agent/visual/slice-0-sampling.png",
    ],
)
def test_vs_code_host_evidence_rejects_external_file_symlink(
    tmp_path: Path,
    relative_path: str,
) -> None:
    _write_test_host_evidence(tmp_path)
    target = tmp_path / relative_path
    outside_root = tmp_path.parent / f"{tmp_path.name}-outside-{target.name}"
    outside_root.mkdir()
    outside = outside_root / target.name
    outside.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside)

    result = runner._vs_code_check(tmp_path)

    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert "symlink" in cast(str, result.details["error"])
    assert relative_path in cast(str, result.details["error"])


def test_vs_code_host_evidence_rejects_symlinked_path_component(tmp_path: Path) -> None:
    _write_test_host_evidence(tmp_path)
    vscode = tmp_path / ".vscode"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-vscode"
    outside.mkdir()
    (outside / "mcp.json").write_bytes((vscode / "mcp.json").read_bytes())
    (vscode / "mcp.json").unlink()
    vscode.rmdir()
    vscode.symlink_to(outside, target_is_directory=True)

    result = runner._vs_code_check(tmp_path)

    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert "symlink" in cast(str, result.details["error"])
    assert ".vscode/mcp.json" in cast(str, result.details["error"])


def test_vs_code_host_evidence_rejects_schema_v1_without_fallback(tmp_path: Path) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    evidence["schema_version"] = 1
    _write_host_evidence(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL
    assert result.details["error"] == "host evidence schema_version must be 2"


@pytest.mark.parametrize(
    "failure",
    ["bad-command", "sampling-failed", "missing-request", "app-failed"],
)
def test_vs_code_host_evidence_rejects_false_positive_inputs(
    tmp_path: Path,
    failure: str,
) -> None:
    evidence = _write_test_host_evidence(tmp_path)
    if failure == "bad-command":
        (tmp_path / ".vscode/mcp.json").write_text(
            json.dumps({"servers": {"noa": {"type": "stdio", "command": "false"}}}),
            encoding="utf-8",
        )
    elif failure == "sampling-failed":
        checks = cast(dict[str, dict[str, object]], evidence["checks"])
        checks["sampling"]["status"] = "fail"
    elif failure == "missing-request":
        checks = cast(dict[str, dict[str, object]], evidence["checks"])
        checks["sampling"]["request_visible"] = False
    else:
        checks = cast(dict[str, dict[str, object]], evidence["checks"])
        checks["mcp_app"]["inline_rendered"] = False
    if failure != "bad-command":
        _write_host_evidence(tmp_path, evidence)

    result = runner._vs_code_check(tmp_path)

    assert result.status is CheckStatus.FAIL


def _bundled_runner_app_html() -> str:
    return files("noa.compat.app").joinpath("index.html").read_text(encoding="utf-8")


def _install_fake_app_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    html: str,
    content_metadata: dict[str, object] | None = None,
    resources: list[tuple[str, dict[str, object]]] | None = None,
) -> None:
    effective_content_metadata = content_metadata or {"ui": {"csp": {}}}
    effective_resources = resources
    if effective_resources is None:
        effective_resources = [("ui://noa/compatibility.html", {"ui": {"csp": {}}})]

    class FakeContent:
        def __init__(self) -> None:
            self.mime_type = "text/html;profile=mcp-app"
            self.text = html
            self.meta = effective_content_metadata

    class FakeResource:
        def __init__(self, uri: str, metadata: dict[str, object]) -> None:
            self.uri = uri
            self.meta = metadata

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            pass

        async def read_resource(self, uri: object) -> list[FakeContent]:
            return [FakeContent()]

        async def list_resources(self) -> list[FakeResource]:
            return [FakeResource(uri, metadata) for uri, metadata in effective_resources]

    monkeypatch.setattr(runner, "Client", FakeClient)


@pytest.mark.parametrize(
    "malicious_html",
    [
        "<script>alert(1)</script>",
        '<main onclick="alert(1)">NoA Compatibility ui://noa/compatibility.html</main>',
        "<style>body { background: url(image.png); }</style>",
        "<p>fetch('/data')</p>",
        "<p>ftp://example.invalid</p>",
        "<iframe>NoA Compatibility ui://noa/compatibility.html</iframe>",
    ],
)
async def test_app_check_rejects_html_policy_violations_in_runner_production_path(
    monkeypatch: pytest.MonkeyPatch,
    malicious_html: str,
) -> None:
    _install_fake_app_client(monkeypatch, html=malicious_html)

    result = await runner._app_check()

    assert result.status is CheckStatus.FAIL
    assert result.details["error_type"] == "AppHTMLValidationError"
    assert "MCP App HTML policy violation" in cast(str, result.details["error"])


@pytest.mark.parametrize(
    "invalid_html",
    [
        _bundled_runner_app_html().replace(
            "</style>",
            'body { background: image-set("//example.invalid/app.png" 1x); }\n  </style>',
        ),
        _bundled_runner_app_html().replace(
            "<h1>NoA Compatibility</h1>",
            "<h1>Wrong heading</h1>",
        ),
        _bundled_runner_app_html().replace(
            "<code>ui://noa/compatibility.html</code>",
            "<code>ui://wrong/app.html</code><!-- ui://noa/compatibility.html -->",
        ),
    ],
)
async def test_app_check_uses_fail_closed_css_and_visible_dom_validation(
    monkeypatch: pytest.MonkeyPatch,
    invalid_html: str,
) -> None:
    _install_fake_app_client(monkeypatch, html=invalid_html)

    result = await runner._app_check()

    assert result.status is CheckStatus.FAIL
    assert result.details["error_type"] == "AppHTMLValidationError"


async def test_app_check_rejects_resource_side_csp_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_app_client(
        monkeypatch,
        html=_bundled_runner_app_html(),
        resources=[
            (
                "ui://noa/compatibility.html",
                {"ui": {"csp": {"resourceDomains": ["https://evil.invalid"]}}},
            )
        ],
    )

    result = await runner._app_check()

    assert result.status is CheckStatus.FAIL
    assert result.details["error_type"] == "AppCSPValidationError"


@pytest.mark.parametrize(
    "resources",
    [
        [],
        [
            ("ui://noa/compatibility.html", {"ui": {"csp": {}}}),
            ("ui://noa/compatibility.html", {"ui": {"csp": {}}}),
        ],
    ],
)
async def test_app_check_requires_exactly_one_listed_app_resource(
    monkeypatch: pytest.MonkeyPatch,
    resources: list[tuple[str, dict[str, object]]],
) -> None:
    _install_fake_app_client(
        monkeypatch,
        html=_bundled_runner_app_html(),
        resources=resources,
    )

    result = await runner._app_check()

    assert result.status is CheckStatus.FAIL
    assert result.details["error_type"] == "ValueError"
    assert "exactly one listed resource" in cast(str, result.details["error"])


async def test_real_runner_aggregates_local_probes_and_blocks_missing_host_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"

    report = await runner.run_compatibility_gate(workspace)

    checks = {check.name: check for check in report.checks}
    assert set(checks) == {
        "python",
        "platform",
        "fastmcp",
        "fastmcp-slim",
        "mcp-sdk",
        "ladybug",
        "packaging",
        "pydantic",
        "anyio",
        "fastmcp-stability",
        "ladybug-transaction-persistence",
        "sqlite-checkpoint-recovery",
        "sampling-modern",
        "sampling-legacy",
        "mcp-app-resource",
        "vs-code-stable",
    }
    for name in {
        "python",
        "platform",
        "fastmcp",
        "fastmcp-slim",
        "mcp-sdk",
        "ladybug",
        "packaging",
        "pydantic",
        "anyio",
        "ladybug-transaction-persistence",
        "sqlite-checkpoint-recovery",
        "sampling-modern",
        "sampling-legacy",
        "mcp-app-resource",
    }:
        assert checks[name].status is CheckStatus.PASS, checks[name].model_dump_json(indent=2)
    assert checks["sampling-modern"].details == {
        "mode": "auto",
        "protocol_version": "2026-07-28",
        "result": {"status": "pass", "answer": "compatible"},
    }
    assert checks["sampling-legacy"].details == {
        "mode": "legacy",
        "protocol_version": "2025-11-25",
        "result": {"status": "pass", "answer": "compatible"},
    }
    assert checks["mcp-app-resource"].details == {
        "uri": "ui://noa/compatibility.html",
        "content_count": 1,
        "mime_type": "text/html;profile=mcp-app",
        "listed_resource_count": 1,
        "exact_uri_resource_count": 1,
        "csp": {
            "connect_domains": [],
            "resource_domains": [],
            "frame_domains": [],
            "base_uri_domains": [],
        },
        "csp_metadata_consistent": True,
        "html_validation": {
            "heading_visible": True,
            "resource_uri_visible": True,
        },
    }
    assert checks["fastmcp-stability"].status is CheckStatus.WARN
    host_check = checks["vs-code-stable"]
    assert host_check.required is True
    assert host_check.status is CheckStatus.BLOCKED
    assert "Task 11" in host_check.summary
    assert report.decision is GateDecision.NO_GO
    assert (workspace / "ladybug").is_dir()
    assert (workspace / "checkpoint").is_dir()


async def test_real_runner_is_stable_across_repeated_same_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    local_functional_checks = {
        "ladybug-transaction-persistence",
        "sqlite-checkpoint-recovery",
        "sampling-modern",
        "sampling-legacy",
        "mcp-app-resource",
    }

    reports = [await runner.run_compatibility_gate(workspace) for _ in range(2)]

    for report in reports:
        checks = {check.name: check for check in report.checks}
        for name in local_functional_checks:
            assert checks[name].status is CheckStatus.PASS, checks[name].model_dump_json(indent=2)
        assert checks["vs-code-stable"].status is CheckStatus.BLOCKED
        assert report.decision is GateDecision.NO_GO


def test_five_fresh_processes_can_run_gate_concurrently_in_same_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "shared-workspace"
    script = """
import asyncio
import sys
from pathlib import Path
from noa.compat.runner import run_compatibility_gate

report = asyncio.run(run_compatibility_gate(Path(sys.argv[1])))
print(report.model_dump_json())
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(workspace)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(5)
    ]

    outputs = [process.communicate(timeout=60) for process in processes]

    for process, (stdout, stderr) in zip(processes, outputs, strict=True):
        assert process.returncode == 0, stderr
        report = CompatibilityReport.model_validate_json(stdout)
        checks = {check.name: check for check in report.checks}
        assert checks["ladybug-transaction-persistence"].status is CheckStatus.PASS
        assert checks["sqlite-checkpoint-recovery"].status is CheckStatus.PASS


async def test_runner_launches_probe_workers_after_precreating_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    calls: list[tuple[str, str, Path, float]] = []

    async def run_probe(
        name: str,
        probe_name: str,
        root: Path,
        timeout_seconds: float = 15,
    ) -> CheckResult:
        assert root.is_dir()
        calls.append((name, probe_name, root, timeout_seconds))
        return CheckResult(name=name, status=CheckStatus.PASS)

    async def sampling_check(mode: str) -> CheckResult:
        return CheckResult(name=f"sampling-{mode}", status=CheckStatus.PASS)

    async def app_check() -> CheckResult:
        return CheckResult(name="app", status=CheckStatus.PASS)

    monkeypatch.setattr(runner, "build_runtime_checks", lambda: [])
    monkeypatch.setattr(runner, "_run_probe_process", run_probe, raising=False)
    monkeypatch.setattr(runner, "_sampling_check", sampling_check)
    monkeypatch.setattr(runner, "_app_check", app_check)

    report = await runner.run_compatibility_gate(workspace)

    assert calls == [
        (
            "ladybug-transaction-persistence",
            "ladybug",
            workspace / "ladybug",
            15,
        ),
        (
            "sqlite-checkpoint-recovery",
            "checkpoint",
            workspace / "checkpoint",
            15,
        ),
    ]
    assert [check.name for check in report.checks] == [
        "ladybug-transaction-persistence",
        "sqlite-checkpoint-recovery",
        "sampling-auto",
        "sampling-legacy",
        "app",
        "vs-code-stable",
    ]


@pytest.mark.parametrize(
    ("name", "probe_name"),
    [
        ("ladybug-transaction-persistence", "ladybug"),
        ("sqlite-checkpoint-recovery", "checkpoint"),
    ],
)
async def test_real_probe_worker_returns_structured_result(
    tmp_path: Path,
    name: str,
    probe_name: runner.ProbeName,
) -> None:
    result = await runner._run_probe_process(name, probe_name, tmp_path)

    assert result.name == name
    assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)


async def test_probe_worker_timeout_terminates_process_without_delayed_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "late-marker"
    script = (
        "import pathlib,sys,time; "
        "time.sleep(0.5); "
        "pathlib.Path(sys.argv[1]).write_text('late', encoding='utf-8')"
    )

    def slow_command(probe_name: str, root: Path) -> list[str]:
        return [sys.executable, "-c", script, str(marker)]

    monkeypatch.setattr(runner, "_probe_command", slow_command, raising=False)
    started_at = monotonic()

    result = await runner._run_probe_process(
        "ladybug-transaction-persistence",
        "ladybug",
        tmp_path,
        timeout_seconds=0.05,
    )

    elapsed = monotonic() - started_at
    assert elapsed < 0.5
    assert result.status is CheckStatus.FAIL
    assert result.details["timeout_seconds"] == 0.05
    assert result.details["terminated"] is True
    sleep(0.6)
    assert not marker.exists()


async def test_probe_worker_keeps_event_loop_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = CheckResult(name="sqlite-checkpoint-recovery", status=CheckStatus.PASS)
    envelope = json.dumps({"kind": "result", "result": result.model_dump(mode="json")})
    script = f"import time; time.sleep(0.3); print({envelope!r})"

    def slow_command(probe_name: str, root: Path) -> list[str]:
        return [sys.executable, "-c", script]

    monkeypatch.setattr(runner, "_probe_command", slow_command, raising=False)
    probe_task = asyncio.create_task(
        runner._run_probe_process("sqlite-checkpoint-recovery", "checkpoint", tmp_path)
    )
    started_at = monotonic()
    await asyncio.sleep(0.05)
    heartbeat_elapsed = monotonic() - started_at
    probe_result = await probe_task

    assert heartbeat_elapsed < 0.15
    assert probe_result.status is CheckStatus.PASS


@pytest.mark.parametrize(
    ("script", "expected_keys"),
    [
        (
            "import sys; sys.stderr.write('worker stderr'); raise SystemExit(3)",
            {"returncode", "stderr_bytes", "stderr_sha256"},
        ),
        (
            "print('not-json')",
            {"error_type", "error", "stdout_sha256", "stdout_bytes"},
        ),
    ],
)
async def test_probe_worker_normalizes_process_output_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    expected_keys: set[str],
) -> None:
    def failing_command(probe_name: str, root: Path) -> list[str]:
        return [sys.executable, "-c", script]

    monkeypatch.setattr(runner, "_probe_command", failing_command, raising=False)

    result = await runner._run_probe_process(
        "sqlite-checkpoint-recovery",
        "checkpoint",
        tmp_path,
    )

    assert result.name == "sqlite-checkpoint-recovery"
    assert result.required is True
    assert result.status is CheckStatus.FAIL
    assert expected_keys.issubset(result.details)
    assert "stderr" not in result.details
    assert "stdout" not in result.details


class _InterruptingProcess:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.returncode: int | None = None
        self.events: list[str] = []

    async def communicate(self) -> NoReturn:
        raise self.error

    def terminate(self) -> None:
        self.events.append("terminate")

    async def wait(self) -> int:
        self.events.append("wait")
        self.returncode = -15
        return self.returncode

    def kill(self) -> None:
        self.events.append("kill")


class _KillRequiredProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.events: list[str] = []
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(10)
        return b"", b""

    def terminate(self) -> None:
        self.events.append("terminate")

    async def wait(self) -> int:
        self.events.append("wait")
        if not self.killed:
            await asyncio.sleep(10)
        self.returncode = -9
        return self.returncode

    def kill(self) -> None:
        self.events.append("kill")
        self.killed = True


class _UnstoppableProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(10)
        return b"", b""

    def terminate(self) -> None:
        self.terminate_calls += 1
        raise RuntimeError("terminate failed")

    async def wait(self) -> int:
        self.wait_calls += 1
        await asyncio.sleep(10)
        return 0

    def kill(self) -> None:
        self.kill_calls += 1
        raise RuntimeError("kill failed")


async def test_probe_timeout_escalates_from_terminate_to_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _KillRequiredProcess()

    async def create_process(*args: object, **kwargs: object) -> _KillRequiredProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    result = await runner._run_probe_process(
        "ladybug-transaction-persistence",
        "ladybug",
        tmp_path,
        timeout_seconds=0.05,
    )

    assert result.status is CheckStatus.FAIL
    assert result.details["terminated"] is True
    assert process.events == ["terminate", "wait", "kill", "wait"]


async def test_probe_timeout_reports_unrecoverable_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _UnstoppableProcess()

    async def create_process(*args: object, **kwargs: object) -> _UnstoppableProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    started_at = monotonic()

    result = await runner._run_probe_process(
        "ladybug-transaction-persistence",
        "ladybug",
        tmp_path,
        timeout_seconds=0.01,
    )

    assert result.status is CheckStatus.FAIL
    assert result.details["terminated"] is False
    cleanup_errors = result.details["cleanup_errors"]
    assert isinstance(cleanup_errors, list)
    assert {error["action"] for error in cleanup_errors} == {
        "terminate",
        "wait-after-terminate",
        "kill",
        "wait-after-kill",
    }
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == 2
    assert monotonic() - started_at < 1.5


class _ParentInterrupt(BaseException):
    pass


async def test_probe_parent_interrupt_terminates_child_and_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interrupt = _ParentInterrupt("parent interrupted")
    process = _InterruptingProcess(interrupt)

    async def create_process(*args: object, **kwargs: object) -> _InterruptingProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    with pytest.raises(type(interrupt), match=str(interrupt)):
        await runner._run_probe_process(
            "ladybug-transaction-persistence",
            "ladybug",
            tmp_path,
        )

    assert process.events == ["terminate", "wait"]


async def test_probe_task_cancellation_terminates_child_without_late_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "cancelled-marker"
    script = (
        "import pathlib,sys,time; "
        "time.sleep(0.5); "
        "pathlib.Path(sys.argv[1]).write_text('late', encoding='utf-8')"
    )

    def slow_command(probe_name: str, root: Path) -> list[str]:
        return [sys.executable, "-c", script, str(marker)]

    monkeypatch.setattr(runner, "_probe_command", slow_command, raising=False)
    task = asyncio.create_task(
        runner._run_probe_process("sqlite-checkpoint-recovery", "checkpoint", tmp_path)
    )
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.6)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("error_type", "expected_exception"),
    [
        ("KeyboardInterrupt", KeyboardInterrupt),
        ("SystemExit", SystemExit),
        ("GeneratorExit", GeneratorExit),
    ],
)
async def test_worker_base_exception_envelope_is_rethrown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    expected_exception: type[BaseException],
) -> None:
    payload: dict[str, object] = {
        "kind": "base_exception",
        "error_type": error_type,
        "error": "worker stopped",
    }
    if error_type == "SystemExit":
        payload["code"] = "worker stopped"
    envelope = json.dumps(payload)

    def command(probe_name: str, root: Path) -> list[str]:
        return [sys.executable, "-c", f"print({envelope!r})"]

    monkeypatch.setattr(runner, "_probe_command", command, raising=False)

    with pytest.raises(expected_exception, match="worker stopped"):
        await runner._run_probe_process(
            "ladybug-transaction-persistence",
            "ladybug",
            tmp_path,
        )


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (KeyboardInterrupt("worker interrupted"), "KeyboardInterrupt"),
        (SystemExit("worker exited"), "SystemExit"),
        (GeneratorExit("worker closed"), "GeneratorExit"),
    ],
)
def test_probe_worker_emits_controlled_base_exception_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    error_type: str,
) -> None:
    import noa.compat.probe_worker as probe_worker

    def interrupted_probe(path: Path) -> NoReturn:
        raise error

    monkeypatch.setitem(probe_worker._PROBES, "ladybug", interrupted_probe)

    assert probe_worker.run(["ladybug", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    expected_envelope: dict[str, object] = {
        "kind": "base_exception",
        "error_type": error_type,
        "error": str(error),
    }
    if isinstance(error, SystemExit):
        expected_envelope["code"] = error.code
    assert envelope == expected_envelope
    assert captured.err == ""


async def test_worker_system_exit_preserves_integer_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = json.dumps(
        {
            "kind": "base_exception",
            "error_type": "SystemExit",
            "error": "3",
            "code": 3,
        }
    )

    def command(probe_name: str, root: Path) -> list[str]:
        return [sys.executable, "-c", f"print({envelope!r})"]

    monkeypatch.setattr(runner, "_probe_command", command, raising=False)

    with pytest.raises(SystemExit) as captured:
        await runner._run_probe_process(
            "ladybug-transaction-persistence",
            "ladybug",
            tmp_path,
        )
    assert captured.value.code == 3


async def test_workspace_initialization_error_still_returns_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "unavailable"
    original_mkdir = Path.mkdir

    def failing_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == workspace:
            raise RuntimeError("workspace unavailable")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    async def sampling_check(mode: str) -> CheckResult:
        name = "sampling-modern" if mode == "auto" else "sampling-legacy"
        return CheckResult(name=name, status=CheckStatus.PASS)

    async def app_check() -> CheckResult:
        return CheckResult(name="mcp-app-resource", status=CheckStatus.PASS)

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)
    monkeypatch.setattr(runner, "build_runtime_checks", lambda: [])
    monkeypatch.setattr(runner, "_sampling_check", sampling_check)
    monkeypatch.setattr(runner, "_app_check", app_check)

    report = await runner.run_compatibility_gate(workspace)

    checks = {check.name: check for check in report.checks}
    assert checks["workspace-initialization"].status is CheckStatus.FAIL
    assert checks["workspace-initialization"].details["error_type"] == "RuntimeError"
    assert checks["workspace-initialization"].details["error"] == "workspace unavailable"
    assert checks["ladybug-transaction-persistence"].status is CheckStatus.BLOCKED
    assert checks["sqlite-checkpoint-recovery"].status is CheckStatus.BLOCKED
    assert checks["sampling-modern"].status is CheckStatus.PASS
    assert checks["sampling-legacy"].status is CheckStatus.PASS
    assert checks["mcp-app-resource"].status is CheckStatus.PASS
    assert checks["vs-code-stable"].status is CheckStatus.BLOCKED
    assert report.decision is GateDecision.NO_GO


async def test_workspace_initialization_propagates_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "interrupted"

    def interrupted_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> NoReturn:
        raise KeyboardInterrupt("workspace interrupted")

    monkeypatch.setattr(Path, "mkdir", interrupted_mkdir)

    with pytest.raises(KeyboardInterrupt, match="workspace interrupted"):
        await runner.run_compatibility_gate(workspace)


async def test_runtime_builder_error_still_returns_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_runtime_checks() -> NoReturn:
        raise RuntimeError("runtime inspection failed")

    async def run_probe(
        name: str,
        probe_name: str,
        root: Path,
        timeout_seconds: float = 15,
    ) -> CheckResult:
        return CheckResult(name=name, status=CheckStatus.PASS)

    async def sampling_check(mode: str) -> CheckResult:
        name = "sampling-modern" if mode == "auto" else "sampling-legacy"
        return CheckResult(name=name, status=CheckStatus.PASS)

    async def app_check() -> CheckResult:
        return CheckResult(name="mcp-app-resource", status=CheckStatus.PASS)

    monkeypatch.setattr(runner, "build_runtime_checks", failing_runtime_checks)
    monkeypatch.setattr(runner, "_run_probe_process", run_probe, raising=False)
    monkeypatch.setattr(runner, "_sampling_check", sampling_check)
    monkeypatch.setattr(runner, "_app_check", app_check)

    report = await runner.run_compatibility_gate(tmp_path / "workspace")

    checks = {check.name: check for check in report.checks}
    assert checks["runtime-environment"].required is True
    assert checks["runtime-environment"].status is CheckStatus.FAIL
    assert checks["runtime-environment"].details == {
        "error_type": "RuntimeError",
        "error": "runtime inspection failed",
    }
    assert checks["ladybug-transaction-persistence"].status is CheckStatus.PASS
    assert checks["sqlite-checkpoint-recovery"].status is CheckStatus.PASS
    assert checks["sampling-modern"].status is CheckStatus.PASS
    assert checks["sampling-legacy"].status is CheckStatus.PASS
    assert checks["mcp-app-resource"].status is CheckStatus.PASS
    assert checks["vs-code-stable"].status is CheckStatus.BLOCKED
    assert report.decision is GateDecision.NO_GO


async def test_runtime_builder_propagates_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupted_runtime_checks() -> NoReturn:
        raise SystemExit("runtime inspection interrupted")

    monkeypatch.setattr(runner, "build_runtime_checks", interrupted_runtime_checks)

    with pytest.raises(SystemExit, match="runtime inspection interrupted"):
        await runner.run_compatibility_gate(tmp_path / "workspace")


class _EnteringFailureClient:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def __aenter__(self) -> NoReturn:
        raise self._error

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


async def test_sampling_probe_normalizes_ordinary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "Client",
        lambda *args, **kwargs: _EnteringFailureClient(RuntimeError("sampling unavailable")),
        raising=False,
    )

    result = await runner._sampling_check("auto")

    assert result.name == "sampling-modern"
    assert result.status is CheckStatus.FAIL
    assert result.details == {
        "mode": "auto",
        "error_type": "RuntimeError",
        "error": "sampling unavailable",
    }


async def test_sampling_probe_propagates_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "Client",
        lambda *args, **kwargs: _EnteringFailureClient(KeyboardInterrupt("sampling interrupted")),
        raising=False,
    )

    with pytest.raises(KeyboardInterrupt, match="sampling interrupted"):
        await runner._sampling_check("legacy")


def test_cli_parse_args_supports_defaults_and_injected_custom_paths(tmp_path: Path) -> None:
    from noa.compat.cli import parse_args

    defaults = parse_args([])
    assert defaults.workspace == Path(".noa/compatibility/workspace")
    assert defaults.host_evidence_root == Path(".")
    assert defaults.json == Path(".noa/compatibility/compatibility.json")
    assert defaults.markdown == Path("docs/compatibility/2026-08-21-slice-0.md")

    custom = parse_args(
        [
            "--workspace",
            str(tmp_path / "workspace"),
            "--host-evidence-root",
            str(tmp_path / "evidence"),
            "--json",
            str(tmp_path / "custom.json"),
            "--markdown",
            str(tmp_path / "custom.md"),
        ]
    )
    assert custom.workspace == tmp_path / "workspace"
    assert custom.host_evidence_root == tmp_path / "evidence"
    assert custom.json == tmp_path / "custom.json"
    assert custom.markdown == tmp_path / "custom.md"


def test_cli_rejects_same_resolved_report_path_as_usage_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from noa.compat.cli import parse_args

    target = tmp_path / "report"

    with pytest.raises(SystemExit) as captured:
        parse_args(
            [
                "--json",
                str(target),
                "--markdown",
                str(target.parent / "." / target.name),
            ]
        )

    assert captured.value.code == 2
    assert "different paths" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("status", "expected_exit_code"),
    [
        (CheckStatus.PASS, 0),
        (CheckStatus.WARN, 0),
        (CheckStatus.BLOCKED, 1),
    ],
)
async def test_cli_returns_decision_exit_code_and_writes_custom_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: CheckStatus,
    expected_exit_code: int,
) -> None:
    import noa.compat.cli as cli

    workspace = tmp_path / "custom-workspace"
    json_path = tmp_path / "custom-report.json"
    markdown_path = tmp_path / "custom-report.md"
    report = _report(CheckResult(name="gate", status=status))
    called_with: list[Path] = []

    async def fake_gate(
        requested_workspace: Path,
        *,
        host_evidence_root: Path | None = None,
    ) -> CompatibilityReport:
        called_with.append(requested_workspace)
        assert host_evidence_root == Path(".")
        return report

    monkeypatch.setattr(cli, "run_compatibility_gate", fake_gate)

    exit_code = await cli._run(
        [
            "--workspace",
            str(workspace),
            "--json",
            str(json_path),
            "--markdown",
            str(markdown_path),
        ]
    )

    assert exit_code == expected_exit_code
    assert called_with == [workspace]
    assert CompatibilityReport.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert "# NoA Slice 0 Compatibility Report" in markdown_path.read_text(encoding="utf-8")
    printed = CompatibilityReport.model_validate_json(capsys.readouterr().out)
    assert printed.decision is report.decision


async def test_cli_real_integration_writes_reports_and_returns_no_go(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import noa.compat.cli as cli

    workspace = tmp_path / "workspace"
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"

    exit_code = await cli._run(
        [
            "--workspace",
            str(workspace),
            "--host-evidence-root",
            str(tmp_path / "missing-evidence"),
            "--json",
            str(json_path),
            "--markdown",
            str(markdown_path),
        ]
    )

    report = CompatibilityReport.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert report.decision is GateDecision.NO_GO
    assert {check.name: check.status for check in report.checks}["vs-code-stable"] is (
        CheckStatus.BLOCKED
    )
    assert "# NoA Slice 0 Compatibility Report" in markdown_path.read_text(encoding="utf-8")
    printed = CompatibilityReport.model_validate_json(capsys.readouterr().out)
    assert printed.decision is GateDecision.NO_GO


def test_pyproject_registers_noa_compat_console_script() -> None:
    with Path("pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)

    assert pyproject["project"]["scripts"]["noa-compat"] == "noa.compat.cli:main"
