from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    BLOCKED = "blocked"


class GateDecision(StrEnum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    NO_GO = "no_go"


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    required: bool = True
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class CompatibilityReport(BaseModel):
    generated_at: datetime
    decision: GateDecision
    checks: list[CheckResult]

    @classmethod
    def from_checks(cls, checks: Iterable[CheckResult]) -> CompatibilityReport:
        materialized = list(checks)
        blocking = any(
            check.required and check.status in {CheckStatus.FAIL, CheckStatus.BLOCKED}
            for check in materialized
        )
        warning = any(check.status is CheckStatus.WARN for check in materialized)

        if blocking:
            decision = GateDecision.NO_GO
        elif warning:
            decision = GateDecision.CONDITIONAL_GO
        else:
            decision = GateDecision.GO

        return cls(
            generated_at=datetime.now(UTC),
            decision=decision,
            checks=materialized,
        )
