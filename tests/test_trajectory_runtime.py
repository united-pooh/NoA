from pathlib import Path

import pytest

from noa.runtime import ResearchRunStore, RunError, RunStage, TrajectoryRunStatus


def test_new_run_has_independent_active_trajectory_status(tmp_path: Path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    run = store.start_run("run-1", total_steps=2, max_sampling_requests=2)
    assert run.stage is RunStage.PREPARED
    assert run.trajectory_status is TrajectoryRunStatus.ACTIVE
    completed = store.advance("run-1", stage=RunStage.COMPLETED)
    assert completed.stage is RunStage.COMPLETED
    assert completed.trajectory_status is TrajectoryRunStatus.COMPLETED
    with pytest.raises(RunError, match="terminal"):
        store.record_sampling("run-1")
    with pytest.raises(RunError, match="terminal"):
        store.cancel("run-1")
    store.close()


def test_trajectory_status_transition_is_strict(tmp_path: Path) -> None:
    store = ResearchRunStore(tmp_path / "runs.sqlite3")
    store.start_run("run-1", total_steps=2, max_sampling_requests=2)
    paused = store.set_trajectory_status("run-1", TrajectoryRunStatus.PAUSED)
    assert paused.trajectory_status is TrajectoryRunStatus.PAUSED
    resumed = store.set_trajectory_status("run-1", TrajectoryRunStatus.ACTIVE)
    assert resumed.trajectory_status is TrajectoryRunStatus.ACTIVE
    done = store.set_trajectory_status("run-1", TrajectoryRunStatus.COMPLETED)
    assert done.trajectory_status is TrajectoryRunStatus.COMPLETED
    with pytest.raises(RunError, match="Cannot transition"):
        store.set_trajectory_status("run-1", TrajectoryRunStatus.ACTIVE)
    store.close()
