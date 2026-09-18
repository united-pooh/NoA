from __future__ import annotations

import warnings
from collections.abc import Awaitable, Callable
from typing import Literal, cast

import anyio
import pytest
from fastmcp import Client
from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams
from fastmcp.exceptions import ToolError
from mcp import MCPDeprecationWarning, MCPError
from mcp.types import (
    CallToolResult,
    CreateMessageRequest,
    CreateMessageResult,
    InputRequiredResult,
    ListRootsResult,
    TextContent,
)

from noa.server import mcp

SamplingMode = Literal["auto", "legacy"]
SamplingRequestContext = RequestContext[object, object]
SamplingHandler = Callable[
    [list[SamplingMessage], SamplingParams, SamplingRequestContext],
    Awaitable[str | CreateMessageResult],
]
SDK_SAMPLING_DEPRECATION = "The sampling capability is deprecated as of 2026-07-28 (SEP-2577)."


def _create_message_result(content: dict[str, object]) -> CreateMessageResult:
    return CreateMessageResult.model_validate(
        {
            "role": "assistant",
            "content": content,
            "model": "compatibility-test",
            "stopReason": "endTurn",
        }
    )


def _valid_handler(
    requests: list[tuple[list[SamplingMessage], SamplingParams]] | None = None,
) -> SamplingHandler:
    async def handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: SamplingRequestContext,
    ) -> str:
        if requests is not None:
            requests.append((messages, params))
        return '{"answer":"compatible"}'

    return handler


async def _call_sampling(
    mode: SamplingMode,
    handler: SamplingHandler,
    question: str = "probe",
    protocol_versions: list[str] | None = None,
) -> dict[str, object]:
    async with Client(
        mcp,
        mode=mode,
        sampling_handler=handler,
        init_timeout=5,
        timeout=5,
    ) as client:
        if protocol_versions is not None:
            protocol_versions.append(client.protocol_version)
        result = await client.call_tool("sampling_compatibility", {"question": question})

    assert result.is_error is False
    return cast(dict[str, object], result.data)


async def test_modern_mrtr_sampling_completes_with_protected_request_state() -> None:
    protocol_versions: list[str] = []

    result = await _call_sampling(
        "auto",
        _valid_handler(),
        protocol_versions=protocol_versions,
    )

    assert result == {"status": "pass", "answer": "compatible"}
    assert protocol_versions == ["2026-07-28"]


async def test_modern_first_call_returns_sampling_input_request() -> None:
    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_valid_handler(),
        init_timeout=5,
        timeout=5,
    ) as client:
        result = await client.session.call_tool(
            "sampling_compatibility",
            {"question": "raw modern request"},
            allow_input_required=True,
        )

    assert isinstance(result, InputRequiredResult)
    assert result.request_state is not None
    assert result.request_state.startswith("v1.")
    assert "noa-sampling-compatibility-v1" not in result.request_state
    assert result.input_requests is not None
    assert set(result.input_requests) == {"answer"}
    request = result.input_requests["answer"]
    assert isinstance(request, CreateMessageRequest)
    assert request.method == "sampling/createMessage"


async def test_modern_input_response_without_protected_state_is_rejected() -> None:
    forged_response = _create_message_result({"type": "text", "text": '{"answer":"injected"}'})

    async with Client(mcp, mode="auto", init_timeout=5, timeout=5) as client:
        result = await client.session.call_tool(
            "sampling_compatibility",
            {"question": "reject unbound response"},
            input_responses={"answer": forged_response},
            allow_input_required=True,
        )

    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    assert result.structured_content != {"status": "pass", "answer": "injected"}


