from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import struct
import sys
import tempfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Literal, NoReturn, cast
from uuid import uuid4

import anyio
from fastmcp import Client
from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams

from noa.compat.app_validation import (
    validate_compatibility_app_csp,
    validate_compatibility_app_html,
)
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport
from noa.compat.runtime import build_runtime_checks
from noa.server import COMPATIBILITY_APP_URI, mcp

SamplingMode = Literal["auto", "legacy"]
ProbeName = Literal["ladybug", "checkpoint"]
SamplingRequestContext = RequestContext[object, object]
_PROCESS_STOP_TIMEOUT_SECONDS = 0.5
_HOST_EVIDENCE_MAX_AGE = timedelta(days=30)
_SEMANTIC_REVIEW_FUTURE_TOLERANCE = timedelta(minutes=5)
_MIN_VISUAL_ARTIFACT_WIDTH = 1280
_MIN_VISUAL_ARTIFACT_HEIGHT = 720
MAX_PNG_FILE_BYTES = 16 * 1024 * 1024
MAX_PNG_PIXELS = 16_000_000
MAX_PNG_DECODED_BYTES = 128 * 1024 * 1024
_PNG_DECOMPRESS_CHUNK_BYTES = 64 * 1024
_NOTE_MANIFEST_START = "<!-- noa-host-evidence-manifest:start -->\n```json\n"
_NOTE_MANIFEST_END = "\n```\n<!-- noa-host-evidence-manifest:end -->"
_NOTE_PROSE_PREFIX = """# Slice 0 MCP App Visual Evidence

## Observed Result

- Ping, modern Sampling request/response visibility, and inline MCP App rendering passed.
- The validator manifest below is the only machine-verifiable metadata source in this note.

## Validator Manifest

"""
_NOTE_PROSE_SUFFIX = "\n"
_VISUAL_ARTIFACT_PATHS = {
    "app": ".agent/visual/slice-0-app.png",
    "sampling": ".agent/visual/slice-0-sampling.png",
}
_VISUAL_SEMANTIC_KINDS = {
    "app": "inline_mcp_app",
    "sampling": "sampling_request_response",
}
_VISUAL_OBSERVED_RESULTS = {
    "app": (
        "Inline NoA Compatibility App heading, card, and ui://noa/compatibility.html URI "
        "are visible."
    ),
    "sampling": "Sampling request and response are visible.",
}


def _probe_command(probe_name: ProbeName, path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "noa.compat.probe_worker",
        probe_name,
        str(path),
    ]


def _probe_failure(
    name: str,
    summary: str,
    details: dict[str, object],
) -> CheckResult:
    return CheckResult(
        name=name,
        status=CheckStatus.FAIL,
        required=True,
        summary=summary,
        details=details,
    )


def _cleanup_error(action: str, exc: BaseException) -> dict[str, str]:
    return {
        "action": action,
        "error_type": type(exc).__name__,
        "error": str(exc),
    }


