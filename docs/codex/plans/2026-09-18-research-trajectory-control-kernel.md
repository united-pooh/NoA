# Research Trajectory Control Kernel Implementation Plan

> **For Codex workers:** Implement task-by-task. Use `update_plan` to track progress, keep only one step in progress at a time, edit files with the repo's established tools and `apply_patch` for manual changes, and run the exact verification commands listed below. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 NoA 从“可恢复的步骤计数器”扩展为 MCP kernel 内的可审计 research trajectory：记录研究目标、实验路径、分支、真实耗时、结果与决策，并计算当前路径相对目标和主线的偏离，让 auto-research 模型在选择下一步前获得稳定的 trajectory snapshot。

**Architecture:** Research Objective、Trajectory Event、分支关系和运行状态属于 SQLite control plane；LadybugDB 继续保存文献知识图谱，CAS 保存实验产物和日志对象。轨迹采用 append-only 事件作为事实源，运行快照是可重建的物化投影。MCP kernel 负责校验、重放、进度/偏离计算和下一步闸门；外部 auto-research runner 负责执行实验并通过 MCP 上报开始、心跳、结束、指标和耗时。预算账本、GPU/金钱/Token 成本核算暂不进入本阶段；现有 `max_sampling_requests` 仅保留为 Sampling 安全上限。

**Tech Stack:** Python 3.11、SQLite/WAL、FastMCP 4、MCP SDK v2、现有 `ResearchRunStore`、Pydantic/标准库、pytest、Ruff、strict mypy。

---

## 现状、范围和不变量

当前 `src/noa/runtime.py` 的 `ResearchRun` 只保存 stage、step、Sampling 次数、任意 payload 和时间戳；`advance_research_run` 只递增 step。它没有事件、父节点、目标、实验耗时、主线或偏离信息。现有 `TechnicalLineage` 是文献关系视图，不作为运行轨迹事实源。

本阶段必须满足以下不变量：

- 目标是版本化且不可原地修改；目标变化产生新版本。
- 轨迹事件 append-only；同一 `idempotency_key` 重放返回原事件，不复制事件。
- 每个事件属于一个 run，有单调 `seq` 和可验证的 `parent_event_id`。
- 分支通过显式 fork 创建，父 run、共同祖先和目标版本不可伪造。
- 运行状态分成两个轴：现有文献业务 `stage`（collecting/acquiring/enriching/review_pending）和新的轨迹 `status`（active/paused/completed/cancelled/abandoned）；两个轴都只能按显式 transition table 转移，调用方不能任意覆盖。
- 时间字段区分 runner 报告的实验耗时、MCP 观察到的请求时间和人工等待时间；缺少测量值时返回 `unknown`，不填零。
- 进度只由带证据的 success criterion 状态计算；事件数量和耗时不能冒充进度。
- 成功条件必须区分根能力验收、必要工程前置、用户明确要求的优化和探索性工作；前置条件完成不等于根能力完成。
- 每个工程前置工作必须声明它阻塞的根能力、解除阻塞的证据和完成后返回的验收步骤；阻塞解除后继续留在该分支需要新的理由或用户明确授权。
- 证据必须带范围和阶段：pilot/局部训练/批量吞吐/视觉 Stage A 不能自动证明端到端单路 30 FPS、语言对齐或最终能力。
- 同一 topic、同一 branch、同一 criterion 引用也可能发生“手段替代目的”；偏离 evaluator 必须同时计算根能力进展、依赖进展和解除阻塞后的主线回归状态。
- 偏离评分由 kernel 根据结构化 facet、criterion、hypothesis 和分支路径确定性计算；模型只能提供带证据的解释。
- 本阶段不增加 money、GPU-hours、Token cost、network cost 或通用预算 reserve/settle 字段。
- NoA 不执行通用 shell 或实验；auto-research runner 通过 MCP event adapter 接入。

### JoyAI/SCNet 失效模式必须被一等建模

本计划以归档会话“调研视觉疲劳编码机制”作为回归样例。它的根目标是：连续 30 FPS 原生视频输入、低成本全画面变化感知、对有效事件进行高分辨率焦点计算、形成有界视觉记忆并完成 JoyAI/Qwen 语言读取和事件/背景评测。8 卡利用率、解码路径、批量教师前向、DDP 和 dtype 修复有些是用户明确要求，有些是解除真实阻塞的必要工作，不能被简单判为偏离；但它们也不能替代语言对齐和最终门控验收。

因此轨迹必须能明确回答：

1. 当前工作是根能力验收、必要前置、用户指定优化还是探索；
2. 它阻塞哪个 criterion，解除阻塞的证据是什么；
3. 前置条件完成后应返回哪个主线步骤；
4. 当前证据的范围是 pilot、批量训练、单路运行、视觉 Stage A、语言 Stage B 还是正式能力评测；
5. 根能力多久没有新增证据，是否已经在解除阻塞后继续局部优化。

