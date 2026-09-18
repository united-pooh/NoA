from __future__ import annotations

from pathlib import Path
from typing import cast

from fastmcp import Client


def _data(result: object) -> dict[str, object]:
    return cast(dict[str, object], result.data)


async def test_trajectory_mcp_roundtrip_replays_identical_snapshot(tmp_path: Path) -> None:
    from noa.server import mcp

    criteria = [
        {
            "criterion_id": "capability",
            "metric": "proof",
            "target": "exists",
            "role": "root_capability",
            "acceptance_scope": "pilot",
        }
    ]
    async with Client(mcp) as client:
        created = await client.call_tool(
            "create_research_objective",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "statement": "validate trajectory replay",
                "criteria": criteria,
                "facets": [{"kind": "topic", "value": "trajectory", "weight": 1.0}],
            },
        )
        assert _data(created)["status"] == "pass"

        started = await client.call_tool(
            "start_research_run",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-main",
            },
        )
        assert _data(started)["status"] == "pass"

        appended = await client.call_tool(
            "append_trajectory_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-main",
                "event_id": "e1",
                "event_kind": "experiment_finished",
                "idempotency_key": "e1",
                "supports_criterion_ids": ["capability"],
                "evidence_scope": "pilot",
                "evidence_status": "verified",
                "metrics": {"proof": "available"},
                "artifacts": ["proof.json"],
            },
        )
        assert _data(appended)["status"] == "pass"

        forked = await client.call_tool(
            "fork_research_path",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "parent_run_id": "run-main",
                "parent_event_id": "e1",
                "child_run_id": "run-branch",
                "branch_id": "branch-a",
            },
        )
        assert _data(forked)["status"] == "pass"

        duplicate_start = await client.call_tool(
            "start_research_run",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-main",
            },
        )
        assert _data(duplicate_start)["type"] == "duplicate_run"

        child = await client.call_tool(
            "append_trajectory_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-branch",
                "event_id": "b2",
                "event_kind": "experiment_finished",
                "idempotency_key": "b2",
                "metrics": {"detail": "branch"},
            },
        )
        assert _data(child)["status"] == "pass"

        mainline_after_fork = await client.call_tool(
            "append_trajectory_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-main",
                "event_id": "e2",
                "event_kind": "experiment_finished",
                "idempotency_key": "e2",
                "metrics": {"detail": "mainline"},
            },
        )
        assert _data(mainline_after_fork)["status"] == "pass"

        first = await client.call_tool(
            "get_research_snapshot",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-branch",
            },
        )
        first_data = _data(first)
        assert first_data["status"] == "pass"
        assert first_data["branch"]["common_ancestor_seq"] == 1  # type: ignore[index]
        assert first_data["progress"]["root_criterion_ids"] == ["capability"]  # type: ignore[index]
        basis_ids = first_data["drift"]["basis_event_ids"]  # type: ignore[index]
        assert "e2" not in basis_ids

    async with Client(mcp) as reopened:
        second = await reopened.call_tool(
            "get_research_snapshot",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-1",
                "run_id": "run-branch",
            },
        )
    assert _data(second) == first_data


async def test_completed_objective_rejects_late_event(tmp_path: Path) -> None:
    from noa.server import mcp

    async with Client(mcp) as client:
        await client.call_tool(
            "create_research_objective",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-2",
                "statement": "complete one capability",
                "criteria": [
                    {
                        "criterion_id": "capability",
                        "metric": "proof",
                        "target": "exists",
                        "role": "root_capability",
                        "acceptance_scope": "pilot",
                    }
                ],
            },
        )
        await client.call_tool(
            "start_research_run",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-2",
                "run_id": "run-main",
            },
        )
        await client.call_tool(
            "append_trajectory_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-2",
                "run_id": "run-main",
                "event_id": "e1",
                "event_kind": "experiment_finished",
                "idempotency_key": "e1",
                "supports_criterion_ids": ["capability"],
                "evidence_scope": "pilot",
                "evidence_status": "verified",
                "metrics": {"proof": True},
                "artifacts": ["proof.json"],
            },
        )
        completed = await client.call_tool(
            "complete_research_objective",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-2",
                "evidence_event_ids": ["e1"],
            },
        )
        assert _data(completed)["objective_status"] == "completed"
        late = await client.call_tool(
            "append_trajectory_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "objective-2",
                "run_id": "run-main",
                "event_id": "e2",
                "event_kind": "experiment_finished",
                "idempotency_key": "e2",
            },
        )
        assert _data(late)["status"] == "error"
        assert _data(late)["type"] == "objective_terminal"
