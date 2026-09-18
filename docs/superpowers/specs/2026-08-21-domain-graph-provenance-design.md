# NoA Slice 1：领域图与出处设计规格

- 日期：2026-08-21
- 状态：冻结，可据此编写实现计划
- 上位契约：`docs/superpowers/specs/2026-08-21-noa-product-contract-design.md`
- 相关决策：ADR 0003、0004、0005、0006、0007、0008、0011
- 实施切片：Slice 1 — Domain Graph and Provenance

## 1. 目的与结论

本规格冻结 NoA 首个业务切片的领域词汇、不可变记录、类型化 UUIDv7、外部标识符、关系谓词、出处断言、投影、Claim/Evidence、语义关系以及 merge/redirect/tombstone 行为。

Slice 1 采用以下边界：

1. 只实现纯领域模型与纯领域服务。
2. 不定义 repository port，不连接 LadybugDB、SQLite 或 CAS。
3. 不包含 FastMCP、MCP、HTTP、文件系统、来源适配器或公共工具。
4. 领域服务只接收完整值、实体快照和记录集合，并返回新值、状态转换或投影结果；它们不读取时钟、随机源、环境变量、数据库或网络。UUIDv7 entropy source 按第 6.3 节隔离为叶子 ID source utility，不属于领域服务或业务决策。
5. 真实持久化属于 Slice 3；公共 MCP Tool 契约属于 Slice 9。
6. Slice 1 完整冻结本切片需要的领域行为，但首个实现按五个小型 TDD 阶段落地，生产代码集中在约五个模块。

本文冻结设计，不改变 `docs/compatibility/README.md` 的 Slice 0 闸门：required check 出现 `fail` 或 `blocked` 时不得开始 Slice 1 生产实现；仅由 prerelease 条件形成的 `conditional_go` 只授权规格工作，除非后续闸门或明确决策另行放行实现。

## 2. 范围

### 2.1 Slice 1 实现范围

- 稳定的 `DomainError`、错误 code 与 context。
- 23 类类型化 UUIDv7 ID。
- `ContentDigest`、`LanguageTag`、`UtcInstant`、`EvidenceLocator`、`IdentifierKey`、`MetadataFieldKey`、`AssertionValue`、`EntityLifecycle`。
- `AcceptedReviewAttestation` 与 `AcceptedOperationAttestation` 的形状、action 绑定和纯领域验证边界。
- DOI、arXiv、OpenAlex、ORCID、ROR、ISSN 的纯函数规范化、校验和目标类型约束。
- 领域实体快照、唯一 current snapshot 索引及其构造不变量。
- structural、factual、reviewed-semantic 三类谓词的封闭注册表。
- `SourceOrigin`、`HumanCorrectionOrigin`、`AuthorityTier`。
- `SourceRecord`、`MetadataAssertion`、`RelationshipAssertion`、`AssertionRetraction` 的不可变语义。
- structural、metadata、grounding、max-one 关系、identifier owner、一般关系集合的确定性投影。
- confirmed `Claim`、`EvidencePassage`、confirmed `SemanticRelation`。
- exact-identity/reviewed-fuzzy merge、redirect terminal resolution、受批准 tombstone。
- 纯领域纵向验收场景和导入边界测试。

### 2.2 明确不做

- 任何数据库 schema、Cypher、SQL、migration 或 repository 实现。
- LadybugDB、SQLite、CAS 的连接、事务或故障恢复。
- workspace 路径、文件读写、内容下载、解析或 `EvidenceLocator` 文法。
- 来源 API、HTTP host allowlist、重试、限流或 Source Record 采集。
- Review Candidate 的 pending/accepted/rejected 状态机、revision、审核工具或审计存储；这些属于 Slice 7。
- Research Run、checkpoint、Sampling 与有界 `continue`；这些属于 Slice 6。
- 公共 MCP tool、错误 envelope、分页、确认和权限；这些属于 Slice 9。
- Collection、Note、Technical Lineage、Lineage Synthesis 的搜索、版本工作流和派生视图；这些属于 Slice 8。Slice 1 只冻结其身份、最小图记录和结构关系。
- MCP App 或其他 UI。
- 视觉 companion、截图或 PNG 变更。

## 3. 架构边界与被拒方案

### 3.1 采用：纯领域模型 + 纯领域服务

领域对象使用不可变 Python 值表达。需要“变更”时，服务返回新的实体快照或新的 append-only 记录，不原地修改调用方对象。投影函数是确定性的：相同输入集合必定得到相同输出，不依赖集合迭代顺序、当前时间或外部状态。

允许的依赖只有 Python 标准库和用于生成 UUIDv7 的 `uuid6==2025.0.1`。`noa.domain` 不依赖 Pydantic；持久化和 MCP 边界以后负责序列化及输入 envelope 校验。

### 3.2 拒绝：在 Slice 1 定义 repository ports

本切片不定义 `WorkRepository`、`AssertionRepository`、`GraphRepository` 等接口，原因如下：

- Slice 1 还没有冻结 Slice 3 的事务、查询批次、journal 和重建边界；现在定义 port 会把未经验证的存储访问形状伪装成领域契约。
- repository mock 容易让测试验证调用顺序而非领域行为，并把领域服务变成数据库编排层。
- 投影、merge 和 terminal resolution 可以用显式实体映射与记录序列完整测试，不需要隐式读取。
- Slice 3 可以围绕已冻结的纯函数输入输出设计 application query/write service，而不是反向让存储 API 塑造领域模型。

这不否定后续应用服务的存储抽象；它只拒绝在 Slice 1 提前冻结 repository 形状。

### 3.3 拒绝：提前接入 LadybugDB

ADR 0005 仍然有效：LadybugDB 是未来权威文献图存储。但 Slice 1 不写实际表、关系表或 Cypher，原因如下：

- 领域不变量必须先能在无数据库环境中由快速单元测试证明。
- 过早映射会把 LadybugDB 的类型、查询和事务限制泄漏进实体及投影语义。
- assertion 是权威记录、current value 是可重建投影；若先做图 schema，容易把派生字段误当权威字段。
- 持久化、operation journal、恢复和 migration 必须在 Slice 3 一起设计，不能在 Slice 1 形成半套写入路径。

## 4. 逻辑记录平面

本节描述逻辑所有权，不代表 Slice 1 创建任何实际存储。

| 平面 | 记录 | 权威语义 |
| --- | --- | --- |
| Knowledge Graph | Work、Publication、Document、Identifier、Person、Venue、Topic、Method、ResearchTask、Dataset、Claim、EvidencePassage、SemanticRelation、Collection、Note、TechnicalLineage、LineageSynthesis | 规范化实体、确认知识和结构关系；生命周期记录可被新快照替换，但历史由后续持久化与审计保留 |
| Append-only Provenance | SourceRecord、MetadataAssertion、RelationshipAssertion、AssertionRetraction | 永不原地覆盖、永不 merge；当前 metadata 与 factual edge 必须从这些记录重建 |
| Control Plane | ReviewCandidate、ResearchRun，以及后续 plan、revision、review event、journal | 不在 Slice 1 做存储映射；Slice 1 只保留 ID 类型和跨平面引用语义 |

`ReviewCandidate` 仍表示“未进入 confirmed graph 的 merge、Claim 或 semantic relationship 提议”；`ResearchRun` 仍表示“有界、可恢复的研究工作流”。两者不是 Slice 1 的 Ladybug 节点、SQLite 表或内存 repository。

## 5. 生产模块布局与导入规则

首个实现使用以下布局：

```text
src/noa/domain/
├── __init__.py
├── errors.py
├── ids.py
├── identifiers.py
├── entities.py
└── provenance.py
```

职责如下：

- `errors.py`：`DomainError` 与稳定 code。
- `ids.py`：`TypedId`、23 个具体 ID 类、prefix registry、UUIDv7 生成和解析。
- `identifiers.py`：通用值对象、`AssertionValue` variants、审核/operation attestation 值对象、外部 Identifier 规范化与 checksum。
- `entities.py`：`EndpointKind`、MetadataField/predicate 封闭 registries、attestation payload bindings/digest、`SourceRecord`、实体快照、结构字段、Claim/Evidence/SemanticRelation record class、current snapshot 索引、Document/Evidence creation、structural validation、redirect resolution、tombstone 与 initial LineageSynthesis creation。
- `provenance.py`：origin、assertion、retraction、confirmed Claim/SemanticRelation constructors、merge basis/service、`DomainProjectionInput`、structural/factual/semantic/grounding projection 与投影结果类型。
- `__init__.py`：仅显式 re-export 稳定公共符号，不包含业务逻辑。

导入方向冻结为：`errors` 无领域依赖；`ids → errors`；`identifiers → errors, ids`；`entities → errors, ids, identifiers`；`provenance → errors, ids, identifiers, entities`。不得反向导入，因此 `SemanticRelation` 使用的 reviewed predicate、`EvidencePassage` 使用的 `SourceRecord` 和全部结构 predicate 都在 `entities.py` 定义，`entities.py` 不导入 `provenance.py`。这消除了实体验证与 projection 之间的循环导入。

`noa.domain` 及其子模块不得导入：

- `fastmcp`、`mcp`；
- `ladybug`、`sqlite3`；
- CAS 或任何 NoA storage/workspace 模块；
- HTTP 客户端；
- `pathlib`、`os`、`shutil` 等文件系统 API；
- 来源适配器、parser、Sampling 或 MCP server。

## 6. 类型化 UUIDv7

### 6.1 文本格式

每个领域 ID 的唯一合法文本格式为：

```text
<prefix>_<canonical lowercase hyphenated RFC9562 UUIDv7>
```

示例：

```text
wrk_0198cd4a-2f4b-7a31-8f25-5f2ca3b77b3a
```

规则：

- prefix 必须与具体 ID 类完全匹配。
- UUID 部分必须是 36 字符、小写、带四个连字符的 canonical 文本。
- UUID `version` 必须为 7，variant 必须是 RFC 4122/RFC 9562 variant。
- 拒绝大写 UUID、无连字符、花括号、URN、额外空白、错误 prefix、UUIDv1/v4/v6/v8。
- 排序可以使用完整 canonical ID 文本形成稳定展示顺序，但 ID 顺序不得用于冲突胜者选择。

### 6.2 prefix registry

| Prefix | ID 类型 | 领域词汇 |
| --- | --- | --- |
| `wrk` | `WorkId` | Work |
| `pub` | `PublicationId` | Publication |
| `doc` | `DocumentId` | Document |
| `idn` | `IdentifierId` | Identifier |
| `per` | `PersonId` | Person |
| `ven` | `VenueId` | Venue |
| `top` | `TopicId` | Topic |
| `mth` | `MethodId` | Method |
| `tsk` | `ResearchTaskId` | Research Task |
| `dts` | `DatasetId` | Dataset |
| `src` | `SourceRecordId` | Source Record |
| `mas` | `MetadataAssertionId` | Metadata Assertion |
| `ras` | `RelationshipAssertionId` | Relationship Assertion |
| `ret` | `AssertionRetractionId` | Assertion Retraction |
| `clm` | `ClaimId` | Claim |
| `evp` | `EvidencePassageId` | Evidence Passage |
| `sem` | `SemanticRelationId` | Semantic Relation |
| `rvc` | `ReviewCandidateId` | Review Candidate |
| `col` | `CollectionId` | Collection |
| `nte` | `NoteId` | Note |
| `lin` | `TechnicalLineageId` | Technical Lineage |
| `syn` | `LineageSynthesisId` | Lineage Synthesis |
| `run` | `ResearchRunId` | Research Run |

### 6.3 生成实现

首个实现必须：

1. 在 `pyproject.toml` 增加精确直接依赖 `uuid6==2025.0.1`。
2. 通过 NoA 的 `uv lock` 流程更新 `uv.lock`。
3. `ids.py` 提供唯一叶子 entropy source `generate_uuid7_value() -> UUID`；它只调用 `uuid6.uuid7()` 并立即校验 version/variant，不包含领域分支，也不归类为领域服务。
4. `TypedId` 是 frozen、可哈希的抽象值基类，唯一实例字段为 `uuid_value: UUID`，并公开 `text: str`、`__str__()`、`sort_key() -> str`。23 个具体 ID 类各自声明固定 `PREFIX: ClassVar[str]`，不得直接实例化 `TypedId`。
5. 每个具体 ID 类继承同一套两个 classmethod：`from_uuid7(uuid_value: UUID) -> Self` 和 `parse(text: str) -> Self`。`from_uuid7` 只包装显式 UUIDv7；`parse` 校验对应 prefix 和 canonical text。两者均再次校验 version/variant。
6. 应用组合点以后以 `WorkId.from_uuid7(generate_uuid7_value())` 这类显式两步调用取得新 ID；projection、merge、confirmation 等领域服务只接收已生成 ID，不读取时钟或随机源。

禁止任何具体 ID 类提供零参数 factory 隐式读取时钟；禁止自写 UUIDv7 时间位、随机位或时钟回拨算法；禁止用 UUIDv4 冒充 UUIDv7；禁止只因字符串形状相似就接受非 v7 UUID。

### 6.4 ID 联合类型

以下名称是封闭 type alias，不是可实例化基类：

- `KnowledgeEntityId = WorkId | PublicationId | DocumentId | IdentifierId | PersonId | VenueId | TopicId | MethodId | ResearchTaskId | DatasetId | ClaimId | EvidencePassageId | SemanticRelationId | CollectionId | NoteId | TechnicalLineageId | LineageSynthesisId`。
- `RelationshipEndpointId = KnowledgeEntityId | SourceRecordId`。
- `LifecycleEntityId = WorkId | PublicationId | DocumentId | IdentifierId | PersonId | VenueId | TopicId | MethodId | ResearchTaskId | DatasetId | ClaimId | EvidencePassageId | CollectionId | NoteId | TechnicalLineageId | LineageSynthesisId`。SemanticRelation 以 retraction 退出 current，没有 lifecycle；SourceRecord 与 provenance records 也没有 lifecycle。
- `MergeableEntityId = WorkId | PublicationId | IdentifierId | PersonId | VenueId | TopicId | MethodId | ResearchTaskId | DatasetId`。
- `AssertionTargetId = MetadataAssertionId | RelationshipAssertionId | SemanticRelationId`。
- `ProvenanceRecordId = SourceRecordId | MetadataAssertionId | RelationshipAssertionId | AssertionRetractionId`。

实现不得使用含义不明的 `EntityId`、`TypedId` 返回值或任意字符串替代这些封闭联合；泛型函数必须用 `TypeVar`/`Self` 保留具体 ID 类型。

## 7. 共享值对象

所有值对象使用不可变、可哈希语义。构造失败抛出稳定 `DomainError`。

### 7.1 `ContentDigest`

- Slice 1 只接受 SHA-256。
- canonical text 为 `sha256:` 加 64 个小写十六进制字符。
- 输入允许十六进制 A–F，存储时转小写；不允许空白、缺位、其他算法或裸 64 字符。
- 领域层不读取文件、不计算 digest，只校验调用方提供的 digest。

### 7.2 `LanguageTag`

- 表示来源文本或派生文本的语言标签；这是 **NoA constrained language-tag profile**，不是完整 BCP 47 实现。
- 唯一接受 grammar 为 ASCII、大小写不敏感的 `(?:[A-Za-z]{2,3}|und)(?:-[A-Za-z0-9]{2,8})*`。
- canonical text 全部小写，例如 `zh-hans`、`en-us`、`und`；本 profile 不赋予 script、region、variant 扩展段不同大小写语义。
- 拒绝空标签、空段、下划线、空白、单字符主语言、四字符主语言、private-use-only 和 grandfathered 特例。
- 本切片不做 IANA registry lookup，也不证明某个子标签已注册；`und` 是未知或非语言文本的显式值，不用 `None` 表示未知语言。

### 7.3 `UtcInstant`

- 包装 timezone-aware `datetime`。
- 拒绝 naive datetime。
- 构造时转换到 UTC，保留微秒。
- canonical text 为 RFC 3339 UTC：微秒为零时严格输出 `YYYY-MM-DDTHH:MM:SSZ`；微秒非零时严格输出六位小数 `YYYY-MM-DDTHH:MM:SS.ffffffZ`，不裁掉末尾零。
- equality 和 ordering 按 UTC instant，而非原始 offset 文本。
- 领域服务不调用当前时钟；时间必须由调用方显式传入。

