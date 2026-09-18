from datetime import UTC, datetime, timedelta

import pytest

from noa.domain import UtcInstant
from noa.domain.errors import DomainError
from noa.trajectory import (
    CriterionRole,
    EvidenceScope,
    EvidenceStatus,
    ResearchObjective,
    SuccessCriterion,
    TrajectoryEvent,
    WorkClass,
    WorkSource,
)
from noa.trajectory_guard import (
    GateResult,
    NextResearchStep,
    append_runner_event,
    evaluate_next_step,
)

BASE = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def _t(seq: int) -> UtcInstant:
    return UtcInstant.from_datetime(BASE + timedelta(minutes=seq))


def _objective() -> ResearchObjective:
    return ResearchObjective(
        "joyai",
        1,
        "validate language-aligned visual memory",
        (),
        (
            SuccessCriterion(
                "writer",
                "checkpoint",
                "exists",
                CriterionRole.PREREQUISITE,
                acceptance_scope=EvidenceScope.VISUAL_STAGE_A,
            ),
            SuccessCriterion(
                "language",
                "alignment",
                "verified",
                CriterionRole.ROOT_CAPABILITY,
                depends_on=("writer",),
                acceptance_scope=EvidenceScope.LANGUAGE_STAGE_B,
            ),
        ),
    )


def _event(
    event_id: str,
    seq: int,
    *,
    kind: str = "experiment_finished",
    supports: tuple[str, ...] = (),
    result: dict[str, object] | None = None,
) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_id,
        "run-main",
        seq,
        None if seq == 1 else f"e{seq - 1}",
        "main",
        kind,
        _t(seq),
        None,
        None,
        None,
        result or {},
        {},
        (),
        "observed",
        "runner",
        event_id,
        supports,
        (),
        EvidenceScope.PILOT,
        EvidenceStatus.OBSERVED,
    )


def _step(
    *,
    criterion_id: str = "writer",
    work_class: WorkClass = WorkClass.PREREQUISITE,
    return_criterion_id: str = "",
) -> NextResearchStep:
    return NextResearchStep(
        hypothesis="repair the writer path",
        criterion_id=criterion_id,
        work_class=work_class,
        work_source=WorkSource.OBSERVED_BLOCKER,
        blocker="writer blocked",
        return_criterion_id=return_criterion_id,
        exit_condition="writer checkpoint exists",
        evidence_scope=EvidenceScope.VISUAL_STAGE_A,
    )


def test_runner_events_are_allowlisted() -> None:
    with pytest.raises(DomainError, match="unsupported runner event"):
        append_runner_event(_objective(), (), _event("e1", 1, kind="freeform_note"))


def test_released_prerequisite_without_return_criterion_forces_mainline() -> None:
    events = (
        _event("e1", 1, kind="prerequisite_unblocked", supports=("writer",)),
        _event("e2", 2),
    )
    decision = evaluate_next_step(_objective(), events, _step())
    assert decision.result is GateResult.RETURN_TO_CAPABILITY_VALIDATION
    assert decision.return_due is True


def test_return_criterion_and_exit_condition_are_gated() -> None:
    released = (
        _event("e1", 1, kind="prerequisite_unblocked", supports=("writer",)),
        _event("e2", 2),
    )
    decision = evaluate_next_step(
        _objective(),
        released,
        NextResearchStep(
            hypothesis="validate language alignment",
            criterion_id="language",
            work_class=WorkClass.CAPABILITY_VALIDATION,
            work_source=WorkSource.HYPOTHESIS,
            blocker="",
            return_criterion_id="language",
            exit_condition="collect language evidence",
            evidence_scope=EvidenceScope.LANGUAGE_STAGE_B,
        ),
    )
    assert decision.result is GateResult.RETURN_TO_CAPABILITY_VALIDATION

    exited = (_event("e1", 1, result={"exit_condition_reached": True}),)
    decision = evaluate_next_step(
        _objective(), exited, _step(criterion_id="writer", work_class=WorkClass.PREREQUISITE)
    )
    assert decision.result is GateResult.RETURN_TO_CAPABILITY_VALIDATION


def test_scope_mismatch_pauses_for_human() -> None:
    proposal = NextResearchStep(
        hypothesis="try a pilot",
        criterion_id="language",
        work_class=WorkClass.CAPABILITY_VALIDATION,
        work_source=WorkSource.HYPOTHESIS,
        blocker="",
        return_criterion_id="",
        exit_condition="collect language evidence",
        evidence_scope=EvidenceScope.PILOT,
    )
    decision = evaluate_next_step(_objective(), (), proposal)
    assert decision.result is GateResult.PAUSE_FOR_HUMAN
