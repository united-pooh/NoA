"""Pure research-trajectory domain values and deterministic evaluators."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from .domain.errors import DomainError
from .domain.identifiers import UtcInstant


def _invalid(field: str, reason: str, *, code: str = "invalid_trajectory") -> DomainError:
    return DomainError(
        code=code,
        message=f"Invalid trajectory {field}: {reason}",
        context={"field": field, "reason": reason},
    )


def _text(value: object, field: str) -> str:
    if type(value) is not str:
        raise _invalid(field, "value must be a string")
    value = value.strip()
    if not value:
        raise _invalid(field, "value must be nonblank")
    return value


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise _invalid(field, "value must be a positive integer")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise _invalid(field, "value must be a non-negative integer")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise _invalid(field, "value must be a tuple of strings")
    result = tuple(_text(item, field) for item in value)
    if len(set(result)) != len(result):
        raise _invalid(field, "values must be unique")
    return result


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(field, "value must be a mapping")
    if any(type(key) is not str for key in value):
        raise _invalid(field, "mapping keys must be strings")
    return MappingProxyType(
        {key: _freeze_json(item, field, {id(value)}) for key, item in value.items()}
    )


def _freeze_json(value: object, field: str, parents: set[int]) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _invalid(field, "JSON numbers must be finite")
        return value
    if id(value) in parents:
        raise _invalid(field, "JSON values cannot contain cycles")
    ancestors = parents | {id(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise _invalid(field, "mapping keys must be strings")
        return MappingProxyType(
            {key: _freeze_json(item, field, ancestors) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field, ancestors) for item in value)
    raise _invalid(field, "value must contain only JSON data")


def _enum(value: object, enum_type: type[StrEnum], field: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    if type(value) is str:
        try:
            return enum_type(value)
        except ValueError as error:
            raise _invalid(field, f"unknown value {value!r}") from error
    raise _invalid(field, f"value must be a {enum_type.__name__}")


class CriterionRole(StrEnum):
    ROOT_CAPABILITY = "root_capability"
    PREREQUISITE = "prerequisite"
    REQUESTED_OPTIMIZATION = "requested_optimization"
    EXPLORATION = "exploration"


class WorkClass(StrEnum):
    CAPABILITY_VALIDATION = "capability_validation"
    PREREQUISITE = "prerequisite"
    REQUESTED_OPTIMIZATION = "requested_optimization"
    EXPLORATION = "exploration"


class WorkSource(StrEnum):
    USER_REQUEST = "user_request"
    OBSERVED_BLOCKER = "observed_blocker"
    HYPOTHESIS = "hypothesis"
    AUTOMATIC_FOLLOWUP = "automatic_followup"


class EvidenceScope(StrEnum):
    PILOT = "pilot"
    BATCH_TRAINING = "batch_training"
    SINGLE_STREAM = "single_stream"
    VISUAL_STAGE_A = "visual_stage_a"
    LANGUAGE_STAGE_B = "language_stage_b"
    END_TO_END = "end_to_end"
    FORMAL_EVALUATION = "formal_evaluation"


class EvidenceStatus(StrEnum):
    OBSERVED = "observed"
    VERIFIED = "verified"
    INSUFFICIENT = "insufficient"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ObjectiveStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    PAUSED = "paused"


_NUMERIC_TARGET = re.compile(r"(<=|>=|==|<|>)\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


@dataclass(frozen=True, slots=True)
class ObjectiveFacet:
    kind: str
    value: str
    weight: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _text(self.kind, "facet.kind"))
        object.__setattr__(self, "value", _text(self.value, "facet.value"))
        if type(self.weight) not in (int, float) or not math.isfinite(float(self.weight)):
            raise _invalid("facet.weight", "value must be finite")
        if self.weight <= 0:
            raise _invalid("facet.weight", "value must be positive")
        object.__setattr__(self, "weight", float(self.weight))

    @property
    def key(self) -> tuple[str, str]:
        return (self.kind, self.value)


@dataclass(frozen=True, slots=True)
class SuccessCriterion:
    criterion_id: str
    metric: str
    target: str
    role: CriterionRole
    depends_on: tuple[str, ...] = ()
    blocking: bool = True
    acceptance_scope: EvidenceScope = EvidenceScope.FORMAL_EVALUATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "criterion_id", _text(self.criterion_id, "criterion_id"))
        object.__setattr__(self, "metric", _text(self.metric, "metric"))
        object.__setattr__(self, "target", _text(self.target, "target"))
        object.__setattr__(self, "role", _enum(self.role, CriterionRole, "role"))
        depends_on = _string_tuple(self.depends_on, "depends_on")
        if self.criterion_id in depends_on:
            raise _invalid("depends_on", "criterion cannot depend on itself")
        object.__setattr__(self, "depends_on", depends_on)
        if type(self.blocking) is not bool:
            raise _invalid("blocking", "value must be boolean")
        object.__setattr__(
            self,
            "acceptance_scope",
            _enum(self.acceptance_scope, EvidenceScope, "acceptance_scope"),
        )


def _validate_dependencies(criteria: tuple[SuccessCriterion, ...]) -> None:
    known = {criterion.criterion_id for criterion in criteria}
    for criterion in criteria:
        unknown = sorted(set(criterion.depends_on) - known)
        if unknown:
            raise _invalid(
                "depends_on",
                f"unknown criterion IDs: {', '.join(unknown)}",
                code="unknown_criterion",
            )
    edges = {criterion.criterion_id: criterion.depends_on for criterion in criteria}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(criterion_id: str) -> None:
        if criterion_id in visiting:
            raise _invalid("depends_on", "criterion dependency graph contains a cycle")
        if criterion_id in visited:
            return
        visiting.add(criterion_id)
        for dependency in edges[criterion_id]:
            visit(dependency)
        visiting.remove(criterion_id)
        visited.add(criterion_id)

    for criterion_id in sorted(edges):
        visit(criterion_id)


@dataclass(frozen=True, slots=True)
class ResearchObjective:
    objective_id: str
    version: int
    statement: str
    facets: tuple[ObjectiveFacet, ...]
    criteria: tuple[SuccessCriterion, ...]
    status: ObjectiveStatus = ObjectiveStatus.ACTIVE
    supersedes_version: int | None = None
    completed_at: UtcInstant | None = None
    completion_evidence_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective_id", _text(self.objective_id, "objective_id"))
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        if not isinstance(self.facets, tuple) or any(
            not isinstance(facet, ObjectiveFacet) for facet in self.facets
        ):
            raise _invalid("facets", "value must be a tuple of ObjectiveFacet")
        if len({facet.key for facet in self.facets}) != len(self.facets):
            raise _invalid("facets", "facet keys must be unique")
        if not isinstance(self.criteria, tuple) or any(
            not isinstance(criterion, SuccessCriterion) for criterion in self.criteria
        ):
            raise _invalid("criteria", "value must be a tuple of SuccessCriterion")
        if len({criterion.criterion_id for criterion in self.criteria}) != len(self.criteria):
            raise _invalid("criteria", "criterion IDs must be unique")
        _validate_dependencies(self.criteria)
        object.__setattr__(self, "status", _enum(self.status, ObjectiveStatus, "status"))
        if self.supersedes_version is not None:
            _positive_int(self.supersedes_version, "supersedes_version")
            if self.supersedes_version >= self.version:
                raise _invalid("supersedes_version", "must precede the current version")
        if self.completed_at is not None and type(self.completed_at) is not UtcInstant:
            raise _invalid("completed_at", "value must be UtcInstant")
        object.__setattr__(
            self,
            "completion_evidence_event_ids",
            _string_tuple(self.completion_evidence_event_ids, "completion_evidence_event_ids"),
        )
        if self.status is ObjectiveStatus.COMPLETED:
            if self.completed_at is None or not self.completion_evidence_event_ids:
                raise _invalid(
                    "status",
                    "completed objectives require completed_at and completion evidence",
                )
        elif self.completed_at is not None or self.completion_evidence_event_ids:
            raise _invalid("status", "only completed objectives can carry completion evidence")

    @property
    def criteria_by_id(self) -> Mapping[str, SuccessCriterion]:
        return MappingProxyType({criterion.criterion_id: criterion for criterion in self.criteria})

    @property
    def root_criteria(self) -> tuple[SuccessCriterion, ...]:
        return tuple(
            criterion
            for criterion in self.criteria
            if criterion.role is CriterionRole.ROOT_CAPABILITY
        )

    @property
    def prerequisite_criteria(self) -> tuple[SuccessCriterion, ...]:
        return tuple(
            criterion for criterion in self.criteria if criterion.role is CriterionRole.PREREQUISITE
        )


@dataclass(frozen=True, slots=True)
class TrajectoryIntent:
    hypothesis_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    facets: tuple[ObjectiveFacet, ...]
    action: str
    work_class: WorkClass
    work_source: WorkSource
    blocks_criterion_ids: tuple[str, ...] = ()
    returns_to_criterion_ids: tuple[str, ...] = ()
    exit_conditions: tuple[str, ...] = ()
    evidence_scope: EvidenceScope = EvidenceScope.PILOT

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hypothesis_ids", _string_tuple(self.hypothesis_ids, "hypothesis_ids")
        )
        object.__setattr__(
            self, "criterion_ids", _string_tuple(self.criterion_ids, "criterion_ids")
        )
        object.__setattr__(
            self,
            "blocks_criterion_ids",
            _string_tuple(self.blocks_criterion_ids, "blocks_criterion_ids"),
        )
        object.__setattr__(
            self,
            "returns_to_criterion_ids",
            _string_tuple(self.returns_to_criterion_ids, "returns_to_criterion_ids"),
        )
        object.__setattr__(
            self, "exit_conditions", _string_tuple(self.exit_conditions, "exit_conditions")
        )
        if not isinstance(self.facets, tuple) or any(
            not isinstance(facet, ObjectiveFacet) for facet in self.facets
        ):
            raise _invalid("intent.facets", "value must be a tuple of ObjectiveFacet")
        if len({facet.key for facet in self.facets}) != len(self.facets):
            raise _invalid("intent.facets", "facet keys must be unique")
        object.__setattr__(self, "action", _text(self.action, "intent.action"))
        object.__setattr__(self, "work_class", _enum(self.work_class, WorkClass, "work_class"))
        object.__setattr__(self, "work_source", _enum(self.work_source, WorkSource, "work_source"))
        object.__setattr__(
            self,
            "evidence_scope",
            _enum(self.evidence_scope, EvidenceScope, "intent.evidence_scope"),
        )


@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    event_id: str
    run_id: str
    seq: int
    parent_event_id: str | None
    branch_id: str
    event_kind: str
    occurred_at: UtcInstant
    started_at: UtcInstant | None
    ended_at: UtcInstant | None
    intent: TrajectoryIntent | None
    result: Mapping[str, object]
    metrics: Mapping[str, object]
    artifacts: tuple[str, ...]
    outcome: str
    source: str
    idempotency_key: str
    supports_criterion_ids: tuple[str, ...] = ()
    blocked_criterion_ids: tuple[str, ...] = ()
    evidence_scope: EvidenceScope = EvidenceScope.PILOT
    evidence_status: EvidenceStatus = EvidenceStatus.OBSERVED

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "run_id",
            "branch_id",
            "event_kind",
            "outcome",
            "source",
            "idempotency_key",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        object.__setattr__(self, "seq", _positive_int(self.seq, "seq"))
        if self.parent_event_id is not None:
            object.__setattr__(
                self, "parent_event_id", _text(self.parent_event_id, "parent_event_id")
            )
            if self.parent_event_id == self.event_id:
                raise _invalid("parent_event_id", "an event cannot be its own parent")
        if self.intent is not None and not isinstance(self.intent, TrajectoryIntent):
            raise _invalid("intent", "value must be TrajectoryIntent")
        if type(self.occurred_at) is not UtcInstant:
            raise _invalid("occurred_at", "value must be UtcInstant")
        if self.started_at is not None and type(self.started_at) is not UtcInstant:
            raise _invalid("started_at", "value must be UtcInstant")
        if self.ended_at is not None and type(self.ended_at) is not UtcInstant:
            raise _invalid("ended_at", "value must be UtcInstant")
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.ended_at < self.started_at
        ):
            raise _invalid("ended_at", "ended_at cannot precede started_at")
        object.__setattr__(self, "result", _mapping(self.result, "result"))
        object.__setattr__(self, "metrics", _mapping(self.metrics, "metrics"))
        object.__setattr__(self, "artifacts", _string_tuple(self.artifacts, "artifacts"))
        object.__setattr__(
            self,
            "supports_criterion_ids",
            _string_tuple(self.supports_criterion_ids, "supports_criterion_ids"),
        )
        object.__setattr__(
            self,
            "blocked_criterion_ids",
            _string_tuple(self.blocked_criterion_ids, "blocked_criterion_ids"),
        )
        if set(self.supports_criterion_ids) & set(self.blocked_criterion_ids):
            raise _invalid("criterion_ids", "a criterion cannot be both supported and blocked")
        object.__setattr__(
            self,
            "evidence_scope",
            _enum(self.evidence_scope, EvidenceScope, "evidence_scope"),
        )
        object.__setattr__(
            self,
            "evidence_status",
            _enum(self.evidence_status, EvidenceStatus, "evidence_status"),
        )


@dataclass(frozen=True, slots=True)
class BranchContext:
    run_id: str
    root_run_id: str
    mainline_run_id: str
    parent_run_id: str | None
    branch_depth: int
    fork_seq: int
    common_ancestor_seq: int | None

    def __post_init__(self) -> None:
        for field_name in ("run_id", "root_run_id", "mainline_run_id"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.parent_run_id is not None:
            object.__setattr__(self, "parent_run_id", _text(self.parent_run_id, "parent_run_id"))
            if self.parent_run_id == self.run_id:
                raise _invalid("parent_run_id", "a run cannot be its own parent")
        object.__setattr__(
            self, "branch_depth", _nonnegative_int(self.branch_depth, "branch_depth")
        )
        object.__setattr__(self, "fork_seq", _positive_int(self.fork_seq, "fork_seq"))
        if (self.branch_depth == 0) != (self.parent_run_id is None):
            raise _invalid("branch_depth", "only root runs can have no parent")
        if self.common_ancestor_seq is not None:
            object.__setattr__(
                self,
                "common_ancestor_seq",
                _positive_int(self.common_ancestor_seq, "common_ancestor_seq"),
            )


@dataclass(frozen=True, slots=True)
class ProgressReport:
    verified_criterion_ids: tuple[str, ...]
    pending_criterion_ids: tuple[str, ...]
    fraction: float | None
    root_criterion_ids: tuple[str, ...]
    prerequisite_criterion_ids: tuple[str, ...]
    evidence_status_by_criterion: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DriftReport:
    path_distance: float | None
    goal_drift: float | None
    score: float | None
    root_progress: float | None
    prerequisite_progress: float | None
    validation_stagnation_events: int
    return_due: bool
    basis_event_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrajectorySnapshot:
    run_id: str
    objective_status: ObjectiveStatus
    branch_elapsed_ms: int | None
    path_elapsed_ms: int | None
    duration_source: str
    progress: ProgressReport
    drift: DriftReport
    next_action: str
    active_blockers: tuple[str, ...]
    last_capability_evidence_seq: int | None
    last_prerequisite_release_seq: int | None


def _scope_satisfies(actual: EvidenceScope, required: EvidenceScope) -> bool:
    # Scope labels describe different evidence populations.  A higher-looking
    # label must not silently stand in for another population (for example,
    # formal aggregate evaluation cannot prove a single-stream measurement).
    return actual is required


def _criterion_map(objective: ResearchObjective) -> Mapping[str, SuccessCriterion]:
    return objective.criteria_by_id


def _validate_history_shape(events: Sequence[TrajectoryEvent]) -> None:
    """Validate append-only ordering and parent links for a replay window."""

    seen_ids: set[str] = set()
    seen_run_sequences: set[tuple[str, int]] = set()
    by_id: dict[str, TrajectoryEvent] = {}
    last_seq_by_run: dict[str, int] = {}
    for index, event in enumerate(events):
        if not isinstance(event, TrajectoryEvent):
            raise _invalid("events", "history must contain TrajectoryEvent values")
        if event.event_id in seen_ids:
            raise _invalid("events", "event IDs must be unique")
        seen_ids.add(event.event_id)
        run_sequence = (event.run_id, event.seq)
        if run_sequence in seen_run_sequences:
            raise _invalid("events", "run sequence numbers must be unique")
        seen_run_sequences.add(run_sequence)
        previous_seq = last_seq_by_run.get(event.run_id)
        if previous_seq is not None and event.seq <= previous_seq:
            raise _invalid("events", "event sequence must increase within a run")
        last_seq_by_run[event.run_id] = event.seq
        if event.parent_event_id is None:
            if event.seq != 1:
                raise _invalid("parent_event_id", "non-root events require a parent")
        else:
            parent = by_id.get(event.parent_event_id)
            if parent is None:
                raise _invalid("parent_event_id", "parent event must precede the child")
            if parent.run_id == event.run_id:
                if event.seq != parent.seq + 1:
                    raise _invalid("seq", "same-run parent must be the immediately preceding event")
            elif event.seq != 1:
                raise _invalid("seq", "a child run must start at sequence 1")
        by_id[event.event_id] = event
        if index == 0 and event.parent_event_id is not None:
            raise _invalid("events", "history cannot begin after an unseen parent")


def validate_history(events: Sequence[TrajectoryEvent]) -> tuple[TrajectoryEvent, ...]:
    """Return an immutable replay window after validating its append-only shape."""

    result = tuple(events)
    _validate_history_shape(result)
    return result


def validate_append(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
    event: TrajectoryEvent,
) -> TrajectoryEvent:
    """Validate one event before a store appends it."""

    if objective.status in {ObjectiveStatus.COMPLETED, ObjectiveStatus.SUPERSEDED}:
        raise _invalid(
            "objective.status",
            "terminal objectives cannot accept events",
            code="objective_terminal",
        )
    history = validate_history(events)
    _validate_event_references(objective, event)
    if event.intent is not None:
        _validate_intent_facets(objective, event.intent)
    if any(existing.event_id == event.event_id for existing in history):
        raise _invalid("event_id", "event ID already exists", code="duplicate_event")
    if history:
        last = history[-1]
        if event.parent_event_id != last.event_id:
            raise _invalid("parent_event_id", "appended event must point to the latest event")
        if event.run_id == last.run_id and event.seq != last.seq + 1:
            raise _invalid("seq", "appended event sequence must increment by one")
        if event.run_id != last.run_id and event.seq != 1:
            raise _invalid("seq", "a child run must start at sequence 1")
    elif event.parent_event_id is not None or event.seq != 1:
        raise _invalid("events", "the first event must be an unparented sequence 1 event")
    return event


def _validate_event_references(objective: ResearchObjective, event: TrajectoryEvent) -> None:
    criteria = _criterion_map(objective)
    referenced = set(event.supports_criterion_ids) | set(event.blocked_criterion_ids)
    if event.intent is not None:
        referenced.update(event.intent.criterion_ids)
        referenced.update(event.intent.blocks_criterion_ids)
        referenced.update(event.intent.returns_to_criterion_ids)
    unknown = sorted(reference for reference in referenced if reference not in criteria)
    if unknown:
        raise _invalid(
            "criterion_ids",
            f"unknown criterion IDs: {', '.join(unknown)}",
            code="unknown_criterion",
        )


def _validate_intent_facets(objective: ResearchObjective, intent: TrajectoryIntent) -> None:
    objective_keys = {facet.key for facet in objective.facets}
    unknown = sorted(facet.key for facet in intent.facets if facet.key not in objective_keys)
    if unknown:
        raise _invalid("intent.facets", f"unknown facets: {unknown}", code="unknown_facet")


def _metric_satisfies(criterion: SuccessCriterion, event: TrajectoryEvent) -> bool:
    if criterion.metric not in event.metrics:
        return False
    value = event.metrics[criterion.metric]
    target = criterion.target.strip()
    if target in {"exists", "verified", "ok"}:
        if target == "exists":
            return value not in (None, False, "", ())
        if isinstance(value, bool):
            return value
        return isinstance(value, str) and value.strip().lower() == target
    match = _NUMERIC_TARGET.fullmatch(target)
    if match is not None and type(value) in (int, float) and not isinstance(value, bool):
        number = float(cast(int | float, value))
        threshold = float(match.group(2))
        operator = match.group(1)
        return {
            "<": number < threshold,
            "<=": number <= threshold,
            ">": number > threshold,
            ">=": number >= threshold,
            "==": number == threshold,
        }[operator]
    return type(value) is str and value == target


def _criterion_evidence_satisfies(
    criterion: SuccessCriterion,
    event: TrajectoryEvent,
) -> bool:
    return (
        event.evidence_status is EvidenceStatus.VERIFIED
        and _scope_satisfies(event.evidence_scope, criterion.acceptance_scope)
        and _metric_satisfies(criterion, event)
        and bool(event.artifacts)
    )


def evaluate_progress(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
) -> ProgressReport:
    events = validate_history(events)
    criteria = _criterion_map(objective)
    candidates: set[str] = set()
    observed: set[str] = set()
    blocked: set[str] = set()
    for event in events:
        _validate_event_references(objective, event)
        for criterion_id in event.supports_criterion_ids:
            criterion = criteria[criterion_id]
            if _criterion_evidence_satisfies(criterion, event):
                candidates.add(criterion_id)
            observed.add(criterion_id)
        blocked.update(event.blocked_criterion_ids)

    # Dependencies are evaluated as a fixed point over the acyclic objective
    # graph.  A root claim cannot become verified merely because its own event
    # says VERIFIED while a required prerequisite remains unverified.
    verified: set[str] = set()
    changed = True
    while changed:
        changed = False
        for criterion in objective.criteria:
            if (
                criterion.criterion_id in candidates
                and criterion.criterion_id not in verified
                and set(criterion.depends_on).issubset(verified)
            ):
                verified.add(criterion.criterion_id)
                changed = True

    ordered_ids = tuple(criterion.criterion_id for criterion in objective.criteria)
    verified_ids = tuple(criterion_id for criterion_id in ordered_ids if criterion_id in verified)
    pending_ids = tuple(
        criterion_id for criterion_id in ordered_ids if criterion_id not in verified
    )
    root_ids = tuple(criterion.criterion_id for criterion in objective.root_criteria)
    prerequisite_ids = tuple(
        criterion.criterion_id for criterion in objective.prerequisite_criteria
    )
    denominator = len(root_ids) or len(ordered_ids)
    root_verified = sum(criterion_id in verified for criterion_id in root_ids)
    fraction = root_verified / denominator if denominator and events else None
    statuses: dict[str, str] = {}
    for criterion_id in ordered_ids:
        if criterion_id in verified:
            statuses[criterion_id] = EvidenceStatus.VERIFIED.value
        elif criterion_id in blocked:
            statuses[criterion_id] = EvidenceStatus.BLOCKED.value
        elif criterion_id in observed:
            statuses[criterion_id] = EvidenceStatus.INSUFFICIENT.value
        else:
            statuses[criterion_id] = "pending"
    return ProgressReport(
        verified_criterion_ids=verified_ids,
        pending_criterion_ids=pending_ids,
        fraction=fraction,
        root_criterion_ids=root_ids,
        prerequisite_criterion_ids=prerequisite_ids,
        evidence_status_by_criterion=MappingProxyType(statuses),
    )


def is_objective_complete(objective: ResearchObjective, events: Sequence[TrajectoryEvent]) -> bool:
    if objective.status is ObjectiveStatus.SUPERSEDED:
        return False
    progress = evaluate_progress(objective, events)
    root_ids = set(progress.root_criterion_ids)
    return bool(root_ids) and root_ids.issubset(progress.verified_criterion_ids)


def complete_objective(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
    *,
    completed_at: UtcInstant | None = None,
) -> ResearchObjective:
    """Return a completed immutable objective after verifying all root claims."""

    if objective.status in {ObjectiveStatus.COMPLETED, ObjectiveStatus.SUPERSEDED}:
        raise _invalid(
            "status", "only active objectives can be completed", code="objective_terminal"
        )
    history = validate_history(events)
    if not is_objective_complete(objective, history):
        raise _invalid(
            "status",
            "all root criteria require verified evidence before completion",
            code="objective_incomplete",
        )
    evidence_ids: list[str] = []
    criteria = objective.criteria_by_id
    for event in history:
        if any(
            criterion_id in criteria
            and criteria[criterion_id].role is CriterionRole.ROOT_CAPABILITY
            and _criterion_evidence_satisfies(criteria[criterion_id], event)
            for criterion_id in event.supports_criterion_ids
        ):
            evidence_ids.append(event.event_id)
    if not evidence_ids:
        raise _invalid("completion_evidence_event_ids", "completion evidence is missing")
    completion_time = completed_at or history[-1].occurred_at
    if type(completion_time) is not UtcInstant:
        raise _invalid("completed_at", "value must be UtcInstant")
    return replace(
        objective,
        status=ObjectiveStatus.COMPLETED,
        completed_at=completion_time,
        completion_evidence_event_ids=tuple(evidence_ids),
    )


def evaluate_drift(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
    path_context: BranchContext,
    dependency_context: Mapping[str, object],
) -> DriftReport:
    events = validate_history(events)
    if not events:
        return DriftReport(
            path_distance=float(path_context.branch_depth),
            goal_drift=None,
            score=None,
            root_progress=0.0 if objective.root_criteria else None,
            prerequisite_progress=0.0 if objective.prerequisite_criteria else None,
            validation_stagnation_events=0,
            return_due=False,
            basis_event_ids=(),
            reasons=("no trajectory events to evaluate",),
        )
    for event in events:
        _validate_event_references(objective, event)
        if event.intent is not None:
            _validate_intent_facets(objective, event.intent)

    progress = evaluate_progress(objective, events)
    objective_facet_weights = {facet.key: facet.weight for facet in objective.facets}
    objective_metrics = {criterion.metric for criterion in objective.criteria}
    last_event = events[-1]
    intent = last_event.intent
    reasons: list[str] = []
    drift_components: list[float] = []

    if intent is None:
        scope_drift = 1.0
        reasons.append("latest event has no structured intent")
    else:
        intent_facet_weights = {facet.key: facet.weight for facet in intent.facets}
        union = set(objective_facet_weights) | set(intent_facet_weights)
        intersection_weight = sum(
            min(objective_facet_weights.get(key, 0.0), intent_facet_weights.get(key, 0.0))
            for key in union
        )
        union_weight = sum(
            max(objective_facet_weights.get(key, 0.0), intent_facet_weights.get(key, 0.0))
            for key in union
        )
        scope_drift = 1.0 - (intersection_weight / union_weight if union_weight else 0.0)
        if scope_drift:
            reasons.append("intent facet coverage differs from objective")
        if not intent.criterion_ids and not intent.blocks_criterion_ids:
            scope_drift = max(scope_drift, 0.5)
            reasons.append("intent does not reference a criterion or blocker")
    drift_components.append(scope_drift)

    metric_keys = {str(key) for key in last_event.metrics}
    unsupported_metrics = metric_keys - objective_metrics
    metric_drift = len(unsupported_metrics) / max(1, len(metric_keys))
    if unsupported_metrics:
        reasons.append(f"metrics are outside objective criteria: {sorted(unsupported_metrics)}")
    drift_components.append(metric_drift)

    released_ids = _context_string_set(dependency_context, "released_criterion_ids")
    active_blockers = _context_string_set(dependency_context, "active_blocker_ids")
    prerequisite_ids = {criterion.criterion_id for criterion in objective.prerequisite_criteria}
    release_indexes = [
        index
        for index, event in enumerate(events)
        if event.event_kind == "prerequisite_unblocked"
        and (
            (not released_ids and prerequisite_ids.intersection(event.supports_criterion_ids))
            or released_ids.intersection(event.supports_criterion_ids)
        )
    ]
    last_release_index = max(release_indexes, default=None)
    if released_ids:
        released_ids.update(
            criterion_id
            for index in release_indexes
            for criterion_id in events[index].supports_criterion_ids
            if criterion_id in prerequisite_ids
        )
    release_targets = _context_string_set(dependency_context, "return_to_criterion_ids")
    if not release_targets:
        release_targets = {
            criterion.criterion_id
            for criterion in objective.root_criteria
            if set(criterion.depends_on).intersection(released_ids)
        }
    root_ids = set(progress.root_criterion_ids)
    target_evidence_indexes = [
        index
        for index, event in enumerate(events)
        if release_targets.intersection(event.supports_criterion_ids)
        and any(
            _criterion_evidence_satisfies(objective.criteria_by_id[criterion_id], event)
            for criterion_id in event.supports_criterion_ids
            if criterion_id in root_ids and criterion_id in release_targets
        )
    ]
    if last_release_index is None:
        stagnation = 0
    else:
        later_events = events[last_release_index + 1 :]
        later_target_evidence = any(index > last_release_index for index in target_evidence_indexes)
        stagnation = 0 if later_target_evidence else len(later_events)
    after_release_start = (last_release_index + 1) if last_release_index is not None else 0
    new_blocker_after_release = any(
        release_targets.intersection(event.blocked_criterion_ids)
        for event in events[after_release_start:]
    )
    dependencies_ready = all(
        set(objective.criteria_by_id[criterion_id].depends_on).issubset(
            set(progress.verified_criterion_ids) | released_ids
        )
        for criterion_id in release_targets
        if criterion_id in objective.criteria_by_id
    )
    relevant_active_blockers = active_blockers.intersection(release_targets | released_ids)
    return_due = (
        last_release_index is not None
        and bool(release_targets)
        and dependencies_ready
        and not relevant_active_blockers
        and not new_blocker_after_release
        and not any(index > last_release_index for index in target_evidence_indexes)
        and bool(events[last_release_index + 1 :])
    )
    if return_due:
        reasons.append("prerequisite released without new root-capability evidence")
    if stagnation:
        reasons.append(f"root-capability validation stagnant for {stagnation} events")

    local_events = sum(event.run_id == path_context.run_id for event in events)
    path_distance = float(path_context.branch_depth + local_events)
    branch_drift = min(1.0, path_distance / max(1.0, float(local_events + 1)))
    drift_components.append(branch_drift)
    goal_drift = sum(drift_components) / len(drift_components)
    score = min(1.0, (goal_drift + (1.0 if return_due else 0.0) + min(1.0, stagnation / 5)) / 3)
    basis = tuple(event.event_id for event in events[-5:])
    return DriftReport(
        path_distance=path_distance,
        goal_drift=goal_drift,
        score=score,
        root_progress=_criterion_progress(progress, progress.root_criterion_ids),
        prerequisite_progress=_criterion_progress(progress, progress.prerequisite_criterion_ids),
        validation_stagnation_events=stagnation,
        return_due=return_due,
        basis_event_ids=basis,
        reasons=tuple(reasons),
    )


def _criterion_progress(progress: ProgressReport, criterion_ids: tuple[str, ...]) -> float | None:
    if not criterion_ids:
        return None
    verified = sum(
        criterion_id in progress.verified_criterion_ids for criterion_id in criterion_ids
    )
    return verified / len(criterion_ids)


def _context_string_set(context: Mapping[str, object], key: str) -> set[str]:
    value = context.get(key, ())
    if not isinstance(value, (tuple, list, set, frozenset)):
        return set()
    return {str(item) for item in value}


__all__ = [
    "BranchContext",
    "CriterionRole",
    "DriftReport",
    "EvidenceScope",
    "EvidenceStatus",
    "ObjectiveFacet",
    "ObjectiveStatus",
    "ProgressReport",
    "ResearchObjective",
    "SuccessCriterion",
    "TrajectoryEvent",
    "TrajectoryIntent",
    "TrajectorySnapshot",
    "WorkClass",
    "WorkSource",
    "complete_objective",
    "evaluate_drift",
    "evaluate_progress",
    "is_objective_complete",
    "validate_append",
    "validate_history",
]
