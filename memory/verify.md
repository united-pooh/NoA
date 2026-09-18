# Verification

## M0 NoA trajectory-control baseline (2026-09-18)

- `UV_CACHE_DIR=/private/tmp/noa-uv-cache uv run ruff check .` — PASS.
- `UV_CACHE_DIR=/private/tmp/noa-uv-cache uv run ruff format --check .` — PASS after excluding planning Markdown under `docs/codex/plans` from formatter input.
- `UV_CACHE_DIR=/private/tmp/noa-uv-cache uv run mypy src` — PASS (27 source files).
- `UV_CACHE_DIR=/private/tmp/noa-uv-cache uv run pytest -q` — **770 passed, 1 failed**. The only failure is the existing reproducible-build test because `uv build` cannot fetch `hatchling==1.32.0` from PyPI under the current network policy (`Operation not permitted`). This remains an environment blocker and is not changed in M0.

## M3 NoA trajectory persistence (2026-09-18)

- `PYTHONPATH=src .venv/bin/pytest tests/test_trajectory.py tests/test_trajectory_store.py tests/test_trajectory_runtime.py -q` — PASS (21 tests).
- `PYTHONPATH=src .venv/bin/pytest -q` — **791 passed, 1 failed**. The only failure remains the existing reproducible-build test because `uv build` cannot fetch the pinned `hatchling` dependency from PyPI under the current network policy.
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .` — PASS.
- `MYPYPATH=src .venv/bin/mypy src` — PASS (29 source files).
- The trajectory store uses SQLite WAL, append-only event rows, idempotency and expected-sequence checks, hash-validated snapshots with replay, and additive `legacy_unknown` migration. No budget fields were added.

## M4 trajectory MCP tools (2026-09-19)

- `PYTHONPATH=src .venv/bin/pytest tests/test_trajectory.py tests/test_trajectory_store.py tests/test_trajectory_runtime.py tests/compat/test_trajectory_tools.py tests/compat/test_server.py -q` — PASS (28 tests).
- `PYTHONPATH=src .venv/bin/pytest -q` — **793 passed, 1 failed**. The remaining failure is the existing `uv build` PyPI network restriction.
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .` — PASS.
- `MYPYPATH=src .venv/bin/mypy src` — PASS (29 source files).
- In-process MCP flow passes: create objective → start mainline → append event → fork → append child event → query snapshot/trajectory → close/reopen and obtain identical snapshot. No budgets were introduced.

## 笔记查询链路打通（2026-08-24）

TDD 新增 3 项回归（`test_note_attachments_survive_round_trip_and_project`、`test_get_note_returns_attachments_with_kinds`、`test_export_graph_view_writes_readable_json`）：

1. `add_note` 落图 payload 补存 `attached_entity_ids` 与 `revision`；Note 快照可从图重建，`note_attached_to` 边进入结构投影。
2. 新只读工具 `get_note`：按 ID 取笔记 + 挂接实体（含 kind 解析）；不存在返回 `note_not_found`。
3. 新只读工具 `export_graph_view`：调用 `views.export_projection_view` 导出到 `<root>/.noa/exports/graph-view.json`，返回路径与计数；JSON 含 current_record_ids / relationships / excluded 三段。
4. 端到端演示：get_note 返回挂接 claim+work → 导出 JSON 含 7 条边（claim_of、claim_supported_by、document_of、evidence_from、note_attached_to ×2、publication_of）。
5. 门：ruff PASS、mypy PASS（27 files）、全量 pytest **771 passed**。

## Claim 落图与建图演示（2026-08-24）

用户问题「实验日志+引用资料能否构成图」的现场验证暴露并修复两个缺陷（TDD，新增 `test_approved_claim_persists_and_note_can_attach`）：

1. `approve_claim_candidate` 此前不把 confirmed Claim 写回图 → 补 `graph.put_entity`，payload 序列化 review attestation 全字段；重建时用载荷字段重算 binding digest 并与存储值交叉核对（`AcceptedReviewAttestation.__post_init__` 本身强制重算校验，直接存 digest 无法通过重建）。
2. 重建路径 `NameError: name 'Claim' is not defined` 被 `except Exception: return None` 静默吞掉（settrace 抓获）；补 `Claim` 导入。教训：宽 except 吞异常会把导入错误伪装成数据损坏，重建函数的回归测试必须覆盖真实 MCP 写入→读回全路径。
3. beartype claw 编译缓存曾导致字节码落后于源码（常量表无 claim 分支），清 `__pycache__` 后恢复；调试时先验编译产物再怀疑逻辑。
4. 门：ruff PASS、mypy PASS、全量 pytest **768 passed**。
5. 建图演示证据：纯 MCP 六节点（wrk/pub/doc/evp/clm/nte），投影出五条结构边（publication_of、document_of、evidence_from、claim_of、claim_supported_by），claim grounding=current。