### 7.4 `EvidenceLocator`

- Slice 1 是 opaque、nonblank 字符串。
- 去除首尾 Unicode 空白后必须非空，canonical 值为去除后的字符串。
- 拒绝 Unicode General Category 为 `Cc`、`Cf` 或 `Cs` 的任意 code point；因此 NUL、换行、tab、bidi/zero-width format controls 和孤立 surrogate 都不合法。`Co` private-use 与 `Cn` unassigned 不因 category 本身被拒绝。
- 不解析页码、段落、XPath、字符 offset 或 JSON Pointer。
- locator grammar、Document 类型相关校验和 locator 可解析性属于 Slice 5。

### 7.5 `IdentifierKey`

`IdentifierScheme` 是封闭枚举：`doi`、`arxiv`、`openalex`、`orcid`、`ror`、`issn`。

- `IdentifierKey` 由 `IdentifierScheme` 和该 scheme 的 canonical normalized value 组成。
- equality 和 hashing 使用二元组 `(scheme, normalized_value)`。
- 只能由 `normalize_identifier()` 或已校验的 scheme 专用构造器产生。
- URI 只是输入/显示形式，不进入 key；例如 DOI key 保存 `10.1000/xyz`，不保存 `https://doi.org/10.1000/xyz`。

### 7.6 `MetadataFieldKey`

`MetadataFieldKey` 是封闭 string enum，不接受任意字符串；member name 是下表 canonical key 大写并把 `.` 替换为 `_`，例如 `WORK_TITLE="work.title"`、`PUBLICATION_YEAR="publication.year"`。`AssertionValueKind` 是封闭枚举：`text`、`integer`、`boolean`、`digest`、`language`、`instant`、`identifier`。`MetadataFieldSpec` 是 frozen 值，字段为 `key: MetadataFieldKey`、`target_kind: EndpointKind`、`value_kind: AssertionValueKind`、`language_scoped: bool`、`integer_range: tuple[int, int] | None`、`allowed_text_values: tuple[str, ...]`。公开只读 `METADATA_FIELD_REGISTRY: Mapping[MetadataFieldKey, MetadataFieldSpec]` 完整对应下表；未使用的 range/allowed tuple 分别为 `None`/空 tuple。canonical key 与目标实体、值类型、是否按语言分槽绑定。

| Key | 目标 | `AssertionValue` variant | 语言分槽 | 额外约束 |
| --- | --- | --- | --- | --- |
| `work.title` | Work | text | 是 | nonblank |
| `work.abstract` | Work | text | 是 | nonblank |
| `work.year` | Work | integer | 否 | `0..9999` |
| `work.language` | Work | language | 否 | 无 |
| `publication.title` | Publication | text | 是 | nonblank |
| `publication.abstract` | Publication | text | 是 | nonblank |
| `publication.year` | Publication | integer | 否 | `0..9999` |
| `publication.language` | Publication | language | 否 | 无 |
| `publication.volume` | Publication | text | 否 | text language 必须为 `und` |
| `publication.issue` | Publication | text | 否 | text language 必须为 `und` |
| `publication.pages` | Publication | text | 否 | text language 必须为 `und` |
| `publication.publisher` | Publication | text | 是 | nonblank |
| `document.language` | Document | language | 否 | 无 |
| `person.display_name` | Person | text | 是 | nonblank |
| `person.given_name` | Person | text | 是 | nonblank |
| `person.family_name` | Person | text | 是 | nonblank |
| `venue.name` | Venue | text | 是 | nonblank |
| `venue.abbreviated_name` | Venue | text | 是 | nonblank |
| `venue.publisher` | Venue | text | 是 | nonblank |
| `venue.type` | Venue | text | 否 | language=`und`；值为 `journal`、`conference`、`repository`、`book_series`、`ebook_platform`、`other` 之一 |
| `topic.label` | Topic | text | 是 | nonblank |
| `topic.description` | Topic | text | 是 | nonblank |
| `method.label` | Method | text | 是 | nonblank |
| `method.description` | Method | text | 是 | nonblank |
| `research_task.label` | ResearchTask | text | 是 | nonblank |
| `research_task.description` | ResearchTask | text | 是 | nonblank |
| `dataset.name` | Dataset | text | 是 | nonblank |
| `dataset.description` | Dataset | text | 是 | nonblank |
| `dataset.version` | Dataset | text | 否 | text language 必须为 `und` |

未列出的实体在 Slice 1 没有 metadata field；其核心内容由实体构造器冻结，而不是塞入任意 metadata map。

### 7.7 `AssertionValue`

`AssertionValue` 是封闭 tagged sum，恰好是以下一个 variant：

- `TextAssertionValue(text: str, language: LanguageTag)`：text 做 Unicode NFC、去除首尾空白后必须非空；内部空白不折叠。
- `IntegerAssertionValue(value: int)`：明确拒绝 `bool`。
- `BooleanAssertionValue(value: bool)`。
- `DigestAssertionValue(value: ContentDigest)`。
- `LanguageAssertionValue(value: LanguageTag)`。
- `InstantAssertionValue(value: UtcInstant)`。
- `IdentifierAssertionValue(value: IdentifierKey)`。

禁止 `float`、`Decimal`、`None`、list、tuple 作为复合值、dict、任意 JSON、bytes 和调用方自定义对象。每个 variant 提供固定的 `sort_key()`；该 key 只用于稳定展示和去重，不用于跨 contender 选胜者。

### 7.8 `EntityLifecycle`

`EntityLifecycle = ActiveLifecycle | RedirectLifecycle | TombstoneLifecycle`，三个 frozen tagged variants 为：

- `ActiveLifecycle`：tag=`active`，没有字段；只由 initial entity create functions 产生。
- `RedirectLifecycle(target_id: LifecycleEntityId, transition_attestation: AcceptedOperationAttestation | AcceptedReviewAttestation, redirected_at: UtcInstant)`：tag=`redirect`；所属 entity validator 必须验证 target ID 与自身为同一具体 ID 类型，attestation action 为 `merge_exact_identity` 或 `merge_fuzzy`，且 `redirected_at >= accepted_at`。
- `TombstoneLifecycle(accepted_operation: AcceptedOperationAttestation, tombstoned_at: UtcInstant)`：tag=`tombstone`；operation action 必须为 `tombstone_entity`、principal kind 为 human，且 `tombstoned_at >= accepted_at`；实体不进入 current projection，但历史 ID 和记录保留。

不存在从 `redirect` 回到 `active`、从 `tombstone` 回到 `active` 的公开转换。

### 7.9 审核与 operation attestation

`ReviewAction` 是封闭枚举：`confirm_claim`、`confirm_semantic_relation`、`merge_fuzzy`。

`AcceptedReviewAttestation` 是 frozen 值对象，字段为：

- `candidate_id: ReviewCandidateId`；
- `candidate_revision: int`，必须为正整数且明确拒绝 `bool`；
- `action: ReviewAction`；
- nonblank `actor`，表示命名人类；
- nonblank `review_event_reference`，表示控制平面中的不可变审核事件引用；
- `payload_digest: ContentDigest`，绑定被接受的 canonical proposal payload；
- `accepted_at: UtcInstant`。

`OperationAction` 是封闭枚举：`source_ingest`、`source_refresh`、`human_correction`、`retract_record`、`merge_exact_identity`、`tombstone_entity`。

`AttestationPrincipalKind` 是封闭枚举：`human`、`service`。

`AcceptedOperationAttestation` 是 frozen 值对象，字段为：

- nonblank `operation_reference`；
- `operation_revision: int`，必须为正整数且明确拒绝 `bool`；
- `action: OperationAction`；
- `principal_kind: AttestationPrincipalKind`；
- nonblank `principal`；
- nonblank `review_event_reference`；
- `payload_digest: ContentDigest`，绑定被接受的 canonical operation payload；
- `accepted_at: UtcInstant`。

Slice 1 **不验证**这些引用在控制平面的真实性、权限、candidate 当前 revision 或 accepted 状态，也不签名 attestation；构造器是 authorization-free internal primitives，只验证字段形状、action 与被执行操作一致、命名人类要求和时间先后。Slice 7/应用服务必须先从受保护控制平面取得并验证 attestation，再调用这些纯函数。调用方手写一个形状合法的 attestation 不构成授权；任何 adapter、parser 或模型都不得直接调用 confirmed/destructive constructor。

`confirm_claim`、`confirm_semantic_relation` 和 fuzzy merge 要求 `AcceptedReviewAttestation`，其 nonblank `actor` 就是应用服务已验证的命名人类审核者。`HumanCorrectionOrigin` 与 tombstone 要求 human principal 的 `AcceptedOperationAttestation`；metadata/factual correction 使用 `human_correction` action，human retraction 使用 `retract_record` action。source refresh 和 exact-identity merge 允许 application policy 接受的 service principal。所有 action 不匹配都以 `attestation_action_mismatch` 失败；payload 不匹配以 `attestation_payload_mismatch` 失败。

### 7.10 attestation payload binding

所有 binding 都是 frozen tagged values。canonical encoder 固定为：UTF-8 前缀 `noa-binding-v1\0`，随后依字段顺序编码 scalar；每个 scalar 先取其 canonical text，再写 8 位小写十六进制 byte length、ASCII `:`、payload bytes。tuple 先编码十进制元素数，再按 canonical ID/text 排序逐项编码。禁止 JSON、dict iteration order、locale、当前时间或对象 `repr()` 参与。`compute_review_payload_digest()` 与 `compute_operation_payload_digest()` 使用标准库 `hashlib.sha256` 返回 `ContentDigest`；领域层不读取文件。

`ReviewPayloadBinding` 是以下封闭联合：

- `ClaimReviewBinding(work_id: WorkId, statement: str, language: LanguageTag, evidence_ids: tuple[EvidencePassageId, ...])`；
- `SemanticRelationReviewBinding(predicate: ReviewedSemanticPredicate, subject_id: KnowledgeEntityId, object_id: KnowledgeEntityId, evidence_ids: tuple[EvidencePassageId, ...])`，先执行 relationship canonicalization；
- `FuzzyMergeReviewBinding(survivor_id: MergeableEntityId, loser_id: MergeableEntityId)`。

`OperationPayloadBinding` 是以下封闭联合：

- `SourceWriteOperationBinding(proposal_digest: ContentDigest)`；
- `HumanMetadataCorrectionBinding(subject_id: KnowledgeEntityId, field: MetadataFieldKey, value: AssertionValue, asserted_at: UtcInstant)`；
- `HumanRelationshipCorrectionBinding(predicate: FactualPredicate, subject_id: RelationshipEndpointId, object_id: RelationshipEndpointId, asserted_at: UtcInstant)`；
- `HumanRetractionBinding(target_id: AssertionTargetId, reason: str, retracted_at: UtcInstant)`；
- `ExactMergeOperationBinding(survivor_id: MergeableEntityId, loser_id: MergeableEntityId, identifier_key: IdentifierKey, supporting_assertion_ids: tuple[RelationshipAssertionId, ...], merged_at: UtcInstant)`；
- `TombstoneOperationBinding(entity_id: LifecycleEntityId, tombstoned_at: UtcInstant)`。

Claim/SemanticRelation confirmation、fuzzy merge、human correction/retraction、exact merge、tombstone 和 source write batch 必须从实际参数构造对应 binding，重新计算 digest，并与 attestation 的 `payload_digest` 做 constant-time equality；不匹配 fail closed。这样 Slice 1 不验证控制平面真实性，但能验证本次领域对象与调用方声称“已接受”的 payload 完全一致。

## 8. 领域实体与最小记录

所有记录均为 frozen snapshot；tuple 字段在构造时去重并按 canonical ID 排序。非空文本执行 Unicode NFC 和首尾去空白。所有 entity、SourceRecord、Claim、SemanticRelation 和 provenance record class 使用 `dataclass(frozen=True, init=False)` 或等价机制；它们的 raw constructor 与 `_from_validated` helper 不从 `noa.domain.__init__` re-export。调用方只能使用第 16 节公开 create/confirm/transition functions，不能直接传入 lifecycle 或绕过 attestation。`LifecycleEntitySnapshot = Work | Publication | Document | Identifier | Person | Venue | Topic | Method | ResearchTask | Dataset | EvidencePassage | Claim | Collection | Note | TechnicalLineage | LineageSynthesis`，不存在字段可变的通用 `EntitySnapshot` 基类。`MergeableEntitySnapshot = Work | Publication | Identifier | Person | Venue | Topic | Method | ResearchTask | Dataset`。

| 实体 | 必需字段与不变量 |
| --- | --- |
| Work | `id`、`lifecycle` |
| Publication | `id`、`work_id`、`lifecycle`；创建时 Work 必须 active |
| Document | `id`、`publication_id`、`content_digest`、nonblank lowercase `media_type`、`lifecycle`；创建时 Publication 必须 active；digest 全局唯一规则见第 8.3 节 |
| Identifier | `id`、`key`、`lifecycle`；Identifier 可以暂时无 owner |
| Person | `id`、`lifecycle` |
| Venue | `id`、`lifecycle` |
| Topic | `id`、`lifecycle` |
| Method | `id`、`lifecycle` |
| ResearchTask | `id`、`lifecycle` |
| Dataset | `id`、`lifecycle` |
| SourceRecord | `id`、`source_system`、`source_record_key`、`retrieved_at`、`payload_digest`、nonblank lowercase `media_type`、`accepted_operation`；operation action 只能是 `source_ingest` 或 `source_refresh`；永远 append-only，无 lifecycle |
| EvidencePassage | `id`、`source_id`、`locator`、nonblank `text`、`source_language`、`recorded_at`、`lifecycle`；source 只能是 Document 或 SourceRecord；source 为 SourceRecord 时 `recorded_at >= retrieved_at` |
| Claim | `id`、`work_id`、nonblank `statement`、`language`、至少一个 `evidence_ids` 元素、`accepted_review: AcceptedReviewAttestation`、`confirmed_at`、`lifecycle`；attestation action 必须为 `confirm_claim`，且 `confirmed_at >= accepted_at` |
| SemanticRelation | `id`、reviewed-semantic `predicate`、合法 endpoints、至少一个 `evidence_ids` 元素、`accepted_review: AcceptedReviewAttestation`、`confirmed_at`；attestation action 必须为 `confirm_semantic_relation`，且 `confirmed_at >= accepted_at`；不可变，由 retraction 退出 current |
| Collection | `id`、nonblank `name`、零个或多个 `member_ids` 元素、`lifecycle` |
| Note | `id`、正整数 `revision`、nonblank `title`、nonblank human-authored Markdown `body`、nonblank `author`、至少一个 `attached_entity_ids` 元素、`lifecycle`；跨 revision 的持久化工作流属于 Slice 8 |
| TechnicalLineage | `id`、nonblank `name`、至少一个 `member_ids` 元素、`lifecycle` |
| LineageSynthesis | `id`、正整数 `revision`、`lineage_id`、`graph_snapshot_digest`、nonblank `body`、`language`、`claim_ids`、`evidence_ids`、`created_at`、`lifecycle`；两类引用合计至少一个 |

`ReviewCandidate` 与 `ResearchRun` 在 Slice 1 不定义持久化记录类；只提供类型化 ID。Claim、SemanticRelation 和 fuzzy merge 通过 `AcceptedReviewAttestation.candidate_id` 引用前者。

### 8.1 merge 支持集合

首版允许 merge：Work、Publication、Identifier、Person、Venue、Topic、Method、ResearchTask、Dataset。

Document 由全局内容 digest 标识；Claim、EvidencePassage、SemanticRelation 是确认知识或证据记录；Collection、Note、TechnicalLineage、LineageSynthesis 有自己的后续版本工作流。它们在首版不执行 merge。SourceRecord、assertion、retraction 属 append-only provenance，绝不 merge。

### 8.2 current snapshot 索引

