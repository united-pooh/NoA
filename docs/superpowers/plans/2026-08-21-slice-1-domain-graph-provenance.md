# Slice 1 Domain Graph and Provenance Implementation Plan

> **For agentic workers:** Implement production code task-by-task. The user has explicitly prioritized a working product over additional test engineering, so this plan does not create new tests, does not continue Slice 0 review work, and does not commit or push.

**Goal:** 实现可直接导入和调用的 `noa.domain` 纯领域图、出处记录、审核治理、merge/tombstone 与确定性投影能力。

**Architecture:** 领域层使用 frozen dataclass、封闭 enum、类型化 UUIDv7 和纯函数服务。`errors → ids → identifiers → entities → provenance` 单向依赖；不接入 MCP、LadybugDB、SQLite、CAS、HTTP 或文件系统。

**Tech Stack:** CPython 3.11、标准库 dataclasses/enum/uuid/hashlib/hmac、`uuid6==2025.0.1`、uv。

---

## 文件结构

- `pyproject.toml`：增加精确直接依赖 `uuid6==2025.0.1`。
- `uv.lock`：通过 `uv lock` 更新锁文件。
- `src/noa/domain/errors.py`：稳定 `DomainError` 与冻结 context。
- `src/noa/domain/ids.py`：23 类 prefix UUIDv7 ID、解析和生成入口。
- `src/noa/domain/identifiers.py`：值对象、AssertionValue、attestation、payload binding 与外部标识符规范化。
- `src/noa/domain/entities.py`：predicate/metadata registries、实体快照、生命周期、索引、结构验证与 entity constructors。
- `src/noa/domain/provenance.py`：source proposal/batch、origin、assertion/retraction、confirmation、merge、grounding 与 projection。
- `src/noa/domain/__init__.py`：显式导出稳定公共 API，不包含业务逻辑。
- `memory/plan.md`、`memory/progress.md`：记录 Slice 1 已进入生产实现并冻结 Slice 0 加固。

### Task 1：建立领域基础与 UUIDv7

- [ ] 在 `pyproject.toml` 的直接依赖中加入 `uuid6==2025.0.1`，运行 `uv lock` 更新 `uv.lock`。
- [ ] 创建 `errors.py`，实现 `DomainError(code, message, context)`；context 复制后以只读 mapping 暴露，只接受规格允许的可序列化 scalar/tuple。
- [ ] 创建 `ids.py`，实现 `generate_uuid7_value()`、`TypedId` 和规格 §6 的 23 个具体 ID 类。
- [ ] 严格校验 canonical lowercase hyphenated RFC9562 UUIDv7、prefix、version 与 variant；不提供零参数 typed-ID factory。
- [ ] 创建最薄 `domain/__init__.py`，先导出 errors/IDs。
- [ ] 运行 `uv run python -c "from noa.domain import WorkId, generate_uuid7_value; value=WorkId.from_uuid7(generate_uuid7_value()); assert WorkId.parse(str(value)) == value"`。

### Task 2：实现值对象、治理 attestation 与标识符

- [ ] 在 `identifiers.py` 实现 `ContentDigest`、`LanguageTag`、`UtcInstant`、`EvidenceLocator`、`IdentifierKey`、`MetadataFieldKey` 与全部 `AssertionValue` variants。
- [ ] 实现 `ReviewAction`、`OperationAction`、`AttestationPrincipalKind`、`AcceptedReviewAttestation`、`AcceptedOperationAttestation` 及其 create functions。
- [ ] 实现规格 §7.10 的 review/operation binding、canonical encoder 与 SHA-256 digest；digest 比较使用 `hmac.compare_digest`。
- [ ] 实现 DOI、arXiv、OpenAlex、ORCID、ROR、ISSN 的严格纯函数规范化、checksum、canonical URI 与 target compatibility。
- [ ] 更新 `domain/__init__.py` 的稳定导出。
- [ ] 运行一个无网络 smoke script，确认 DOI canonicalization、ORCID checksum、UTC canonical text 和 attestation digest 可构造。

### Task 3：实现 predicate registry、实体和生命周期

