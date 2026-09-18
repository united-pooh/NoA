from __future__ import annotations

from pathlib import Path
from typing import cast

from fastmcp import Client


def _data(result: object) -> dict[str, object]:
    return cast(dict[str, object], result.data)


async def test_joyai_scnet_path_covers_stage_gates_and_replay(tmp_path: Path) -> None:
    """Exercise the HCU → Stage A → Stage B → formal evaluation path."""

    from noa.server import mcp

    criteria = [
        {
            "criterion_id": "writer",
            "metric": "writer_checkpoint",
            "target": "exists",
            "role": "prerequisite",
            "acceptance_scope": "visual_stage_a",
        },
        {
            "criterion_id": "snapshot",
            "metric": "index_complete",
            "target": "verified",
            "role": "prerequisite",
            "acceptance_scope": "visual_stage_a",
        },
        {
            "criterion_id": "language",
            "metric": "reader_alignment",
            "target": "verified",
            "role": "root_capability",
            "depends_on": ["writer"],
            "acceptance_scope": "language_stage_b",
        },
        {
            "criterion_id": "formal",
            "metric": "event_background_discrimination",
            "target": "verified",
            "role": "root_capability",
            "depends_on": ["language"],
            "acceptance_scope": "formal_evaluation",
        },
    ]

    async with Client(mcp) as client:
        assert (
            _data(
                await client.call_tool(
                    "create_research_objective",
                    {
                        "workspace_root": str(tmp_path),
                        "objective_id": "joyai-scnet",
                        "statement": "validate native visual memory language capability",
                        "criteria": criteria,
                    },
                )
            )["status"]
            == "pass"
        )
        assert (
            _data(
                await client.call_tool(
                    "start_research_run",
                    {
                        "workspace_root": str(tmp_path),
                        "objective_id": "joyai-scnet",
                        "run_id": "run-main",
                    },
                )
            )["status"]
            == "pass"
        )

        async def event(
            event_id: str,
            event_kind: str,
            *,
            at: str,
            ended_at: str | None = None,
            result: dict[str, object] | None = None,
            metrics: dict[str, object] | None = None,
            artifacts: list[str] | None = None,
            supports: list[str] | None = None,
            blocked: list[str] | None = None,
            scope: str = "pilot",
            evidence_status: str = "observed",
        ) -> dict[str, object]:
            response = await client.call_tool(
                "record_runner_event",
                {
                    "workspace_root": str(tmp_path),
                    "objective_id": "joyai-scnet",
                    "run_id": "run-main",
                    "event_id": event_id,
                    "event_kind": event_kind,
                    "idempotency_key": event_id,
                    "occurred_at": at,
                    "started_at": at,
                    "ended_at": ended_at or at,
                    "result": result,
                    "metrics": metrics,
                    "artifacts": artifacts,
                    "supports_criterion_ids": supports,
                    "blocked_criterion_ids": blocked,
                    "evidence_scope": scope,
                    "evidence_status": evidence_status,
                },
            )
            payload = _data(response)
            assert payload["status"] == "pass", payload
            return payload

        await event(
            "hcu-pilot",
            "experiment_finished",
            at="2026-09-19T00:00:00Z",
            result={"stage": "hcu_pilot", "utilization": "8_gpu"},
            metrics={"hcu_utilization": 0.97},
            artifacts=["hcu-pilot.json"],
        )
        await event(
            "writer-unblocked",
            "prerequisite_unblocked",
            at="2026-09-19T00:00:01Z",
            supports=["writer"],
            scope="visual_stage_a",
        )
        await event(
            "writer-optimization",
            "experiment_finished",
            at="2026-09-19T00:00:03Z",
            result={"stage": "decoder_optimization", "new_blocker": False},
            metrics={"decoder_latency_ms": 12},
            artifacts=["decoder-optimization.json"],
        )
        proposal = _data(
            await client.call_tool(
                "propose_next_research_step",
                {
                    "workspace_root": str(tmp_path),
                    "objective_id": "joyai-scnet",
                    "hypothesis": "continue decoder optimization",
                    "criterion_id": "writer",
                    "work_class": "prerequisite",
                    "work_source": "observed_blocker",
                    "exit_condition": "writer checkpoint exists",
                    "evidence_scope": "visual_stage_a",
                },
            )
        )
        assert proposal["result"] == "return_to_capability_validation"
        assert proposal["return_due"] is True

        await event(
            "writer-stage-a",
            "experiment_finished",
            at="2026-09-19T00:00:04Z",
            metrics={"writer_checkpoint": "exists"},
            artifacts=["writer.ckpt"],
            supports=["writer"],
            scope="visual_stage_a",
            evidence_status="verified",
        )
        blocked_snapshot = await event(
            "snapshot-partial",
            "experiment_finished",
            at="2026-09-19T00:00:05Z",
            result={"index": "partial"},
            metrics={"index_complete": False},
            artifacts=["index.partial.json"],
            blocked=["snapshot"],
            scope="visual_stage_a",
            evidence_status="blocked",
        )
        assert blocked_snapshot["event"]["evidence_status"] == "blocked"  # type: ignore[index]

        await event(
            "snapshot-complete",
            "experiment_finished",
            at="2026-09-19T00:00:06Z",
            result={"index": "complete"},
            metrics={"index_complete": "verified"},
            artifacts=["index.json"],
            supports=["snapshot"],
            scope="visual_stage_a",
            evidence_status="verified",
        )
        await event(
            "language-stage-b",
            "experiment_finished",
            at="2026-09-19T00:00:07Z",
            metrics={"reader_alignment": "verified"},
            artifacts=["language-stage-b.json"],
            supports=["language"],
            scope="language_stage_b",
            evidence_status="verified",
        )
        await event(
            "formal-events-background",
            "experiment_finished",
            at="2026-09-19T00:00:08Z",
            ended_at="2026-09-19T00:00:08Z",
            metrics={"event_background_discrimination": "verified"},
            artifacts=["formal-evaluation.json"],
            supports=["formal"],
            scope="formal_evaluation",
            evidence_status="verified",
        )

        first = _data(
            await client.call_tool(
                "get_research_snapshot",
                {
                    "workspace_root": str(tmp_path),
                    "objective_id": "joyai-scnet",
                    "run_id": "run-main",
                },
            )
        )
        assert first["status"] == "pass"
        assert first["root_progress"] == 1.0
        assert first["prerequisite_progress"] == 1.0
        assert first["path_distance"] == 0.0
        assert first["elapsed"]["path_ms"] == 8000  # type: ignore[index]
        assert first["progress"]["verified_criterion_ids"] == [  # type: ignore[index]
            "writer",
            "snapshot",
            "language",
            "formal",
        ]
        assert first["active_blockers"] == []
        assert first["last_capability_evidence_seq"] == 8
        assert first["last_prerequisite_release_seq"] == 2
        assert first["next_action"] == "continue"

        completed = _data(
            await client.call_tool(
                "complete_research_objective",
                {
                    "workspace_root": str(tmp_path),
                    "objective_id": "joyai-scnet",
                    "evidence_event_ids": ["language-stage-b", "formal-events-background"],
                },
            )
        )
        assert completed["objective_status"] == "completed"

    async with Client(mcp) as reopened:
        second = _data(
            await reopened.call_tool(
                "get_research_snapshot",
                {
                    "workspace_root": str(tmp_path),
                    "objective_id": "joyai-scnet",
                    "run_id": "run-main",
                },
            )
        )
        trajectory = _data(
            await reopened.call_tool(
                "get_research_trajectory",
                {
                    "workspace_root": str(tmp_path),
                    "objective_id": "joyai-scnet",
                    "run_id": "run-main",
                    "view": "path",
                },
            )
        )
    assert second == first | {
        "objective_status": "completed",
        "objective": first["objective"] | {"status": "completed"},  # type: ignore[index]
    }
    assert trajectory["status"] == "pass"
    assert len(trajectory["events"]) == 8  # type: ignore[arg-type]