这组字段不引入预算账本，也不把必要工程工作误判为浪费；它只防止工程进展被错误计入最终能力进度。

## 文件落点

- Create: `docs/superpowers/specs/2026-09-18-research-trajectory-control-kernel.md` — 冻结领域词汇、事件 schema、状态转移、偏离算法和 MCP 契约。
- Create: `docs/adr/0013-add-research-trajectory-control-kernel.md` — 记录 trajectory 进入 MCP control plane、runner/kernel 分离和本阶段不做预算的决策。
- Create: `src/noa/trajectory.py` — 不可变目标、事件、分支上下文、进度和偏离值对象，以及纯 evaluator。
- Create: `src/noa/trajectory_store.py` — SQLite schema、迁移、append-only event store、快照投影和事件重放。
- Modify: `src/noa/runtime.py` — 把现有 ResearchRun 接到 objective、trajectory store、合法状态转移和时间投影。
- Modify: `src/noa/server.py` — 新增目标、轨迹、分支、快照和下一步闸门 MCP tools；统一 trajectory 工具错误 envelope。
- Modify: `src/noa/compat/sampling.py` — 保持兼容性探针不变；为研究运行提供可选的 request/response/failure 轨迹事件 hook。
- Create: `tests/test_trajectory.py` — 值对象、进度、偏离和路径重放的纯单元测试。
- Create: `tests/compat/test_trajectory_tools.py` — MCP tools、SQLite 重启、幂等、分支和 auto-research runner fixture 测试。
- Modify: `tests/compat/test_runtime.py` — 合法状态转移、旧 run 迁移和 Sampling event hook 回归。
- Modify: `tests/compat/test_packaging.py` — 将新增 trajectory source、tests 和 docs 纳入精确 sdist allowlist。
- Modify: `CONTEXT.md` — 增加 Research Objective、Trajectory Event、Trajectory Snapshot、branch 和 drift 术语。
- Modify: `README.md`, `SKILL.md`, `docs/package/README.md`, `agents/openai.yaml`, `pyproject.toml` — 将旧 Skill/compatibility-spike 叙事迁移到 MCP kernel；保留旧研究日志语义到 trajectory event 的字段映射。

### Task 1: 冻结 Research Trajectory 契约

**Files:**
- Create: `docs/superpowers/specs/2026-09-18-research-trajectory-control-kernel.md`
- Create: `docs/adr/0013-add-research-trajectory-control-kernel.md`
- Modify: `CONTEXT.md`

- [ ] **Step 0: 冻结目标分层和依赖回归契约**

在规格和 ADR 中增加以下枚举和值对象：

```text
criterion_role = root_capability | prerequisite | requested_optimization | exploration
work_class = capability_validation | prerequisite | requested_optimization | exploration
work_source = user_request | observed_blocker | hypothesis | automatic_followup
evidence_scope = pilot | batch_training | single_stream | visual_stage_a | language_stage_b | end_to_end | formal_evaluation
evidence_status = observed | verified | insufficient | blocked | unknown
```

每个 criterion 必须声明 `role`、`depends_on`、`blocking`、`acceptance_scope`；每个 proposal/event 必须声明 `work_class`、`work_source`、`blocks_criterion_ids`、`returns_to_criterion_ids`、`exit_conditions` 和 `evidence_scope`。依赖边只允许 `enables`、`blocks`、`validates`、`returns_to` 四种关系。

规格必须冻结以下状态转移：

```text
prerequisite_started
  -> prerequisite_unblocked
  -> return_due
  -> capability_validation_started
```

`prerequisite_unblocked` 不能自动使 root criterion 变成 verified；如果下一个事件仍是同一前置分支，则 gate 必须要求新的 blocker evidence 或用户授权，并可返回 `return_to_capability_validation`。

- [ ] **Step 1: 写出目标、事件和快照 schema**

在规格中冻结以下 JSON 形状：

```json
{
  "objective_id": "obj_0198cd4e-0000-7a31-8f25-000000000001",
  "version": 1,
  "status": "active",
  "statement": "提升验证准确率，同时保持延迟约束",
  "facets": {
    "topic": ["data augmentation"],
    "deliverable": ["validated model"],
    "metric": ["validation_accuracy", "p95_latency_ms"],
    "constraint": ["latency <= 50ms"],
    "method": ["ablation"]
  },
  "criteria": [
    {
      "id": "accuracy",
      "metric": "validation_accuracy",
      "target": ">=0.85",
      "role": "root_capability",
      "depends_on": ["writer_training"],
      "blocking": true,
      "acceptance_scope": "formal_evaluation"
    }
  ]
}
```

