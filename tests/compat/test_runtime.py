from __future__ import annotations

import platform
from importlib.metadata import PackageNotFoundError, version
from typing import NoReturn

import pytest

import noa.compat.runtime as runtime
from noa.compat.models import CheckStatus
from noa.compat.runtime import EXPECTED_DISTRIBUTIONS, build_runtime_checks

DEPENDENCY_CHECK_NAMES = {
    "fastmcp",
    "fastmcp-slim",
    "mcp-sdk",
    "ladybug",
    "packaging",
    "pydantic",
    "anyio",
}


def test_expected_distributions_match_exact_slice_zero_contract() -> None:
    assert EXPECTED_DISTRIBUTIONS == {
        "fastmcp": "4.0.0b3",
        "fastmcp-slim": "4.0.0b3",
        "mcp": "2.0.0",
        "ladybug": "0.19.1",
        "packaging": "26.3",
        "pydantic": "2.13.4",
        "anyio": "4.14.2",
    }


def test_current_runtime_satisfies_required_checks_with_prerelease_warning() -> None:
    checks = {check.name: check for check in build_runtime_checks()}

    assert set(checks) == {
        "python",
        "platform",
        *DEPENDENCY_CHECK_NAMES,
        "fastmcp-stability",
    }
    for name in {"python", "platform", *DEPENDENCY_CHECK_NAMES}:
        assert checks[name].status is CheckStatus.PASS, checks[name].model_dump()
    assert checks["fastmcp-stability"].status is CheckStatus.WARN
    assert checks["fastmcp-stability"].required is True


def test_version_mismatch_returns_fail_with_expected_and_actual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mismatched_version(distribution: str) -> str:
        return "4.0.0"

    monkeypatch.setattr("noa.compat.runtime.version", mismatched_version)

    result = runtime._version_check("fastmcp", "fastmcp", "4.0.0b3")

    assert result.status is CheckStatus.FAIL
    assert result.details == {"expected": "4.0.0b3", "actual": "4.0.0"}


def test_missing_distribution_returns_fail_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_version(distribution: str) -> NoReturn:
        raise PackageNotFoundError(distribution)

    monkeypatch.setattr("noa.compat.runtime.version", missing_version)

    result = runtime._version_check("ladybug", "ladybug", "0.19.1")

    assert result.status is CheckStatus.FAIL
    assert result.details == {"expected": "0.19.1", "actual": None}


def test_build_runtime_checks_normalizes_a_missing_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def version_with_missing_ladybug(distribution: str) -> str:
        if distribution == "ladybug":
            raise PackageNotFoundError(distribution)
        return version(distribution)

    monkeypatch.setattr("noa.compat.runtime.version", version_with_missing_ladybug)

    checks = {check.name: check for check in build_runtime_checks()}

    assert checks["ladybug"].status is CheckStatus.FAIL
    assert checks["ladybug"].details == {"expected": "0.19.1", "actual": None}


def test_non_darwin_platform_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "mac_ver", lambda: ("", ("", "", ""), ""))

    checks = {check.name: check for check in build_runtime_checks()}

    assert checks["platform"].status is CheckStatus.FAIL


def test_macos_older_than_15_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "mac_ver", lambda: ("14.7.9", ("", "", ""), "arm64"))

    checks = {check.name: check for check in build_runtime_checks()}

    assert checks["platform"].status is CheckStatus.FAIL


def test_stable_fastmcp_passes_stability_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def version_with_stable_fastmcp(distribution: str) -> str:
        if distribution == "fastmcp":
            return "4.0.0"
        return version(distribution)

    monkeypatch.setattr("noa.compat.runtime.version", version_with_stable_fastmcp)

    checks = {check.name: check for check in build_runtime_checks()}

    assert checks["fastmcp-stability"].status is CheckStatus.PASS
    assert checks["fastmcp-stability"].required is True
    assert checks["fastmcp-stability"].details == {"version": "4.0.0"}