`EntitySnapshotIndex` 是 frozen 值对象，唯一公开字段为只读 `by_id: Mapping[LifecycleEntityId, LifecycleEntitySnapshot]`，由 `build_entity_snapshot_index(snapshots: Iterable[LifecycleEntitySnapshot])` 构建。每个出现于输入的 `LifecycleEntityId` 必须恰好出现一次；第二个相同 ID 即使内容完全相同也以 `duplicate_entity_snapshot` 失败，绝不按 revision、时间、UUID、输入顺序或 dict 覆盖选择。索引还验证 concrete class 与 ID 类型一致、redirect 只出现在 merge 支持类型、所有直接结构字段的静态类型，并对已有 Documents 执行第 8.3 节全局 digest 唯一性检查；它不要求系统中所有可能 ID 都存在，只要求每个已提供 ID 唯一。

`SourceRecordIndex` 是 frozen 值对象，唯一公开字段为只读 `by_id: Mapping[SourceRecordId, SourceRecord]`，同理由 `build_source_record_index(records: Iterable[SourceRecord])` 构建；相同 `SourceRecordId` 出现两次以 `duplicate_record_id` 失败。MetadataAssertion、RelationshipAssertion、AssertionRetraction 和 SemanticRelation tuple 在投影入口也按各自 ID 检查唯一性；同 ID 的副本不是共同支持。SemanticRelation 不在 `EntitySnapshotIndex`，因为它没有 lifecycle，并由 retraction 控制 current。两个 index builder 都复制输入并以 `types.MappingProxyType` 或等价不可变 mapping 暴露 `by_id`，不保留调用方可变 dict。

Slice 8 的历史 Note/LineageSynthesis revisions 不直接混入 current `EntitySnapshotIndex`；应用服务必须依据显式、已接受的 revision-head 记录传入唯一 current snapshot。Slice 1 不按最大 revision 或最新时间推断 head。

### 8.3 Document 内容身份

Document 的业务唯一键是全局 `ContentDigest`，不是 `(publication_id, content_digest)`；UUIDv7 `DocumentId` 是稳定引用 ID，不改变内容身份。`create_document` 必须扫描 `EntitySnapshotIndex` 中所有 Document，包括 tombstone 历史占用：

- 若同 digest 的历史 Document 已 tombstone，优先以 `duplicate_document_digest` 失败并返回 existing Document ID；digest 永久被历史占用。Slice 1 不提供 Document recovery/untombstone/new-ID override；若未来产品需要恢复相同 bytes，必须另作 ADR 与兼容性设计。
- 否则，同 digest 且其 Publication terminal 与请求的 Publication terminal 相同：以 `duplicate_document_digest` 失败，并在 context 返回 existing Document ID；应用层的幂等导入应复用该 ID，不创建第二条记录。
- 否则，同 digest 但 Publication terminals 不同：以 `document_publication_conflict` 失败；必须先通过受批准 Publication merge 使 owners 收敛，或保留冲突而不导入，不能复制同一内容 Document。

`build_entity_snapshot_index` 的 bulk 检查先完成 ID/class/redirect 引用验证，再按 digest 分组。每组按 `DocumentId.text` 排序，仅把首两个 IDs 作为稳定错误 context，不据此选择保留者：若组内任一 Document 已 tombstone，或两个 Documents resolve 到同一 Publication terminal，抛 `duplicate_document_digest`；否则抛 `document_publication_conflict`。Publication 缺失/redirect 损坏先按对应 dangling/redirect error 失败。这样 bulk build 与单个 `create_document` 使用同一分类且不依赖输入顺序。

因此同一 bytes 不能同时成为两个不同 current Publication 的 Document。这是 `CONTEXT.md`“Document 由 content hash 标识”的首版具体化。

### 8.4 LineageSynthesis revision 身份

`LineageSynthesisId` 是跨 revision 稳定的 asset ID。Slice 1 只公开 initial create，固定 `revision=1`；调用方不能传 revision。Slice 8 若实现后续 revision，必须保持相同 ID、使用 `previous.revision + 1`、保持 `lineage_id` 不变、要求 `created_at >= previous.created_at`，并保存 immutable history 与显式 accepted head。Slice 1 不实现 revise workflow，也不以最大 revision 或 `created_at` 选 current；这里仅冻结未来 identity/version semantics。

## 9. 外部 Identifier 规范化

### 9.1 通用输入规则

- 输入必须是字符串，先去除首尾 Unicode 空白。
- URI 输入只做纯字符串解析，不发起 DNS、HTTP 或 redirect。
- URI 不得含 userinfo、非默认或显式 port、query、fragment。
- scheme/host 比较不区分 ASCII 大小写；未列出的 host 一律拒绝。
- normalizer 不猜测、不删除尾随标点、不从任意段落抽取 identifier。
- checksum 不通过时必须失败，不能只标 warning。

### 9.2 DOI

- `IdentifierScheme.DOI`。
- 接受 bare DOI、大小写不敏感的 `doi:` 前缀，以及 `http`/`https` URI。
- URI host 只接受 `doi.org`、`dx.doi.org`；path 必须只表示一个 DOI。
- URL path 按 UTF-8 严格 percent-decode 一次；二次编码不再展开。
- NoA Slice 1 明确采用比完整 DOI name space 更窄的 **ASCII compatibility profile**：`10.` + 4–9 个十进制数字 + `/` + 至少一个 suffix 字符；suffix 只接受 ASCII 字母数字和 `-._;()/:`。这保证当前 Crossref/DataCite/OpenAlex adapter 与 URI round-trip 的确定性，但会拒绝标准生态中可能存在的其他合法 Unicode 或 legacy punctuation DOI；扩大 profile 必须另作兼容性变更并加 corpus 测试，normalizer 不得自行放宽。
- 等价比较只把 Basic Latin `A-Z` 转为 `a-z`；canonical value 为小写 ASCII DOI name。
- 无 checksum。
- canonical URI：`https://doi.org/{value}`。
- owner 目标：Publication 或 Dataset；不得绑定 Work。

### 9.3 arXiv

- `IdentifierScheme.ARXIV`。
- 接受 bare ID、大小写不敏感的 `arxiv:` 前缀，以及 host 恰为 `arxiv.org` 的 `http`/`https` URL。
- URL path 只接受 `/abs/{id}`、`/pdf/{id}`、`/pdf/{id}.pdf`。
- modern ID：`YYMM.NNNN`（0704–1412）或 `YYMM.NNNNN`（1501 起），可加 `vN`；月份必须 `01..12`，序号不能全零，版本必须从 `v1` 起且无前导零。
- legacy ID：`archive/YYMMNNN`，可加 `vN`；月份范围为 1991-07 至 2007-03，archive canonical 为小写，archive 字符为小写字母、数字、点和连字符，序号不能全零。
- canonical value 不含 `arXiv:`、URL、`.pdf`；archive 和 `v` 使用小写。
- 无 checksum。
- canonical URI：`https://arxiv.org/abs/{value}`。
- owner 目标仅 Publication。

### 9.4 OpenAlex

- `IdentifierScheme.OPENALEX`。
- 接受 bare ID、`openalex:` 前缀、`https://openalex.org/{ID}`、`https://openalex.org/{plural}/{ID}`、`https://api.openalex.org/{plural}/{ID}`。
- prefix canonical 为大写，数字部分必须为正十进制整数且无前导零。
- Slice 1 接受的 prefix 与 plural：`W/works`、`A/authors`、`S/sources`、`I/institutions`、`C/concepts`、`P/publishers`、`F/funders`、`T/topics`；URI 中 plural 必须与 prefix 匹配。
- canonical value 例如 `W2741809807`。
- 无 checksum。
- canonical URI：`https://openalex.org/{value}`。
- owner 目标：`W→Publication`、`A→Person`、`S→Venue`、`C/T→Topic`。
- `I`、`P`、`F` 可以规范化并保留为无 owner Identifier，但当前没有兼容实体类型；不得把 Institution、Publisher 或 Funder 偷映射成 Venue。

### 9.5 ORCID

- `IdentifierScheme.ORCID`。
- 接受 16 字符 compact form、canonical hyphenated form、`orcid:` 前缀，以及 host 恰为 `orcid.org` 的 `http`/`https` URI。
- canonical value 为 `dddd-dddd-dddd-dddC`，最后一位 `C` 为数字或大写 `X`；保留所有前导零。
- checksum 使用 ISO/IEC 7064 MOD 11-2：对前 15 位依次执行 `total = (total + digit) * 2`，`result = (12 - total % 11) % 11`，10 表示 `X`。
- canonical URI：`https://orcid.org/{value}`。
- owner 目标仅 Person。

### 9.6 ROR

- `IdentifierScheme.ROR`。
- 接受 bare 9 字符 ID、`ror:` 前缀、`ror.org/{id}`，以及 host 恰为 `ror.org` 的 `http`/`https` URI。
- canonical value 为小写，形状 `0` + 6 个 Crockford Base32 字符 + 2 个十进制 checksum；Base32 字符排除 `i`、`l`、`o`、`u`。
- 将中间 6 字符按 Crockford Base32 解码为整数 `n`；checksum 必须等于两位十进制 `98 - ((n * 100) % 97)`，不足两位左补零。
- canonical URI：`https://ror.org/{value}`。
- ROR 表示 organization。NoA 当前没有 Organization 实体，因此只规范化并保留无 owner Identifier；不得映射到 Venue。

### 9.7 ISSN

- `IdentifierScheme.ISSN`。
- 接受 8 字符 compact form、canonical hyphenated form、大小写不敏感的 `issn:` 前缀，以及 `https://portal.issn.org/resource/ISSN/{value}`。
- canonical value 为 `dddd-dddC`，最后一位为数字或大写 `X`；拒绝全零。
- checksum：前 7 位分别乘 `8,7,6,5,4,3,2` 求和；`check = (11 - sum % 11) % 11`，10 表示 `X`。
- canonical URI：`https://portal.issn.org/resource/ISSN/{value}`。
- owner 目标仅 Venue。

### 9.8 Identifier owner 约束

`has_identifier` 是 source-attributed factual 关系。一个规范化 `IdentifierKey` 在 current projection 中最多有一个 owner。相同 key 的多个 Identifier 实体或多个 owner 都形成显式 projection conflict；系统不得按最早 ID、最晚 assertion、UUID、provider 名称或插入顺序偷选。

由 SourceRecord 规范化出的每个 Identifier 必须同时产生 `observed_identifier(SourceRecord → Identifier)` factual assertion。它与 SourceOrigin 一起保存 Identifier 的来源，即使 ROR 或 OpenAlex `I/P/F` 因没有兼容 owner 而保持 ownerless，也能从 append-only provenance 重建其 source system、source record key 和 payload digest。人工直接关联已有 key 时，HumanCorrectionOrigin 保留在 `has_identifier` assertion；不得伪造 SourceRecord。

## 10. Predicate registry

### 10.1 通用规则

`PredicateKind` 是封闭枚举：`structural`、`factual`、`reviewed_semantic`。`EndpointKind` 是封闭枚举：`work`、`publication`、`document`、`identifier`、`person`、`venue`、`topic`、`method`、`research_task`、`dataset`、`source_record`、`evidence_passage`、`claim`、`semantic_relation`、`collection`、`note`、`technical_lineage`、`lineage_synthesis`。`Cardinality` 是封闭枚举：`exactly_one`、`zero_or_one`、`one_or_more`、`zero_or_more`，分别显示为 `1`、`0..1`、`1..*`、`0..*`。

`StructuralPredicate`、`FactualPredicate`、`ReviewedSemanticPredicate` 分别是第 10.2、10.3、10.4 节表中 canonical predicate strings 的封闭枚举；`Predicate = StructuralPredicate | FactualPredicate | ReviewedSemanticPredicate`。`PredicateSpec` 是 frozen 值，字段为 `predicate: Predicate`、`kind: PredicateKind`、`subject_kinds: tuple[EndpointKind, ...]`、`object_kinds: tuple[EndpointKind, ...]`、`subject_cardinality: Cardinality`、`object_cardinality: Cardinality`、`irreflexive: bool`、`acyclic: bool`、`symmetric: bool` 与唯一正整数 `registry_order: int`。每个 predicate enum member name 是 canonical string 大写，例如 `PUBLICATION_OF="publication_of"`。公开只读 `PREDICATE_REGISTRY: Mapping[Predicate, PredicateSpec]` 按 predicate 索引；`registry_order` 是第 10.2 表自上而下从 1 开始，随后连续接第 10.3、10.4 表，不得另行排序或留洞。

- registry 是封闭枚举；未知 predicate 失败。
- 每个 predicate 固定 kind、canonical direction、endpoint 类型、两端 cardinality、irreflexive、acyclic、symmetric。
- structural 关系只从第 10.5 节列出的实体字段派生；不存在第二套结构记录形式，也不用 `RelationshipAssertion` 表示。
- factual 关系只能由 `RelationshipAssertion` 表示。
- reviewed-semantic 关系只能由 confirmed `SemanticRelation` 表示。
- 不定义 inverse predicate，例如没有 `author_of`、`cited_by`、`has_publication`。反向遍历是查询行为，不复制反向边。
- symmetric predicate 的 endpoints 按 canonical typed-ID 文本升序保存；反向输入被规范为同一 logical key，不能形成第二条反向边。
- irreflexive 和 endpoint 类型在创建时检查；redirect 后形成的 self-edge 在 projection 中标为 conflict，不抛出读取异常。
- acyclic 按单个 predicate 的 current logical edges 检查，不把不同 predicate 混成一个 DAG。

cardinality 记法：`1` 为恰好一个，`0..1` 为最多一个，`1..*` 为至少一个，`0..*` 为任意个。structural 的下限由实体构造器执行；factual/reviewed 的 max-one 和 cycle 冲突由 projection 返回数据，不因来源数据冲突抛异常。

### 10.2 structural predicates

| Predicate | Canonical direction | Subject cardinality | Object cardinality | Irreflexive | Acyclic | Symmetric |
| --- | --- | --- | --- | --- | --- | --- |
| `publication_of` | Publication → Work | `1` | `0..*` | 是 | 是 | 否 |
| `document_of` | Document → Publication | `1` | `0..*` | 是 | 是 | 否 |
| `evidence_from` | EvidencePassage → Document、SourceRecord | `1` | `0..*` | 是 | 是 | 否 |
| `claim_of` | Claim → Work | `1` | `0..*` | 是 | 是 | 否 |
| `claim_supported_by` | Claim → EvidencePassage | `1..*` | `0..*` | 是 | 是 | 否 |
| `semantic_supported_by` | SemanticRelation → EvidencePassage | `1..*` | `0..*` | 是 | 是 | 否 |
| `collection_contains` | Collection → Work、Publication、Document、Person、Venue、Topic、Method、ResearchTask、Dataset、Claim、SemanticRelation | `0..*` | `0..*` | 是 | 是 | 否 |
| `note_attached_to` | Note → Work、Publication、Document、Person、Venue、Topic、Method、ResearchTask、Dataset、Claim、EvidencePassage、SemanticRelation、Collection、TechnicalLineage | `1..*` | `0..*` | 是 | 是 | 否 |
| `lineage_contains` | TechnicalLineage → Work、Claim、Method、ResearchTask、Dataset、SemanticRelation | `1..*` | `0..*` | 是 | 是 | 否 |
| `synthesis_of` | LineageSynthesis → TechnicalLineage | `1` | `0..*` | 是 | 是 | 否 |
| `synthesis_cites_claim` | LineageSynthesis → Claim | `0..*` | `0..*` | 是 | 是 | 否 |
| `synthesis_cites_evidence` | LineageSynthesis → EvidencePassage | `0..*` | `0..*` | 是 | 是 | 否 |

`LineageSynthesis` 另有组合不变量：`synthesis_cites_claim` 与 `synthesis_cites_evidence` 的总数至少为 1。

### 10.3 factual predicates