async def test_modern_tampered_request_state_is_rejected() -> None:
    question = "reject tampered state"
    response = _create_message_result({"type": "text", "text": '{"answer":"valid"}'})

    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_valid_handler(),
        init_timeout=5,
        timeout=5,
    ) as client:
        first = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            allow_input_required=True,
        )
        assert isinstance(first, InputRequiredResult)
        assert first.request_state is not None
        index = len(first.request_state) // 2
        replacement = "A" if first.request_state[index] != "A" else "B"
        tampered_state = (
            first.request_state[:index] + replacement + first.request_state[index + 1 :]
        )

        with pytest.raises(MCPError) as captured:
            await client.session.call_tool(
                "sampling_compatibility",
                {"question": question},
                input_responses={"answer": response},
                request_state=tampered_state,
                allow_input_required=True,
            )

    assert captured.value.code == -32602
    assert captured.value.message == "Invalid or expired requestState"
    assert captured.value.data == {"reason": "invalid_request_state"}


async def test_modern_request_state_is_bound_to_original_question() -> None:
    response = _create_message_result({"type": "text", "text": '{"answer":"valid"}'})

    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_valid_handler(),
        init_timeout=5,
        timeout=5,
    ) as client:
        first = await client.session.call_tool(
            "sampling_compatibility",
            {"question": "original question"},
            allow_input_required=True,
        )
        assert isinstance(first, InputRequiredResult)
        assert first.request_state is not None

        with pytest.raises(MCPError) as captured:
            await client.session.call_tool(
                "sampling_compatibility",
                {"question": "different question"},
                input_responses={"answer": response},
                request_state=first.request_state,
                allow_input_required=True,
            )

    assert captured.value.code == -32602
    assert captured.value.message == "Invalid or expired requestState"
    assert captured.value.data == {"reason": "invalid_request_state"}


async def test_modern_state_only_continuation_is_rejected() -> None:
    question = "reject state only"

    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_valid_handler(),
        init_timeout=5,
        timeout=5,
    ) as client:
        first = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            allow_input_required=True,
        )
        assert isinstance(first, InputRequiredResult)
        assert first.request_state is not None

        result = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            request_state=first.request_state,
            allow_input_required=True,
        )

    assert isinstance(result, CallToolResult)
    assert result.is_error is True


async def test_modern_continuation_rejects_wrong_response_type() -> None:
    question = "reject wrong response type"

    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_valid_handler(),
        init_timeout=5,
        timeout=5,
    ) as client:
        first = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            allow_input_required=True,
        )
        assert isinstance(first, InputRequiredResult)
        assert first.request_state is not None

        result = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            input_responses={"answer": ListRootsResult(roots=[])},
            request_state=first.request_state,
            allow_input_required=True,
        )

    assert isinstance(result, CallToolResult)
    assert result.is_error is True


async def test_modern_continuation_rejects_extra_response_key() -> None:
    question = "reject extra response key"
    response = _create_message_result({"type": "text", "text": '{"answer":"valid"}'})

    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_valid_handler(),
        init_timeout=5,
        timeout=5,
    ) as client:
        first = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            allow_input_required=True,
        )
        assert isinstance(first, InputRequiredResult)
        assert first.request_state is not None

        result = await client.session.call_tool(
            "sampling_compatibility",
            {"question": question},
            input_responses={"answer": response, "extra": response},
            request_state=first.request_state,
            allow_input_required=True,
        )

    assert isinstance(result, CallToolResult)
    assert result.is_error is True


async def test_legacy_sampling_create_message_completes() -> None:
    protocol_versions: list[str] = []

    result = await _call_sampling(
        "legacy",
        _valid_handler(),
        protocol_versions=protocol_versions,
    )

    assert result == {"status": "pass", "answer": "compatible"}
    assert protocol_versions == ["2025-11-25"]


async def test_legacy_sampling_locally_suppresses_its_deprecation_warning() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", MCPDeprecationWarning)
        result = await _call_sampling("legacy", _valid_handler())

    assert result == {"status": "pass", "answer": "compatible"}
    assert not any(issubclass(warning.category, MCPDeprecationWarning) for warning in captured)


