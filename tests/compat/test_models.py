from datetime import UTC

import pytest

from noa.compat import CheckStatus


def test_required_failure_prevents_go_decision() -> None:
    from noa.compat import CheckResult, CheckStatus, CompatibilityReport, GateDecision

    report = CompatibilityReport.from_checks(
        [CheckResult(name="required-check", status=CheckStatus.FAIL)]
    )

    assert report.decision is GateDecision.NO_GO


def test_warning_without_blocking_failure_is_conditional_go() -> None:
    from noa.compat import CheckResult, CheckStatus, CompatibilityReport, GateDecision

    report = CompatibilityReport.from_checks(
        [CheckResult(name="warning-check", status=CheckStatus.WARN)]
    )

    assert report.decision is GateDecision.CONDITIONAL_GO


@pytest.mark.parametrize("blocking_status", [CheckStatus.FAIL, CheckStatus.BLOCKED])
def test_blocking_status_takes_precedence_over_warning(blocking_status: CheckStatus) -> None:
    from noa.compat import CheckResult, CompatibilityReport, GateDecision

    report = CompatibilityReport.from_checks(
        [
            CheckResult(name="warning-check", status=CheckStatus.WARN),
            CheckResult(name="blocking-check", status=blocking_status),
        ]
    )

    assert report.decision is GateDecision.NO_GO


def test_optional_failure_allows_go_decision() -> None:
    from noa.compat import CheckResult, CheckStatus, CompatibilityReport, GateDecision

    checks = (
        check
        for check in [CheckResult(name="optional-check", status=CheckStatus.FAIL, required=False)]
    )

    report = CompatibilityReport.from_checks(checks)

    assert report.decision is GateDecision.GO
    assert [check.name for check in report.checks] == ["optional-check"]


def test_required_blocked_check_prevents_go_decision() -> None:
    from noa.compat import CheckResult, CheckStatus, CompatibilityReport, GateDecision

    report = CompatibilityReport.from_checks(
        [CheckResult(name="blocked-check", status=CheckStatus.BLOCKED)]
    )

    assert report.decision is GateDecision.NO_GO


def test_pass_only_checks_allow_go_decision() -> None:
    from noa.compat import CheckResult, CheckStatus, CompatibilityReport, GateDecision

    report = CompatibilityReport.from_checks(
        [CheckResult(name="passing-check", status=CheckStatus.PASS)]
    )

    assert report.decision is GateDecision.GO


def test_generated_at_is_timezone_aware_utc() -> None:
    from noa.compat import CheckResult, CheckStatus, CompatibilityReport

    report = CompatibilityReport.from_checks(
        [CheckResult(name="passing-check", status=CheckStatus.PASS)]
    )

    assert report.generated_at.tzinfo is UTC
    assert report.generated_at.utcoffset() is not None
