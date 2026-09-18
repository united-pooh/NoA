"""Deterministic runner events and next-step guardrails for NoA trajectories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .domain.errors import DomainError
from .trajectory import (
    BranchContext,
    EvidenceScope,
    ResearchObjective,
    TrajectoryEvent,
    WorkClass,
    WorkSource,
    evaluate_drift,
    validate_append,
    validate_history,
)


class GateResult(StrEnum):
    CONTINUE = "continue"
    CONTINUE_PREREQUISITE = "continue_prerequisite"
    RETURN_TO_CAPABILITY_VALIDATION = "return_to_capability_validation"
    CHECKPOINT_REVIEW = "checkpoint_review"
    PAUSE_FOR_HUMAN = "pause_for_human"
    ABANDON_BRANCH = "abandon_branch"


RUNNER_EVENT_KINDS = frozenset(
    {
        "run_started",
        "experiment_started",
        "experiment_heartbeat",
        "experiment_finished",
        "prerequisite_started",
        "prerequisite_unblocked",
        "objective_completed",
        "objective_reopened",
    }
)


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise DomainError(
            "invalid_next_step",
            f"{field} must be a string",
            {"field": field, "reason": "not a string"},
        )
    value = value.strip()
    if not value and not allow_empty:
        raise DomainError(
            "invalid_next_step",
            f"{field} must be nonblank",
            {"field": field, "reason": "blank"},
        )
    return value


@dataclass(frozen=True, slots=True)
class NextResearchStep:
    hypothesis: str
    criterion_id: str
    work_class: WorkClass
    work_source: WorkSource
    blocker: str
    return_criterion_id: str
    exit_condition: str
    evidence_scope: EvidenceScope

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypothesis", _text(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "criterion_id", _text(self.criterion_id, "criterion_id"))
        object.__setattr__(self, "blocker", _text(self.blocker, "blocker", allow_empty=True))
        object.__setattr__(
            self,
            "return_criterion_id",
            _text(self.return_criterion_id, "return_criterion_id", allow_empty=True),
        )
        object.__setattr__(self, "exit_condition", _text(self.exit_condition, "exit_condition"))
        if not isinstance(self.work_class, WorkClass):
            object.__setattr__(self, "work_class", WorkClass(str(self.work_class)))
        if not isinstance(self.work_source, WorkSource):
            object.__setattr__(self, "work_source", WorkSource(str(self.work_source)))
        if not isinstance(self.evidence_scope, EvidenceScope):
            object.__setattr__(self, "evidence_scope", EvidenceScope(str(self.evidence_scope)))


@dataclass(frozen=True, slots=True)
class GateDecision:
    result: GateResult
    reasons: tuple[str, ...]
    next_action: str
    validation_stagnation_events: int
    return_due: bool


def validate_runner_event(event: TrajectoryEvent) -> TrajectoryEvent:
    if event.event_kind not in RUNNER_EVENT_KINDS:
        raise DomainError(
            "invalid_runner_event",
            f"unsupported runner event kind {event.event_kind!r}",
            {"event_kind": event.event_kind},
        )
    return event


def append_runner_event(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
    event: TrajectoryEvent,
) -> TrajectoryEvent:
    """Validate a runner event against the immutable objective/history."""

    validate_runner_event(event)
    return validate_append(objective, events, event)


def evaluate_next_step(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
    proposal: NextResearchStep,
) -> GateDecision:
    """Return a structured next-step gate without invoking a model."""

    history = validate_history(events)
    criteria = objective.criteria_by_id
    criterion = criteria.get(proposal.criterion_id)
    if criterion is None:
        return GateDecision(
            GateResult.PAUSE_FOR_HUMAN,
            (f"unknown criterion {proposal.criterion_id!r}",),
            "repair_proposal",
            0,
            False,
        )
    if objective.status.value in {"completed", "superseded"}:
        return GateDecision(
            GateResult.ABANDON_BRANCH,
            ("completed objectives require a new version before more work",),
            "create_new_objective_version",
            0,
            False,
        )

    drift = evaluate_drift(
        objective,
        history,
        _mainline_context(history),
        {},
    )
    reasons: list[str] = []
    if proposal.evidence_scope is not criterion.acceptance_scope:
        reasons.append(
            f"evidence scope {proposal.evidence_scope.value!r} cannot satisfy "
            f"{criterion.acceptance_scope.value!r}"
        )
    if (
        proposal.work_class is WorkClass.CAPABILITY_VALIDATION
        and criterion.role.value != "root_capability"
    ):
        reasons.append("capability validation must target a root criterion")
    if proposal.work_class is WorkClass.PREREQUISITE and criterion.role.value != "prerequisite":
        reasons.append("prerequisite work must target a prerequisite criterion")

    releases = [
        event
        for event in history
        if event.event_kind == "prerequisite_unblocked" and event.supports_criterion_ids
    ]
    last_release = releases[-1] if releases else None
    return_due = drift.return_due
    if return_due and not proposal.return_criterion_id:
        reasons.append("released prerequisite requires an explicit return criterion")
        return GateDecision(
            GateResult.RETURN_TO_CAPABILITY_VALIDATION,
            tuple(reasons),
            "return_to_capability_validation",
            drift.validation_stagnation_events,
            True,
        )
    if return_due and proposal.return_criterion_id not in criteria:
        reasons.append("return criterion is unknown")
        return GateDecision(
            GateResult.PAUSE_FOR_HUMAN,
            tuple(reasons),
            "repair_proposal",
            drift.validation_stagnation_events,
            True,
        )
    if return_due and proposal.return_criterion_id == proposal.criterion_id:
        return GateDecision(
            GateResult.RETURN_TO_CAPABILITY_VALIDATION,
            ("prerequisite is released; validate the declared return criterion",),
            "return_to_capability_validation",
            drift.validation_stagnation_events,
            True,
        )
    if proposal.return_criterion_id and criterion.criterion_id != proposal.return_criterion_id:
        reasons.append("proposal declares a return criterion different from its target")
    if reasons:
        return GateDecision(
            GateResult.PAUSE_FOR_HUMAN,
            tuple(reasons),
            "repair_proposal",
            drift.validation_stagnation_events,
            return_due,
        )

    if history and history[-1].result.get("exit_condition_reached") is True:
        return GateDecision(
            GateResult.RETURN_TO_CAPABILITY_VALIDATION,
            ("the previous experiment reached its exit condition",),
            "validate_capability",
            drift.validation_stagnation_events,
            return_due,
        )
    if (
        last_release is not None
        and proposal.work_class is WorkClass.PREREQUISITE
        and drift.validation_stagnation_events > 0
    ):
        return GateDecision(
            GateResult.CHECKPOINT_REVIEW,
            ("prerequisite was released but the proposal continues prerequisite work",),
            "checkpoint_review",
            drift.validation_stagnation_events,
            return_due,
        )
    if proposal.work_class is WorkClass.PREREQUISITE:
        return GateDecision(
            GateResult.CONTINUE_PREREQUISITE,
            ("proposal addresses an active prerequisite",),
            "continue_prerequisite",
            drift.validation_stagnation_events,
            return_due,
        )
    return GateDecision(
        GateResult.CONTINUE,
        ("proposal is connected to the active objective",),
        "continue",
        drift.validation_stagnation_events,
        return_due,
    )


def _mainline_context(events: Sequence[TrajectoryEvent]) -> BranchContext:
    run_id = events[-1].run_id if events else "mainline"
    return BranchContext(run_id, run_id, run_id, None, 0, 1, None)


__all__ = [
    "RUNNER_EVENT_KINDS",
    "GateDecision",
    "GateResult",
    "NextResearchStep",
    "append_runner_event",
    "evaluate_next_step",
    "validate_runner_event",
]