事件必须包含 `event_id`、`run_id`、`seq`、`parent_event_id`、`branch_id`、`event_kind`、`occurred_at`、`intent`、`result`、`metrics`、`artifacts`、`outcome` 和 `idempotency_key`。实验开始/结束事件必须包含 `experiment_id` 和 runner 报告的 `started_at`、`ended_at` 或 `duration_ms`。

目标生命周期必须显式记录 `active → completed | superseded | paused`。所有 root criterion 达到其 acceptance scope 后，kernel 产生 `objective_completed` 状态；后续工作必须创建新的 objective version 或显式 `objective_reopened`，不能静默继续污染已完成目标。

快照必须包含 `objective`、`run`、`branch`、`elapsed`、`progress`、`drift`、`recent_events` 和 `next_action`；不得包含本阶段未实现的预算字段。

- [ ] **Step 2: 冻结偏离、进展和回归向量的定义**

明确 `DriftReport` 包含 `scope_drift`、`hypothesis_drift`、`metric_drift`、`constraint_drift`、`branch_drift`、`root_progress`、`prerequisite_progress`、`validation_stagnation`、`return_due`、`score`、`basis_event_ids` 和 `reasons`。其中 `validation_stagnation` 表示根能力 criterion 在前置条件解除后连续多少事件没有新增证据，不表示前置工作本身没有价值。本阶段不加入 `resource_drift`，因为预算暂不纳入。

增加 `EvidenceScope` 和 `CriterionProgress`：同一 metric 只有在满足 criterion 的 `acceptance_scope` 后才能进入 `verified`；范围较窄的证据只能标记 `observed` 或 `insufficient`。例如，8 卡 HCU pilot 不得直接验证 single-stream end-to-end 30 FPS，视觉 Stage A loss 不得直接验证 language Stage B 对齐。

- [ ] **Step 3: 记录状态迁移和旧数据策略**

冻结 `prepared → active → paused → completed/abandoned/cancelled` 的轨迹 status；保留现有 collection/acquiring/enriching/review_pending 作为业务 stage，不把分支状态硬塞进旧 stage。旧 `research_runs` 行迁移后标记 `trajectory_state="legacy_unknown"`，只能生成 synthetic root snapshot，不能伪造历史事件。

- [ ] **Step 4: 写 ADR 并做规格审阅**

ADR 必须说明：轨迹事实在 SQLite control plane；知识事实仍在 LadybugDB；产物仍在 CAS；runner/kernel 分离；Sampling 上限保留但不视为研究预算。

### Task 2: 实现纯轨迹领域模型和确定性 evaluator

**Files:**
- Create: `src/noa/trajectory.py`
- Create: `tests/test_trajectory.py`

- [ ] **Step 1: 写失败测试：目标和事件校验**

覆盖：空 statement、重复 criterion ID、未知 facet、负 duration、结束时间早于开始时间、空事件 kind、重复 hypothesis 引用和错误 branch parent 都必须失败。

运行：

```bash
uv run pytest tests/test_trajectory.py -q
```

预期：新测试在实现前失败。

- [ ] **Step 2: 实现不可变值对象**

实现以下类型，不依赖 SQLite、FastMCP 或环境变量：