## MCP 图持久化缺口修复（2026-08-24）

调查结论：审批闭环断点在 server.py `_snapshot_from_payload` 只重建 Work；另发现跨层摘要不一致——CandidateStore 存 canonical JSON sha256，而 `ApprovalService._require_review` 比对 domain binding digest（长度分帧编码），MCP 审批路径必然 `attestation_payload_mismatch`（Slice 7 smoke 因绕过 store 直构 attestation 而未暴露）。

TDD 修复（RED 12 项 → GREEN）：

1. 新增 `tests/compat/test_knowledge_tools.py`：前缀表、confirm 门禁、未知 kind/重复实体/缺失父级/非法 digest/media_type 拒绝、四类快照入图与图往返重建、纯 MCP 端到端 submit→approve→search。
2. `put_entity_snapshot`：复用 domain `create_*` 结构校验，payload 保持顶层扁平字段兼容检索索引；错误码透传 domain code。
3. `review.py` 提取公共 `review_binding_digest(kind, payload)`；server 审批改用语义 binding digest 构造 attestation，store JSON sha256 继续负责行级防篡改。
4. 门：ruff/format PASS、mypy src PASS（27 files）、全量 pytest **767 passed**（755+12）、packaging allowlist 收录新测试文件。
5. 现场演示证据：纯 MCP 调用完成 list_id_prefixes → 4 实体入图 → submit（digest 绑定）→ approve（claim_id 返回）→ knowledge_search 命中 evidence_passage。

## 发布门红项修复记录

2026-08-22 解冻并修复三处 Slice 0 既有失败，全量 `uv run pytest` 回到 755 passed：

1. `tests/compat/test_app.py`：补 `from fastmcp.apps import ResourceCSP` 导入（原 F821）。
2. `tests/compat/test_packaging.py`：sdist/wheel allowlist 收录 `noa/domain/*` 与 `tests/domain/*`；`_REQUIRED_DEPENDENCIES` 增加 `uuid6==2025.0.1`。
3. `tests/compat/test_runner.py`：`mcp-app-resource.details` 期望补 `listed_resource_count`、`exact_uri_resource_count`、`csp_metadata_consistent`。

## Slice 1 provenance 开发门记录

2026-08-22 按开发门完成 `provenance.py`（Task 4）：

1. `uv run mypy src` — PASS（20 files）；`ruff check .` / `format --check .` — PASS。
2. 全量 `uv run pytest` — 755 passed。
3. smoke：source ingest batch（digest 绑定 + origin 派生）→ human metadata correction → human retraction → 重复 retraction 以 `assertion_already_retracted` 拒绝 → 错误 payload digest 以 `attestation_payload_mismatch` 拒绝 — PASS。

下一步：Task 5 confirmed knowledge、merge 与 projection。

## Slice 1 projection/merge 开发门记录

2026-08-22 按开发门完成 Task 5（`provenance.py` 追加）：

1. `uv run mypy src` — PASS（20 files）；`ruff check .` / `format --check .` — PASS；全量 `uv run pytest` — 755 passed。
2. §20 缩短场景 smoke（TASK5_SMOKE_OK）：human title 权威 resolved → 同层第二值 `same_tier_value_conflict`；A→C→D→A extends 环三条边全部 `acyclic_cycle`；`compares_with` 正反两条 relation 聚合为单逻辑边 + 双 `SemanticEvidenceSupport`；撤回 C→D 后其余两边 RESOLVED、被撤回 grounding 返回 `retracted`；fuzzy merge B→A 产生 redirect、redirect loser 新写入以 `noncanonical_write_endpoint` 拒绝；Claim 中文 statement 由英文 evidence 支持 grounding CURRENT；tombstone Document 后 Claim 变 `no_current_evidence` 且 evidence exclusion 为 `tombstoned_evidence_source`。
3. 包导出完整性检查（`__all__` vs namespace）通过。

Slice 1 生产实现完成；剩余 Task 6 收尾（compileall/diff-check/memory 更新已随各片执行）。下一步可选：接入 Slice 2 Workspace and Security Kernel，或先补 provenance/projection 的回归测试。

## Slice 7–9 开发门记录（2026-08-22）

最终全量门：pytest **755 passed**、ruff/format/mypy strict 全绿、导出完整性 OK。

