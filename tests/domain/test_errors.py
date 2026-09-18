"""Contract tests for noa.domain.errors.DomainError (spec section 15)."""

from collections.abc import Mapping
from typing import cast

import pytest

from noa.domain.errors import DomainContextValue, DomainError


def test_domain_error_exposes_stable_code_message_context() -> None:
    error = DomainError(
        code="invalid_typed_id",
        message="Invalid wrk UUIDv7 value: UUID version must be 7",
        context={
            "expected_prefix": "wrk",
            "value": "wrk_0198cd4a",
            "reason": "UUID version must be 7",
        },
    )

    assert error.code == "invalid_typed_id"
    assert error.message == "Invalid wrk UUIDv7 value: UUID version must be 7"
    assert isinstance(error.context, Mapping)
    assert error.context["expected_prefix"] == "wrk"
    assert error.context["value"] == "wrk_0198cd4a"
    assert error.context["reason"] == "UUID version must be 7"


def test_domain_error_is_an_exception_whose_str_is_the_message() -> None:
    error = DomainError(code="some_code", message="human readable", context={})

    assert isinstance(error, Exception)
    assert str(error) == "human readable"


def test_domain_error_context_is_copied_at_construction() -> None:
    source: dict[str, DomainContextValue] = {"key": "value"}
    error = DomainError(code="code", message="message", context=source)

    source["key"] = "mutated"
    source["extra"] = "added"

    assert error.context == {"key": "value"}


def test_domain_error_context_is_frozen_against_mutation() -> None:
    error = DomainError(code="code", message="message", context={"key": "value"})

    with pytest.raises(TypeError):
        error.context["key"] = "other"  # type: ignore[index]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("text", "text"),
        ("", ""),
        (0, 0),
        (7, 7),
        (-3, -3),
        (True, True),
        (False, False),
        (("a", "b"), ("a", "b")),
        ((), ()),
    ],
)
def test_domain_error_accepts_contract_context_values(
    value: DomainContextValue,
    expected: DomainContextValue,
) -> None:
    error = DomainError(code="code", message="message", context={"key": value})

    assert error.context["key"] == expected


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        None,
        ["a"],
        [{"a": 1}],
        {"a": 1},
        {"set"},
        b"bytes",
        ("a", 1),
        (1, 2),
        (None,),
        object(),
        3.0,
    ],
)
def test_domain_error_rejects_non_contract_context_values(value: object) -> None:
    context = cast("dict[str, DomainContextValue]", {"key": value})

    with pytest.raises(TypeError):
        DomainError(code="code", message="message", context=context)


def test_domain_error_rejects_non_string_context_keys() -> None:
    context = cast("dict[str, DomainContextValue]", {7: "value"})

    with pytest.raises(TypeError):
        DomainError(code="code", message="message", context=context)


def test_domain_error_message_is_free_text_and_never_machine_parsed() -> None:
    free_text = "line1\nline2 {not json}: 状态 100% ✔ <tag>"
    first = DomainError(code="shared_code", message=free_text, context={})
    second = DomainError(code="shared_code", message="totally different text", context={})

    assert first.message == free_text
    assert second.message == "totally different text"
    assert first.code == second.code == "shared_code"