```python
@dataclass(frozen=True)
class ObjectiveFacet:
    kind: str
    value: str
    weight: float

@dataclass(frozen=True)
class ResearchObjective:
    objective_id: str
    version: int
    statement: str
    facets: tuple[ObjectiveFacet, ...]
    criteria: tuple[SuccessCriterion, ...]
    status: str
    supersedes_version: int | None
    completed_at: UtcInstant | None
    completion_evidence_event_ids: tuple[str, ...]

@dataclass(frozen=True)
class SuccessCriterion:
    criterion_id: str
    metric: str
    target: str
    role: str
    depends_on: tuple[str, ...]
    blocking: bool
    acceptance_scope: str

@dataclass(frozen=True)
class TrajectoryIntent:
    hypothesis_ids: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    facets: tuple[ObjectiveFacet, ...]
    action: str
    work_class: str
    work_source: str
    blocks_criterion_ids: tuple[str, ...]
    returns_to_criterion_ids: tuple[str, ...]
    exit_conditions: tuple[str, ...]
    evidence_scope: str

@dataclass(frozen=True)
class TrajectoryEvent:
    event_id: str
    run_id: str
    seq: int
    parent_event_id: str | None
    branch_id: str
    event_kind: str
    occurred_at: UtcInstant
    started_at: UtcInstant | None
    ended_at: UtcInstant | None
    intent: TrajectoryIntent | None
    result: Mapping[str, object]
    metrics: Mapping[str, object]
    artifacts: tuple[str, ...]
    outcome: str
    source: str
    idempotency_key: str
    supports_criterion_ids: tuple[str, ...]
    blocked_criterion_ids: tuple[str, ...]
    evidence_scope: str
    evidence_status: str

@dataclass(frozen=True)
class BranchContext:
    run_id: str
    root_run_id: str
    mainline_run_id: str
    parent_run_id: str | None
    branch_depth: int
    fork_seq: int
    common_ancestor_seq: int | None

@dataclass(frozen=True)
class DriftReport:
    path_distance: float | None
    goal_drift: float | None
    score: float | None
    root_progress: float | None
    prerequisite_progress: float | None
    validation_stagnation_events: int
    return_due: bool
    basis_event_ids: tuple[str, ...]
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class ProgressReport:
    verified_criterion_ids: tuple[str, ...]
    pending_criterion_ids: tuple[str, ...]
    fraction: float | None
    root_criterion_ids: tuple[str, ...]
    prerequisite_criterion_ids: tuple[str, ...]
    evidence_status_by_criterion: Mapping[str, str]

@dataclass(frozen=True)
class TrajectorySnapshot:
    run_id: str
    objective_status: str
    branch_elapsed_ms: int | None
    path_elapsed_ms: int | None
    duration_source: str
    progress: ProgressReport
    drift: DriftReport
    next_action: str
    active_blockers: tuple[str, ...]
    last_capability_evidence_seq: int | None
    last_prerequisite_release_seq: int | None

def evaluate_progress(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
) -> ProgressReport:
    pass

def evaluate_drift(
    objective: ResearchObjective,
    events: Sequence[TrajectoryEvent],
    path_context: BranchContext,
    dependency_context: Mapping[str, object],
) -> DriftReport:
    pass
```

`evaluate_progress` 只统计满足 `acceptance_scope` 的 `verified` criterion，并同时输出 root/prerequisite 两组进度；没有 criteria 或 evidence 时返回 `fraction=None`。`evaluate_drift` 必须接收可重放的历史事件窗口和依赖上下文，而不是只接收当前单个 event。它分开计算 `path_distance`、`goal_drift`、`root_progress`、`prerequisite_progress` 和 `validation_stagnation`，使用 weighted Jaccard/facet coverage、未定义 metric 引用、硬约束违反、连续无根能力证据事件、解除阻塞后的回归状态和共同祖先深度，并返回可重算 basis；第一版不使用 embedding 或 LLM 距离。

- [ ] **Step 3: 运行纯 evaluator 测试**

```bash
uv run pytest tests/test_trajectory.py -q
```

预期：所有目标、事件、进度、偏离和确定性重放测试通过。

- [ ] **Step 4: 运行静态检查**

```bash
uv run ruff check src/noa/trajectory.py tests/test_trajectory.py
uv run mypy src/noa/trajectory.py
```

预期：Ruff 和 strict mypy 通过。

### Task 3: 增加 SQLite append-only trajectory store 和迁移

**Files:**
- Create: `src/noa/trajectory_store.py`
- Modify: `src/noa/runtime.py`
- Create: `tests/compat/test_trajectory_tools.py`
- Modify: `tests/compat/test_runtime.py`

- [ ] **Step 1: 写失败测试：schema、顺序、幂等和重启**

测试必须验证：

1. 创建 objective 和 run 后，事件按 `seq` 追加。
2. 缺失 parent、跳号、错误 branch 和重复 event ID 被拒绝。
3. 相同 idempotency key 返回同一 event，不产生第二条记录。
4. 关闭数据库后重开，事件、objective 和 snapshot 完整恢复。
5. 旧 `research_runs` 表可以 additive migration，旧行状态为 `legacy_unknown`。
6. 所有 root criterion 完成后 objective 进入 `completed`；普通事件不能继续追加；revision 会生成新版本并保留 `supersedes_version`。

- [ ] **Step 2: 建立 SQLite schema**

新增表：

