---
status: accepted
---

# Add a research trajectory control kernel

NoA will store auto-research trajectory facts in the SQLite control plane as
append-only events and rebuildable snapshots. A trajectory records the
objective version, success criteria, experiments, elapsed runner-reported
time, branches, evidence scope, progress, and next-step guardrails.

The kernel separates four kinds of work: root capability validation,
necessary prerequisites, user-requested optimization, and exploration. A
prerequisite can unblock a root criterion, but it cannot verify that
criterion. When a prerequisite is released, the next-step gate can require
the runner to return to capability validation.

The kernel is responsible for validation, persistence, replay, progress,
drift, and guardrails. An external runner remains responsible for executing
experiments and reporting start, heartbeat, finish, metrics, artifacts, and
runner timestamps. NoA does not execute arbitrary shell commands or infer
external experiment time from MCP request duration.

The existing literature graph remains in LadybugDB, research artifacts remain
in CAS, and the existing document `stage` remains separate from trajectory
status. Legacy runs without event order, parent links, or timestamps are
marked `legacy_unknown`; migration does not invent missing history.

This phase intentionally excludes money, GPU-hours, Token cost, network cost,
and generic reserve/settle budget accounting. `max_sampling_requests` stays
as an independent Sampling safety limit.