async def test_legacy_handler_deprecation_warning_remains_visible() -> None:
    async def warning_handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: SamplingRequestContext,
    ) -> str:
        warnings.warn(SDK_SAMPLING_DEPRECATION, MCPDeprecationWarning, stacklevel=1)
        return '{"answer":"compatible"}'

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", MCPDeprecationWarning)
        result = await _call_sampling("legacy", warning_handler)

    assert result == {"status": "pass", "answer": "compatible"}
    matching = [
        warning for warning in captured if issubclass(warning.category, MCPDeprecationWarning)
    ]
    assert len(matching) == 1
    assert str(matching[0].message) == SDK_SAMPLING_DEPRECATION
    assert matching[0].filename.endswith("test_sampling.py")


async def test_overlapping_legacy_calls_do_not_pollute_warning_filters() -> None:
    filters_before = tuple(warnings.filters)
    first_started = anyio.Event()
    second_started = anyio.Event()
    release_first = anyio.Event()
    release_second = anyio.Event()
    first_finished = anyio.Event()
    results: list[dict[str, object]] = []

    def blocking_handler(started: anyio.Event, release: anyio.Event) -> SamplingHandler:
        async def handler(
            messages: list[SamplingMessage],
            params: SamplingParams,
            context: SamplingRequestContext,
        ) -> str:
            started.set()
            await release.wait()
            return '{"answer":"compatible"}'

        return handler

    async def run_call(handler: SamplingHandler, finished: anyio.Event | None = None) -> None:
        results.append(await _call_sampling("legacy", handler))
        if finished is not None:
            finished.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(
            run_call,
            blocking_handler(first_started, release_first),
            first_finished,
        )
        await first_started.wait()
        task_group.start_soon(
            run_call,
            blocking_handler(second_started, release_second),
        )
        await second_started.wait()
        release_first.set()
        await first_finished.wait()
        release_second.set()

    assert results == [
        {"status": "pass", "answer": "compatible"},
        {"status": "pass", "answer": "compatible"},
    ]
    assert tuple(warnings.filters) == filters_before

    with warnings.catch_warnings(record=True) as captured:
        warnings.warn_explicit(
            SDK_SAMPLING_DEPRECATION,
            MCPDeprecationWarning,
            filename=__file__,
            lineno=1,
            module="noa.compat.sampling",
        )

    matching = [
        warning for warning in captured if issubclass(warning.category, MCPDeprecationWarning)
    ]
    assert len(matching) == 1
    assert str(matching[0].message) == SDK_SAMPLING_DEPRECATION


async def test_modern_and_legacy_render_the_same_single_sampling_request() -> None:
    question = "Which protocol path is compatible?"
    requests_by_mode: dict[
        SamplingMode,
        list[tuple[list[SamplingMessage], SamplingParams]],
    ] = {"auto": [], "legacy": []}

    for mode in ("auto", "legacy"):
        result = await _call_sampling(
            mode,
            _valid_handler(requests=requests_by_mode[mode]),
            question,
        )
        assert result == {"status": "pass", "answer": "compatible"}

    modern_requests = requests_by_mode["auto"]
    legacy_requests = requests_by_mode["legacy"]
    assert len(modern_requests) == len(legacy_requests) == 1

    modern_messages, modern_params = modern_requests[0]
    legacy_messages, legacy_params = legacy_requests[0]
    assert modern_messages == legacy_messages
    assert modern_params.max_tokens == legacy_params.max_tokens == 80
    assert len(modern_messages) == 1
    content = modern_messages[0].content
    assert isinstance(content, TextContent)
    assert question in content.text
    assert content.text.count(question) == 1
    assert '{"answer":"<short text>"}' in content.text


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize(
    "model_output",
    [
        "not-json",
        '{"answer":""}',
        '{"answer":"   "}',
        '{"answer":"compatible","unexpected":true}',
        '{"answer":"' + ("x" * 257) + '"}',
    ],
)
async def test_invalid_text_sampling_output_is_rejected(
    mode: SamplingMode,
    model_output: str,
) -> None:
    async def invalid_handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: SamplingRequestContext,
    ) -> str:
        return model_output

    result = await _call_sampling(mode, invalid_handler)

    assert result == {"status": "invalid_model_output", "answer": None}


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_non_text_sampling_output_is_rejected(mode: SamplingMode) -> None:
    async def image_handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: SamplingRequestContext,
    ) -> CreateMessageResult:
        return _create_message_result(
            {
                "type": "image",
                "data": "aW1hZ2U=",
                "mimeType": "image/png",
            }
        )

    result = await _call_sampling(mode, image_handler)

    assert result == {"status": "invalid_model_output", "answer": None}