```sql
CREATE TABLE research_objectives (
    objective_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    statement TEXT NOT NULL,
    facets_json TEXT NOT NULL,
    criteria_json TEXT NOT NULL,
    dependency_graph_json TEXT NOT NULL,
    objective_status TEXT NOT NULL,
    supersedes_version INTEGER,
    completed_at TEXT,
    completion_evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (objective_id, version)
);
CREATE TABLE trajectory_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    parent_event_id TEXT,
    branch_id TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    intent_json TEXT,
    result_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    artifacts_json TEXT NOT NULL,
    outcome TEXT NOT NULL,
    source TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    supports_criterion_ids_json TEXT NOT NULL,
    blocked_criterion_ids_json TEXT NOT NULL,
    evidence_scope TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, seq),
    UNIQUE (run_id, idempotency_key)
);
CREATE TABLE trajectory_snapshots (
    run_id TEXT PRIMARY KEY,
    last_event_seq INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

`trajectory_events` 的 elapsed 由 `started_at`/`ended_at` 计算；未结束的 experiment duration 为 `unknown`。所有 JSON 在写入前 canonicalize，所有写入使用 SQLite transaction。`append_event` 必须接受 `expected_seq`，按 `(run_id, idempotency_key)` 做 digest 冲突检测；过期 snapshot、乱序 seq、错误 parent、依赖引用和 payload 冲突都 fail-closed。依赖状态和 root/prerequisite 进度必须能从事件重放得到，不能只存在于易失内存。

迁移函数必须以 `PRAGMA user_version` 或等价的显式 schema version 控制 `research_runs` 的 additive columns：`objective_id`、`parent_run_id`、`root_run_id`、`mainline_run_id`、`branch_depth`、`started_at`、`ended_at`、`last_event_seq`、`trajectory_status`、`trajectory_state`。迁移在重开 WAL 数据库后必须幂等。

- [ ] **Step 3: 实现 `TrajectoryStore`**

实现以下方法：

```python
create_objective(objective: ResearchObjective) -> ResearchObjective
load_objective(objective_id: str, version: int | None = None) -> ResearchObjective
revise_objective(objective_id: str, base_version: int, objective: ResearchObjective) -> ResearchObjective
complete_objective(objective_id: str, version: int, evidence_event_ids: tuple[str, ...]) -> ResearchObjective
append_event(event: TrajectoryEvent, *, expected_seq: int) -> TrajectoryEvent
load_events(run_id: str, *, limit: int = 100, after_seq: int = 0) -> list[TrajectoryEvent]
load_snapshot(run_id: str) -> TrajectorySnapshot
fork_run(parent_run_id: str, parent_event_id: str, child_run_id: str, branch_id: str) -> ResearchRun
```

`append_event` 在同一个 transaction 中写事件、更新 `trajectory_snapshots`，并用 `evaluate_progress`/`evaluate_drift` 重算当前快照。快照损坏时允许从事件重放重建。`load_snapshot` 同时返回 `branch_elapsed_ms`、`path_elapsed_ms`、`duration_source`、`branch_depth`、`hops_from_mainline`、`last_common_checkpoint`、`root_progress`、`prerequisite_progress`、`active_blockers`、`last_capability_evidence_seq`、`last_prerequisite_release_seq` 和 `return_due`。

- [ ] **Step 4: 接入 `ResearchRunStore`**

扩展 `ResearchRun`：`objective_id`、`parent_run_id`、`root_run_id`、`mainline_run_id`、`branch_depth`、`started_at`、`ended_at`、`last_event_seq`、`trajectory_status`、`trajectory_state`。保留旧 `stage` 作为文献业务 phase；将 `advance` 改为兼容 wrapper，内部只能通过合法 transition table 和 event 追加推进。终态不能被 `cancel` 或 `record_sampling` 覆盖；Sampling 只能在 active run 上计数。

- [ ] **Step 5: 运行控制面测试**

```bash
uv run pytest tests/compat/test_trajectory_tools.py tests/compat/test_runtime.py -q
```

预期：迁移、重启、事件顺序、幂等和状态转移全部通过。

### Task 4: 增加分支、耗时和轨迹 MCP tools

**Files:**
- Modify: `src/noa/server.py`
- Modify: `src/noa/runtime.py`
- Modify: `tests/compat/test_trajectory_tools.py`

- [ ] **Step 1: 写失败测试：工具契约**

测试下列工具的成功、未知 ID、重复请求、错误 parent、非法时间、非法状态、缺失依赖、错误 evidence scope、不满足回归条件的 proposal，以及 objective 已完成后拒绝静默追加事件：

```text
create_research_objective
revise_research_objective
complete_research_objective
start_research_run
append_trajectory_event
fork_research_path
get_research_snapshot
get_research_trajectory
pause_research_run
abandon_research_branch
```

- [ ] **Step 2: 实现创建目标和启动 run**

`start_research_run` 必须接收 `objective_id`；没有 objective 不允许创建 auto-research run。保留 `max_sampling_requests` 作为可选的 Sampling 安全上限，但在响应和文档中不称为研究预算。

当所有 root criteria 均达到 acceptance scope 时，`complete_research_objective` 才能成功；如果仍有 pending root criterion，返回缺失证据及其依赖。完成后的 objective 拒绝普通 `append_trajectory_event`，只能通过 `revise_research_objective` 创建新版本，或显式记录 `objective_reopened` 并要求新的理由。

- [ ] **Step 3: 实现事件和分支工具**

`append_trajectory_event` 接收 runner 的 `event_kind`、`intent`、`result`、`metrics`、`artifacts`、`started_at`、`ended_at` 和 `idempotency_key`。MCP kernel 从成对的 start/finish 时间计算 elapsed，并记录 `duration_source="runner_observed"`；没有 finish 时返回 `duration_source="unknown"`。kernel 只验证和记录，不代替 runner 测量 GPU 或外部进程时间。

事件写入还必须接收 `supports_criterion_ids`、`blocked_criterion_ids`、`evidence_scope` 和 `evidence_status`。当事件声称验证 root criterion 时，kernel 校验其 scope 是否达到 criterion 的 `acceptance_scope`；不满足时只记录 `insufficient`，不能写成 `verified`。

`fork_research_path` 写入不可变 `branch_forked` event，并让子 run 继承 objective version、主线引用和父 checkpoint。

- [ ] **Step 4: 实现快照和轨迹查询**

`get_research_snapshot` 返回可直接放入模型 context 的紧凑 JSON；`get_research_trajectory` 支持 `summary`、`path`、`branches`、`events` 四种视图和 `after_seq` 分页。

- [ ] **Step 5: 统一 trajectory 工具错误 envelope**

返回：

```json
{
  "status": "error",
  "type": "invalid_trajectory_event",
  "message": "parent_event_id does not belong to run",
  "retryable": false,
  "suggestion": "use the latest event from get_research_snapshot"
}
```

- [ ] **Step 6: 运行 MCP 回归**

```bash
uv run pytest tests/compat/test_trajectory_tools.py -q
```

预期：真实 MCP in-process client 能够创建目标、启动主线、记录实验、fork 分支、查询 snapshot，并在重启后得到相同结果。

### Task 5: 接入 auto-research runner 和 Sampling 轨迹

**Files:**
- Modify: `src/noa/compat/sampling.py`
- Modify: `src/noa/runtime.py`
- Modify: `src/noa/server.py`
- Modify: `tests/compat/test_trajectory_tools.py`
- Create: `docs/integration/auto-research-mcp.md`

- [ ] **Step 1: 写 runner fixture**

在测试中模拟以下顺序：

```text
run_started
experiment_started(exp-a)
experiment_heartbeat(exp-a)
experiment_finished(exp-a, started_at=10:00, ended_at=10:15, outcome=failed)
branch_forked(main -> branch-b)
experiment_finished(exp-b, started_at=10:20, ended_at=10:45, outcome=improved)
```

另增加 JoyAI/SCNet 同主题回归序列：

```text
objective_created(root: continuous_30fps_visual_memory)
prerequisite_started(ddp_utilization, source=user_request, returns_to=language_alignment)
experiment_finished(hcu_pilot, scope=pilot, outcome=verified)
prerequisite_unblocked(ddp_utilization)
proposal(optimize_decode_again, no_new_blocker_evidence)
gate -> return_to_capability_validation
stage_a_finished(scope=visual_stage_a, supports=writer_training)
proposal(launch_snapshot_reader, returns_to=language_stage_b)
gate -> continue_prerequisite
snapshot_blocked(missing_complete_index)
snapshot_unblocked(index_complete)
gate -> return_to_capability_validation
language_stage_b_finished(scope=language_stage_b)
formal_evaluation_finished(scope=formal_evaluation, supports=event_background_gate)
```

验证 snapshot 能返回 `branch_elapsed_ms`、`path_elapsed_ms`、active experiment 列表、最近结果、主线共同祖先、分支深度、root/prerequisite 两组进度、证据范围、解除阻塞后的回归状态和偏离原因。特别验证：HCU pilot、视觉 Stage A 和批量 FPS 都不能把语言对齐或事件/背景正式评测标记为 verified。

- [ ] **Step 2: 为 Sampling 增加可选 event hook**

研究运行中的 Sampling 记录 `sampling_requested`、`sampling_completed` 或 `sampling_failed` 事件；默认只保存 question digest、协议模式和结构化结果 digest，不把完整 prompt 自动写进轨迹。现有 compatibility probe 保持行为不变。

- [ ] **Step 3: 实现 next-step gate**

新增 `propose_next_research_step`：调用方必须提交 `hypothesis_ids`、`criterion_ids`、`facets`、预期结果、下一动作、`work_class`、`work_source`、`blocks_criterion_ids`、`returns_to_criterion_ids` 和 `exit_conditions`。kernel 返回：

```text
continue
continue_prerequisite
return_to_capability_validation
checkpoint_review
pause_for_human
abandon_branch
```

当 proposal 未引用 active objective/criterion、偏离超过 policy 阈值或违反硬约束时，不能直接返回 `continue`。以下情况必须至少返回 `return_to_capability_validation` 或 `checkpoint_review`：

- `work_class=prerequisite` 已产生 `prerequisite_unblocked`，但 proposal 没有引用 `returns_to_criterion_ids`；
- root criterion 在最近窗口没有新增 evidence，而同一 prerequisite 分支已连续推进超过 policy 阈值；
- proposal 继续优化的 metric 已达到声明的 exit condition，却没有新的 blocker evidence；
- 证据范围仍是 pilot/batch_training，但 proposal 声称要推进 formal evaluation 以外的结论；
- 用户追加了新目标但没有创建新的 objective version。

`checkpoint_review` 的输出必须列出：已解除的 blocker、尚未验证的 root criteria、最后一个能力证据、当前前置分支的累计耗时、继续当前分支的理由，以及返回主线的最小下一步。`continue_prerequisite` 仅表示仍有可验证 blocker，不表示根目标已经推进。

- [ ] **Step 4: 写 auto-research 接入文档**

文档必须明确：runner 负责执行和测量；MCP 负责记录、重放、偏离和闸门；NoA 不提供通用 shell 执行；缺少 finish 时间时显示 unknown；失败实验和 abandoned branch 不删除。

- [ ] **Step 5: 运行接入测试**

```bash
uv run pytest tests/compat/test_sampling.py tests/compat/test_trajectory_tools.py -q
```

预期：兼容性 Sampling 测试保持通过，研究 Sampling 能生成对应 trajectory events，失败和取消不会污染下一次 run。

### Task 6: 迁移旧 NoA Skill 的证据/决策功能到 MCP kernel

**Files:**
- Modify: `src/noa/server.py`
- Modify: `CONTEXT.md`
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `docs/package/README.md`
- Modify: `agents/openai.yaml`
- Modify: `pyproject.toml`
- Modify: `tests/compat/test_packaging.py`
- Create: `docs/migration/noa-skill-to-mcp-kernel.md`

- [ ] **Step 1: 建立旧字段到事件字段的映射**

将旧 Skill 的 evidence layer 映射为 `observation_recorded` 和 `experiment_finished` 字段：command、commit、run ID、dataset、config、environment、metrics、failures、artifacts、wall-clock、throughput、memory 和 stability。将 decision layer 映射为 `decision_made`：motivation、hypothesis、baseline、variants、interpretation、tradeoff、decision 和 next step。

- [ ] **Step 2: 更新产品入口和安装说明**

README、package metadata 和 `agents/openai.yaml` 统一描述为 NoA MCP kernel；说明 `noa` 是 MCP server，Research Trajectory 是核心功能，旧 Markdown 日志只作为导入/导出格式，不是第二权威源。

- [ ] **Step 3: 编写迁移文档**

明确旧日志不会被自动伪造为完整 trajectory；没有原始时间、父节点或事件顺序的历史条目必须标记 `legacy_unknown`，只能作为人工补录输入。

- [ ] **Step 4: 运行文档和 metadata 检查**

```bash
uv run pytest tests/test_package_metadata.py -q
uv run ruff check README.md SKILL.md src/noa/server.py
```

预期：包描述、入口和 MCP 工具名称一致，旧 Skill 文档不再声称它是当前主入口。

### Task 7: 端到端验收和发布前验证

**Files:**
- Modify: `tests/compat/test_trajectory_tools.py`
- Create: `tests/compat/fixtures/trajectory_research_case.json`
- Modify: `memory/verify.md`（实现阶段再更新，不在本计划阶段编辑）

- [ ] **Step 1: 固定一条真实验收场景**

场景必须包含：一个初始目标、根能力 criteria、必要前置 criterion、用户指定优化、主线实验、失败实验、同主题过度优化分支、回到主线的分支、一个已验证 criterion 和一次 MCP 进程重启。验收输出必须能回答：

```text
当前走到哪一步？
主线和当前分支的共同祖先是什么？
当前路径累计报告了多长时间？
哪些验收条件已经被验证？
当前偏离来自哪些事件？
哪些工作只是前置条件，何时已经解除阻塞？
解除阻塞后为什么继续当前分支，是否已经满足返回主线条件？
当前证据属于哪个 scope，能支持哪个 criterion，不能支持哪个 criterion？
下一步为什么是 continue / checkpoint / return / abandon？
```

- [ ] **Step 2: 验证事件重放一致性**

从空数据库重放 fixture，比较重放前后 snapshot 的 canonical JSON digest、progress、drift、branch path 和 recent events，必须完全一致。

- [ ] **Step 3: 运行开发门**

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest tests/test_trajectory.py tests/compat/test_runtime.py tests/compat/test_trajectory_tools.py -q
```

