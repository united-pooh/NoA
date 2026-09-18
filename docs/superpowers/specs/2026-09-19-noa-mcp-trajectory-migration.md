# NoA Skill to MCP trajectory migration

## Decision

The MCP trajectory kernel is the sole runtime authority for an active research
process. The NoA Skill remains the human-facing workflow and Markdown import /
export surface. A Markdown edit never changes objective state, branch state,
elapsed time, evidence status, or completion state until it is imported as a
validated kernel event.

## Mapping existing records

| Existing NoA record | Kernel representation | Migration rule |
| --- | --- | --- |
| Evidence-layer command, configuration, run ID, metric, failure, or artifact | `observation_recorded`; use `experiment_started`, `experiment_heartbeat`, and `experiment_finished` for a bounded experiment | Copy source values into `result`, `metrics`, and `artifacts`. Set the declared `evidence_scope` and `evidence_status`; an observation does not become verification by being imported. |
| Decision-layer hypothesis, comparison, interpretation, trade-off, or decision | `decision_recorded` | Link the decision to its `criterion_id` and supporting event IDs. Preserve the distinction between an observed result, an interpretation, and an unverified hypothesis. |
| Next step, blocker, retry condition, or return criterion | a decision event with `intent`, followed by `propose_next_research_step` | The deterministic gate decides whether the runner may continue, continue prerequisite work, return to capability validation, request review, pause, or abandon the branch. |
| Branch or checkpoint described by the old log | `fork_research_path` plus ordered child events | Require an actual parent run and parent event. If the source does not establish either, leave the imported lineage unknown. |

The import process must reject unknown objective or criterion references. It
must preserve the source text and source location as event evidence, while
leaving fields absent from the source absent from the event. In particular,
the importer must not infer a timestamp from file order, a parent from nearby
headings, a branch from topic changes, or completion from a positive sentence.

## Legacy history

Runs created before the trajectory kernel are marked `legacy_unknown` by the
additive runtime migration. This is an explicit uncertainty state. It does not
mean that a run failed, and it does not authorize reconstructing missing
history. New events can establish facts from the point of import onward; they
cannot rewrite an old run into a complete trajectory.

## Export and compatibility

Exports are generated from the replayed objective, events, and snapshot. They
may retain the existing NoA headings for readability, but the exported
Markdown is a view and not a second state store. A later import reads only
explicitly represented facts and keeps all other fields unknown.

The product entry points therefore describe two complementary responsibilities:

1. The Skill gathers evidence, asks for a decision, and presents a readable
   record.
2. The MCP kernel validates, persists, replays, and guards the research
   trajectory.

No budget ledger is introduced by this migration.
