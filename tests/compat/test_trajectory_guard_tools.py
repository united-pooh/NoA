from pathlib import Path
from typing import cast

from fastmcp import Client


def _data(result: object) -> dict[str, object]:
    return cast(dict[str, object], result.data)


async def test_joyai_prerequisite_release_routes_back_to_capability_validation(
    tmp_path: Path,
) -> None:
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
            "criterion_id": "language",
            "metric": "reader_alignment",
            "target": "verified",
            "role": "root_capability",
            "depends_on": ["writer"],
            "acceptance_scope": "language_stage_b",
        },
    ]
    async with Client(mcp) as client:
        created = await client.call_tool(
            "create_research_objective",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "joyai",
                "statement": "validate language aligned visual memory",
                "criteria": criteria,
            },
        )
        assert _data(created)["status"] == "pass"
        started = await client.call_tool(
            "start_research_run",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "joyai",
                "run_id": "run-main",
            },
        )
        assert _data(started)["status"] == "pass"
        released = await client.call_tool(
            "record_runner_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "joyai",
                "run_id": "run-main",
                "event_id": "e1",
                "event_kind": "prerequisite_unblocked",
                "idempotency_key": "e1",
                "supports_criterion_ids": ["writer"],
            },
        )
        assert _data(released)["status"] == "pass"
        continued = await client.call_tool(
            "record_runner_event",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "joyai",
                "run_id": "run-main",
                "event_id": "e2",
                "event_kind": "experiment_finished",
                "idempotency_key": "e2",
            },
        )
        assert _data(continued)["status"] == "pass"
        proposal = await client.call_tool(
            "propose_next_research_step",
            {
                "workspace_root": str(tmp_path),
                "objective_id": "joyai",
                "hypothesis": "keep optimizing the writer",
                "criterion_id": "writer",
                "work_class": "prerequisite",
                "work_source": "observed_blocker",
                "exit_condition": "writer checkpoint exists",
                "evidence_scope": "visual_stage_a",
            },
        )
        assert _data(proposal)["result"] == "return_to_capability_validation"