| Predicate | Canonical direction | Subject cardinality | Object cardinality | Irreflexive | Acyclic | Symmetric |
| --- | --- | --- | --- | --- | --- | --- |
| `has_identifier` | Publication、Dataset、Person、Venue、Topic → Identifier | `0..*` | `0..1` | 是 | 是 | 否 |
| `observed_identifier` | SourceRecord → Identifier | `0..*` | `0..*` | 是 | 是 | 否 |
| `authored_by` | Publication → Person | `0..*` | `0..*` | 是 | 是 | 否 |
| `published_in` | Publication → Venue | `0..1` | `0..*` | 是 | 是 | 否 |
| `cites` | Publication → Publication | `0..*` | `0..*` | 是 | 否 | 否 |
| `is_version_of` | Publication → Publication | `0..1` | `0..*` | 是 | 是 | 否 |
| `has_topic` | Work → Topic | `0..*` | `0..*` | 是 | 是 | 否 |
| `describes_dataset` | Publication → Dataset | `0..*` | `0..*` | 是 | 是 | 否 |

`has_identifier` 还必须通过第 9 节的 scheme/prefix target compatibility。`observed_identifier` 保存“哪个不可变 SourceRecord 观察到该 IdentifierKey”的出处；其 SourceOrigin 必须指向同一个 subject SourceRecord。`RelationshipAssertion` 不得承载 structural 或 reviewed-semantic predicate。

### 10.4 reviewed-semantic predicates

| Predicate | Canonical direction | Subject cardinality | Object cardinality | Irreflexive | Acyclic | Symmetric |
| --- | --- | --- | --- | --- | --- | --- |
| `supports` | Claim → Claim | `0..*` | `0..*` | 是 | 否 | 否 |
| `contradicts` | Claim ↔ Claim，按 ID canonicalize | `0..*` | `0..*` | 是 | 否 | 是 |
| `extends` | Work → Work | `0..*` | `0..*` | 是 | 是 | 否 |
| `improves_on` | Work → Work | `0..*` | `0..*` | 是 | 是 | 否 |
| `compares_with` | Work ↔ Work，按 ID canonicalize | `0..*` | `0..*` | 是 | 否 | 是 |
| `uses_method` | Work → Method | `0..*` | `0..*` | 是 | 是 | 否 |
| `addresses_task` | Work → ResearchTask | `0..*` | `0..*` | 是 | 是 | 否 |
| `uses_dataset` | Work → Dataset | `0..*` | `0..*` | 是 | 是 | 否 |
| `about_topic` | Work、Claim → Topic | `0..*` | `0..*` | 是 | 是 | 否 |
| `derived_from` | Method → Method | `0..*` | `0..*` | 是 | 是 | 否 |

`SemanticRelation` 和 `AssertionRetraction` 是总产品契约中未单独列出的必要补充：前者让“reviewed semantic relationship”有独立、可引用、带证据的 confirmed 记录；后者让“immutable retraction”成为 append-only 事实，而不是对 assertion 的布尔字段原地更新。

### 10.5 structural 记录与投影

structural predicate 与字段的唯一映射如下；未列出的字段不得产生 structural edge：

| Predicate | 唯一来源字段 |
| --- | --- |
| `publication_of` | `Publication.work_id` |
| `document_of` | `Document.publication_id` |
| `evidence_from` | `EvidencePassage.source_id` |
| `claim_of` | `Claim.work_id` |
| `claim_supported_by` | `Claim.evidence_ids` |
| `semantic_supported_by` | `SemanticRelation.evidence_ids` |
| `collection_contains` | `Collection.member_ids` |
| `note_attached_to` | `Note.attached_entity_ids` |
| `lineage_contains` | `TechnicalLineage.member_ids` |
| `synthesis_of` | `LineageSynthesis.lineage_id` |
| `synthesis_cites_claim` | `LineageSynthesis.claim_ids` |
| `synthesis_cites_evidence` | `LineageSynthesis.evidence_ids` |

`RelationshipKey` 是 frozen 值对象，字段为 `predicate: Predicate`、`subject_id: RelationshipEndpointId`、`object_id: RelationshipEndpointId`；构造时执行 endpoint 类型、canonical direction、symmetric canonicalization 与 irreflexive 校验。`ProjectedStructuralRelationship` 是 frozen 值，字段为 canonical `key: RelationshipKey` 和按 ID 排序的 `supporting_subject_record_ids: tuple[KnowledgeEntityId, ...]`；相同 terminal key 只出现一次，但所有产生该 key 的 current subject snapshot/semantic record ID 都保留为支持。

`project_structural_relationships(projection_input: DomainProjectionInput) -> StructuralProjection` 的算法冻结如下：

1. 输入必须已通过第 8.2/12.1 节唯一性校验；SemanticRelation 来自 `projection_input.semantic_relations`，其他 structural subjects 来自 entity index。缺失 lifecycle target snapshot 或 SemanticRelation record 抛 `dangling_structural_reference`；缺 SourceRecord 抛 `source_record_not_found`。
2. 先 resolve 所有 redirect。redirect loser 不进入 candidate subject set；任何字段引用 loser 时改用同类型 terminal，原 snapshot/record 不改写。cycle/type mismatch 使用第 14.2 节错误。
3. 建立 monotone current-set fixed point。初始集合包含所有 active、非 redirect、没有 required structural target 的 lifecycle roots，以及所有存在的 SourceRecord。按 `PREDICATE_REGISTRY.registry_order` 反复扫描剩余 candidates：single required slot 的 terminal target 已在 current set 才可加入；`1..*` slot 至少一个 target current 才可加入；所有 required slots 均满足后加入。一次完整扫描无新增即结束；扫描上限为 candidate 数，超过上限以 `structural_evaluation_cycle` 失败，不猜测 current。
4. EvidencePassage 的 required source 参与同一 fixed point：active Document 必须 current，SourceRecord 必须存在。Document source 因自身或 required ancestor tombstone 而非 current 时，Evidence 统一以 `tombstoned_evidence_source` 排除。Claim 只有在 `work_id` terminal current 且至少一个 evidence current 时加入；SemanticRelation 只有未 retracted、两个 semantic endpoints current 且至少一个 evidence current 时加入。grounding callables 必须读取同一 fixed-point result，不能只检查 evidence。
5. Collection 的 `0..*` members 不决定 Collection 自身 current；Note/TechnicalLineage 的 `1..*` targets、LineageSynthesis 的 `lineage_id` 与两类 citation 合计下限则决定 subject current。由此 Work tombstone 会依次排除 Publication、Document、Evidence、Claim 及所有依赖它们的 required subjects，不存在只传播一层的实现差异。
6. fixed point 完成后才生成 edges。optional/`0..*` target 不 current 时仅排除该 edge；required target 不 current 导致 subject 以 `required_structural_target_not_current` 排除。若 target 是 retracted SemanticRelation、ungrounded Claim/SemanticRelation 或 source 不 current 的 EvidencePassage，edge 分别使用 target 的 `retracted`、`no_current_evidence`、`tombstoned_endpoint` 或 `tombstoned_evidence_source` 具体 reason，而不是只看 lifecycle。
7. 每个 single-valued structural slot 在数据模型中都是单个 typed field，不接受 tuple；构造器验证恰好一个。重复 snapshot 在第 8.2 节先失败，因此 exact-one 不产生“任选一个”的 projection conflict。
8. multi-valued 字段先按原 ID 去重，再 resolve terminal，再按 canonical logical key 去重。redirect 后收敛到同一 target 是一条关系，不是冲突。关系按 canonical key 排序；输入顺序、snapshot 时间和 UUID 不参与 current 选择。

`StructuralProjection` 是 frozen 结果，字段为 `current_record_ids: tuple[KnowledgeEntityId, ...]`、`relationships: tuple[ProjectedStructuralRelationship, ...]` 与 `excluded: tuple[StructuralExclusion, ...]`。`StructuralExclusion` 是 frozen 值，字段为 `subject_id: KnowledgeEntityId`、`relationship_key: RelationshipKey | None` 和 `reason: ProjectionExclusionReason`。损坏输入抛 `DomainError`；tombstone/grounding/current 下限不满足是结构化 exclusion，不抛错。

## 11. 出处、断言与撤回

### 11.1 `AuthorityTier`

`AuthorityTier` 是封闭枚举：`aggregator`、`authoritative_source`、`human_correction`。固定优先级如下：

```text
human_correction > authoritative_source > aggregator
```

实现使用显式 rank map，不依赖 enum 声明顺序或字符串排序。

- `aggregator`：聚合、推断或二次整理来源，例如聚合索引给出的 metadata。
- `authoritative_source`：对该 assertion 所述字段或关系具有直接权威的来源记录。tier 是 assertion 级，不是 source system 全局级。
- `human_correction`：命名人类通过受保护审核流程提交的修正。

Slice 4/application policy 决定某个 SourceRecord 对某字段使用哪一层；Slice 1 不按 provider 名称自动推断 authority。

### 11.2 origin

`SourceOrigin`：

- `source_record_id: SourceRecordId`；
- `authority_tier: AuthorityTier`，只能是 `aggregator` 或 `authoritative_source`；
- `accepted_operation: AcceptedOperationAttestation`，action 只能是 `source_ingest` 或 `source_refresh`。

构造 assertion/retraction 时，origin 的 attestation 必须与 referenced SourceRecord 的 `accepted_operation` 完全相同；source assertion 还要求 `asserted_at >= accepted_operation.accepted_at`。因此 initial ingest 与 refresh additions 都绑定到显式 accepted staged operation。

`HumanCorrectionOrigin`：

- `accepted_operation: AcceptedOperationAttestation`；
- attestation action 只能是 `human_correction` 或 `retract_record`，`principal_kind` 必须为 `human`；MetadataAssertion/RelationshipAssertion 要求前者，human retraction 要求后者；
- `actor` 与 `review_reference` 分别由 attestation 的 `principal` 与 `review_event_reference` 派生，不允许调用方另传可能不一致的字符串；
- authority 固定为 `human_correction`，调用方不能降级或伪装。

只有这两个 origin variant。不存在 `ModelOrigin`、`SamplingOrigin` 或任意字符串 origin。模型输出只能形成 ReviewCandidate，不能创建 metadata/factual assertion，也不能构造 confirmed Claim/SemanticRelation。Slice 1 只做 attestation 形状/action 校验，不把可手写值对象误当授权证明；真实性与权限由第 7.9 节边界负责。

### 11.3 `SourceRecord`

- immutable snapshot；相同 source system 的刷新创建新 `SourceRecordId`。
- `source_system` 为 lowercase slug：`[a-z][a-z0-9_-]{0,63}`。
- `source_record_key` 是该系统内稳定、nonblank、opaque key。
- lineage key 为 `(source_system, source_record_key)`。
- payload bytes 在未来 CAS；Slice 1 只保存 `payload_digest`，不读取内容。
- `accepted_operation.action` 首次采集用 `source_ingest`，同 lineage 刷新用 `source_refresh`；principal 可以是 application policy 接受的 service 或 human。
- SourceRecord 不 merge、不 tombstone、不覆盖。

### 11.4 `MetadataAssertion`

必需字段：

- `id: MetadataAssertionId`；
- `subject_id: KnowledgeEntityId`；
- `field: MetadataFieldKey`；
- `value: AssertionValue`；
- `origin: SourceOrigin | HumanCorrectionOrigin`；
- `asserted_at: UtcInstant`。

构造规则：

- subject 类型必须与 field registry 一致，创建时 subject active。
- value variant、语言分槽和额外约束必须匹配 field。
- SourceOrigin 指向的 SourceRecord 必须存在，origin/source record attestation 必须相同；`asserted_at >= retrieved_at` 且 `asserted_at >= accepted_operation.accepted_at`。HumanCorrectionOrigin 的 operation action 必须为 `human_correction`，且 `asserted_at >= accepted_at`。
- 记录创建后任何字段都不可修改。
- 不用 `None` 或空字符串表达来源声称“没有值”；不存在 assertion 即没有该来源的正向声明。

### 11.5 `RelationshipAssertion`

必需字段：

- `id: RelationshipAssertionId`；
- `predicate: FactualPredicate`；
- `subject_id: RelationshipEndpointId`、`object_id: RelationshipEndpointId`；
- `origin: SourceOrigin | HumanCorrectionOrigin`；
- `asserted_at: UtcInstant`。

构造规则：

- 创建时 endpoints 必须存在；具有 lifecycle 的 endpoint 必须 active；类型匹配并满足 irreflexive 和 Identifier target compatibility。
- 使用 SourceOrigin 时，`source_record_id` 必须存在于 `SourceRecordIndex`，origin/source record attestation 必须相同，且 `asserted_at >= SourceRecord.retrieved_at`、`asserted_at >= accepted_operation.accepted_at`；与 MetadataAssertion 使用完全相同的 source-relative timestamp 规则。HumanCorrectionOrigin 的 operation action 必须为 `human_correction`，且 `asserted_at >= accepted_at`。
- `observed_identifier` 必须使用 SourceOrigin，且 `origin.source_record_id == subject_id`；HumanCorrectionOrigin 不得伪造 source observation。
- symmetric canonicalization 规则适用于未来新增的 symmetric factual predicate；当前 factual registry 没有 symmetric predicate。若未来加入，A→B 与 B→A 输入都 canonicalize 成同一 `RelationshipKey`；不同 RelationshipAssertionId 保留为共同支持，不因反向输入而拒绝。
- max-one cardinality 不在写入时拒绝第二个来源 assertion；它是 projection conflict 数据。
- 记录创建后不可修改。

### 11.6 `AssertionRetraction`

必需字段：

- `id: AssertionRetractionId`；
- `target_id: AssertionTargetId`；
- `origin: SourceOrigin | HumanCorrectionOrigin`；
- `accepted_operation: AcceptedOperationAttestation`；
- nonblank `reason`；
- `retracted_at: UtcInstant`。

规则：

- retraction 本身 append-only、不可修改、不可被 retraction。
- 一个 target 最多有一个有效 retraction；重复请求由上层幂等处理返回既有记录，纯领域构造面对第二条不同 retraction 时失败。
- `retracted_at` 不得早于 target 的 `asserted_at` 或 `confirmed_at`，也不得早于 `accepted_operation.accepted_at`。
- HumanCorrectionOrigin 可以撤回任意 assertion 或 SemanticRelation；其 operation action 必须为 `retract_record`、principal 必须为 human，且 `origin.accepted_operation` 必须等于 retraction 字段中的 `accepted_operation`。
- SourceOrigin 只能撤回 SourceOrigin assertion，且新旧 SourceRecord 的 lineage key 必须相同；新 SourceRecord 必须存在，origin、new SourceRecord 与 retraction 三处的 accepted operation 必须完全相同，`retracted_at >= new_source_record.retrieved_at` 且 `retracted_at >= accepted_at`。它不能撤回 human correction 或 SemanticRelation。其 `accepted_operation.action` 必须为 `source_refresh`。
- Source refresh 不删除旧 assertion。未来 adapter 只能输出含新 SourceRecord、新 assertions 和待撤回 target IDs 的 proposal；应用服务验证 accepted source-refresh operation 后，才调用 Slice 1 constructors 创建新 assertion/retraction。adapter 不得直接改变 graph。
- 没有 unretract。需要恢复被撤回的内容时，创建新的 assertion 或新的 reviewed SemanticRelation，使用新 ID 和新的出处。

### 11.7 staged-operation 治理

Slice 1 不实现 adapter 或 operation journal，但定义一个纯领域 source batch，使 staged invariant 可表示和测试。

`SourceRecordProposal` 字段为 `source_record_id`、`source_system`、`source_record_key`、`retrieved_at`、`payload_digest`、`media_type`。`SourceMetadataAssertionProposal` 字段为 `assertion_id`、`subject_id`、`field`、`value`、`authority_tier`、`asserted_at`。`SourceRelationshipAssertionProposal` 字段为 `assertion_id`、`predicate`、`subject_id`、`object_id`、`authority_tier`、`asserted_at`。`SourceRetractionProposal` 字段为 `retraction_id`、`target_id`、nonblank `reason`、`retracted_at`。这些 proposal 不含 origin/attestation，避免自行伪造已接受状态。

`SourceWriteBatchProposal` 是 frozen 值，字段为 `source_record: SourceRecordProposal`、三个按 record ID 排序的 tuple：`metadata_assertions`、`relationship_assertions`、`retractions`。其 `canonical_digest()` 使用第 7.10 节 encoder，完整覆盖所有字段。`SourceWriteBatch` 是 frozen result，字段为一个 `SourceRecord` 与三个已验证 record tuples：`metadata_assertions`、`relationship_assertions`、`retractions`。