预期：新增切片测试全绿，现有 runtime/sampling 回归不变。

- [ ] **Step 4: 运行全量检查**

```bash
uv run pytest -q
```

如果环境无法初始化默认 uv cache，使用仓库允许的临时 cache 目录重跑，并把 cache/网络导致的构建失败与代码失败分开记录；不能把历史测试记录当作本次 fresh pass。

- [ ] **Step 5: 形成完成判定**

只有以下条件同时满足才把本阶段标记完成：

1. 任意 auto-research runner event 都能追加、查询和重放。
2. 目标、主线、分支、耗时、进度和偏离都能在一个 MCP snapshot 中返回。
3. 模型不能绕过 objective/criterion 引用直接推进下一步。
4. 旧 run 迁移不会伪造历史轨迹。
5. 本阶段没有引入研究预算账本；Sampling 上限仍是独立的协议安全限制。
6. JoyAI/SCNet 同主题 fixture 中，用户明确的 HCU 优化和真实阻塞修复可以继续；解除阻塞后的无新证据局部优化会触发回主线或 checkpoint，而不是被误判为主题漂移。
7. 批量吞吐、pilot HCU、视觉 Stage A、语言 Stage B 和正式 end-to-end 评测的证据范围不会相互冒充。

## 实施顺序和检查点

