from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version

from packaging.version import InvalidVersion, Version

from noa.compat.models import CheckResult, CheckStatus

EXPECTED_DISTRIBUTIONS = {
    "fastmcp": "4.0.0b3",
    "fastmcp-slim": "4.0.0b3",
    "mcp": "2.0.0",
    "ladybug": "0.19.1",
    "packaging": "26.3",
    "pydantic": "2.13.4",
    "anyio": "4.14.2",
}

_CHECK_NAMES = {"mcp": "mcp-sdk"}


def _version_check(name: str, distribution: str, expected: str) -> CheckResult:
    try:
        actual = version(distribution)
    except PackageNotFoundError:
        return CheckResult(
            name=name,
            status=CheckStatus.FAIL,
            summary=f"{distribution} is not installed.",
            details={"expected": expected, "actual": None},
        )

    return CheckResult(
        name=name,
        status=CheckStatus.PASS if actual == expected else CheckStatus.FAIL,
        summary=f"{distribution} {actual}",
        details={"expected": expected, "actual": actual},
    )


def _python_check() -> CheckResult:
    actual = ".".join(str(component) for component in sys.version_info[:3])
    return CheckResult(
        name="python",
        status=CheckStatus.PASS if sys.version_info[:2] == (3, 11) else CheckStatus.FAIL,
        summary=actual,
        details={"expected": "3.11.x", "actual": actual},
    )


def _platform_check() -> CheckResult:
    system = platform.system()
    macos_version = platform.mac_ver()[0]
    platform_ok = False
    if system == "Darwin" and macos_version:
        try:
            platform_ok = Version(macos_version) >= Version("15")
        except InvalidVersion:
            platform_ok = False

    actual = f"{system} {macos_version}".strip()
    return CheckResult(
        name="platform",
        status=CheckStatus.PASS if platform_ok else CheckStatus.FAIL,
        summary=actual,
        details={"expected": "Darwin with macOS >= 15", "actual": actual},
    )


def _stability_check(fastmcp_check: CheckResult) -> CheckResult:
    actual = fastmcp_check.details.get("actual")
    if not isinstance(actual, str):
        return CheckResult(
            name="fastmcp-stability",
            status=CheckStatus.FAIL,
            required=True,
            summary="FastMCP version is unavailable; stability cannot be determined.",
            details={"version": actual},
        )

    try:
        fastmcp_version = Version(actual)
    except InvalidVersion:
        return CheckResult(
            name="fastmcp-stability",
            status=CheckStatus.FAIL,
            required=True,
            summary="FastMCP version is invalid; stability cannot be determined.",
            details={"version": actual},
        )

    prerelease = fastmcp_version.is_prerelease
    return CheckResult(
        name="fastmcp-stability",
        status=CheckStatus.WARN if prerelease else CheckStatus.PASS,
        required=True,
        summary=(
            "FastMCP 4 is prerelease; release remains blocked on a stable validated pin."
            if prerelease
            else "FastMCP 4 pin is stable."
        ),
        details={"version": str(fastmcp_version)},
    )


def build_runtime_checks() -> list[CheckResult]:
    checks = [_python_check(), _platform_check()]
    dependency_checks = [
        _version_check(_CHECK_NAMES.get(distribution, distribution), distribution, expected)
        for distribution, expected in EXPECTED_DISTRIBUTIONS.items()
    ]
    checks.extend(dependency_checks)
    fastmcp_check = next(check for check in dependency_checks if check.name == "fastmcp")
    checks.append(_stability_check(fastmcp_check))
    return checks