`create_source_write_batch(proposal, accepted_operation, projection_input) -> SourceWriteBatch` 执行：

1. proposal 的 `source_record_id` 必须尚未存在。action=`source_ingest` 时同 lineage 不得已存在、retractions 必须为空；action=`source_refresh` 时同 lineage 至少有一个既有 SourceRecord。
2. `accepted_operation.payload_digest` 必须等于 `SourceWriteOperationBinding(proposal.canonical_digest())` 的 digest，且 `accepted_operation.accepted_at >= proposal.source_record.retrieved_at`；不能用检索发生前已接受的 operation 声称 ingest/refresh。
3. 创建带同一 accepted operation 的 SourceRecord；为每条 assertion 创建指向该 SourceRecord 且携带同一 operation 的 SourceOrigin；每条 `asserted_at >= max(retrieved_at, accepted_at)`。
4. refresh retraction 的 target 必须是同 lineage SourceOrigin assertion；retraction、origin、新 SourceRecord 三处 operation 完全相同，且 `retracted_at >= max(target_time, retrieved_at, accepted_at)`。
5. batch 内与既有输入的 record ID、retraction target 唯一性全部检查；任一项失败则纯函数整体抛错，不返回 partial result。

治理边界冻结为：

1. source adapter/parser 只能产生 `SourceWriteBatchProposal`；模型只能产生 ReviewCandidate proposal；MCP 层不能直接调用 raw record constructor。
2. application service 先在控制平面验证 candidate/operation revision、accepted 状态、actor/principal、权限和幂等键，再传入 attestation。Slice 1 以 payload digest 验证实际领域参数与已接受 payload 相同，但不验证签名或权限真实性。
3. human correction/retraction、confirmed records、merge 和 tombstone 同样使用第 7.10 节 payload binding；wrong action/digest/time fail closed。
4. exact-identity merge 与 fuzzy merge 使用第 14.1 节不同 basis；fuzzy merge 必须有命名人类 accepted review。tombstone 与任意 destructive retraction 必须有 accepted operation。
5. Slice 3 才负责 two-phase writes、journal、recovery 和事务原子性；本节的 tuple input/output 不是 repository port 或存储实现。

### 11.8 canonical write endpoints

所有新 MetadataAssertion、RelationshipAssertion、Claim、SemanticRelation、Document、EvidencePassage 及 structural entity 引用必须使用 **active terminal ID**。创建函数对每个 lifecycle endpoint 调用 `resolve_terminal`：原 ID 已是 active terminal 才接受；redirect loser 即使可解析到 active survivor，也以 `noncanonical_write_endpoint` 失败；tombstone terminal 以 `entity_not_active` 失败。SourceRecord 没有 redirect/lifecycle，只要求存在。这样新记录不会继续扩大旧别名使用面。

历史记录保持创建时 ID，不被重写；projection 继续通过 redirect chain 聚合到 terminal。`DomainProjectionInput` 的历史重验不得对已存在记录套用本节的“新写必须 terminal”规则。

## 12. Projection 语义

### 12.1 通用结果与输入

`ProjectionStatus` 是封闭枚举：

- `missing`：没有符合 current 条件的 active contender。
- `resolved`：规则得到唯一 current 值、target 或 logical edge。
- `conflicted`：存在 active contenders，但规则禁止任意选一个。

`ProjectionRecordId = MetadataAssertionId | RelationshipAssertionId | SemanticRelationId`。`ProjectionContender[T]` 是 frozen 泛型值，字段为 `value: T`、`authority_tier: AuthorityTier | None`、`supporting_record_ids: tuple[ProjectionRecordId, ...]`；IDs 去重排序。`ProjectionExclusion` 字段为 `record_id: ProjectionRecordId`、`reason: ProjectionExclusionReason`。

`ProjectionResult[T]` 是 frozen 泛型结果，字段为：

- `status: ProjectionStatus`；
- `resolved_value: T | None`；
- `contenders: tuple[ProjectionContender[T], ...]`；
- `excluded: tuple[ProjectionExclusion, ...]`；
- `conflict_reason: ProjectionConflictReason | None`。

不变量：只有 `resolved` 可有且必须有 `resolved_value`；只有 `conflicted` 可有且必须有 `conflict_reason`；`missing` 的 contenders 为空；所有 tuple 按第 12.10 节排序。`RelationshipKey` 作为关系投影中的 `T`。预期的来源冲突、max-one 冲突、identifier owner 冲突和关系 cycle 都是 projection 数据，不抛 `DomainError`。

`DomainProjectionInput` 是 frozen 纯内存输入，字段为 `entity_index: EntitySnapshotIndex`、`source_record_index: SourceRecordIndex`、`semantic_relations: tuple[SemanticRelation, ...]`、`metadata_assertions: tuple[MetadataAssertion, ...]`、`relationship_assertions: tuple[RelationshipAssertion, ...]`、`retractions: tuple[AssertionRetraction, ...]`。Claim 位于 entity index；SemanticRelation 因无 lifecycle 而使用独立 tuple。所有 record tuple 在构造时检查 record ID 唯一，并重新验证仍可由 immutable record 自身与 append-only indexes 证明的内在不变量：字段形状、origin/attestation 一致性、source-relative time、predicate kind、创建时引用 ID 的存在性和 retraction target。它不得把“今天 endpoint 仍 active/仍是 terminal”当作历史记录有效性的重验条件；redirect/tombstone 后的历史 endpoints 必须保留并在 projection 阶段 resolve/exclude。它不接收 repository/session。输入记录自身损坏、重复 record ID、未知 predicate、missing SourceRecord、redirect cycle 或 dangling reference 才抛 `DomainError`。

### 12.2 current eligibility

所有 projection family 共享第 10.5 节私有 `evaluate_current_record_set()` 的一次结果；结构 invalidity 是全局 current eligibility，不允许 metadata/factual 投影各自只看 lifecycle。处理顺序冻结为：

1. 检查 retraction records 并建立 retracted target 集合；被撤回的 MetadataAssertion、RelationshipAssertion、SemanticRelation 不进入 current，但完整历史仍可作为 exclusion 输出。
2. resolve 所有 lifecycle IDs；SourceRecord 作为 immutable terminal 只检查存在性；历史 assertion 自身不重写。redirect cycle、dangling redirect、类型不匹配或缺 SourceRecord 是损坏状态，立即失败。
3. 运行第 10.5 节 monotone fixed point，得到全局 `current_record_ids` 与每个 non-current record 的精确 reason。active lifecycle 只是必要条件；required structural ancestor、Evidence source、Claim Work anchor、semantic endpoints 与 current evidence 都参与同一计算。
4. MetadataAssertion 只有其未撤回且 terminal subject 在 current set 中才成为 contender。RelationshipAssertion 只有其未撤回且 terminal endpoints（SourceRecord 除外）都在 current set 中才成为 contender。否则分别输出 subject/endpoint 的精确 exclusion，不产生可见 value/edge。
5. Claim 与 SemanticRelation grounding 直接读取同一结果，并另列 current evidence subset；过滤后无 current evidence 使用 `no_current_evidence`，Claim Work 或 semantic endpoint non-current 使用 `tombstoned_endpoint`，record 自身 tombstone 使用 `tombstoned_entity`。
6. 对剩余 symmetric predicate canonicalize terminal endpoints。redirect 后违反 irreflexive 的 logical edge标为 `conflicted`，reason=`irreflexive_after_redirect`。
7. 先处理 max-one slots，再对候选 current edges做 acyclic 检查。任何 timestamp、UUID、provider 名称、dict/insertion order 都不参与 eligibility 或胜者选择。

### 12.3 Claim/SemanticRelation grounding callable

`GroundingStatus` 是封闭枚举：`current`、`excluded`。`GroundingExclusion` 是 frozen 值，字段为 `evidence_id: EvidencePassageId`、`reason: ProjectionExclusionReason`；这里 reason 只允许 `tombstoned_entity` 或 `tombstoned_evidence_source`，损坏引用不是 exclusion。

`ClaimGroundingProjection` 字段为：

- `claim_id: ClaimId`；
- `status: GroundingStatus`；
- `current_evidence_ids: tuple[EvidencePassageId, ...]`；
- `excluded_evidence: tuple[GroundingExclusion, ...]`；
- `record_exclusion_reason: ProjectionExclusionReason | None`。

`SemanticRelationGroundingProjection` 结构相同，但首字段为 `semantic_relation_id: SemanticRelationId`。所有 IDs 去重并按 canonical text 排序。`status=current` 时 `current_evidence_ids` 至少一个且 `record_exclusion_reason=None`；`status=excluded` 时 reason 必须是 `retracted`、`tombstoned_entity`、`tombstoned_endpoint` 或 `no_current_evidence`。若 record 本身 current 但 evidence 过滤后为空，固定使用 `no_current_evidence`。多个条件同时成立时 record reason 优先级固定为 `retracted` > `tombstoned_entity` > `tombstoned_endpoint` > `no_current_evidence`；evidence subset 与每条 evidence exclusion 仍始终计算并返回。

两个公开纯函数为：

- `evaluate_claim_grounding(claim: Claim, projection_input: DomainProjectionInput) -> ClaimGroundingProjection`；
- `evaluate_semantic_relation_grounding(relation: SemanticRelation, projection_input: DomainProjectionInput) -> SemanticRelationGroundingProjection`。

算法：Claim 必须与 `EntitySnapshotIndex` 中同 ID 的唯一 snapshot 完全相同；SemanticRelation 必须与 `projection_input.semantic_relations` 中同 ID 的唯一 record 完全相同；缺失使用 `dangling_structural_reference`，同 ID 内容不同使用 `record_input_mismatch`。三个公开 projection paths 共同调用一个私有纯函数 `evaluate_current_record_set(projection_input)`，它实现第 10.5 节 fixed point；禁止 grounding 与 structural projection 互相递归。

随后逐个列出 evidence eligibility。EvidencePassage 自身 tombstone 使用 `tombstoned_entity`，其 Document source 因自身或 required ancestor tombstone 而非 current 时使用 `tombstoned_evidence_source`；合法 SourceRecord source 必须存在。Claim 的 `work_id` terminal 不 current 时，record-level reason 为 `tombstoned_endpoint`；SemanticRelation 任一 semantic endpoint 不 current 时同样为 `tombstoned_endpoint`。即使 record 因 endpoint/retraction 排除，仍返回可审计的 current evidence subset。缺 Evidence snapshot 抛 `dangling_structural_reference`，缺 SourceRecord 抛 `source_record_not_found`，重复 snapshot/record ID 在构建 `DomainProjectionInput` 时失败。函数不读取 repository，也不修改 immutable evidence tuple。

`project_structural_relationships`、两个 grounding callables 与 semantic edge projection 必须共享该 evaluator，不能复制 eligibility 规则。第 20 节可直接调用它们断言 `current_evidence_ids`、每条 excluded evidence reason 和 record exclusion reason。

### 12.4 metadata slot

- 非语言分槽 key：`(terminal_subject_id, field)`。
- 语言分槽 key：`(terminal_subject_id, field, TextAssertionValue.language)`。
- contender 按完整 `AssertionValue` equality 分组；相同值的多个 assertion 是共同支持，不是冲突。
- 每个 value group 的 authority 为其 active supporting assertions 的最高 tier。
- 只比较最高 authority tier：
  - 该层只有一个 distinct value：`resolved`；所有更低层不同值保留为 contender，但不进入 current。
  - 该层有多个 distinct values：`conflicted`，没有 winner。
- 较低层与 winner 相同的 assertions 仍显示为共同支持。

时间戳不影响胜者。较新的同层 assertion 不覆盖较旧 assertion。

### 12.5 同 source system 的刷新

projection 不执行“同一 source system 只保留最新 SourceRecord”或“同 lineage key 只看最大 retrieved_at”的隐式过滤。所有未显式 retracted 的旧 assertion 都继续参与投影。

因此，同一来源刷新为新值但未撤回旧值时，会按相同 authority 形成 conflict。这是故意的 fail-visible 行为，用来暴露遗漏的 refresh retraction，而不是以 last-write 隐藏历史错误。

### 12.6 max-one factual slot

适用于：

- `(Publication, published_in)`；
- `(Publication, is_version_of)`；
- `(IdentifierKey, has_identifier inverse owner)`。

规则：

- 对每个候选 target 聚合 supporting assertions，其 authority 为最高 supporting tier。
- 最高 tier 只有一个 distinct target 时 resolved；低层其他 target 保留为 contender。
- 最高 tier 有多个 distinct target 时 conflicted；普通 max-one slot reason 为 `max_one_conflict`，Identifier owner slot 必须使用更具体的 `identifier_owner_conflict`。
- 不使用 assertion 时间、UUID、provider 字典序、SourceRecord ID 或输入顺序选 target。

### 12.7 multi-valued factual slot

`observed_identifier`、`authored_by`、`cites`、`has_topic`、`describes_dataset` 允许多个 target。每个合法 logical edge 是独立 slot；任一 active assertion 即可支持 resolved edge。authority 不用于压制另一个合法 target，因为 cardinality 允许多值。删除错误 edge 需要显式 retraction。

### 12.8 Identifier owner projection

处理顺序：

1. 按 `IdentifierKey` 聚合 active Identifier 实体。
2. 若同一 key 有多个 active、互不 redirect 的 Identifier 实体，返回 `conflicted`，reason 为 `duplicate_identifier_record`；不得按 ID 选 canonical Identifier。
3. 若只有一个 terminal Identifier，再按第 12.6 节投影 owner；同一最高 tier 有多个 owner 时固定返回 `conflicted`，reason 为 `identifier_owner_conflict`。
4. 无 owner assertion 时，Identifier 保留但 owner slot 为 `missing`。
5. owner 类型或 OpenAlex prefix 不兼容是无效输入记录，不是 contender。

### 12.9 acyclic predicate

对每个标记 acyclic 的 predicate，在 max-one 处理后，对 resolved candidate edges 运行确定性的 strongly connected component 检查：

- 单节点 self-edge 和多节点 SCC 中的所有该 predicate edges 标为 `conflicted`，reason 为 `acyclic_cycle`。
- cycle 中不选择“最早”或“最可信”边；全部 cycle edges 不进入 current。
- 不在 cycle 中的 edges 保持 resolved。

### 12.10 稳定排序

排序只用于可重复输出，不参与 resolution。authority rank 固定为 `human_correction=3`、`authoritative_source=2`、`aggregator=1`。

- `SourceOrigin.stable_key()` 固定为 `("source", source_record_id.text, accepted_operation.operation_reference, accepted_operation.operation_revision, accepted_operation.payload_digest.text)`。
- `HumanCorrectionOrigin.stable_key()` 固定为 `("human", operation_reference, operation_revision, principal, review_event_reference, payload_digest.text)`。
- reviewed SemanticRelation 的 support origin key 固定为 `("review", candidate_id.text, candidate_revision, actor, review_event_reference, payload_digest.text)`。
- MetadataAssertion/RelationshipAssertion 的完整展示 key 固定为 `(-authority_rank, value_or_relationship_key.sort_key(), origin.stable_key(), asserted_at.text, id.text)`；SemanticRelation support key 固定为 `(relationship_key.sort_key(), review_origin_key, confirmed_at.text, id.text)`。
- contender 先按 `-authority_rank`、领域 value `sort_key()` 排序；其 `supporting_record_ids` 不是裸 ID 排序，而是按对应完整隐藏记录的上述展示 key 排序后投影出 IDs。exclusion 按 `(reason.value, record_id.text)` 排序。
- logical relationship 结果按 `(terminal_subject_id.text, predicate.registry_order, terminal_object_id.text)` 排序；symmetric endpoints 已先 canonicalize。

禁止把 origin、时间、typed ID 或任何展示 tie-break 当作 winner 规则。

## 13. Claim、Evidence 与 reviewed semantic knowledge

### 13.1 `EvidencePassage`

