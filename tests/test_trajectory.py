from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from noa.domain import UtcInstant
from noa.domain.errors import DomainError
from noa.trajectory import (
    BranchContext,
    CriterionRole,
    EvidenceScope,
    EvidenceStatus,
    ObjectiveFacet,
    ResearchObjective,
    SuccessCriterion,
    TrajectoryEvent,
    TrajectoryIntent,
    WorkClass,
    WorkSource,
    evaluate_drift,
    evaluate_progress,
    is_objective_complete,
)

BASE_TIME = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _instant(offset_minutes: int = 0) -> UtcInstant:
    return UtcInstant.from_datetime(BASE_TIME + timedelta(minutes=offset_minutes))


def _objective() -> ResearchObjective:
    return ResearchObjective(
        objective_id="joyai-visual-memory",
        version=1,
        statement="验证连续 30 FPS 视觉记忆能完成语言读取和事件背景评测",
        facets=(
            ObjectiveFacet("topic", "joyai", 1.0),
            ObjectiveFacet("deliverable", "language-aligned-memory", 1.0),
            ObjectiveFacet("constraint", "30fps", 0.5),
        ),
        criteria=(
            SuccessCriterion(
                "hcu_utilization",
                "hcu_mean",
                ">=0.90",
                CriterionRole.REQUESTED_OPTIMIZATION,
                acceptance_scope=EvidenceScope.PILOT,
            ),
            SuccessCriterion(
                "writer_training",
                "writer_checkpoint",
                "exists",
                CriterionRole.PREREQUISITE,
                acceptance_scope=EvidenceScope.VISUAL_STAGE_A,
            ),
            SuccessCriterion(
                "language_alignment",
                "reader_alignment",
                "verified",
                CriterionRole.ROOT_CAPABILITY,
                depends_on=("writer_training",),
                acceptance_scope=EvidenceScope.LANGUAGE_STAGE_B,
            ),
            SuccessCriterion(
                "event_background_gate",
                "false_activation_rate",
                "<=0.05",
                CriterionRole.ROOT_CAPABILITY,
                depends_on=("language_alignment",),
                acceptance_scope=EvidenceScope.FORMAL_EVALUATION,
            ),
        ),
    )


def _event(
    event_id: str,
    seq: int,
    *,
    kind: str = "observation_recorded",
    supports: tuple[str, ...] = (),
    blocked: tuple[str, ...] = (),
    scope: EvidenceScope = EvidenceScope.PILOT,
    status: EvidenceStatus = EvidenceStatus.OBSERVED,
    intent: TrajectoryIntent | None = None,
    metrics: dict[str, object] | None = None,
    started: int | None = None,
    ended: int | None = None,
) -> TrajectoryEvent:
    return TrajectoryEvent(
        event_id=event_id,
        run_id="run-main",
        seq=seq,
        parent_event_id=None if seq == 1 else f"e{seq - 1}",
        branch_id="main",
        event_kind=kind,
        occurred_at=_instant(seq),
        started_at=None if started is None else _instant(started),
        ended_at=None if ended is None else _instant(ended),
        intent=intent,
        result={},
        metrics={} if metrics is None else metrics,
        artifacts=("test-evidence",),
        outcome="observed",
        source="test",
        idempotency_key=event_id,
        supports_criterion_ids=supports,
        blocked_criterion_ids=blocked,
        evidence_scope=scope,
        evidence_status=status,
    )


def _branch() -> BranchContext:
    return BranchContext(
        run_id="run-main",
        root_run_id="run-main",
        mainline_run_id="run-main",
        parent_run_id=None,
        branch_depth=0,
        fork_seq=1,
        common_ancestor_seq=None,
    )


def test_rejects_blank_objective_and_duplicate_criteria() -> None:
    with pytest.raises(DomainError, match="statement"):
        ResearchObjective("id", 1, " ", (), ())

    criterion = SuccessCriterion("same", "metric", "target", CriterionRole.ROOT_CAPABILITY)
    with pytest.raises(DomainError, match="criterion IDs"):
        ResearchObjective("id", 1, "objective", (), (criterion, criterion))


def test_rejects_invalid_event_duration_and_duplicate_intent_references() -> None:
    with pytest.raises(DomainError, match="ended_at"):
        _event("e1", 1, started=10, ended=5)

    with pytest.raises(DomainError, match="unique"):
        TrajectoryIntent(
            hypothesis_ids=("h1", "h1"),
            criterion_ids=(),
            facets=(),
            action="measure",
            work_class=WorkClass.PREREQUISITE,
            work_source=WorkSource.OBSERVED_BLOCKER,
        )


def test_progress_does_not_promote_hcu_pilot_to_root_capability() -> None:
    objective = _objective()
    events = [
        _event(
            "e1",
            1,
            supports=("hcu_utilization",),
            scope=EvidenceScope.PILOT,
            status=EvidenceStatus.VERIFIED,
            metrics={"hcu_mean": 0.938},
        )
    ]

    progress = evaluate_progress(objective, events)

    assert progress.verified_criterion_ids == ("hcu_utilization",)
    assert progress.root_criterion_ids == ("language_alignment", "event_background_gate")
    assert progress.fraction == 0.0
    assert progress.evidence_status_by_criterion["hcu_utilization"] == "verified"
    assert progress.evidence_status_by_criterion["language_alignment"] == "pending"


def test_narrow_stage_a_evidence_is_insufficient_for_language_stage_b() -> None:
    objective = _objective()
    event = _event(
        "e1",
        1,
        supports=("language_alignment",),
        scope=EvidenceScope.VISUAL_STAGE_A,
        status=EvidenceStatus.VERIFIED,
    )

    progress = evaluate_progress(objective, [event])

    assert "language_alignment" not in progress.verified_criterion_ids
    assert progress.evidence_status_by_criterion["language_alignment"] == "insufficient"