async def _wait_for_process(
    process: asyncio.subprocess.Process,
    *,
    action: str,
    cleanup_errors: list[dict[str, str]],
) -> bool:
    try:
        await asyncio.wait_for(process.wait(), timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
    except TimeoutError:
        cleanup_errors.append(
            {
                "action": action,
                "error_type": "TimeoutError",
                "error": f"process did not exit within {_PROCESS_STOP_TIMEOUT_SECONDS} seconds",
            }
        )
        return False
    except BaseException as exc:
        cleanup_errors.append(_cleanup_error(action, exc))
        return False
    return True


async def _stop_process(process: asyncio.subprocess.Process) -> dict[str, object]:
    cleanup_errors: list[dict[str, str]] = []
    if process.returncode is None:
        try:
            process.terminate()
        except BaseException as exc:
            cleanup_errors.append(_cleanup_error("terminate", exc))
        if process.returncode is None and not await _wait_for_process(
            process,
            action="wait-after-terminate",
            cleanup_errors=cleanup_errors,
        ):
            try:
                process.kill()
            except BaseException as exc:
                cleanup_errors.append(_cleanup_error("kill", exc))
            if process.returncode is None:
                await _wait_for_process(
                    process,
                    action="wait-after-kill",
                    cleanup_errors=cleanup_errors,
                )
    return {
        "terminated": process.returncode is not None,
        "cleanup_errors": cleanup_errors,
    }


def _stderr_diagnostics(stderr: bytes) -> dict[str, object]:
    if not stderr:
        return {}
    return {
        "stderr_bytes": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    }


def _raise_worker_base_exception(
    error_type: str,
    message: str,
    system_exit_code: object = None,
) -> NoReturn:
    if error_type == "KeyboardInterrupt":
        raise KeyboardInterrupt(message)
    if error_type == "SystemExit":
        if system_exit_code is not None and not isinstance(system_exit_code, int | str):
            raise RuntimeError("Worker returned an invalid SystemExit code")
        raise SystemExit(system_exit_code)
    if error_type == "GeneratorExit":
        raise GeneratorExit(message)
    raise RuntimeError(f"Unsupported worker BaseException type: {error_type}")


async def _run_probe_process(
    name: str,
    probe_name: ProbeName,
    path: Path,
    timeout_seconds: float = 15,
) -> CheckResult:
    try:
        process = await asyncio.create_subprocess_exec(
            *_probe_command(probe_name, path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        return _probe_failure(
            name,
            f"{name} worker failed to start.",
            {"error_type": type(exc).__name__, "error": str(exc)},
        )

    cleanup_attempted = False
    try:
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            cleanup_attempted = True
            with anyio.CancelScope(shield=True):
                cleanup = await _stop_process(process)
            return _probe_failure(
                name,
                f"{name} worker timed out.",
                {"timeout_seconds": timeout_seconds, **cleanup},
            )
        except Exception as exc:
            cleanup_attempted = True
            with anyio.CancelScope(shield=True):
                cleanup = await _stop_process(process)
            return _probe_failure(
                name,
                f"{name} worker failed.",
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    **cleanup,
                },
            )
        except BaseException:
            cleanup_attempted = True
            with anyio.CancelScope(shield=True):
                await _stop_process(process)
            raise

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_details = _stderr_diagnostics(stderr)
        if process.returncode != 0 or stderr:
            return _probe_failure(
                name,
                f"{name} worker process failed.",
                {"returncode": process.returncode, **stderr_details},
            )

        try:
            envelope = json.loads(stdout_text)
            kind = envelope["kind"]
        except Exception as exc:
            return _probe_failure(
                name,
                f"{name} worker returned an invalid envelope.",
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                    "stdout_bytes": len(stdout),
                },
            )

        if kind == "base_exception":
            _raise_worker_base_exception(
                cast(str, envelope.get("error_type", "")),
                cast(str, envelope.get("error", "")),
                envelope.get("code"),
            )
        if kind == "exception":
            return _probe_failure(
                name,
                f"{name} worker raised an exception.",
                {
                    "error_type": cast(str, envelope.get("error_type", "Exception")),
                    "error": cast(str, envelope.get("error", "")),
                },
            )
        if kind != "result":
            return _probe_failure(
                name,
                f"{name} worker returned an unknown envelope kind.",
                {"kind": kind},
            )
        try:
            result = CheckResult.model_validate(envelope["result"])
        except Exception as exc:
            return _probe_failure(
                name,
                f"{name} worker returned an invalid result.",
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
        if result.name != name:
            return _probe_failure(
                name,
                f"{name} worker returned the wrong check name.",
                {"expected_name": name, "actual_name": result.name},
            )
        return result
    finally:
        if not cleanup_attempted and process.returncode is None:
            with anyio.CancelScope(shield=True):
                await _stop_process(process)


async def _sampling_handler(
    messages: list[SamplingMessage],
    params: SamplingParams,
    context: SamplingRequestContext,
) -> str:
    return '{"answer":"compatible"}'


async def _sampling_check(mode: SamplingMode) -> CheckResult:
    name = "sampling-modern" if mode == "auto" else "sampling-legacy"
    try:
        with anyio.fail_after(15):
            async with Client(
                mcp,
                mode=mode,
                sampling_handler=_sampling_handler,
                init_timeout=5,
                timeout=5,
            ) as client:
                protocol_version = client.protocol_version
                result = await client.call_tool("sampling_compatibility", {"question": name})
        data = result.data
        passed = result.is_error is False and data == {
            "status": "pass",
            "answer": "compatible",
        }
        return CheckResult(
            name=name,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            summary=f"Sampling probe completed in {mode} mode.",
            details={
                "mode": mode,
                "protocol_version": protocol_version,
                "result": data,
            },
        )
    except Exception as exc:
        return CheckResult(
            name=name,
            status=CheckStatus.FAIL,
            summary=f"Sampling probe failed in {mode} mode.",
            details={
                "mode": mode,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


async def _app_check() -> CheckResult:
    try:
        with anyio.fail_after(15):
            async with Client(mcp) as client:
                contents = await client.read_resource(COMPATIBILITY_APP_URI)
                resources = await client.list_resources()
        if len(contents) != 1:
            raise ValueError("MCP App must return exactly one resource content")
        matching_resources = [
            resource for resource in resources if str(resource.uri) == COMPATIBILITY_APP_URI
        ]
        if len(matching_resources) != 1:
            raise ValueError("MCP App must have exactly one listed resource for the exact URI")

        content = contents[0]
        listed_resource = matching_resources[0]
        content_metadata = cast(dict[str, object], content.meta)
        resource_metadata = cast(dict[str, object], listed_resource.meta)
        csp_validation = validate_compatibility_app_csp(content_metadata, resource_metadata)
        text = content.text or ""
        html_validation = validate_compatibility_app_html(
            text,
            expected_heading="NoA Compatibility",
            expected_resource_uri=COMPATIBILITY_APP_URI,
        )
        passed = content.mime_type == "text/html;profile=mcp-app" and content.text is not None
        return CheckResult(
            name="mcp-app-resource",
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            summary="Bundled MCP App resource and deny-by-default CSP probe completed.",
            details={
                "uri": COMPATIBILITY_APP_URI,
                "content_count": len(contents),
                "listed_resource_count": len(resources),
                "exact_uri_resource_count": len(matching_resources),
                "mime_type": content.mime_type,
                "csp": csp_validation.domains,
                "csp_metadata_consistent": csp_validation.metadata_consistent,
                "html_validation": {
                    "heading_visible": html_validation.heading_visible,
                    "resource_uri_visible": html_validation.resource_uri_visible,
                },
            },
        )
    except Exception as exc:
        return CheckResult(
            name="mcp-app-resource",
            status=CheckStatus.FAIL,
            summary="MCP App resource probe failed.",
            details={
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def _decode_png(image: bytes) -> tuple[int, int]:
    if len(image) > MAX_PNG_FILE_BYTES:
        raise ValueError("PNG file exceeds size limit")
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("artifact is not a PNG")
    offset = 8
    chunk_index = 0
    width = height = bit_depth = color_type = None
    compression_method = filter_method = interlace = None
    idat = bytearray()
    saw_idat = False
    idat_ended = False
    saw_plte = False
    plte_entries = 0
    saw_iend = False
    while offset < len(image):
        if offset + 12 > len(image):
            raise ValueError("truncated PNG chunk")
        length = struct.unpack(">I", image[offset : offset + 4])[0]
        chunk_type = image[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(image):
            raise ValueError("truncated PNG payload")
        payload = image[data_start:data_end]
        expected_crc = struct.unpack(">I", image[data_end:crc_end])[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("invalid PNG chunk CRC")
        if any(
            character not in range(ord("A"), ord("Z") + 1)
            and character not in range(ord("a"), ord("z") + 1)
            for character in chunk_type
        ):
            raise ValueError("invalid PNG chunk type")
        if chunk_type[2] not in range(ord("A"), ord("Z") + 1):
            raise ValueError("invalid PNG chunk reserved bit")
        if chunk_index == 0 and chunk_type != b"IHDR":
            raise ValueError("IHDR must be the first PNG chunk")
        if chunk_type == b"IHDR":
            if chunk_index != 0 or length != 13 or width is not None:
                raise ValueError("invalid PNG IHDR")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression_method,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
        elif chunk_type == b"PLTE":
            if width is None or saw_plte or saw_idat:
                raise ValueError("invalid PNG PLTE order")
            if length < 3 or length > 768 or length % 3 != 0:
                raise ValueError("invalid PNG PLTE length")
            if color_type in {0, 4}:
                raise ValueError("PNG PLTE is forbidden for color type")
            saw_plte = True
            plte_entries = length // 3
            if color_type == 3 and bit_depth is not None and plte_entries > 2**bit_depth:
                raise ValueError("indexed PNG PLTE has too many entries")
        elif chunk_type == b"IDAT":
            if width is None:
                raise ValueError("PNG IDAT appeared before IHDR")
            if idat_ended:
                raise ValueError("PNG IDAT chunks must be consecutive")
            saw_idat = True
            idat.extend(payload)
        elif chunk_type == b"IEND":
            if length != 0 or width is None or not saw_idat:
                raise ValueError("invalid PNG IEND")
            saw_iend = True
            offset = crc_end
            break
        else:
            if chunk_type[0] & 0x20 == 0:
                raise ValueError("unsupported critical PNG chunk")
            if saw_idat:
                idat_ended = True
        offset = crc_end
        chunk_index += 1
    if offset != len(image) or not saw_iend or width is None or height is None or not idat:
        raise ValueError("incomplete PNG structure")
    if color_type == 3 and not saw_plte:
        raise ValueError("indexed PNG requires PLTE")
    if (
        width <= 0
        or height <= 0
        or bit_depth != 8
        or color_type not in {2, 6}
        or compression_method != 0
        or filter_method != 0
        or interlace != 0
    ):
        raise ValueError("unsupported PNG encoding")
    if height > MAX_PNG_PIXELS // width:
        raise ValueError("PNG pixel count exceeds limit")
    channels = 3 if color_type == 2 else 4
    if width > (MAX_PNG_DECODED_BYTES - 1) // channels:
        raise ValueError("PNG decoded data exceeds limit")
    row_size = 1 + width * channels
    if height > MAX_PNG_DECODED_BYTES // row_size:
        raise ValueError("PNG decoded data exceeds limit")
    expected_size = height * row_size
    output_limit = expected_size + 1
    decompressor = zlib.decompressobj()
    decoded = bytearray()
    compressed = memoryview(idat)
    for start in range(0, len(compressed), _PNG_DECOMPRESS_CHUNK_BYTES):
        chunk = compressed[start : start + _PNG_DECOMPRESS_CHUNK_BYTES]
        remaining_output = output_limit - len(decoded)
        if remaining_output <= 0:
            raise ValueError("PNG decompressed data exceeds expected size")
        decoded.extend(decompressor.decompress(chunk, remaining_output))
        if len(decoded) > expected_size or decompressor.unconsumed_tail:
            raise ValueError("PNG decompressed data exceeds expected size")
        if decompressor.eof:
            if decompressor.unused_data or start + len(chunk) < len(compressed):
                raise ValueError("PNG zlib stream has trailing data")
            break
    remaining_output = output_limit - len(decoded)
    decoded.extend(decompressor.flush(remaining_output))
    if len(decoded) > expected_size:
        raise ValueError("PNG decompressed data exceeds expected size")
    if not decompressor.eof:
        raise ValueError("incomplete PNG zlib stream")
    if decompressor.unused_data:
        raise ValueError("PNG zlib stream has trailing data")
    if decompressor.unconsumed_tail:
        raise ValueError("PNG zlib stream has unconsumed data")
    if len(decoded) != expected_size:
        raise ValueError("invalid PNG image data")
    if any(decoded[row_index * row_size] > 4 for row_index in range(height)):
        raise ValueError("invalid PNG scanline filter")
    return width, height


def _safe_evidence_path(evidence_root: Path, relative_path: str) -> Path:
    root = evidence_root.absolute()
    if root.is_symlink():
        raise ValueError("unsafe evidence root uses a symlink")
    resolved_root = root.resolve(strict=False)
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe evidence path escapes evidence root: {relative_path}")
    candidate = resolved_root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(f"unsafe evidence path uses symlink: {relative_path}")
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"unsafe evidence path escapes evidence root: {relative_path}") from exc
    return candidate


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _load_strict_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)


def _load_strict_json_file(path: Path) -> object:
    return _load_strict_json(path.read_text(encoding="utf-8"))


def _require_exact_object(
    value: object,
    *,
    label: str,
    keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    payload = cast(dict[str, object], value)
    if set(payload) != keys:
        raise ValueError(f"{label} must contain exactly {sorted(keys)}")
    return payload


def _require_nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    digest = _require_nonempty_string(value, label=label)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _parse_pixel_dimensions(value: object, *, label: str) -> tuple[int, int]:
    dimensions = _require_exact_object(
        value,
        label=label,
        keys={"width", "height"},
    )
    return (
        _require_positive_int(dimensions["width"], label=f"{label}.width"),
        _require_positive_int(dimensions["height"], label=f"{label}.height"),
    )


def _parse_timestamp(value: object, *, label: str) -> datetime:
    timestamp_text = _require_nonempty_string(value, label=label)
    timestamp = datetime.fromisoformat(timestamp_text)
    if timestamp.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return timestamp.astimezone(UTC)


def _parse_captured_at(value: object) -> datetime:
    return _parse_timestamp(value, label="visual.captured_at")


def _visual_artifact_audit(
    evidence_root: Path,
    *,
    name: str,
    value: object,
    logical_width: int,
    logical_height: int,
    captured_at: datetime,
    validation_now: datetime,
) -> tuple[dict[str, object], bool, str | None]:
    artifact = _require_exact_object(
        value,
        label=f"visual.{name}",
        keys={
            "artifact",
            "pixel_dimensions",
            "sha256",
            "bytes",
            "semantic_kind",
            "semantic_review",
        },
    )
    expected_relative_path = _VISUAL_ARTIFACT_PATHS[name]
    relative_path = _require_nonempty_string(
        artifact["artifact"],
        label=f"visual.{name}.artifact",
    )
    if relative_path != expected_relative_path:
        raise ValueError(f"visual.{name}.artifact must be {expected_relative_path}")
    claimed_width, claimed_height = _parse_pixel_dimensions(
        artifact["pixel_dimensions"],
        label=f"visual.{name}.pixel_dimensions",
    )
    claimed_sha256 = _require_sha256(
        artifact["sha256"],
        label=f"visual.{name}.sha256",
    )
    claimed_bytes = _require_positive_int(
        artifact["bytes"],
        label=f"visual.{name}.bytes",
    )
    semantic_kind = _require_nonempty_string(
        artifact["semantic_kind"],
        label=f"visual.{name}.semantic_kind",
    )
    semantic_review = _require_exact_object(
        artifact["semantic_review"],
        label=f"visual.{name}.semantic_review",
        keys={"reviewer_type", "reviewed_at", "artifact_sha256", "observed_result"},
    )
    reviewer_type = _require_nonempty_string(
        semantic_review["reviewer_type"],
        label=f"visual.{name}.semantic_review.reviewer_type",
    )
    reviewed_at_text = _require_nonempty_string(
        semantic_review["reviewed_at"],
        label=f"visual.{name}.semantic_review.reviewed_at",
    )
    reviewed_at = _parse_timestamp(
        reviewed_at_text,
        label=f"visual.{name}.semantic_review.reviewed_at",
    )
    reviewed_sha256 = _require_sha256(
        semantic_review["artifact_sha256"],
        label=f"visual.{name}.semantic_review.artifact_sha256",
    )
    observed_result = _require_nonempty_string(
        semantic_review["observed_result"],
        label=f"visual.{name}.semantic_review.observed_result",
    )

    image_path = _safe_evidence_path(evidence_root, relative_path)
    image_size = image_path.stat().st_size
    if image_size > MAX_PNG_FILE_BYTES:
        raise ValueError(
            f"visual artifact exceeds maximum file size of {MAX_PNG_FILE_BYTES} bytes: {image_path}"
        )
    image = image_path.read_bytes()
    if len(image) > MAX_PNG_FILE_BYTES:
        raise ValueError(
            f"visual artifact exceeds maximum file size of {MAX_PNG_FILE_BYTES} bytes: {image_path}"
        )
    actual_sha256 = hashlib.sha256(image).hexdigest()
    actual_dimensions: dict[str, int] | None
    validation_error: str | None = None
    try:
        actual_width, actual_height = _decode_png(image)
        actual_dimensions = {"width": actual_width, "height": actual_height}
    except (ValueError, zlib.error) as exc:
        actual_width = actual_height = 0
        actual_dimensions = None
        validation_error = f"{name} visual artifact is invalid: {exc}"

    claimed_dimensions = {"width": claimed_width, "height": claimed_height}
    bytes_match = claimed_bytes == len(image)
    sha256_match = claimed_sha256 == actual_sha256
    dimensions_match = actual_dimensions == claimed_dimensions
    meets_logical_viewport = (
        actual_dimensions is not None
        and actual_width >= logical_width
        and actual_height >= logical_height
    )
    meets_minimum_dimensions = (
        actual_dimensions is not None
        and actual_width >= _MIN_VISUAL_ARTIFACT_WIDTH
        and actual_height >= _MIN_VISUAL_ARTIFACT_HEIGHT
    )
    aspect_ratio_matches = (
        actual_dimensions is not None
        and abs((actual_width / actual_height) - (logical_width / logical_height)) < 0.1
    )
    semantic_kind_matches = semantic_kind == _VISUAL_SEMANTIC_KINDS[name]
    semantic_review_reviewer_matches = reviewer_type == "independent_agent"
    semantic_review_sha256_matches_claim = reviewed_sha256 == claimed_sha256
    semantic_review_sha256_matches_actual = reviewed_sha256 == actual_sha256
    semantic_review_observed_result_matches = observed_result == _VISUAL_OBSERVED_RESULTS[name]
    semantic_review_not_before_capture = reviewed_at >= captured_at
    semantic_review_not_too_far_future = (
        reviewed_at <= validation_now + _SEMANTIC_REVIEW_FUTURE_TOLERANCE
    )
    image_mtime = datetime.fromtimestamp(image_path.stat().st_mtime, UTC)
    audit: dict[str, object] = {
        "artifact": relative_path,
        "path": str(image_path),
        "claimed": {
            "bytes": claimed_bytes,
            "sha256": claimed_sha256,
            "pixel_dimensions": claimed_dimensions,
        },
        "actual": {
            "bytes": len(image),
            "sha256": actual_sha256,
            "pixel_dimensions": actual_dimensions,
        },
        "bytes_match": bytes_match,
        "sha256_match": sha256_match,
        "dimensions_match": dimensions_match,
        "meets_logical_viewport": meets_logical_viewport,
        "meets_minimum_dimensions": meets_minimum_dimensions,
        "minimum_dimensions": {
            "width": _MIN_VISUAL_ARTIFACT_WIDTH,
            "height": _MIN_VISUAL_ARTIFACT_HEIGHT,
        },
        "aspect_ratio_matches": aspect_ratio_matches,
        "semantic_kind": semantic_kind,
        "expected_semantic_kind": _VISUAL_SEMANTIC_KINDS[name],
        "semantic_kind_matches": semantic_kind_matches,
        "semantic_review": {
            "reviewer_type": reviewer_type,
            "reviewed_at": reviewed_at_text,
            "artifact_sha256": reviewed_sha256,
            "observed_result": observed_result,
        },
        "expected_observed_result": _VISUAL_OBSERVED_RESULTS[name],
        "semantic_review_reviewer_matches": semantic_review_reviewer_matches,
        "semantic_review_sha256_matches_claim": semantic_review_sha256_matches_claim,
        "semantic_review_sha256_matches_actual": semantic_review_sha256_matches_actual,
        "semantic_review_observed_result_matches": semantic_review_observed_result_matches,
        "semantic_review_not_before_capture": semantic_review_not_before_capture,
        "semantic_review_not_too_far_future": semantic_review_not_too_far_future,
        "semantic_verification_basis": "independent_review_record_hash_bound",
        "mtime": image_mtime.isoformat(),
    }
    if validation_error is not None:
        audit["validation_error"] = validation_error
    valid = (
        validation_error is None
        and bytes_match
        and sha256_match
        and dimensions_match
        and meets_logical_viewport
        and meets_minimum_dimensions
        and aspect_ratio_matches
        and semantic_kind_matches
        and semantic_review_reviewer_matches
        and semantic_review_sha256_matches_claim
        and semantic_review_sha256_matches_actual
        and semantic_review_observed_result_matches
        and semantic_review_not_before_capture
        and semantic_review_not_too_far_future
    )
    return audit, valid, validation_error


def _parse_note_manifest(note: str) -> dict[str, object]:
    if note.count(_NOTE_MANIFEST_START) != 1 or note.count(_NOTE_MANIFEST_END) != 1:
        raise ValueError("host evidence note must contain exactly one manifest")
    prose_prefix, separator, remainder = note.partition(_NOTE_MANIFEST_START)
    if not separator:
        raise ValueError("host evidence note manifest is missing")
    payload_text, separator, prose_suffix = remainder.partition(_NOTE_MANIFEST_END)
    if not separator:
        raise ValueError("host evidence note manifest is incomplete")
    if prose_prefix != _NOTE_PROSE_PREFIX or prose_suffix != _NOTE_PROSE_SUFFIX:
        raise ValueError(
            "host evidence note must use the canonical prose around its only metadata manifest"
        )
    manifest = _require_exact_object(
        _load_strict_json(payload_text),
        label="host evidence note manifest",
        keys={"host", "captured_at", "logical_viewport", "artifacts"},
    )
    note_host = _require_exact_object(
        manifest["host"],
        label="host evidence note manifest.host",
        keys={"name", "version", "commit", "architecture"},
    )
    for field in ("name", "version", "commit", "architecture"):
        _require_nonempty_string(
            note_host[field],
            label=f"host evidence note manifest.host.{field}",
        )
    _require_nonempty_string(
        manifest["captured_at"],
        label="host evidence note manifest.captured_at",
    )
    _parse_pixel_dimensions(
        manifest["logical_viewport"],
        label="host evidence note manifest.logical_viewport",
    )
    note_artifacts = _require_exact_object(
        manifest["artifacts"],
        label="host evidence note manifest.artifacts",
        keys={"app", "sampling"},
    )
    for name in ("app", "sampling"):
        artifact = _require_exact_object(
            note_artifacts[name],
            label=f"host evidence note manifest.artifacts.{name}",
            keys={
                "path",
                "sha256",
                "bytes",
                "pixel_dimensions",
                "semantic_kind",
                "semantic_review",
            },
        )
        _require_nonempty_string(
            artifact["path"],
            label=f"host evidence note manifest.artifacts.{name}.path",
        )
        _require_sha256(
            artifact["sha256"],
            label=f"host evidence note manifest.artifacts.{name}.sha256",
        )
        _require_positive_int(
            artifact["bytes"],
            label=f"host evidence note manifest.artifacts.{name}.bytes",
        )
        _parse_pixel_dimensions(
            artifact["pixel_dimensions"],
            label=f"host evidence note manifest.artifacts.{name}.pixel_dimensions",
        )
        _require_nonempty_string(
            artifact["semantic_kind"],
            label=f"host evidence note manifest.artifacts.{name}.semantic_kind",
        )
        semantic_review = _require_exact_object(
            artifact["semantic_review"],
            label=f"host evidence note manifest.artifacts.{name}.semantic_review",
            keys={"reviewer_type", "reviewed_at", "artifact_sha256", "observed_result"},
        )
        _require_nonempty_string(
            semantic_review["reviewer_type"],
            label=(f"host evidence note manifest.artifacts.{name}.semantic_review.reviewer_type"),
        )
        _parse_timestamp(
            semantic_review["reviewed_at"],
            label=f"host evidence note manifest.artifacts.{name}.semantic_review.reviewed_at",
        )
        _require_sha256(
            semantic_review["artifact_sha256"],
            label=(f"host evidence note manifest.artifacts.{name}.semantic_review.artifact_sha256"),
        )
        _require_nonempty_string(
            semantic_review["observed_result"],
            label=(f"host evidence note manifest.artifacts.{name}.semantic_review.observed_result"),
        )
    return manifest


def _vs_code_check(evidence_root: Path | None) -> CheckResult:
    if evidence_root is None:
        return CheckResult(
            name="vs-code-stable",
            status=CheckStatus.BLOCKED,
            required=True,
            summary="Waiting for Task 11 VS Code Stable host evidence.",
            details={"scope": "host-evidence", "evidence_status": "pending"},
        )

    try:
        evidence_path = _safe_evidence_path(
            evidence_root,
            ".agent/visual/slice-0-host-evidence.json",
        )
        if not evidence_path.is_file():
            return CheckResult(
                name="vs-code-stable",
                status=CheckStatus.BLOCKED,
                required=True,
                summary="VS Code Stable host evidence has not been provided.",
                details={"missing_path": str(evidence_path), "evidence_status": "pending"},
            )
        note_path = _safe_evidence_path(evidence_root, ".agent/visual/slice-0-app.md")
        config_path = _safe_evidence_path(evidence_root, ".vscode/mcp.json")
        evidence = _require_exact_object(
            _load_strict_json_file(evidence_path),
            label="host evidence",
            keys={"schema_version", "host", "mcp_server", "checks", "visual"},
        )
        if type(evidence["schema_version"]) is not int or evidence["schema_version"] != 2:
            raise ValueError("host evidence schema_version must be 2")
        note = note_path.read_text(encoding="utf-8")
        config = _load_strict_json_file(config_path)

        host = _require_exact_object(
            evidence["host"],
            label="host",
            keys={"name", "version", "commit", "architecture", "code_version_output"},
        )
        version = _require_nonempty_string(host["version"], label="host.version")
        commit = _require_nonempty_string(host["commit"], label="host.commit")
        architecture = _require_nonempty_string(
            host["architecture"],
            label="host.architecture",
        )
        host_valid = host["name"] == "VS Code Stable" and host["code_version_output"] == [
            version,
            commit,
            architecture,
        ]
        mcp_server = _require_exact_object(
            evidence["mcp_server"],
            label="mcp_server",
            keys={"name", "status", "transport", "config_path"},
        )
        mcp_server_valid = mcp_server == {
            "name": "noa",
            "status": "pass",
            "transport": "stdio",
            "config_path": ".vscode/mcp.json",
        }

        checks = _require_exact_object(
            evidence["checks"],
            label="checks",
            keys={"compatibility_ping", "sampling", "mcp_app"},
        )
        ping = _require_exact_object(
            checks["compatibility_ping"],
            label="checks.compatibility_ping",
            keys={"status", "result"},
        )
        sampling = _require_exact_object(
            checks["sampling"],
            label="checks.sampling",
            keys={
                "status",
                "protocol_path",
                "authorization_prompt_observed",
                "authorization_result",
                "request_visible",
                "response_visible",
                "result_status",
            },
        )
        app = _require_exact_object(
            checks["mcp_app"],
            label="checks.mcp_app",
            keys={
                "status",
                "inline_rendered",
                "title_visible",
                "uri_wrapped_inside_card",
                "text_contrast",
            },
        )
        ping_valid = ping == {
            "status": "pass",
            "result": {"status": "pass", "value": "vscode"},
        }
        sampling_valid = sampling == {
            "status": "pass",
            "protocol_path": "2026-07-28",
            "authorization_prompt_observed": False,
            "authorization_result": "sampling_succeeded_without_separate_prompt",
            "request_visible": True,
            "response_visible": True,
            "result_status": "pass",
        }
        app_valid = app == {
            "status": "pass",
            "inline_rendered": True,
            "title_visible": "NoA Compatibility",
            "uri_wrapped_inside_card": True,
            "text_contrast": "body-color-inherited",
        }

        visual = _require_exact_object(
            evidence["visual"],
            label="visual",
            keys={"status", "captured_at", "logical_viewport", "app", "sampling"},
        )
        logical_width, logical_height = _parse_pixel_dimensions(
            visual["logical_viewport"],
            label="visual.logical_viewport",
        )
        logical_viewport = {"width": logical_width, "height": logical_height}
        captured_at = _parse_captured_at(visual["captured_at"])
        validation_now = datetime.now(UTC)
        artifacts: dict[str, object] = {}
        artifacts_valid = True
        artifact_errors: list[str] = []
        for artifact_name in ("app", "sampling"):
            audit, artifact_valid, validation_error = _visual_artifact_audit(
                evidence_root,
                name=artifact_name,
                value=visual[artifact_name],
                logical_width=logical_width,
                logical_height=logical_height,
                captured_at=captured_at,
                validation_now=validation_now,
            )
            artifacts[artifact_name] = audit
            artifacts_valid = artifacts_valid and artifact_valid
            if validation_error is not None:
                artifact_errors.append(validation_error)

        note_mtime = datetime.fromtimestamp(note_path.stat().st_mtime, UTC)
        evidence_age_seconds = (validation_now - captured_at).total_seconds()
        evidence_is_fresh = 0 <= evidence_age_seconds <= _HOST_EVIDENCE_MAX_AGE.total_seconds()
        expected_note_artifacts: dict[str, object] = {}
        for name in ("app", "sampling"):
            artifact_audit = cast(dict[str, object], artifacts[name])
            actual = cast(dict[str, object], artifact_audit["actual"])
            expected_note_artifacts[name] = {
                "path": artifact_audit["artifact"],
                "sha256": actual["sha256"],
                "bytes": actual["bytes"],
                "pixel_dimensions": actual["pixel_dimensions"],
                "semantic_kind": artifact_audit["semantic_kind"],
                "semantic_review": artifact_audit["semantic_review"],
            }
        expected_note_manifest: dict[str, object] = {
            "host": {
                "name": host["name"],
                "version": version,
                "commit": commit,
                "architecture": architecture,
            },
            "captured_at": visual["captured_at"],
            "logical_viewport": logical_viewport,
            "artifacts": expected_note_artifacts,
        }
        note_manifest = _parse_note_manifest(note)
        note_manifest_matches = note_manifest == expected_note_manifest
        expected_config = {
            "inputs": [],
            "servers": {
                "noa": {
                    "type": "stdio",
                    "command": "uv",
                    "args": ["run", "--frozen", "python", "-m", "noa"],
                }
            },
        }
        passed = (
            host_valid
            and mcp_server_valid
            and ping_valid
            and sampling_valid
            and app_valid
            and visual["status"] == "pass"
            and artifacts_valid
            and evidence_is_fresh
            and config == expected_config
            and note_manifest_matches
        )
        details: dict[str, object] = {
            "schema_version": 2,
            "version": version,
            "commit": commit,
            "architecture": architecture,
            "protocol_path": sampling["protocol_path"],
            "authorization_prompt_observed": sampling["authorization_prompt_observed"],
            "authorization_result": sampling["authorization_result"],
            "sampling_request_visible": sampling["request_visible"],
            "sampling_response_visible": sampling["response_visible"],
            "inline_app_rendered": app["inline_rendered"],
            "note_path": str(note_path),
            "evidence_path": str(evidence_path),
            "artifacts": artifacts,
            "captured_at": visual["captured_at"],
            "evidence_age_seconds": evidence_age_seconds,
            "evidence_is_fresh": evidence_is_fresh,
            "note_mtime": note_mtime.isoformat(),
            "note_manifest": note_manifest,
            "expected_note_manifest": expected_note_manifest,
            "note_manifest_matches": note_manifest_matches,
            "logical_viewport": logical_viewport,
            "config_path": str(config_path),
        }
        if artifact_errors:
            details["error"] = "; ".join(artifact_errors)
    except FileNotFoundError as exc:
        return CheckResult(
            name="vs-code-stable",
            status=CheckStatus.FAIL,
            required=True,
            summary="Declared VS Code Stable host evidence is incomplete.",
            details={"missing_path": str(exc.filename), "evidence_status": "invalid"},
        )
    except Exception as exc:
        return CheckResult(
            name="vs-code-stable",
            status=CheckStatus.FAIL,
            required=True,
            summary="VS Code Stable host evidence could not be validated.",
            details={"error_type": type(exc).__name__, "error": str(exc)},
        )

    return CheckResult(
        name="vs-code-stable",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        required=True,
        summary=(
            "VS Code Stable MCP server, Sampling, request history, and inline App passed."
            if passed
            else "VS Code Stable host evidence failed validation."
        ),
        details=details,
    )


async def run_compatibility_gate(
    workspace: Path,
    *,
    host_evidence_root: Path | None = None,
) -> CompatibilityReport:
    ladybug_root = workspace / "ladybug"
    checkpoint_root = workspace / "checkpoint"
    checks: list[CheckResult] = []
    workspace_ready = True
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        ladybug_root.mkdir(parents=True, exist_ok=True)
        checkpoint_root.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        workspace_ready = False
        checks.append(
            CheckResult(
                name="workspace-initialization",
                status=CheckStatus.FAIL,
                required=True,
                summary="Compatibility workspace initialization failed.",
                details={
                    "workspace": str(workspace),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        )

    try:
        checks.extend(build_runtime_checks())
    except Exception as exc:
        checks.append(
            CheckResult(
                name="runtime-environment",
                status=CheckStatus.FAIL,
                required=True,
                summary="Runtime environment inspection failed.",
                details={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        )

    if workspace_ready:
        checks.append(
            await _run_probe_process(
                "ladybug-transaction-persistence",
                "ladybug",
                ladybug_root,
            )
        )
        checks.append(
            await _run_probe_process(
                "sqlite-checkpoint-recovery",
                "checkpoint",
                checkpoint_root,
            )
        )
    else:
        checks.extend(
            [
                CheckResult(
                    name="ladybug-transaction-persistence",
                    status=CheckStatus.BLOCKED,
                    required=True,
                    summary="LadybugDB probe blocked by workspace initialization failure.",
                    details={"blocked_by": "workspace-initialization"},
                ),
                CheckResult(
                    name="sqlite-checkpoint-recovery",
                    status=CheckStatus.BLOCKED,
                    required=True,
                    summary="SQLite checkpoint probe blocked by workspace initialization failure.",
                    details={"blocked_by": "workspace-initialization"},
                ),
            ]
        )

    checks.append(await _sampling_check("auto"))
    checks.append(await _sampling_check("legacy"))
    checks.append(await _app_check())
    checks.append(_vs_code_check(host_evidence_root))
    return CompatibilityReport.from_checks(checks)


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("|", "\\|").replace("\n", "<br>")


def _markdown(payload: dict[str, object]) -> str:
    generation = cast(str, payload["generated_at"])
    decision = cast(str, payload["decision"])
    checks = cast(list[dict[str, object]], payload["checks"])
    host_status = next(
        (cast(str, check["status"]) for check in checks if check["name"] == "vs-code-stable"),
        "not-recorded",
    )
    lines = [
        "# NoA Slice 0 Compatibility Report",
        "",
        "This report combines automated local probes with recorded host evidence.",
        (
            "The machine-readable JSON report is authoritative; "
            "this Markdown file is a checked-in view."
        ),
        f"VS Code Stable host evidence status: `{host_status}`.",
        "",
        f"- Decision: `{decision}`",
        f"- Generated: `{generation}`",
        "",
        "| Check | Status | Required | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for check in checks:
        summary = _escape_markdown_table_cell(cast(str, check["summary"]))
        lines.append(
            f"| `{check['name']}` | `{check['status']}` | "
            f"`{str(check['required']).lower()}` | {summary} |"
        )
    lines.extend(["", "## Details", ""])
    for check in checks:
        details = cast(dict[str, object], check["details"])
        lines.extend(
            [
                f"### {check['name']}",
                "",
                "```json",
                json.dumps(details, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _resolved_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _validate_report_paths(json_path: Path, markdown_path: Path) -> tuple[Path, Path]:
    resolved_json = _resolved_path(json_path)
    resolved_markdown = _resolved_path(markdown_path)
    if resolved_json == resolved_markdown:
        raise ValueError("JSON and Markdown reports must use different paths.")
    return resolved_json, resolved_markdown


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid4().hex}.tmp")


def _write_prepared_temp(path: Path, content: bytes) -> Path:
    temporary_path = _temporary_path(path)
    primary_error: BaseException | None = None
    try:
        with temporary_path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary_path
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if primary_error is not None:
            _cleanup_paths([temporary_path], primary_error)


def _cleanup_paths(paths: list[Path], primary_error: BaseException | None) -> None:
    cleanup_errors: list[BaseException] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except BaseException as exc:
            cleanup_errors.append(exc)
    if not cleanup_errors:
        return
    if primary_error is None:
        first, *remaining = cleanup_errors
        for error in remaining:
            first.add_note(f"Suppressed additional cleanup error: {type(error).__name__}: {error}")
        raise first
    for error in cleanup_errors:
        primary_error.add_note(f"Suppressed cleanup error: {type(error).__name__}: {error}")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    primary_error: BaseException | None = None
    try:
        temporary_path = _write_prepared_temp(path, content)
        temporary_path.replace(path)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if temporary_path is not None:
            _cleanup_paths([temporary_path], primary_error)


def _destination_lock_path(path: Path) -> Path:
    digest = hashlib.sha256(str(path).encode()).hexdigest()
    lock_root = Path(tempfile.gettempdir()) / "noa-compatibility-report-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    return lock_root / f"{digest}.lock"


@contextmanager
def _report_destination_locks(*paths: Path) -> Iterator[None]:
    lock_streams: list[BinaryIO] = []
    ordered_paths = sorted(set(paths), key=str)
    primary_error: BaseException | None = None
    try:
        for path in ordered_paths:
            lock_stream = cast(BinaryIO, _destination_lock_path(path).open("a+b"))
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            except BaseException as exc:
                try:
                    lock_stream.close()
                except BaseException as close_error:
                    exc.add_note(
                        "Suppressed lock stream close error: "
                        f"{type(close_error).__name__}: {close_error}"
                    )
                raise
            lock_streams.append(lock_stream)
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for lock_stream in reversed(lock_streams):
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            except BaseException as exc:
                cleanup_errors.append(exc)
            try:
                lock_stream.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if primary_error is not None:
            for cleanup_error in cleanup_errors:
                primary_error.add_note(
                    "Suppressed report lock cleanup error: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
        elif cleanup_errors:
            first, *remaining = cleanup_errors
            for cleanup_error in remaining:
                first.add_note(
                    "Suppressed additional report lock cleanup error: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
            raise first


def _restore_target(
    path: Path,
    *,
    existed: bool,
    previous_content: bytes | None,
    primary_error: BaseException,
) -> None:
    rollback_temp: Path | None = None
    try:
        if existed:
            if previous_content is None:
                raise RuntimeError(f"Missing rollback content for {path}")
            rollback_temp = _write_prepared_temp(path, previous_content)
            rollback_temp.replace(path)
        else:
            path.unlink(missing_ok=True)
    except BaseException as exc:
        primary_error.add_note(
            f"Suppressed report rollback error for {path}: {type(exc).__name__}: {exc}"
        )
    finally:
        if rollback_temp is not None:
            _cleanup_paths([rollback_temp], primary_error)


def write_report(
    report: CompatibilityReport,
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    resolved_json, resolved_markdown = _validate_report_paths(json_path, markdown_path)
    json_content = report.model_dump_json(indent=2)
    json_payload = cast(dict[str, object], json.loads(json_content))
    markdown_content = _markdown(json_payload)
    json_bytes = json_content.encode("utf-8")
    markdown_bytes = markdown_content.encode("utf-8")

    resolved_json.parent.mkdir(parents=True, exist_ok=True)
    resolved_markdown.parent.mkdir(parents=True, exist_ok=True)

    json_temp: Path | None = None
    markdown_temp: Path | None = None
    primary_error: BaseException | None = None
    try:
        json_temp = _write_prepared_temp(resolved_json, json_bytes)
        markdown_temp = _write_prepared_temp(resolved_markdown, markdown_bytes)
        with _report_destination_locks(resolved_json, resolved_markdown):
            json_existed = resolved_json.exists()
            markdown_existed = resolved_markdown.exists()
            previous_json = resolved_json.read_bytes() if json_existed else None
            previous_markdown = resolved_markdown.read_bytes() if markdown_existed else None
            json_replaced = False
            markdown_replaced = False
            try:
                json_temp.replace(resolved_json)
                json_replaced = True
                markdown_temp.replace(resolved_markdown)
                markdown_replaced = True
            except BaseException as exc:
                primary_error = exc
                if json_replaced:
                    _restore_target(
                        resolved_json,
                        existed=json_existed,
                        previous_content=previous_json,
                        primary_error=exc,
                    )
                if markdown_replaced:
                    _restore_target(
                        resolved_markdown,
                        existed=markdown_existed,
                        previous_content=previous_markdown,
                        primary_error=exc,
                    )
                raise
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        remaining_temps = [path for path in (json_temp, markdown_temp) if path is not None]
        _cleanup_paths(remaining_temps, primary_error)