- **Slice 7** `src/noa/review.py`：候选 payload 白名单验证（未知键/缺键/类型 fail-closed）；审批摘要对齐 domain binding 摘要后经 `confirm_claim` 真实落域；错误 digest 的 review 被 `attestation_payload_mismatch` 拒绝；批量拒绝含 per-item outcome、重复 approve 报 `candidate_not_pending`；audit_trail 记录 submit/approve/reject。SLICE789_SMOKE_OK。
- **Slice 8** `src/noa/views.py`：SearchIndex 确定性打分（exact/prefix/substring）、NoteStore 主键(note_id,revision) 版本历史、lineage 视图 BFS 遍历 + 边状态保留、structural projection 导出为可重建 JSON。SLICE789_SMOKE_OK。
- **Slice 9** `server.py` 工具面：写工具（add_note/approve/acquire_and_stage）无 confirm 一律 `confirmation_required`；approve 用伪造 digest 走到 `attestation_payload_mismatch`；run 工具 start/advance 正常；ingest 对非 allowlist scheme 在预连接层拒绝（`url_scheme_denied`）。SLICE9_SMOKE_OK。

顺带修复：`project_structural_relationships` 中 `semantic_supported_by` 边 subject 误用 relation.subject_id（应为 relation.id）——domain 测试与 smoke 均已覆盖该路径。

已知边界：候选审批的 MCP 工具路径尚未接 sampling 自动生成（模型输出→候选由调用方组装）；views 检索基于 graph JSON payload，metadata assertion 入图后需扩展。

## Slice 2–6 开发门记录（2026-08-22，快速垂直交付）

每片实现后即跑开发门；最终全量门：pytest **755 passed**、ruff/format/mypy strict 全绿、`__all__` 导出完整性 OK。

- **Slice 2** `src/noa/workspace.py`：布局创建、绝对/相对穿越拒绝、symlink 逃逸拒绝（与 escape 检查等价 fail-closed）、flock 双重获取拒绝。SLICE23_SMOKE_OK。
- **Slice 3** `src/noa/storage.py`：CAS 去重 + 原子发布；Ladybug 事务内 upsert/回滚验证（真实 lb.Database）；journal prepared→rolled_back、graph_committed→completed 幂等恢复；重复 idempotency key 拒绝。SLICE23_SMOKE_OK。
- **Slice 4** `src/noa/adapters.py`：Crossref/OpenAlex payload 规范化（DOI checksum 路径、年份、作者）、分页限速迭代器、单记录 batch proposal 经 `create_source_write_batch` 真实落域。SLICE456_SMOKE_OK。
- **Slice 5** `src/noa/acquisition.py`：本地 HTTP 抓取→CAS→HTML 抽取（script 剥离）；allowlist 外 host 预连接拒绝；PDF 显式 `capability_unavailable`；XML DTD/entity 拒绝。SLICE456_SMOKE_OK。
- **Slice 6** `src/noa/runtime.py`：run start/advance/resume/cancel/duplicate 拒绝；sampling 预算耗尽 fail-closed（协议层由 compat sampling 测试覆盖）。

已知边界（诚实声明）：Slice 2–6 为最小可用纵向切片——无回归测试文件、GraphStore 仅实体快照存取（assertion/projection 尚未入图）、adapters 无真实网络 fetch、PDF 解析未接 GROBID。

## 验证分层

自 2026-08-22 起验证分两层：日常任务默认只跑开发门；发布门条目一律推迟到正式 release 前一次性集中执行，不得混入日常切片。

### 开发门（每个任务/切片默认）

1. `uv run ruff check . && uv run ruff format --check .`
2. `uv run mypy src`
3. 当前切片测试：`uv run pytest`（实现中途允许只跑定向测试文件）
4. 生产 import smoke：真实 import 改动模块或启动对应 CLI

开发门通过即视为本切片完成，可继续下一个纵向切片。

### 发布门（仅正式 release 前）

- 完整 `uv run pytest` 全绿
- `uv build` 可复现构建，wheel/sdist allowlist 与包元数据校验
- FastMCP 升级到稳定版后重跑完整 `noa-compat` Slice 0 闸门
- 故障注入：跨 LadybugDB、SQLite、CAS 的全部 journal 状态覆盖
- 安全矩阵：路径逃逸、SSRF、重定向、恶意文档、prompt injection、审批绕过
- 规模预算：约 5 万篇文献的核心导入、查询和重建达标
- 宿主证据：VS Code Stable 端到端场景与双截图独立复核
- 数据：开放导出可重建权威状态，迁移和回滚路径已验证
- UI：MCP App 真实构建、运行、截图并由独立检查验证

## Slice 1 产品化收尾验证（2026-08-23）

