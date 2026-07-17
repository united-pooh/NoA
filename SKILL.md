---
name: noa
description: Maintain evidence-driven, reproducible Markdown research and experiment logs from raw notes, code changes, commands, run outputs, metrics, and decisions. Use when the user invokes $noa, mentions NoA or 生盐诺亚, or asks to create, update, organize, summarize, or standardize a research log, experiment log, negative-result record, lab notebook, or research-process journal.
---

# NoA（生盐诺亚）

Turn research activity into a durable decision record. Preserve the reasoning path, the evidence that changed the decision, and the negative results that prevent repeated work.

NoA is not a minute-by-minute diary and not a results-polishing assistant. Its central question is:

> Is the evidence strong enough to change the current research or engineering decision?

## Work in two layers

Maintain both layers when the available material supports them:

1. **Evidence layer**: commands, commits, run IDs, configurations, datasets, environments, raw metrics, failures, and artifacts.
2. **Decision layer**: motivation, falsifiable hypothesis, comparison, interpretation, tradeoff, decision, transferable lesson, and next step.

The published log entry should stay readable. Keep raw details concise or link to their source rather than dumping unfiltered terminal output.

## Resolve the task and target

First determine what the user authorized:

- For analysis, explanation, or style review, inspect the material and respond read-only.
- For a draft, return a complete Markdown entry without editing files.
- For create, maintain, append, or update requests, edit the requested log and verify the result.

Resolve the log path in this order:

1. Use the path explicitly supplied by the user.
2. Otherwise, search the active repository for an existing `dev/LOG.md`, `LOG.md`, `RESEARCH_LOG.md`, or `docs/research-log.md`.
3. If the user asked to create a new log and no candidate exists, use `dev/LOG.md` for an experiment-heavy code repository and `RESEARCH_LOG.md` otherwise. State the selected path.

Always read the existing log before changing it. Preserve its language, title hierarchy, chronology, terminology, and already-recorded conclusions.

## Inspect the real evidence first

When a repository, experiment result, log, notebook, chart, dataset, task page, or command output is referenced, inspect that artifact before writing the entry.

Collect the following when available:

- research question and motivation;
- falsifiable hypothesis;
- baseline and control conditions;
- independent variables and fixed conditions;
- repository, branch, commit, PR, or patch;
- exact command, configuration, run ID, seed, dataset version, hardware, and software environment;
- quality metrics and uncertainty;
- step efficiency, wall-clock time, throughput, memory, compute, cost, and stability when relevant;
- implementation difficulty, code growth, maintenance burden, and known gaps;
- direct observations, interpretations, decision, and open questions.

Never invent missing details. If a missing fact would materially change the conclusion, ask up to five concise questions. If the user asks for an immediate draft, mark the gap as `[待补]` instead.

## Choose the right entry depth

Use the smallest structure that preserves the research value:

- **Short result**: one idea, clear comparison, clear decision. Record the attempt, evidence, and decision in a few paragraphs or bullets.
- **Standard experiment**: meaningful hypothesis, baseline, variants, and quantitative result. Use sections such as motivation, method, results, and conclusion.
- **Deep investigation**: multiple implementation paths, surprising failures, substantial engineering work, or unresolved mechanisms. Preserve the evolution of the approach, hard parts, tables, interpretation, decision, and retry conditions.

Do not fill empty headings merely to satisfy a template. Every section must answer a real research question.

## Build the evidence-to-decision chain

Organize each substantive entry around this sequence:

1. Context, source of the idea, or observed problem.
2. Falsifiable hypothesis and success criterion.
3. Baseline, controls, and experimental design.
4. Variants attempted and important implementation details.
5. Failures, traps, and changes made during investigation.
6. Quantitative and qualitative results.
7. Direct observations separated from explanations or hypotheses.
8. Benefit versus cost and complexity.
9. Explicit decision.
10. Transferable lessons, unresolved questions, and next step.

Use this as a reasoning order, not a mandatory list of headings.

## Write in the NoA style

- Follow the user's language. Default to concise technical Chinese when the existing log is Chinese.
- Use first-person technical narrative when it clarifies how the investigation evolved.
- Prefer exact numbers and relative changes over vague adjectives.
- Compare against a named baseline. State when two runs are not strictly comparable.
- Use tables for sweeps and multi-variant comparisons.
- Use minimal code, formulas, or commands only when they explain the mechanism or enable reproduction.
- Treat negative, null, and mixed results as first-class research outcomes.
- Record counterintuitive findings and unexplained behavior without forcing a story.
- Separate labels explicitly when confusion is possible:
  - **观察**: directly measured or verified fact.
  - **解释**: current causal interpretation.
  - **推测**: unverified possibility.
- Evaluate the metric that matters to the actual objective. For systems and model training, step quality alone is insufficient when wall-clock time, throughput, memory, cost, or operational complexity changes.
- Include code complexity and maintenance burden in the decision when they are material.
- Use decisive action language: `采用`, `设为默认`, `保持可选`, `不合并`, `回退`, `需要复现`, or `满足条件后重试`.
- Do not erase an earlier conclusion. When new evidence reverses it, explain what changed.

## Format entries

Maintain reverse chronological order unless the existing log clearly uses another convention.

Use this heading form when compatible with the existing file:

```markdown
## YYYY-MM-DD：实验主题（状态）
```

Choose the status from evidence, for example:

- `进行中`
- `正面结果`
- `负面结果`
- `混合结果`
- `待复现`

Do not label an unfinished experiment as positive or negative prematurely.

A full entry may use a subset of these sections:

```markdown
### 背景 / 动机
### 假设与成功标准
### 实验设计
### 实现与踩坑
### 结果
### 观察与解释
### 关键经验
### 可复现信息
### 结论 / 决定
### 待办（如果重新尝试）
```

## Maintain a living research record

When new evidence arrives:

1. Decide whether it updates an active entry, contradicts an older entry, or deserves a new dated entry.
2. Preserve the earlier path and negative results.
3. Update `进行中` only when new evidence changes its factual state.
4. Consolidate repetitive progress notes once a milestone is complete, while retaining run references needed for reproduction.
5. Cross-reference related earlier entries instead of duplicating their full content.

## Verify before finishing

For file mutations:

1. Re-read the changed entry in context.
2. Confirm chronology and Markdown structure.
3. Check that reported numbers match the source artifacts.
4. Check that observation and interpretation are not conflated.
5. Check that the final decision follows from the declared success criterion.
6. Report the file changed, the entry added or updated, and any `[待补]` information.

For chat-only drafts, output the finished Markdown entry first. Keep commentary outside the entry brief.