- source 只能是 active Document 或存在于 `SourceRecordIndex` 的 SourceRecord；SourceRecord source 还要求 `recorded_at >= retrieved_at`，违反时使用 `source_asserted_before_retrieval`。
- `locator` 和 `text` 均必须 nonblank。
- `source_language` 描述证据原文语言。
- EvidencePassage 不等于 citation；它是可定位、可审核的原文片段。
- Document 被 tombstone 后，EvidencePassage 和其支持的 Claim/SemanticRelation 保留历史，但该 EvidencePassage 以 `tombstoned_evidence_source` 排除 current；若 confirmed record 因此不再有任何 current evidence，则以 `no_current_evidence` 排除 current。SourceRecord 没有 tombstone。

### 13.2 `Claim`

- Claim 类只表示 confirmed object，没有 pending/draft/model-generated 状态。
- 必须属于一个 active Work。
- 必须引用至少一个 active EvidencePassage，ID 去重并稳定排序。
- `statement` nonblank；`language` 是 Claim 自身语言。
- Claim language 与 Evidence source language 独立。例如中文 Claim 可以由英文 Evidence 支持；系统不得把翻译后的 Claim 文本冒充来源原文。
- 必须带 `accepted_review: AcceptedReviewAttestation`，action 为 `confirm_claim`，并保留 candidate ID、accepted revision、命名人类 actor 与 review event reference；其 payload digest 必须等于实际 work/statement/language/sorted evidence 构成的 `ClaimReviewBinding` digest。
- 模型候选不能直接“变成” Claim；Slice 7/应用服务必须先验证 candidate 当前状态、revision、命名人类 acceptance 和权限，再调用 Slice 1 confirmed constructor。
- Slice 1 constructor 是 authorization-free internal primitive，只验证 attestation 形状/action/time 与领域不变量，不实现 ReviewCandidate 状态机，也不把调用成功解释为授权成功。

### 13.3 `SemanticRelation`

- 只接受 reviewed-semantic predicate。
- endpoint 类型、canonical direction、irreflexive、symmetric 规则必须通过。
- 至少一个 active EvidencePassage。
- 必须带 `accepted_review: AcceptedReviewAttestation`，action 为 `confirm_semantic_relation`，并保留 candidate ID、accepted revision、命名人类 actor 与 review event reference；其 payload digest 必须等于 canonical predicate/endpoints/sorted evidence 构成的 `SemanticRelationReviewBinding` digest。
- 与 Claim 相同，模型输出只能创建 candidate；人类 acceptance 的真实性、当前 revision 和权限由 Slice 7/应用服务验证后才能调用 authorization-free confirmed constructor。
- 记录不可修改；退出 current 使用 `AssertionRetraction`。
- 多个未撤回 SemanticRelation 若 canonical predicate/endpoints 相同，包括 A→B 与 B→A 两种 symmetric 输入，visible graph 只显示一条 logical edge，并保留全部 relation IDs 与 evidence 作为共同支持；只有相同 SemanticRelationId 重复出现才是 `duplicate_record_id` 损坏。
- reviewed-semantic acyclic predicate 的 cycle 按第 12.9 节处理。

## 14. merge、redirect 与 tombstone

### 14.1 merge

`ExactIdentityMergeBasis = DuplicateIdentifierBasis | SharedIdentifierBasis`，两个 frozen variant 为：

- `DuplicateIdentifierBasis(identifier_key: IdentifierKey, accepted_operation: AcceptedOperationAttestation)`：只用于两个 Identifier，要求 key 完全相同；
- `SharedIdentifierBasis(identifier_key: IdentifierKey, survivor_assertion_id: RelationshipAssertionId, loser_assertion_id: RelationshipAssertionId, accepted_operation: AcceptedOperationAttestation)`：用于两个非 Identifier、同 concrete type 实体；两个未撤回 `has_identifier` assertions 必须分别从 survivor/loser terminal 指向同一个 active Identifier terminal，且 scheme 与实体类型兼容。

两种 exact basis 都携带 action=`merge_exact_identity` 的 `AcceptedOperationAttestation`。exact 表示 identity 证据可由当前 authority records 确定，不表示 adapter 可直接执行；application service 仍须先接受 staged operation。

`ReviewedFuzzyMergeBasis(survivor_id: MergeableEntityId, loser_id: MergeableEntityId, accepted_review: AcceptedReviewAttestation)` 携带 action=`merge_fuzzy` 的 attestation；service 验证 IDs 与函数参数相同，且 payload digest 等于 `FuzzyMergeReviewBinding(survivor_id, loser_id)`。应用服务另负责证明 candidate/revision/attestation 真实对应控制平面记录。名称、标题、embedding、相似度或 provider heuristic 都只能形成 fuzzy candidate，不能形成 exact basis。

`MergeBasis = ExactIdentityMergeBasis | ReviewedFuzzyMergeBasis`。`MergeResult` 是 frozen 结果，字段为 `survivor: MergeableEntitySnapshot`、`redirected_loser: MergeableEntitySnapshot`、`basis: MergeBasis`、`merged_at: UtcInstant`；`MergeableEntitySnapshot` 是第 8.1 节九个 concrete snapshot class 的封闭联合。

`merge_entities(survivor, loser, basis, merged_at, projection_input) -> MergeResult` 的规则：

- 调用方必须显式指定 survivor 和 loser；领域服务不根据创建时间、metadata 完整度、UUID 或来源数自动选择。
- 两者必须与 `EntitySnapshotIndex` 中唯一 snapshots 完全相同，否则使用 `record_input_mismatch`；两者 ID 不同、concrete type 相同、terminal 为自身且均 active。
- 类型必须位于第 8.1 节 merge 支持集合；basis 必须按上文与输入 authority records 一致。
- `merged_at` 必须不早于 basis attestation 的 `accepted_at`。exact basis 还必须从实际 survivor/loser、identifier key、按 ID 排序的 supporting assertion IDs 与 `merged_at` 构造 `ExactMergeOperationBinding` 并验证 payload digest；fuzzy basis 必须从实际 ID pair 构造 `FuzzyMergeReviewBinding` 并验证 payload digest。
- Publication 是唯一具有 singular structural anchor 的 mergeable type；两者 `work_id` resolve 后必须是同一个 active Work terminal，否则以 `merge_structural_anchor_mismatch` 失败。若重复 Publications 分属重复 Works，必须先 merge Works 再 merge Publications。
- Identifier merge 额外要求 `IdentifierKey` 完全相同。
- 返回 survivor 的原值和一个 lifecycle 变为 `RedirectLifecycle(target_id=survivor.id, transition_attestation=basis attestation, redirected_at=merged_at)` 的 loser 新 snapshot；不复制 loser 的 structural fields 到 survivor。anchor 相容性确保 loser 停止发 edge 后不会静默丢失不同归属。
- 不改写 MetadataAssertion、RelationshipAssertion、Claim、Evidence 或 SemanticRelation 中的旧 ID；投影时 resolve redirect。
- 不 merge append-only provenance。
- 没有 unmerge。

### 14.2 terminal resolution

`resolve_terminal(entity_id: LifecycleEntityId, entity_index: EntitySnapshotIndex) -> TerminalResolution`：

- 沿同类型 redirect 链前进，直到 active 或 tombstone。
- 返回 terminal ID、terminal lifecycle 和完整 redirect path。
- target 不存在时抛 `dangling_redirect`。
- 重复访问同一 ID 时抛 `redirect_cycle`。
- redirect target 类型不同时抛 `redirect_type_mismatch`。
- tombstone 是合法 terminal，不自动抛错；current projection 负责排除。

### 14.3 tombstone

`TombstoneResult` 是 frozen 结果，字段为 `snapshot: LifecycleEntitySnapshot`、`accepted_operation: AcceptedOperationAttestation` 与 `tombstoned_at: UtcInstant`。

`tombstone_entity(entity, accepted_operation, tombstoned_at, entity_index) -> TombstoneResult`：

- attestation action 必须为 `tombstone_entity`、principal 必须是命名 human，且调用前由 application service 验证真实 accepted operation；纯函数只做 shape/action/payload/time 校验。
- 只接受与 index 中唯一 snapshot 相同（否则 `record_input_mismatch`）的 active、非 append-only provenance、非 SemanticRelation 实体。
- `tombstoned_at >= accepted_operation.accepted_at`，并从实际 `entity.id` 与 `tombstoned_at` 构造 `TombstoneOperationBinding` 验证 payload digest。
- 返回 lifecycle 为 `TombstoneLifecycle(accepted_operation, tombstoned_at)` 的新 snapshot，保留相同 ID 和其他历史字段；governance evidence 内嵌于 lifecycle 并随 result 返回，不能丢弃。
- redirect loser 不能单独 tombstone；若 survivor 后续 tombstone，整个 redirect chain 的 terminal 为 tombstone。
- 不删除 assertion、retraction、Evidence 或旧引用。
- 没有 untombstone。除 Document 外，未来若要恢复同一现实对象，只能新建实体并通过显式审核决定是否迁移关系；Document digest 永久保留，Slice 1 明确不支持恢复相同 bytes。

## 15. 错误契约

`DomainError` 至少公开：

```text
code: str
message: str
context: Mapping[str, str | int | bool | tuple[str, ...]]
```

- `code` 和 context key 是稳定机器契约。
- `message` 面向人类，可以改写，不得被状态机解析。
- context 在构造时复制并冻结；不得包含任意领域对象、异常对象或不可序列化值。

| Code | 触发条件 | 必需 context keys |
| --- | --- | --- |
| `invalid_typed_id` | ID 文本、version、variant 或 canonical form 无效 | `expected_prefix`, `value`, `reason` |
| `id_prefix_mismatch` | prefix 与 ID 类型不符 | `expected_prefix`, `actual_prefix` |
| `invalid_value_object` | 通用值对象不变量失败 | `type`, `field`, `reason` |
| `invalid_identifier` | identifier grammar/host/URI 无效 | `scheme`, `value`, `reason` |
| `identifier_checksum_mismatch` | ORCID/ROR/ISSN checksum 错误 | `scheme`, `normalized_value` |
| `identifier_target_incompatible` | key 不能绑定该实体类型 | `scheme`, `normalized_value`, `target_kind` |
| `unknown_metadata_field` | field 不在 registry | `field` |
| `metadata_field_target_mismatch` | field 与 subject 类型不符 | `field`, `target_kind` |
| `assertion_value_mismatch` | value variant/语言/范围不符 | `field`, `expected`, `actual` |
| `unknown_predicate` | predicate 不在 registry | `predicate` |
| `predicate_kind_mismatch` | assertion/relation 使用错误 kind | `predicate`, `expected_kind`, `actual_kind` |
| `predicate_endpoint_mismatch` | endpoint 类型不符 | `predicate`, `subject_kind`, `object_kind` |
| `irreflexive_relationship` | 创建时 subject=object | `predicate`, `entity_id` |
| `duplicate_entity_snapshot` | current input 中同一实体 ID 出现多个 snapshot | `entity_id`, `entity_kind` |
| `duplicate_record_id` | 同一 append-only/semantic record ID 出现多次 | `record_id`, `record_kind` |
| `record_input_mismatch` | service 参数与 index/tuple 中同 ID 的权威 snapshot/record 不完全相同 | `record_id`, `record_kind` |
| `invalid_lifecycle_transition` | snapshot replacement 不是受支持的 active→redirect/tombstone 转换 | `entity_id`, `from_lifecycle`, `to_lifecycle` |
| `noncanonical_write_endpoint` | 新写使用 redirect loser 而非 active terminal ID | `endpoint_id`, `terminal_id`, `record_kind` |
| `structural_cardinality_violation` | 实体缺少必需结构端点或把 single slot 表为多个值 | `predicate`, `entity_id`, `expected`, `actual` |
| `dangling_structural_reference` | structural target snapshot 或 SemanticRelation record 缺失 | `predicate`, `subject_id`, `target_id` |
| `structural_evaluation_cycle` | current fixed-point 超出候选数扫描上限仍未收敛 | `candidate_count`, `scan_count` |
| `entity_not_active` | 写操作要求 active 实体 | `entity_id`, `lifecycle` |
| `entity_type_mismatch` | 同类型操作收到不同实体类型 | `left_kind`, `right_kind` |
| `merge_not_supported` | 类型不在 merge 集合 | `entity_kind` |
| `merge_self` | survivor=loser | `entity_id` |
| `merge_identifier_key_mismatch` | Identifier key 不同 | `survivor_key`, `loser_key` |
| `merge_basis_invalid` | exact/reviewed basis 与实体或 authority records 不一致 | `survivor_id`, `loser_id`, `reason` |
| `merge_structural_anchor_mismatch` | mergeable entities 的 singular structural terminals 不同 | `survivor_id`, `loser_id`, `predicate`, `survivor_target`, `loser_target` |
| `dangling_redirect` | redirect target 缺失 | `entity_id`, `target_id` |
| `redirect_cycle` | redirect 链有环 | `path` |
| `redirect_type_mismatch` | redirect target 类型不同 | `entity_id`, `target_id` |
| `invalid_origin` | origin variant/tier 不合法 | `origin_kind`, `reason` |
| `source_record_not_found` | SourceOrigin/Evidence/observed edge 引用的 SourceRecord 缺失 | `source_record_id`, `record_kind`, `record_id` |
| `source_asserted_before_retrieval` | assertion/retraction/evidence 的时间早于来源 retrieved_at | `source_record_id`, `record_id`, `recorded_at`, `retrieved_at` |
| `invalid_attestation` | attestation 字段形状、revision 或 human 要求无效 | `attestation_kind`, `reason` |
| `attestation_action_mismatch` | attestation action 与操作不符 | `operation_kind`, `subject_ids`, `expected_action`, `actual_action` |
| `attestation_payload_mismatch` | 实际 canonical payload digest 与 attestation 不同 | `operation_kind`, `subject_ids`, `expected_digest`, `actual_digest` |
| `attestation_time_invalid` | confirmed/retracted/merged/tombstoned/source accepted 时间顺序无效 | `operation_kind`, `subject_ids`, `accepted_at`, `recorded_at` |
| `retraction_target_invalid` | target 类型或记录不存在 | `target_id`, `reason` |
| `assertion_already_retracted` | target 已有有效 retraction | `target_id`, `existing_retraction_id` |
| `retraction_origin_mismatch` | source lineage 不同或 source 撤回 human/semantic | `target_id`, `reason` |
| `retraction_time_invalid` | retracted_at 早于目标记录 | `target_id` |
| `evidence_source_invalid` | Evidence source 不是 Document/SourceRecord 或不 current | `source_id`, `reason` |
| `claim_evidence_required` | Claim 无 evidence | `claim_id` |
| `semantic_evidence_required` | SemanticRelation 无 evidence | `semantic_relation_id` |
| `accepted_review_required` | Claim/SemanticRelation/fuzzy merge 缺 typed accepted review attestation | `record_kind`, `record_id` |
| `duplicate_document_digest` | 全局 digest 被 tombstone 历史占用或同一 Publication terminal 下重复 | `content_digest`, `existing_document_id`, `requested_document_id`, `publication_id` |
| `document_publication_conflict` | 同 digest 被不同 current Publication terminals 声称 | `content_digest`, `existing_document_id`, `requested_document_id`, `existing_publication_id`, `requested_publication_id` |
| `tombstone_not_allowed` | 对不支持类型、非 active 实体或无 accepted operation 的 tombstone | `entity_id`, `reason` |
| `projection_slot_not_supported` | `project_relationship_slot` 用于非 factual 或 subject cardinality 不是 `0..1` 的 predicate | `predicate`, `subject_cardinality` |

`ProjectionConflictReason` 是封闭枚举：`same_tier_value_conflict`、`max_one_conflict`、`identifier_owner_conflict`、`duplicate_identifier_record`、`irreflexive_after_redirect`、`acyclic_cycle`。`ProjectionExclusionReason` 是封闭枚举：`retracted`、`tombstoned_entity`、`tombstoned_endpoint`、`required_structural_target_not_current`、`tombstoned_evidence_source`、`no_current_evidence`。两组 reason 都不是 `DomainError.code`。

## 16. 纯领域公共接口