Task 6 收尾门全部通过，Slice 1 正式完成：

1. `uv run ruff check .` / `ruff format --check .` — PASS（71 files）；`uv run mypy src` — PASS（27 files）；定向 `mypy src/noa/domain` — PASS（6 files）。
2. 全量 `uv run pytest` — **755 passed**。
3. `python -m compileall -q src/noa/domain` — PASS；`ID_PREFIX_REGISTRY` 输出 `23`。
4. `git diff --check` — PASS（仓库仍全部 untracked，未 commit）。
5. 端到端生产 smoke（SLICE1_PRODUCTION_SMOKE_OK，临时脚本未入库）：Work→Publication→Document→EvidencePassage 实体链 → crossref draft→single_entry_proposal → operation attestation（proposal digest 绑定）→ create_source_write_batch → SourceOrigin → projection input → title/year metadata 投影 RESOLVED → confirm_claim（review attestation digest 绑定）→ evaluate_claim_grounding = CURRENT；domain `__all__` 导出完整性 OK。
6. smoke 调试中发现的一次 MISSING 为临时脚本重建索引时丢失 Work 快照所致，非产品缺陷；产品代码零改动。



2026-08-22 按开发门完成 `entities.py` 实体快照层：

1. `uv run pytest tests/domain -q` — 448 passed（含 test_entities 106 项，RED→GREEN）。
2. `uv run ruff check .` / `ruff format --check .` — PASS（src 与 tests/domain 无问题）。
3. `uv run mypy src` — PASS，19 个 source files 无问题。
4. import+tombstone smoke：Work→Publication→Document→Evidence 构建链、`resolve_terminal`、带 digest 绑定的 `tombstone_entity`、`replace_entity_snapshot`、tombstone 后 `entity_not_active` 拒绝 — PASS。

全量 `pytest` 存在 3 个冻结的 Slice 0 既有失败（test_app ResourceCSP 缺导入、test_packaging sdist allowlist 未含 Slice 1 文件、test_runner host evidence 时效），不阻塞本切片；留待 release gate。下一步：`provenance.py`（Task 4）。

## 历史证据（发布级）

以下为按旧发布级标准执行的历史记录，仅作审计留存；不构成对当前开发切片的要求。

## Slice 0 最终闸门

2026-08-21 已按顺序完成确定性完整验证：

1. `uv sync --python 3.11 --all-groups --frozen` — PASS，审计 83 个环境包。
2. `uv lock --check` — PASS，lockfile 可解析且为最新状态。
3. `uv run ruff check .` — PASS。
4. `uv run ruff format --check .` — PASS，50 个文件已格式化。
5. `uv run mypy src tests` — PASS，23 个 source files 无问题。
6. `uv run pytest` — PASS，232/232。
7. `uv build --out-dir dist` — PASS，生成 `dist/noa_mcp-0.1.0a0.tar.gz` 与 `dist/noa_mcp-0.1.0a0-py3-none-any.whl`。
8. `uv run noa-compat --workspace .noa/compatibility/workspace --host-evidence-root . --json .noa/compatibility/compatibility.json --markdown docs/compatibility/2026-08-21-slice-0.md` — PASS 并重新生成最新 JSON/Markdown 报告。
9. 使用 `CompatibilityReport.model_validate_json` 严格读回 JSON，并断言 decision、required checks 与唯一非 PASS 项 — PASS。

最终 decision 为 `conditional_go`。全部 required 功能和宿主 checks 为 PASS，唯一非 PASS 是 FastMCP prerelease WARN。

## Task #58 验证（部分完成，按用户要求冻结）

2026-08-21 已按严格 TDD 完成的部分：

1. RED→GREEN：schema v2 semantic review validator、生产 App validator、FTP 外部 URL 加固。
2. 双 artifact bytes/SHA-256/dimensions 与 JSON/manifest 一致。
3. 目标测试 201 passed；完整 `uv run pytest` 286 passed；Ruff/mypy PASS。
4. 遗留缺口：CSS/CSP/可见 DOM 验证与反向 PNG 留待 release gate。

## Task 60 本地运行记录 ignore 验证

2026-08-21 已按 TDD 完成：

1. RED→GREEN：根目录与 packaged `.gitignore` 增加 `.paw/`、`.playwright-cli/`。
2. 质量审阅：临时仓库后置 negation 场景固定为 fail-sensitive 回归测试。
3. 哨兵路径 `git check-ignore --quiet --no-index` 验证 Git 最终规则。
4. sdist/wheel 精确成员集合不变；Ruff/mypy/`uv build`/`git diff --check` 均 PASS。
