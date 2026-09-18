# NoA

NoA is an evidence-driven research-record system. It preserves the evidence, reasoning, and negative results needed to understand and revisit research decisions.

## Language

**Research evidence**:
Verifiable source material that can support or challenge a conclusion, such as configurations, commands, code changes, run identifiers, metrics, failures, environments, and artifacts.
_Avoid_: Proof, raw data

**Evidence layer**:
The part of a research record that identifies what was executed or observed and what is needed to reproduce it.
_Avoid_: Appendix, dump

**Decision layer**:
The part of a research record that connects a hypothesis, comparison, interpretation, trade-off, decision, and next step to the evidence layer.
_Avoid_: Summary, opinion

**Research log**:
The durable Markdown record maintained by NoA. It preserves both positive and negative results and retains earlier conclusions when later evidence changes a decision.
_Avoid_: Diary, changelog

**Research run**:
A bounded, resumable NoA workflow for collection, import, enrichment, review, refresh, or synthesis.
_Avoid_: Session, background job

**Research objective**:
An immutable, versioned statement of the capability being pursued, its success criteria, dependencies, and required evidence scopes.
_Avoid_: Task prompt, current step

**Trajectory event**:
An append-only, ordered record of an observation, proposal, experiment, decision, branch, or state transition in a research run.
_Avoid_: Log line, model message

**Trajectory snapshot**:
A rebuildable control-plane projection containing the current objective, branch, elapsed time, evidence-backed progress, drift, blockers, and next-step guardrail.
_Avoid_: Cached answer, research summary

**Root capability**:
A success criterion describing the final user-facing research capability. Engineering prerequisites and requested optimizations cannot verify it unless their evidence meets its declared acceptance scope.
_Avoid_: Implementation task, benchmark result

**Prerequisite**:
A bounded condition that enables or unblocks a root capability criterion and must declare the mainline criterion to return to after release.
_Avoid_: Optional improvement, final result

**Evidence scope**:
The stage and measurement boundary of an observation, such as pilot, batch training, single-stream, visual Stage A, language Stage B, end-to-end, or formal evaluation.
_Avoid_: Confidence, quality score

**Trajectory drift**:
The deterministic relationship between the current path and its objective, criteria, dependencies, common ancestor, and recent root-capability evidence.
_Avoid_: Topic similarity, model intuition

**Evidence packet**:
The minimal, source-attributed subset of research evidence disclosed to a model for one decision step.
_Avoid_: Context dump, prompt context

**Log proposal**:
A source-attributed candidate change to a research log that has not yet been applied.
_Avoid_: Draft entry, generated answer

**Research work**:
A distinct research contribution that may appear through multiple publications or versions.
_Avoid_: Paper, PDF

**Publication**:
A citable manifestation or version of a research work, identified when possible by a DOI, arXiv ID, or another persistent identifier.
_Avoid_: Work, file

**Document**:
A locally held representation of a publication, such as a PDF, TEI document, or extracted text, identified by its content hash.
_Avoid_: Publication, paper

**Claim**:
A normalized, reviewable statement attributed to a research work and grounded in one or more evidence passages.
_Avoid_: Summary, topic

**Evidence passage**:
A source-located excerpt from an abstract or document that supports the review of a claim or semantic relationship.
_Avoid_: Citation, context

**Source record**:
An immutable snapshot of metadata received from one scholarly source at a recorded time.
_Avoid_: Canonical metadata

**Collection plan**:
An approved, bounded specification for discovering and importing literature, including queries, filters, graph-expansion depth, result limits, and access budget.
_Avoid_: Search query, crawl

**Technical lineage**:
A traceable view of how research claims, methods, and tasks develop, branch, improve, or conflict over time.
_Avoid_: Timeline, literature summary

**Note**:
A versioned human-authored Markdown record attached to one or more graph entities.
_Avoid_: Claim, annotation field

**Lineage synthesis**:
A versioned research asset that narrates a technical lineage against a recorded graph snapshot and cited claims or evidence passages.
_Avoid_: Live summary, generated answer

**Review candidate**:
A proposed merge, claim, or semantic relationship that is not part of the confirmed graph until accepted with its evidence packet.
_Avoid_: Confirmed edge, suggestion

**Metadata assertion**:
A source-attributed statement about one normalized entity field. The entity's current value is a rebuildable projection over active assertions and human corrections.
_Avoid_: Canonical field, source record

**Relationship assertion**:
A source-attributed statement that a factual relationship exists, such as a citation or version link. The visible relationship is a projection over its active assertions.
_Avoid_: Semantic edge, confirmed claim

**Enrichment plan**:
An approved, bounded specification for extracting claims, methods, tasks, datasets, and semantic relationship candidates from selected research works.
_Avoid_: Collection plan, automatic extraction

**Collection**:
A named grouping of research entities used to scope collection, enrichment, review, search, and synthesis.
_Avoid_: Topic, search result