- [ ] 在 `entities.py` 定义 `EndpointKind`、`PredicateKind`、`Cardinality`、三类 predicate enums、`PredicateSpec`、`PREDICATE_REGISTRY` 与 `METADATA_FIELD_REGISTRY`。
- [ ] 定义 `ActiveLifecycle`、`RedirectLifecycle`、`TombstoneLifecycle` 与全部 frozen entity/record snapshots。
- [ ] 实现 `EntitySnapshotIndex`、`SourceRecordIndex`、重复 ID fail-closed、Document digest 全局唯一和 `replace_entity_snapshot()`。
- [ ] 实现 active-only initial constructors、Evidence/Collection/Note/TechnicalLineage/LineageSynthesis constructors 与 canonical write endpoint 规则。
- [ ] 实现 `canonicalize_relationship()`、`resolve_terminal()`、结构字段校验和 tombstone transition。
- [ ] 更新 `domain/__init__.py` 的稳定导出，并运行 import + Work→Publication→Document→Evidence 的内存 smoke script。

### Task 4：实现来源批次与 append-only provenance

- [ ] 在 `provenance.py` 定义 `AuthorityTier`、`SourceOrigin`、`HumanCorrectionOrigin`、Metadata/Relationship assertions、Retraction 与 proposal/result types。
- [ ] 实现 `create_source_write_batch()`，将完整 proposal digest 绑定到 accepted source operation，任一元素失败时不返回 partial result。
- [ ] 实现 human metadata/relationship correction 与 human/source retraction；保持 origin/action/payload/time/lineage fail-closed。
- [ ] 实现 `DomainProjectionInput` 的 iterable 复制、record ID 唯一性和历史记录内在不变量校验。
- [ ] 更新 `domain/__init__.py`，运行 SourceRecord + metadata assertion + explicit retraction 的内存 smoke script。

### Task 5：实现 confirmed knowledge、merge 与 current projection

- [ ] 实现 `confirm_claim()`、`confirm_semantic_relation()`，验证 accepted review action、payload digest、时间、canonical endpoint 和 evidence 下限。
- [ ] 实现 exact/fuzzy merge basis、`merge_entities()`、受控 redirect snapshot 和 Publication structural anchor 规则。
- [ ] 实现共享 `evaluate_current_record_set()` fixed point，供 structural projection、grounding 和 factual/semantic projection 共同使用。
- [ ] 实现 Claim/SemanticRelation grounding、metadata authority resolution、max-one、identifier owner、multi-valued relationships、symmetric canonicalization 和 acyclic SCC conflict。
- [ ] 保证所有输出稳定排序，时间、UUID、provider 和输入顺序不参与胜者选择。
- [ ] 更新 `domain/__init__.py`，运行规格 §20 的缩短内存场景：authority resolution、显式 retraction、redirect、Claim grounding、semantic relation、Document tombstone。

### Task 6：产品化收尾

- [ ] 运行 `uv run python -m compileall -q src/noa/domain`。
- [ ] 运行 `uv run python -c "import noa.domain; print(len(noa.domain.ID_PREFIX_REGISTRY))"`，输出必须为 `23`。
- [ ] 运行 `uv run ruff check src/noa/domain pyproject.toml` 和 `uv run mypy src/noa/domain`，只修生产代码问题。
- [ ] 运行 `git diff --check`；不执行 Slice 0 测试、不新增测试文件、不修改视觉 artifact。
- [ ] 更新 `memory/plan.md` 与 `memory/progress.md`，准确记录已实现内容和仍未接入的 Slice 3 持久化边界。

## 执行约束

- 不提交、不推送。
- 不继续 Task #55–#61 的 Slice 0 加固。
- 不创建 repository port、数据库 schema、Cypher、SQL、MCP tool 或 UI。
- 不新增测试文件；仅用短 smoke command、Ruff、mypy、compileall 和 diff check 验证生产实现可导入、可调用。
- 若完整规格与本计划表述冲突，以 `docs/superpowers/specs/2026-08-21-domain-graph-provenance-design.md` 为准。