以下名称、参数角色、可读字段和返回类型是首版稳定接口。所有参数均可实现为 keyword-only；不得以任意 `dict`、字符串 ID、未定义基类或 caller-supplied lifecycle 替代。entity、SourceRecord、origin、assertion、retraction、Claim、SemanticRelation 和 lifecycle variant 的 raw `__init__` 均不公开；模块内 `_from_validated` 也不从 `noa.domain.__init__` re-export。

### 16.1 ID、值对象、binding 与 attestation

```text
generate_uuid7_value() -> UUID
TypedId.from_uuid7(uuid_value: UUID) -> Self
TypedId.parse(text: str) -> Self

ContentDigest.parse(text: str) -> ContentDigest
LanguageTag.parse(text: str) -> LanguageTag
UtcInstant.from_datetime(value: datetime) -> UtcInstant
EvidenceLocator.parse(text: str) -> EvidenceLocator
normalize_identifier(scheme: IdentifierScheme, raw: str) -> IdentifierKey
assert_identifier_target_compatible(key: IdentifierKey, target_id: KnowledgeEntityId) -> None

TextAssertionValue.create(text: str, language: LanguageTag) -> TextAssertionValue
IntegerAssertionValue.create(value: int) -> IntegerAssertionValue
BooleanAssertionValue.create(value: bool) -> BooleanAssertionValue
DigestAssertionValue.create(value: ContentDigest) -> DigestAssertionValue
LanguageAssertionValue.create(value: LanguageTag) -> LanguageAssertionValue
InstantAssertionValue.create(value: UtcInstant) -> InstantAssertionValue
IdentifierAssertionValue.create(value: IdentifierKey) -> IdentifierAssertionValue

compute_review_payload_digest(binding: ReviewPayloadBinding) -> ContentDigest
compute_operation_payload_digest(binding: OperationPayloadBinding) -> ContentDigest

create_accepted_review_attestation(
    candidate_id: ReviewCandidateId,
    candidate_revision: int,
    action: ReviewAction,
    actor: str,
    review_event_reference: str,
    payload_digest: ContentDigest,
    accepted_at: UtcInstant,
) -> AcceptedReviewAttestation

create_accepted_operation_attestation(
    operation_reference: str,
    operation_revision: int,
    action: OperationAction,
    principal_kind: AttestationPrincipalKind,
    principal: str,
    review_event_reference: str,
    payload_digest: ContentDigest,
    accepted_at: UtcInstant,
) -> AcceptedOperationAttestation
```

`ContentDigest`、`LanguageTag`、`EvidenceLocator` 分别只读暴露 `text: str`；`UtcInstant` 暴露 `value: datetime` 与 `text: str`；`IdentifierKey` 暴露 `scheme`、`normalized_value`、`canonical_uri`；AssertionValue variants 只读暴露第 7.7 节同名字段。所有值对象提供确定性的 `sort_key()`。`MetadataFieldKey`、各 action/kind/predicate 是封闭 enum，只能由声明 member 或精确 canonical value 构造。第 7.10 节所有 binding class 的字段就是其精确 public constructor；tuple 参数在构造时去重排序，文本执行各自 canonicalization。digest 比较使用 `hmac.compare_digest` 或等价 constant-time bytes comparison。

### 16.2 proposal、origin、索引与输入

```text
create_source_record_proposal(
    source_record_id: SourceRecordId,
    source_system: str,
    source_record_key: str,
    retrieved_at: UtcInstant,
    payload_digest: ContentDigest,
    media_type: str,
) -> SourceRecordProposal

create_source_metadata_assertion_proposal(
    assertion_id: MetadataAssertionId,
    subject_id: KnowledgeEntityId,
    field: MetadataFieldKey,
    value: AssertionValue,
    authority_tier: AuthorityTier,
    asserted_at: UtcInstant,
) -> SourceMetadataAssertionProposal

create_source_relationship_assertion_proposal(
    assertion_id: RelationshipAssertionId,
    predicate: FactualPredicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
    authority_tier: AuthorityTier,
    asserted_at: UtcInstant,
) -> SourceRelationshipAssertionProposal

create_source_retraction_proposal(
    retraction_id: AssertionRetractionId,
    target_id: MetadataAssertionId | RelationshipAssertionId,
    reason: str,
    retracted_at: UtcInstant,
) -> SourceRetractionProposal

create_source_write_batch_proposal(
    source_record: SourceRecordProposal,
    metadata_assertions: Iterable[SourceMetadataAssertionProposal],
    relationship_assertions: Iterable[SourceRelationshipAssertionProposal],
    retractions: Iterable[SourceRetractionProposal],
) -> SourceWriteBatchProposal

create_source_origin(
    source_record: SourceRecord,
    authority_tier: AuthorityTier,
    accepted_operation: AcceptedOperationAttestation,
) -> SourceOrigin

create_human_correction_origin(
    accepted_operation: AcceptedOperationAttestation,
    required_action: OperationAction,
) -> HumanCorrectionOrigin

build_entity_snapshot_index(snapshots: Iterable[LifecycleEntitySnapshot]) -> EntitySnapshotIndex
replace_entity_snapshot(
    entity_index: EntitySnapshotIndex,
    replacement: LifecycleEntitySnapshot,
) -> EntitySnapshotIndex
build_source_record_index(records: Iterable[SourceRecord]) -> SourceRecordIndex
build_domain_projection_input(
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    semantic_relations: Iterable[SemanticRelation],
    metadata_assertions: Iterable[MetadataAssertion],
    relationship_assertions: Iterable[RelationshipAssertion],
    retractions: Iterable[AssertionRetraction],
) -> DomainProjectionInput
```

Proposal factories复制输入并形成按 record ID 排序的 frozen tuples；`SourceWriteBatchProposal.canonical_digest() -> ContentDigest` 精确覆盖全部 proposal 字段。`create_source_origin` 只接受 source tier 且 operation 必须与 SourceRecord 完全相同；`create_human_correction_origin` 只接受 `human_correction` 或 `retract_record` 和 human principal。origin 只读字段及 `stable_key()` 由第 11.2、12.10 节冻结。

三个 build 函数复制 iterable 并 fail closed。`replace_entity_snapshot` 要求 ID 已存在、concrete class 相同、旧 snapshot active，且 replacement 只能是由 merge 返回的 redirect 或由 tombstone 返回的 tombstone；它用 replacement 替换唯一 entry 后重新运行完整 index validator。其他 active→active、redirect/tombstone→任何状态、ID/class 改变均以 `invalid_lifecycle_transition` 失败。新增实体使用重新 `build_entity_snapshot_index((*old.by_id.values(), new_entity))`，不是 replacement helper。

### 16.3 initial entity 与 confirmed record 构造

```text
create_work(work_id: WorkId) -> Work
create_publication(
    publication_id: PublicationId,
    work_id: WorkId,
    entity_index: EntitySnapshotIndex,
) -> Publication
create_document(
    document_id: DocumentId,
    publication_id: PublicationId,
    content_digest: ContentDigest,
    media_type: str,
    entity_index: EntitySnapshotIndex,
) -> Document
create_identifier(identifier_id: IdentifierId, key: IdentifierKey) -> Identifier
create_person(person_id: PersonId) -> Person
create_venue(venue_id: VenueId) -> Venue
create_topic(topic_id: TopicId) -> Topic
create_method(method_id: MethodId) -> Method
create_research_task(research_task_id: ResearchTaskId) -> ResearchTask
create_dataset(dataset_id: DatasetId) -> Dataset
create_evidence_passage(
    evidence_id: EvidencePassageId,
    source_id: DocumentId | SourceRecordId,
    locator: EvidenceLocator,
    text: str,
    source_language: LanguageTag,
    recorded_at: UtcInstant,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
) -> EvidencePassage
create_collection(
    collection_id: CollectionId,
    name: str,
    member_ids: Iterable[KnowledgeEntityId],
    entity_index: EntitySnapshotIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> Collection
create_note(
    note_id: NoteId,
    title: str,
    body: str,
    author: str,
    attached_entity_ids: Iterable[KnowledgeEntityId],
    entity_index: EntitySnapshotIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> Note
create_technical_lineage(
    lineage_id: TechnicalLineageId,
    name: str,
    member_ids: Iterable[KnowledgeEntityId],
    entity_index: EntitySnapshotIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> TechnicalLineage
create_initial_lineage_synthesis(
    synthesis_id: LineageSynthesisId,
    lineage_id: TechnicalLineageId,
    graph_snapshot_digest: ContentDigest,
    body: str,
    language: LanguageTag,
    claim_ids: Iterable[ClaimId],
    evidence_ids: Iterable[EvidencePassageId],
    created_at: UtcInstant,
    entity_index: EntitySnapshotIndex,
) -> LineageSynthesis

confirm_claim(
    claim_id: ClaimId,
    work_id: WorkId,
    statement: str,
    language: LanguageTag,
    evidence_ids: Iterable[EvidencePassageId],
    accepted_review: AcceptedReviewAttestation,
    confirmed_at: UtcInstant,
    projection_input: DomainProjectionInput,
) -> Claim
confirm_semantic_relation(
    relation_id: SemanticRelationId,
    predicate: ReviewedSemanticPredicate,
    subject_id: KnowledgeEntityId,
    object_id: KnowledgeEntityId,
    evidence_ids: Iterable[EvidencePassageId],
    accepted_review: AcceptedReviewAttestation,
    confirmed_at: UtcInstant,
    projection_input: DomainProjectionInput,
) -> SemanticRelation

validate_structural_entity(
    entity: LifecycleEntitySnapshot,
    entity_index: EntitySnapshotIndex,
    source_record_index: SourceRecordIndex,
    semantic_relations: Iterable[SemanticRelation],
) -> None
```

所有 `create_*` initial functions 固定产生 `ActiveLifecycle()`，调用方不能传 lifecycle。`create_note` 与 `create_initial_lineage_synthesis` 固定 `revision=1`；Slice 1 没有 revise API。所有 structural references/new write endpoints 必须符合第 11.8 节 active terminal 规则。tuple fields 去重排序后再检查下限。Claim/SemanticRelation 还必须重算 review binding digest，并要求 `confirmed_at >= accepted_at`。

### 16.4 provenance 与 staged governance

```text
create_source_write_batch(
    proposal: SourceWriteBatchProposal,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> SourceWriteBatch

create_human_metadata_assertion(
    assertion_id: MetadataAssertionId,
    subject_id: KnowledgeEntityId,
    field: MetadataFieldKey,
    value: AssertionValue,
    asserted_at: UtcInstant,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> MetadataAssertion

create_human_relationship_assertion(
    assertion_id: RelationshipAssertionId,
    predicate: FactualPredicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
    asserted_at: UtcInstant,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> RelationshipAssertion

create_human_retraction(
    retraction_id: AssertionRetractionId,
    target_id: AssertionTargetId,
    reason: str,
    retracted_at: UtcInstant,
    accepted_operation: AcceptedOperationAttestation,
    projection_input: DomainProjectionInput,
) -> AssertionRetraction
```

不存在 public atom-level source assertion/retraction constructor，也不存在 generic `create_metadata_assertion`、`create_relationship_assertion` 或 caller-supplied origin 的 public API。source records 只能由完整 batch 返回。human functions 从 attestation 派生 `HumanCorrectionOrigin`，重算第 7.10 节相应 operation binding，验证 action/payload/time/new canonical endpoints 后一次返回一个 immutable record。函数是纯函数；异常时没有 partial result 或调用方对象修改。

### 16.5 relationship、grounding 与 projection

`TerminalResolution` 是 frozen 值，字段为 `terminal_id: LifecycleEntityId`、`terminal_lifecycle: EntityLifecycle`、`path: tuple[LifecycleEntityId, ...]`。`SemanticEvidenceSupport` 是 frozen 值，字段为 `semantic_relation_id: SemanticRelationId` 与 `current_evidence_ids: tuple[EvidencePassageId, ...]`。`ProjectedRelationship` 是 frozen 值，字段为 `key: RelationshipKey`、`status: ProjectionStatus`、`supporting_record_ids: tuple[RelationshipAssertionId | SemanticRelationId, ...]`、`semantic_evidence_support: tuple[SemanticEvidenceSupport, ...]`、`excluded: tuple[ProjectionExclusion, ...]`、`conflict_reason: ProjectionConflictReason | None`。factual result 的 semantic support tuple 为空；reviewed-semantic result 对每个 supporting relation 保留其 current evidence subset，symmetric grouping 不丢 relation 或 evidence。

```text
canonicalize_relationship(
    predicate: Predicate,
    subject_id: RelationshipEndpointId,
    object_id: RelationshipEndpointId,
) -> RelationshipKey
resolve_terminal(
    entity_id: LifecycleEntityId,
    entity_index: EntitySnapshotIndex,
) -> TerminalResolution
project_structural_relationships(
    projection_input: DomainProjectionInput,
) -> StructuralProjection
evaluate_claim_grounding(
    claim: Claim,
    projection_input: DomainProjectionInput,
) -> ClaimGroundingProjection
evaluate_semantic_relation_grounding(
    relation: SemanticRelation,
    projection_input: DomainProjectionInput,
) -> SemanticRelationGroundingProjection
project_metadata(
    subject_id: KnowledgeEntityId,
    field: MetadataFieldKey,
    language_slot: LanguageTag | None,
    projection_input: DomainProjectionInput,
) -> ProjectionResult[AssertionValue]
project_relationship_slot(
    subject_id: RelationshipEndpointId,
    predicate: FactualPredicate,
    projection_input: DomainProjectionInput,
) -> ProjectionResult[RelationshipEndpointId]
project_identifier_owner(
    key: IdentifierKey,
    projection_input: DomainProjectionInput,
) -> ProjectionResult[KnowledgeEntityId]
project_relationships(
    predicate: FactualPredicate | ReviewedSemanticPredicate,
    projection_input: DomainProjectionInput,
) -> tuple[ProjectedRelationship, ...]
```

`language_slot` 对语言分槽 metadata 必须非 `None`，对非语言分槽必须为 `None`。`project_relationship_slot` 只接受 factual 且 subject cardinality=`zero_or_one` 的 predicate；其他 predicate 以 `projection_slot_not_supported` 失败，multi-valued predicate 使用 `project_relationships`。grounding exact result 与 shared evaluator 规则见第 12.3 节。

### 16.6 merge、tombstone 与 immutable snapshot replacement

```text
merge_entities(
    survivor: MergeableEntitySnapshot,
    loser: MergeableEntitySnapshot,
    basis: MergeBasis,
    merged_at: UtcInstant,
    projection_input: DomainProjectionInput,
) -> MergeResult

tombstone_entity(
    entity: LifecycleEntitySnapshot,
    accepted_operation: AcceptedOperationAttestation,
    tombstoned_at: UtcInstant,
    entity_index: EntitySnapshotIndex,
) -> TombstoneResult
```

`DuplicateIdentifierBasis`、`SharedIdentifierBasis`、`ReviewedFuzzyMergeBasis` 的精确 public fields 由第 14.1 节冻结；它们通过同名 validated `create(...)` classmethod 构造，raw `__init__` 不公开。merge/tombstone 返回的新 snapshot 必须通过 `replace_entity_snapshot` 纳入后续 `DomainProjectionInput`；领域服务绝不原地修改旧 index。

所有接口只能接收显式值、frozen index 和记录集合；不能接收 repository、connection、session、filesystem path、MCP context 或回调式数据加载器。

## 17. Slice 3 的 Ladybug 映射约束

本节是未来非实施契约，不包含实际 schema 或 Cypher。