def test_unknown_facets_and_criteria_fail_closed() -> None:
    objective = _objective()
    intent = TrajectoryIntent(
        hypothesis_ids=("h1",),
        criterion_ids=("language_alignment",),
        facets=(ObjectiveFacet("topic", "unrelated", 1.0),),
        action="investigate",
        work_class=WorkClass.EXPLORATION,
        work_source=WorkSource.HYPOTHESIS,
    )
    with pytest.raises(DomainError, match="unknown facets"):
        evaluate_drift(objective, [_event("e1", 1, intent=intent)], _branch(), {})

    with pytest.raises(DomainError, match="unknown criterion"):
        evaluate_progress(objective, [_event("e1", 1, supports=("missing",))])


def test_prerequisite_release_sets_return_due_without_root_progress() -> None:
    objective = _objective()
    events = [
        _event(
            "e1",
            1,
            kind="prerequisite_unblocked",
            supports=("writer_training",),
            scope=EvidenceScope.PILOT,
            status=EvidenceStatus.INSUFFICIENT,
        ),
        _event(
            "e2",
            2,
            kind="experiment_finished",
            metrics={"decode_fps": 62},
        ),
    ]

    drift = evaluate_drift(
        objective,
        events,
        _branch(),
        {"released_criterion_ids": ("writer_training",)},
    )

    assert drift.root_progress == 0.0
    assert drift.prerequisite_progress == 0.0
    assert drift.validation_stagnation_events == 1
    assert drift.return_due is True
    assert "prerequisite released" in " ".join(drift.reasons)


def test_root_evidence_clears_stagnation_and_can_complete_objective() -> None:
    objective = _objective()
    events = [
        _event(
            "e1",
            1,
            supports=("writer_training",),
            scope=EvidenceScope.VISUAL_STAGE_A,
            status=EvidenceStatus.VERIFIED,
            metrics={"writer_checkpoint": True},
        ),
        _event(
            "e2",
            2,
            supports=("language_alignment",),
            scope=EvidenceScope.LANGUAGE_STAGE_B,
            status=EvidenceStatus.VERIFIED,
            metrics={"reader_alignment": True},
        ),
        _event(
            "e3",
            3,
            supports=("event_background_gate",),
            scope=EvidenceScope.FORMAL_EVALUATION,
            status=EvidenceStatus.VERIFIED,
            metrics={"false_activation_rate": 0.01},
        ),
    ]

    progress = evaluate_progress(objective, events)
    drift = evaluate_drift(objective, events, _branch(), {})

    assert progress.fraction == 1.0
    assert is_objective_complete(objective, events) is True
    assert drift.root_progress == 1.0
    assert drift.return_due is False


def test_empty_history_is_unknown_but_deterministic() -> None:
    drift = evaluate_drift(_objective(), (), _branch(), {})

    assert drift.path_distance == 0.0
    assert drift.goal_drift is None
    assert drift.score is None
    assert drift.reasons == ("no trajectory events to evaluate",)


def test_completed_objective_requires_evidence_and_timestamp() -> None:
    with pytest.raises(DomainError, match="completion evidence"):
        ResearchObjective(
            "id",
            1,
            "objective",
            (),
            (SuccessCriterion("root", "metric", "target", CriterionRole.ROOT_CAPABILITY),),
            status="completed",
        )


def test_formal_evaluation_does_not_substitute_for_single_stream_measurement() -> None:
    objective = ResearchObjective(
        "o",
        1,
        "stream",
        (),
        (
            SuccessCriterion(
                "fps",
                "fps",
                ">=30",
                CriterionRole.ROOT_CAPABILITY,
                acceptance_scope=EvidenceScope.SINGLE_STREAM,
            ),
        ),
    )
    event = replace(
        _event(
            "e1",
            1,
            supports=("fps",),
            scope=EvidenceScope.FORMAL_EVALUATION,
            status=EvidenceStatus.VERIFIED,
        ),
        metrics={"fps": 100},
        artifacts=("report",),
    )
    assert evaluate_progress(objective, [event]).verified_criterion_ids == ()


def test_evidence_below_target_and_without_artifact_cannot_verify() -> None:
    good = replace(
        _event("e1", 1, supports=("hcu_utilization",), status=EvidenceStatus.VERIFIED),
        metrics={"hcu_mean": 0.98},
        artifacts=("measurement",),
    )
    assert evaluate_progress(_objective(), [good]).verified_criterion_ids == ("hcu_utilization",)
    for bad in (replace(good, metrics={"hcu_mean": 0.2}), replace(good, artifacts=())):
        assert evaluate_progress(_objective(), [bad]).verified_criterion_ids == ()


def test_objective_dependencies_must_exist_and_be_acyclic() -> None:
    a = SuccessCriterion("a", "a", "ok", CriterionRole.ROOT_CAPABILITY, depends_on=("b",))
    with pytest.raises(DomainError):
        ResearchObjective("o", 1, "goal", (), (a,))
    b = SuccessCriterion("b", "b", "ok", CriterionRole.PREREQUISITE, depends_on=("a",))
    with pytest.raises(DomainError):
        ResearchObjective("o", 1, "goal", (), (a, b))


def test_history_rejects_wrong_parent() -> None:
    with pytest.raises(DomainError):
        evaluate_progress(
            _objective(), [_event("e1", 1), replace(_event("e2", 2), parent_event_id="wrong")]
        )


def test_snapshot_values_do_not_follow_mutated_input() -> None:
    payload: dict[str, object] = {"nested": {"items": [1, 2]}}
    event = replace(_event("e1", 1), result=payload)
    payload["nested"] = {"items": [3]}
    assert event.result["nested"] != payload["nested"]
