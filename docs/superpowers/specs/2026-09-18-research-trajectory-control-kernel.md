# Research Trajectory Control Kernel Specification

## 1. Purpose

The kernel gives an auto-research runner a durable, auditable answer to five
questions: what the original objective was, where the current path is, how
long the runner-reported work took, which evidence verifies the objective,
and whether the next step should continue or return to the mainline.

The first acceptance case is the JoyAI/SCNet experiment: 30 FPS continuous
visual input, low-cost full-frame change detection, focused high-resolution
processing, bounded visual memory, language-model reading, and formal event
versus background evaluation. HCU optimization and input/dtype fixes may be
valid prerequisites; they do not prove language alignment or final gating
ability.

## 2. Objective contract

`ResearchObjective` is immutable by version. A revision creates a new version
and records the base version it supersedes. Its criteria use these roles:

- `root_capability`: final user-facing capability;
- `prerequisite`: a condition needed to run or measure a root criterion;
- `requested_optimization`: an explicitly requested engineering target;
- `exploration`: a hypothesis or optional investigation.

Each criterion declares `depends_on`, `blocking`, and `acceptance_scope`.
Dependencies use only `enables`, `blocks`, `validates`, and `returns_to`.

Objective status is `active`, `completed`, `superseded`, or `paused`. An
objective becomes `completed` only when every blocking root criterion has
verified evidence at its declared scope. Additional work requires a new
objective version or an explicit `objective_reopened` event.

## 3. Work and evidence contract

Every proposal and event declares:

- `work_class`: capability validation, prerequisite, requested optimization,
  or exploration;
- `work_source`: user request, observed blocker, hypothesis, or automatic
  follow-up;
- `blocks_criterion_ids` and `returns_to_criterion_ids`;
- `exit_conditions`;
- `evidence_scope`: `pilot`, `batch_training`, `single_stream`,
  `visual_stage_a`, `language_stage_b`, `end_to_end`, or
  `formal_evaluation`.

Evidence status is `observed`, `verified`, `insufficient`, `blocked`, or
`unknown`. Evidence at a narrower scope cannot verify a criterion requiring
a broader scope. For example, a batch FPS result cannot verify single-stream
30 FPS, and a visual Stage A loss cannot verify language Stage B alignment.

## 4. Event and snapshot behavior

Events are append-only, belong to one run, use a monotonic sequence, and
reference their parent event. An idempotency key makes retries return the
original event. Experiment elapsed time comes from runner `started_at` and
`ended_at`; missing finish data remains `unknown`.

Snapshots are rebuildable projections. They include objective/version,
branch/common ancestor, branch and path elapsed time, root and prerequisite
progress, active blockers, last capability evidence, last prerequisite
release, drift, validation stagnation, and next action.

Progress is calculated separately for root capability and prerequisites.
Event count, elapsed time, HCU, throughput, and loss cannot substitute for
verified criterion evidence.

## 5. Drift and return guardrail

The deterministic evaluator receives the objective, replayable event history,
branch context, and dependency context. It calculates:

- path distance from the common ancestor;
- goal drift from objective facets, hypotheses, metrics, and constraints;
- root capability progress;
- prerequisite progress;
- consecutive events without new root evidence after a prerequisite release;
- `return_due` when the released prerequisite branch has no new blocker
  evidence or has met its exit condition.

The gate returns one of:
`continue`, `continue_prerequisite`, `return_to_capability_validation`,
`checkpoint_review`, `pause_for_human`, or `abandon_branch`.

It must not return `continue` when a prerequisite is released but the next
proposal has no return criterion, when the current scope cannot support the
claim, or when a completed objective is being extended without a new version.

## 6. State and compatibility

Trajectory status is independent from the existing literature `stage`.
Existing `advance` remains a compatibility wrapper but can only perform
legal transitions and append a corresponding event. Terminal runs reject
Sampling and cancellation updates. Legacy rows migrate additively and expose
`legacy_unknown` rather than fabricated events.

Budget accounting is explicitly outside this specification. Sampling request
limits remain a protocol safety mechanism only.