按以下顺序执行，每个任务完成后单独验证：

```text
Task 1  契约与 ADR
  ↓
Task 2  纯模型/evaluator
  ↓
Task 3  SQLite store/迁移
  ↓
Task 4  MCP tools/分支/快照
  ↓
Task 5  runner + Sampling 接入
  ↓
Task 6  旧 Skill 能力迁移和入口统一
  ↓
Task 7 端到端验收
```

第一个可演示垂直切片是 Task 1–4：不依赖真实训练任务，也不包含预算，但已经能在 MCP 中记录目标、实验、分支、耗时和偏离。Task 5 才把它接到真实 auto-research runner。Task 6 解决“旧 Skill 有研究记录语义、新 MCP 没有对应 API”的迁移断层。

Task 1 的目标分层和 Task 5 的回归闸门必须先于任何真实 runner 接入验收；否则系统只能知道“做了很多相关工作”，不能判断工作是否已经回到 JoyAI 的语言对齐和正式能力验证。

## 计划自审

- **需求覆盖：** 目标、traj、分支、耗时、主线偏离和模型下一步上下文都有对应任务；预算明确排除并保留 Sampling 安全上限。
- **真实失效模式覆盖：** JoyAI/SCNet 的“工程前置与根能力同主题但手段替代目的”已经有明确字段、依赖图、证据 scope、回主线状态和专用 fixture。
- **进度语义：** root capability、prerequisite、requested optimization、exploration 四类进度分开；前置完成不自动增加根能力完成度。
- **阻塞回归：** 每个前置分支必须记录 blocker evidence、exit condition 和 return criterion；解除阻塞后继续局部优化需要新证据或用户授权。
- **证据边界：** pilot、批量吞吐、视觉 Stage A、语言 Stage B 和 formal end-to-end 不能相互冒充。
- **事实边界：** 当前实现只有最小 ResearchRun 计数器，计划没有把现有能力描述成已完成。
- **持久化边界：** 运行轨迹在 SQLite control plane，文献事实在 LadybugDB，产物在 CAS，没有把瞬时实验事件塞入文献图。
- **迁移边界：** 旧数据只生成 `legacy_unknown`，不伪造缺失时间、父节点或分支。
- **验证边界：** 先纯 evaluator，再 store，再 MCP，再 runner fixture，最后跑全量开发门；每一步都有失败测试和明确命令。

## JoyAI/SCNet 验收矩阵

| 证据或工作 | 允许推进 | 不允许直接宣称 |
|---|---|---|
| 8 卡 HCU pilot | 解除训练并行/利用率前置阻塞 | 单路端到端 30 FPS、语言对齐、最终门控能力 |
| OpenCV/批量 H2D/uint8 修复 | 解除输入或 dtype 阻塞 | 视觉记忆已经对齐语言模型 |
| 批量训练 FPS | 验证训练吞吐范围 | 直播输入端到端吞吐 |
| 视觉 Stage A writer/checkpoint | 进入 snapshot/reader 前置 | JoyAI/Qwen 语言问答 |
| 完整 snapshot/index | 解除 Stage B 数据阻塞 | 已完成 reader 或正式能力评测 |
| Language Stage B reader | 进入正式语言评测 | 事件开启/背景关闭已经证明 |
| 正式事件/背景评测 | 验证根能力 criterion | 其他未测 criterion |

矩阵中的“允许推进”是依赖图上的可达关系；它不是自动批准继续在同一个局部问题上优化。每次 proposal 都必须声明下一步将验证哪个 criterion，或解除哪个仍在生效的 blocker。