- 使用 typed node/relationship tables；不得把所有实体压入一个无类型 `Entity` 表和任意 JSON 属性。
- typed ID 文本是主键；外部 IdentifierKey 不是实体主键。
- SourceRecord、MetadataAssertion、RelationshipAssertion、AssertionRetraction 为 append-only 权威记录。
- current metadata、visible factual edges、identifier owner 和 conflict 状态是可重建 projection；缓存可丢弃重建。
- merge 只更新实体 lifecycle/redirect 表达，不批量改写 assertion endpoints。
- SemanticRelation 保留自身 ID、evidence 与完整 `AcceptedReviewAttestation`；visible semantic edge 可由 active records 重建。
- 所有查询必须 parameterized；禁止把 ID、predicate、field 或 source value 拼接进查询字符串。
- predicate 与 entity type 必须映射到预先声明的 typed table/relationship type，不接受用户任意 label。
- Slice 3 schema/migration 必须保存足够的 entity snapshots、lifecycle/redirect、append-only provenance、review attestation 和 accepted operation references，使 current projection 可重建，并为 Slice 8 的开放导出保留全部权威字段；Slice 3 本身不要求实现开放导出命令或格式。
- projection 失败不得回写或删除权威 assertion 来“修复”显示结果。

## 18. TDD 测试矩阵

| 测试组 | 先观察的失败 | 通过条件 |
| --- | --- | --- |
| ID 生成/解析 | 模块不存在；v4/错误 prefix 被拒 | 23 prefix 均包装 RFC9562 UUIDv7；唯一 entropy source 调用 `uuid6.uuid7()`；不存在零参数 typed-ID factory；canonical round-trip；错误格式有稳定 code/context |
| dependency pin | package metadata 中无 uuid6 | `uuid6==2025.0.1` 为直接依赖且 lock 校验通过 |
| 值对象 | 空值、naive datetime、float/None/JSON 被误收 | 所有第 7 节不变量和 canonical form 通过表驱动测试 |
| DOI | 错 host、suffix、大小写处理 | bare/label/官方 host 归一到同 key；不删尾标点；错误 grammar 失败 |
| arXiv | 0704/1412/1501 边界、legacy 月份和 v0 | modern/legacy 边界精确；URL 与 bare 等价 |
| OpenAlex | plural/prefix 不匹配、未知 prefix | host/route/prefix 精确；目标类型表完整；ownerless `I/P/F` 通过 `observed_identifier` 保留来源 |
| ORCID/ROR/ISSN | checksum 错误仍被接受 | 官方样例通过，单字符篡改失败；ownerless ROR 通过 `observed_identifier` 保留来源且不映射 Venue |
| entity constructors | caller 直传 redirect/tombstone lifecycle、缺结构端点、redirect loser 新写、Evidence 错 source、重复 Document digest | active-only public create functions、raw constructor 不导出、canonical endpoint、结构 cardinality、Document 全局 digest/bulk conflict 精确 |
| snapshot/index integrity | 相同 ID 被 dict 后写覆盖或按 revision 选 current | duplicate entity snapshot 与 duplicate record ID fail closed；不看时间、revision、UUID 或输入顺序 |
| structural projection | redirect 后保留 loser outgoing edge、required ancestor 只传播一层、ungrounded/retracted target 仍 current | shared fixed point、transitive exclusion、redirect terminal、optional edge 精确 reason、dedup、cardinality、cycle bound 与稳定排序全覆盖 |
| predicate registry | kind 或 endpoint 混用 | 每个 predicate 的方向、endpoint、cardinality、I/A/S 有参数化测试 |
| source batch/origin/assertion | adapter 逐原子写、operation 早于 retrieval、payload 不匹配、missing SourceRecord 或 semantic predicate 进入 factual assertion | proposal digest 绑定整批、无 partial result、只有两类 origin、source/operation 时间、factual/semantic 边界与 `observed_identifier` 精确 |
| retraction | 原地 active 标志、跨 source 撤回、二次撤回 | append-only target 规则、lineage 规则和时间规则通过 |
| metadata projection | last-write 或 provider 排序偷选 | authority 唯一胜出；同层不同值 conflicted；低层 contender 保留 |
| refresh projection | 自动忽略旧 SourceRecord | 未显式 retraction 时旧新同层冲突；显式 retraction 后 resolved |
| redirect projection | assertion endpoint 被重写 | assertion 保持原 ID，但 terminal projection 聚合到 survivor |
| tombstone projection | tombstone 仍 current、无 accepted operation 也可执行 | human accepted operation 必需；terminal tombstone 从 current 排除且历史可见；Document tombstone 传递产生 `tombstoned_evidence_source`，零 current evidence 产生 `no_current_evidence` |
| relation max-one | published_in/owner 任意选一个 | 高层唯一胜；同层多 target conflicted；不看时间/UUID/provider |
| relation cycle | 删除任意一条边破环 | SCC 内所有 cycle edges conflicted，其他 edges 保持 resolved |
| symmetric relation | A↔B 和 B↔A 双边或只保留一个 relation 的 evidence | canonical 单 logical edge，所有 relation IDs 与各自 current evidence support 均保留 |
| Claim grounding | Document tombstone 后 Claim 仍 current 或没有 callable 输出 evidence subset | `evaluate_claim_grounding` 精确返回 current/excluded、`current_evidence_ids`、`tombstoned_evidence_source` 与 `no_current_evidence` |
| Claim/Evidence | 无 evidence、语言被强制相同、伪造 action | evidence 必需；source language 与 Claim language 独立；typed accepted review/action/time 必需 |
| SemanticRelation grounding | retracted 或零 current evidence relation 仍 visible | grounding callable 与 Claim 使用同一 evaluator；返回 `retracted`/`tombstoned_evidence_source`/`no_current_evidence` 和 current subset |
| SemanticRelation | candidate 直接进入图、反向 symmetric support 被拒 | 仅 reviewed predicate + evidence + accepted review 可 confirmed；反向输入 canonicalize 且 distinct relation IDs 全保留；可 retraction |
| staged governance | wrong action/digest/time 仍能 refresh/correct/confirm/merge/tombstone | domain-side action/payload/time binding fail closed；应用侧 authenticity/permission 边界明确；exact/fuzzy/destructive action 分离 |
| merge/redirect/snapshot replacement | 自动 survivor、pair 未绑定、时间早于 acceptance、跨类型/不同 anchor、旧 index 未替换 | 显式 survivor；exact/fuzzy payload basis；operation time；同类型 active；anchor 相容；受控 replacement；无逆操作 |
| LineageSynthesis initial identity | Slice 1 暴露 revise 或 caller 自传 revision | initial create 固定 revision=1；ID 跨未来 revisions 稳定；Slice 1 无 revise/head 推断 |
| import boundary | domain 导入 storage/MCP 或 entities↔provenance 循环导入 | AST/import smoke test 证明冻结依赖方向且 `noa.domain` 不导入禁止依赖 |
| 纯函数确定性 | shuffle 输入改变结果 | 多次随机重排同一记录集合，projection 结构完全相同 |

不新增 Hypothesis 依赖；首版使用 pytest 参数化和固定 shuffle seeds 即可覆盖确定性。

## 19. 五个实施阶段

每阶段先写失败测试、运行并记录失败，再写最小实现；阶段完成后运行该阶段测试、全套 domain tests、Ruff、mypy strict 和 `git diff --check`。不在同一阶段混入 Slice 0 重构。

### 阶段 1：错误与 typed UUIDv7

- 生产：`errors.py`、`ids.py`、薄 `__init__.py`。
- 配置：精确增加 `uuid6==2025.0.1` 并更新 NoA lock。
- 测试：23 prefixes、版本/variant/canonical、错误 code/context、唯一 `uuid6.uuid7()` entropy source、禁止零参数 typed-ID factory 和 uuid4 fallback。

### 阶段 2：值对象、attestation 与外部 Identifier

- 生产：`identifiers.py`。
- 测试：第 7、9 节全部 value object、binding canonical digest、attestation shape/action/payload/time mismatch、normalizer/checksum/host/target cases。
- 目标：不引入网络、文件系统、控制平面 client 或 provider SDK。

### 阶段 3：predicate registry、实体与生命周期

- 生产：`entities.py`；先定义 predicate enums/specs 与 SourceRecord，再定义 Evidence/Claim/SemanticRelation record class 和其余 snapshots，最后定义 active-only create functions、唯一 current index、replacement、Document identity、structural validation、redirect resolution 与 tombstone。该顺序遵守第 5 节单向导入。
- 测试：registry、active-only constructors/raw bypass、SourceRecord、duplicate snapshots、canonical write endpoints、structural field mapping、Document bulk digest、Evidence source/time、initial-only LineageSynthesis、replacement、redirect、tombstone payload/time。
- ReviewCandidate/ResearchRun 仅验证 typed references，不实现状态机或存储。

### 阶段 4：origin 与 append-only provenance

- 生产：`provenance.py` 的 source proposal/batch、origin、human assertion/retraction、confirmed constructors、merge basis/service 与 `DomainProjectionInput` 部分；它从 `entities.py` 导入 registry、records、indexes 和 lifecycle services，不反向导入。
- 测试：无 public source atom write；batch action/payload/retrieval time/atomic result；`observed_identifier`；human correction/retraction payload；Claim/SemanticRelation confirmation；pair-bound exact/fuzzy merge、operation time 与 anchor；record ID 唯一。

### 阶段 5：projection 与完整纯领域纵向验收

- 生产：完成 `provenance.py` structural projection、Claim/SemanticRelation grounding callables、metadata/factual/semantic projections；只为稳定公共 API 调整薄 `__init__.py`。
- 测试：shared fixed-point transitive currentness、structural redirects/cardinality、authority、conflict、显式 retraction、grounding reason/current evidence subset、tombstone、max-one misuse error、identifier owner、SCC、symmetric evidence support、精确 stable keys、输入 shuffle、完整场景、禁止依赖与循环导入。
- 不创建 repository、Ladybug schema、MCP tool 或 UI。

## 20. 完整纯领域纵向验收场景

验收测试在内存中显式构造所有输入，不使用 mock repository：

1. 生成 Work A/B/C/D、Publication P1/P2 与 P1 的 Document；所有 initial creators 只产生 active lifecycle。重复全局 digest 按第 8.3 节稳定失败。
2. 规范化 DOI，创建 Identifier。构造 Crossref ingest `SourceWriteBatchProposal`，先由 proposal 计算 digest，再创建 action=`source_ingest` 且 payload-bound 的 accepted operation；batch 同时返回 SourceRecord、`observed_identifier` 与 P1 title assertion。用相同流程创建 OpenAlex batch，并给 loser Work B 添加 title assertion。
3. Crossref `authoritative_source` 与 OpenAlex `aggregator` 对 P1 英文 title 的不同值投影为 Crossref winner，同时保留低层 contender。第二个 authoritative ingest 给出另一 title 后，slot `conflicted`，不得按时间选择。
4. 从实际 subject/field/value/time 构造 `HumanMetadataCorrectionBinding`，创建 action=`human_correction` 的 human accepted operation，再调用 `create_human_metadata_assertion`；最高层唯一值 resolved。
5. adapter 仅提出 Crossref refresh batch：新 SourceRecord、新 title assertion 与旧 Crossref assertion 的 retraction。accepted operation action=`source_refresh`、digest 绑定整批且 acceptance 不早于 retrieval；调用一次 `create_source_write_batch`，旧记录保留但退出 current。故意篡改任一 proposal 字段必须得到 `attestation_payload_mismatch` 且无 partial batch。
6. 通过 source/human safe APIs 创建 `has_identifier` assertions：两个 owner 都是 P1 时 resolved；同层加入 P2 后为 `identifier_owner_conflict`；human correction 指向 P1 后 resolved 且 P2 contender 保留。
7. 从 `(Work A ID, Work B ID)` 构造 `FuzzyMergeReviewBinding` 与 action=`merge_fuzzy` accepted review，创建 `ReviewedFuzzyMergeBasis`。交换 loser 或 survivor 参数必须 payload mismatch；正确调用传入显式 `merged_at >= accepted_at`。
8. merge 返回 Work B redirect snapshot。用 `replace_entity_snapshot` 替换 index，重建 `DomainProjectionInput`；附着在 B 的历史 metadata 不改写 ID，但 terminal projection 聚合到 A，B 不再产生 structural outgoing edge。
9. 从 Document 创建英文 EvidencePassage。用实际 work/statement/language/evidence 构造 `ClaimReviewBinding` 与 accepted review，confirmed 中文 Claim；`evaluate_claim_grounding` 返回 current 和该 Evidence ID，证明 Claim/source language 独立。
10. 用各自 payload-bound reviews confirmed `A extends C`、`C extends D`、`D extends A`，形成三节点环；projection 将三条 edge 都标为 `acyclic_cycle`。另 confirmed `A compares_with C` 与反向输入 `C compares_with A`，使用 distinct relation IDs/evidence，projection 只产生一个 symmetric logical edge并保留两条 `SemanticEvidenceSupport`。
11. 从实际 target/reason/time 构造 action=`retract_record` human operation并撤回 `C extends D`；重建 input 后，其余两个 `extends` relations 变为 resolved。显式调用 `evaluate_semantic_relation_grounding` 验证一个未撤回 relation 仍 current；被撤回 relation 返回 `retracted`。
12. 从实际 Document ID/tombstone time 构造 `TombstoneOperationBinding` 与 human accepted operation，调用 tombstone 并通过 `replace_entity_snapshot` 更新 index、重建 input。Claim 和所有仍依赖该 Document evidence 的 SemanticRelation grounding 返回空 current evidence、`tombstoned_evidence_source` 与 `no_current_evidence`，immutable evidence tuples 不变。
13. 以独立 payload-bound operation tombstone survivor Work A，再 replacement/rebuild。required-current fixed point 传递排除 P1、Document、Evidence、Claim 及依赖记录；所有指向 A terminal 的 metadata/factual/structural/semantic 输出精确 exclusion，历史仍可读。
14. 尝试以 redirect loser B 创建新 assertion/relation，固定得到 `noncanonical_write_endpoint`；历史 B assertion 仍能经 redirect 投影。
15. 多次 shuffle entity/assertion/retraction/semantic input；projection status、winner、contenders、current evidence subsets、semantic evidence support、exclusions 与排序完全一致。重复 snapshot/record ID fail closed。
16. 场景全过程只调用纯领域函数；不访问数据库、repository、MCP、HTTP、文件系统、parser 或 UI。

## 21. 完成标准

Slice 1 规格对应的首个实现只有在以下条件全部满足时完成：

- 五个生产模块和薄 `__init__.py` 按本规格实现，无 repository port。
- `uuid6==2025.0.1` 精确 direct pin 已进入 NoA lock；没有自写 UUIDv7 或 uuid4 fallback。
- 第 18 节测试矩阵与第 20 节纵向场景通过。
- `noa.domain` import graph 不包含 FastMCP、MCP、LadybugDB、SQLite、CAS、HTTP、文件系统、adapter 或 parser。
- Ruff、format check、mypy strict、pytest、lock check、package build 与 `git diff --check` 通过。
- structural、assertion/retraction、Claim/SemanticRelation grounding 与 current projection 可由纯内存输入重建，结果不依赖输入顺序；duplicate snapshots/record IDs fail closed。
- confirmed、refresh、merge、retraction、tombstone 的 attestation action 与 application-service governance 测试通过。
- 没有生产 schema、Cypher、SQL、MCP tool、HTTP、文件写入或 UI 变更。
- 因无 UI 变更，不要求视觉 artifact，也不得修改现有 PNG。

## 22. 参考依据

- NoA 产品契约与总体设计：`docs/superpowers/specs/2026-08-21-noa-product-contract-design.md`
- 领域词汇：`CONTEXT.md`
- ADR 0005：LadybugDB 是未来权威文献图存储。
- ADR 0006：来源事实使用 assertion，current value 是投影，人工修正是高优先级 assertion。
- ADR 0007：知识图、控制平面与内容对象分离。
- ADR 0011：类型前缀 UUIDv7，external identifier 不作主键。
- arXiv identifier：<https://info.arxiv.org/help/arxiv_identifier.html>
- Crossref DOI construction：<https://www.crossref.org/documentation/member-setup/constructing-your-dois>
- DataCite DOI display：<https://support.datacite.org/docs/datacite-doi-display-guidelines>
- OpenAlex ID：<https://help.openalex.org/how-to/finding-openalex-ids>
- ORCID checksum：<https://support.orcid.org/hc/en-us/articles/360006897674-Structure-of-the-ORCID-Identifier>
- ROR identifier：<https://ror.readme.io/docs/identifier>
- ISSN checksum：<https://www.loc.gov/issn/basics/basics-checkdigit.html>