def test_sampling_request_is_stable_and_does_not_include_context() -> None:
    from noa.compat.sampling import build_sampling_request

    question = "Return a short compatibility answer."

    first = build_sampling_request(question)
    second = build_sampling_request(question)

    assert first == second
    assert first.method == "sampling/createMessage"
    assert first.params.max_tokens == 80
    assert first.params.include_context is None
    assert len(first.params.messages) == 1
    content = first.params.messages[0].content
    assert isinstance(content, TextContent)
    assert content.text == (
        f'Return only one JSON object matching {{"answer":"<short text>"}}. Question: {question}'
    )


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_missing_sampling_capability_returns_exact_result(mode: SamplingMode) -> None:
    with anyio.fail_after(1):
        async with Client(mcp, mode=mode, init_timeout=5, timeout=5) as client:
            result = await client.call_tool(
                "sampling_compatibility",
                {"question": "probe"},
            )

    assert result.is_error is False
    assert result.data == {"status": "unsupported_capability", "answer": None}


async def test_modern_missing_capability_does_not_return_input_required() -> None:
    with anyio.fail_after(1):
        async with Client(mcp, mode="auto", init_timeout=5, timeout=5) as client:
            result = await client.session.call_tool(
                "sampling_compatibility",
                {"question": "raw unsupported request"},
                allow_input_required=True,
            )

    assert isinstance(result, CallToolResult)
    assert result.is_error is False
    assert result.structured_content == {
        "status": "unsupported_capability",
        "answer": None,
    }


async def _refusing_handler(
    messages: list[SamplingMessage],
    params: SamplingParams,
    context: SamplingRequestContext,
) -> str:
    raise RuntimeError("sampling handler refused")


async def test_modern_handler_error_propagates_original_mcp_error() -> None:
    async with Client(
        mcp,
        mode="auto",
        sampling_handler=_refusing_handler,
        init_timeout=5,
        timeout=5,
    ) as client:
        with pytest.raises(MCPError) as captured:
            await client.call_tool("sampling_compatibility", {"question": "probe"})

    assert captured.value.code == -32603
    assert captured.value.message == "sampling handler refused"
    assert captured.value.data is None


async def test_legacy_handler_error_is_masked_as_exact_tool_error() -> None:
    async with Client(
        mcp,
        mode="legacy",
        sampling_handler=_refusing_handler,
        init_timeout=5,
        timeout=5,
    ) as client:
        with pytest.raises(
            ToolError,
            match=r"^Error calling tool 'sampling_compatibility'$",
        ):
            await client.call_tool("sampling_compatibility", {"question": "probe"})


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_cancelled_sampling_does_not_poison_the_server(mode: SamplingMode) -> None:
    cancelled = anyio.Event()

    async def blocked_handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: SamplingRequestContext,
    ) -> str:
        try:
            await anyio.sleep_forever()
            raise AssertionError("unreachable")
        finally:
            cancelled.set()

    async with Client(
        mcp,
        mode=mode,
        sampling_handler=blocked_handler,
        init_timeout=5,
        timeout=5,
    ) as client:
        with pytest.raises(TimeoutError):
            with anyio.fail_after(0.1):
                await client.call_tool("sampling_compatibility", {"question": "blocked"})
        with anyio.fail_after(1):
            await cancelled.wait()

    result = await _call_sampling(mode, _valid_handler(), "recovery")
    assert result == {"status": "pass", "answer": "compatible"}


async def test_sampling_tool_is_registered_with_a_description() -> None:
    async with Client(mcp, init_timeout=5, timeout=5) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert "sampling_compatibility" in tools
    assert tools["sampling_compatibility"].description
