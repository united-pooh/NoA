from __future__ import annotations

import re
import warnings
from typing import Annotated

from fastmcp import Context
from mcp import MCPDeprecationWarning
from mcp.types import (
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    InputRequiredResult,
    SamplingMessage,
    TextContent,
)
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

REQUEST_STATE = "noa-sampling-compatibility-v1"
_SDK_SAMPLING_DEPRECATION = "The sampling capability is deprecated as of 2026-07-28 (SEP-2577)."


class SamplingEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ]


def build_sampling_request(question: str) -> CreateMessageRequest:
    return CreateMessageRequest(
        method="sampling/createMessage",
        params=CreateMessageRequestParams(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            'Return only one JSON object matching {"answer":"<short text>"}. '
                            f"Question: {question}"
                        ),
                    ),
                )
            ],
            max_tokens=80,
        ),
    )


def parse_sampling_result(result: CreateMessageResult) -> dict[str, str | None]:
    if not isinstance(result.content, TextContent):
        return {"status": "invalid_model_output", "answer": None}

    try:
        envelope = SamplingEnvelope.model_validate_json(result.content.text)
    except ValidationError:
        return {"status": "invalid_model_output", "answer": None}

    return {"status": "pass", "answer": envelope.answer}


async def resolve_sampling(
    question: str,
    ctx: Context,
) -> dict[str, str | None] | InputRequiredResult:
    responses = ctx.input_responses
    request_state = ctx.request_state
    if responses is not None or request_state is not None:
        if request_state != REQUEST_STATE:
            raise RuntimeError("invalid sampling continuation request state")
        if responses is None or set(responses) != {"answer"}:
            raise RuntimeError("sampling continuation requires exactly one answer response")
        response = responses["answer"]
        if not isinstance(response, CreateMessageResult):
            raise RuntimeError("sampling continuation answer has an invalid response type")
        return parse_sampling_result(response)

    request_context = ctx.request_context
    if request_context is None:
        raise RuntimeError("sampling requires an established MCP request context")

    client_capabilities = ctx.session.client_capabilities
    if client_capabilities is None or client_capabilities.sampling is None:
        return {"status": "unsupported_capability", "answer": None}

    request = build_sampling_request(question)
    if request_context.protocol_version in MODERN_PROTOCOL_VERSIONS:
        return InputRequiredResult(
            result_type="input_required",
            input_requests={"answer": request},
            request_state=REQUEST_STATE,
        )

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=rf"^{re.escape(_SDK_SAMPLING_DEPRECATION)}$",
            category=MCPDeprecationWarning,
            module=rf"^{re.escape(__name__)}$",
        )
        pending = ctx.session.create_message(
            messages=request.params.messages,
            max_tokens=request.params.max_tokens,
        )
    result = await pending
    return parse_sampling_result(result)
