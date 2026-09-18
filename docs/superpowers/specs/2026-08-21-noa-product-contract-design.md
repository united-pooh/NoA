# NoA 文献知识图谱 MCP：产品契约与总体设计

- 日期：2026-08-21
- 状态：已批准
- 实施策略：兼容性闸门 + 风险优先垂直切片
- 首个支持宿主：macOS 上的 VS Code Stable
- 相关决策：`docs/adr/0001` 至 `docs/adr/0012`

## 1. 背景

当前仓库发布的是一个面向 Codex 的研究日志 Skill。已接受的 ADR 将 NoA 重新定义为一个以文献知识图谱为核心、由 MCP 客户端 Sampling 提供模型能力的 Python MCP 服务。新产品不是旧 Skill 的增量扩展，而是一次产品替换。

本设计整合现有领域词汇和 12 份 ADR，冻结首发产品契约、系统边界、数据流、错误语义、验证闸门和实施顺序。各复杂子系统仍需在实施前形成独立规格和计划。

本文是产品契约与实施切片总纲，不直接生成一份覆盖 Slice 0–11 的实现计划。当前下一份实现计划只覆盖 Slice 0：Product Contract and Compatibility Gate。Slice 1–11 必须先分别完成并批准子规格，再各自制定实现计划。

## 2. 目标

NoA 首发版本帮助一个本地用户在一个显式本地工作区中：

1. 从受支持的学术数据源发现和采集文献。
2. 保留不可覆盖的来源记录与出处信息。
3. 将 Work、Publication、Document、Claim 和 Evidence Passage 组织为可查询知识图谱。
4. 使用客户端 Sampling 提出 Claim 和语义关系候选。
5. 通过人工审核把候选提交为受治理的知识层。
6. 搜索和浏览文献、证据、关系、集合、笔记与技术谱系。
7. 通过开放格式导出可迁移数据，并从权威数据重建派生视图。
8. 在进程中断或部分写入后安全恢复，不静默丢失、覆盖或伪造状态。

## 3. 非目标

首发版本不提供：

- 通用自治实验执行器。
- 任意 shell 或命令执行。
- 多工作区服务模式。
- 多写者并发编辑。
- 直接调用 Anthropic、OpenAI 或其他模型提供商 API。
- 在缺少 MCP Sampling 的宿主上进行模型辅助 enrichment。
- 自动批准模型生成的语义候选。
- 把 Markdown 作为第二个可写权威数据源。
- 让 MCP App 直接连接或修改 LadybugDB、SQLite 或 CAS。
- 默认把受版权保护的全文纳入开放导出。
- 首发支持所有桌面操作系统；首个发布目标限定为 macOS。

旧研究日志 Skill 不作为新架构的一部分继续演进。迁移阶段可以保留历史文件用于说明和迁移，但新产品发布后 README、安装说明和入口必须以 MCP 服务为准。

## 4. 首发产品契约

### 4.1 运行画像

- 本地运行。
- 一个服务进程绑定一个用户显式选择的 workspace root。
- 单写者；允许多个只读查询，但所有变更通过一个受控写入通道串行化。
- 目标规模约 5 万个 Work；规模基准以真实索引、查询、重建和导出场景验收。
- 首发宿主为 macOS 上的 VS Code Stable。
- Python 运行时为 CPython 3.11。

### 4.2 MCP 与模型能力

- MCP 服务基于 FastMCP 4 和官方 MCP SDK v2。
- 生产依赖使用精确版本固定，而不是宽松范围。
- 模型能力仅来自客户端 MCP Sampling。
- 服务端拥有并验证 Research Run 状态机；模型只能对有界输入生成结构化候选，不能选择或跳过工作流步骤。
- legacy 路径指 VS Code 协商的 MCP `2025-11-25 sampling/createMessage`；MRTR 路径指通过官方 MCP Python SDK v2 使用的 `2026-07-28` MRTR 形式。
- 同时实现并测试两条路径，并根据客户端协商能力选择；不得通过自然语言猜测能力。
- 如果 VS Code Stable 只暴露其中一条路径，另一条必须通过基于官方 SDK v2 的 reference client 协议 harness 验证。
- 客户端不支持 Sampling 时，非模型工具仍可用；依赖模型的操作返回结构化的“不支持能力”错误，不回退到直接模型 API。
- 缺少 Sampling 的客户端不属于首发受支持宿主；Codex 和 Claude Code 在未提供 Sampling 时明确为 unsupported hosts。
- 如果 VS Code Stable 停止广告 Sampling、MCP 规范或 Python SDK 移除所需兼容路径，或最迟在 2027-07-28，必须重新开启 ADR 0001 和 ADR 0009。
- 每次升级 FastMCP、官方 MCP SDK 或相关 MCP types 的精确 pin，都必须重跑完整协议与行为套件，包括两条 Sampling 路径、MCP App、受保护审批工具、取消以及中断恢复。

### 4.3 数据源

首发必需适配器：

- OpenAlex
- Crossref
- DataCite
- arXiv
- Unpaywall

首发可选且默认关闭：

- Semantic Scholar
- GROBID
- SPECTER2

可选组件不得改变核心领域接口。禁用时必须产生明确能力状态，不得静默降低结果语义。

### 4.4 语言策略

- 来源标题、摘要、全文片段和原始 payload 保留来源语言。
- 规范化实体允许多语言标签。
- 首发模型派生内容默认使用中文：Claim 候选和 Lineage Synthesis。
- Note 始终是版本化的人类撰写 Markdown，不属于模型生成内容。
- 派生中文内容必须指向原始 Evidence Passage、生成上下文，以及适用时的记录图快照，不能替换来源文本。
- 后续可以增加 workspace 级派生语言配置，但首发不为多个语言建立并行生成管线。

### 4.5 数据治理默认值

- 模型永不自动批准候选或计划。
- Collection Plan、Enrichment Plan、fuzzy merge、Claim 或语义关系候选、refresh change 和破坏性维护必须先进入 staged 或 pending 状态，并向用户展示有界范围和支持证据。
- 只有命名的人类通过受保护且始终要求确认的独立提交工具，才能将上述对象推进到 approved、executable 或 confirmed 状态；模型不得执行批准。
- MCP App 的变更按钮只能调用受保护服务端工具；确认、权限、revision 校验和审计全部由服务端执行。
- 全文、TEI 和解析缓存默认不进入开放导出；开放导出保留可合法导出的元数据、图结构、出处、内容哈希、用户笔记和审核记录。
- 因版权或隐私策略执行的删除可以移除受控 CAS 内容字节，但不得改写 Source Record 或 assertion 历史；系统保留最小 tombstone、内容哈希和审计事实。“不可变”表示不得原地覆盖，不表示受策略约束的内容字节永远不可删除。
- 模型原始请求和响应默认仅本地保留 30 天；长期复现保留 prompt 版本、模型元数据、输入摘要、输出结构化结果和内容哈希。

## 5. 总体架构

系统按责任边界分为六层。

### 5.1 MCP 接入层

职责：

- stdio 生命周期。
- Tools、Resources 和 MCP App 资源注册。
- 客户端能力协商。
- legacy Sampling 与 MRTR 的统一适配。
- 输入 schema 验证、分页、取消传播和结构化错误映射。

该层不包含领域决策，不直接写数据库。

### 5.2 应用服务层

职责：

- Research Run 的创建、继续、暂停、取消和恢复。
- 把一次 `continue` 限制为一个有界步骤。
- 构建 Collection Plan、Enrichment Plan 和 Review 操作。
- 协调领域服务、数据源适配器、Sampling 和持久化事务。
- 执行确认、revision、幂等键、lease 和审计检查。

应用服务层是所有变更操作的唯一入口。

### 5.3 领域层

核心实体：

- Work
- Publication
- Document
- Identifier
- Person
- Venue
- Topic
- Method
- Research Task
- Dataset
- Source Record
- Metadata Assertion
- Relationship Assertion
- Claim
- Evidence Passage
- Review Candidate
- Collection
- Note
- Technical Lineage
- Lineage Synthesis
- Research Run

领域层定义实体不变量、ID 类型、断言投影、merge/redirect/tombstone、候选状态和审核规则。它不依赖 FastMCP、具体数据库驱动或外部 HTTP 客户端。

Source Record、Metadata Assertion、Relationship Assertion 和原始来源 payload 不得原地覆盖。人工修正必须表示为更高优先级 assertion；来源刷新通过增加或撤回 assertion 更新投影，并保留历史记录。

### 5.4 基础设施层

- LadybugDB：权威图和可移植 Cypher 查询。
- SQLite：Research Run、计划、checkpoint、审批 revision、lease、审计和 operation journal。
- CAS：原始来源 payload、可保留文档、解析产物和其他内容对象。
- 派生视图：从权威状态生成的只读 Markdown 和 App 查询投影。

三种权威存储不伪装成分布式 ACID。所有跨存储变更通过显式 operation journal 和幂等恢复协调。

### 5.5 外部适配层

职责：

- 学术来源查询、分页、限速、重试和响应持久化。
- URL 验证、重定向验证和内容获取。
- PDF/XML/TEI 的隔离解析。
- 可选 GROBID 和 SPECTER2 集成。
- 外部标识符规范化。

适配器输出受版本化 schema 约束的中间对象，不直接操作领域图。

### 5.6 展示层

- MCP Tools 是完整、稳定、可自动化的产品 API。
- MCP App 提供渐进式图谱、证据、候选、集合和谱系浏览。
- App 静态资源随产品打包，不依赖外部 CDN 或运行时网络资源。
- App 不持有数据库凭证，不绕过工具确认，不复制业务规则。

## 6. 数据与状态流

### 6.1 采集流程

1. 用户创建 Collection Plan 草案。
2. 服务端验证 workspace、来源、预算和查询参数，并返回有界范围、预期操作和支持证据。
3. 命名的人类通过受保护且始终要求确认的提交工具批准该计划。
4. 只有已批准的计划才能创建或推进 Research Run 到可执行状态。
5. 每次 `continue` 从一个来源执行有界分页或批次。
6. 原始响应先写入 CAS，SQLite 记录内容哈希、来源、游标、幂等键和处理状态。
7. 规范化器从 Source Record 产生实体和事实断言草案。
8. operation journal 协调 LadybugDB 投影与 SQLite 状态更新。
9. 运行保存 checkpoint，返回进度、待处理项和下一步能力。

外部失败不会覆盖已提交图；失败按来源和游标记录为可重试或终止状态。

### 6.2 文档获取与解析流程

1. 从已配置适配器获得经批准的开放获取 HTTPS 候选 URL。
2. 在每次请求、DNS 解析和重定向前执行 scheme、host allowlist、IP、端口和目标策略验证。
3. 流式下载到 workspace root 内的隔离临时区域，执行大小、时间、内容类型和哈希限制。
4. 合法且符合策略的内容发布到 CAS。
5. PDF/XML 解析在无网络、低权限、有限 CPU/内存/文件数/时间的独立进程中运行。
6. 解析产物写入 CAS，并以 Evidence Locator 关联 Document。
7. 解析失败作为结构化结果保留，不伪造空全文或成功状态。

### 6.3 Sampling enrichment 流程

1. 应用服务从已提交事实和 Evidence Passage 构建最小化、来源归属明确、经过敏感内容过滤的有界 evidence packet。
2. packet 包含明确的“不信任内容”边界和允许输出 schema。
3. MCP 接入层按客户端能力选择 legacy 或 MRTR。
4. 对模型结果做严格 schema、枚举、ID、证据引用和大小验证。
5. 合格结果写为 Review Candidate；不合格结果记录失败类型，不进入图。
6. 候选保持 pending，直到人类通过带 revision 的受保护工具提交或拒绝。

模型只能提出 Claim 和语义关系 Review Candidate，不能创建或修改 Metadata Assertion、Relationship Assertion 或任何其他事实断言。

### 6.4 人工审核与提交流程

1. 审核者读取候选、证据、来源和生成元数据。
2. 变更请求携带 candidate ID、expected revision、审核者身份和明确动作。
3. 服务端重新读取最新状态并校验候选仍可审核。
4. staged 对象完成写入和哈希，operation journal 以不可变 operation ID 记录 prepared 操作、预期写集和幂等键。
5. LadybugDB 提交领域事务。
6. 必要对象从 staged 原子发布为 committed。
7. SQLite 记录审核事件并完成业务状态和 journal 阶段更新。
8. 派生视图标记为待重建，并在当前 MCP 请求内的有界步骤或由客户端或用户再次调用触发的后续有界步骤中重建。

不假设 MCP 工具返回后仍有长生命周期后台执行。重复提交同一幂等键返回已有结果；revision 冲突返回显式冲突，不覆盖新状态。

## 7. 跨存储一致性与恢复

### 7.1 Journal 原则

operation journal 至少记录：

- operation ID
- operation type
- idempotency key
- workspace ID
- expected revision
- staged object hashes
- LadybugDB write intent
- SQLite write intent
- 当前阶段
- 尝试次数
- 最后错误
- 创建、更新时间和操作者

详细状态枚举由 Persistence and Recovery 子规格冻结。总体语义必须区分：准备、图已提交、对象已发布、控制平面已提交、视图待重建、完成、已回滚、可重试失败和需要人工修复。

### 7.2 恢复规则

- 启动时扫描未完成 journal。
- 所有恢复动作必须幂等。
- 已提交权威数据不因派生视图失败而回滚。
- 对仍处于 prepared 且 LadybugDB 中不存在实际写集的操作，恢复可以按不可变 operation ID 幂等回滚 staged 对象并记录回滚结果。
- 一旦图写集已经提交，只允许幂等 roll-forward，不得通过删除已提交知识伪造回滚。
- 图已提交但控制平面未提交时，恢复逻辑根据 operation ID 检查实际写集并完成对象发布和控制平面记录；不能盲目重复创建实体。
- staged 对象发布失败时保留 journal 和对象，不把引用暴露为完整状态。
- 无法自动判断的异常进入 `manual_repair_required`，服务拒绝相关写入但保持只读查询和诊断可用。
- 恢复和人工修复都产生审计事件。

## 8. 安全边界

### 8.1 Workspace

- MCP Client Roots 只能作为发现提示，不能作为授权边界。
- 所有数据库文件、内容寻址对象、生成视图、导入、导出、下载临时文件和解析临时产物，在规范化并解析符号链接后都必须位于显式 workspace root 内；运行时状态位于 `.noa/`。
- 拒绝路径穿越、workspace 外绝对路径、逃逸 root 的符号链接，以及利用 hard link 或竞态访问 root 外对象的操作。
- 导入和导出只能选择 workspace root 内符合策略的路径，默认不跟随符号链接。
- 不提供通用命令执行能力。

### 8.2 网络

- 网络访问仅限已配置的学术来源适配器和经批准的开放获取文档下载。
- 文档获取只接受由已配置适配器产生、且通过允许策略的 HTTPS 候选 URL。
- 每次请求、DNS 解析和重定向都重新验证 scheme、host allowlist、IP、端口和目标策略，并拒绝私有地址、回环、link-local、云元数据地址及其他非允许目标。
- 下载使用时间、大小、重定向次数和并发限制。
- 可选 GROBID 和 SPECTER2 集成不得引入远程服务调用、运行时网络下载或扩大既有网络权限；其不可用时返回明确能力状态。
- 密钥只从受控配置来源读取，不进入 prompt、日志、导出或 App。

### 8.3 不可信内容

- 文献文本、PDF、XML、HTML、来源元数据和模型输出都视为不可信。
- 不可信内容和模型输出不得发起网络访问、获取凭证、调用工具、批准候选、改变工作流或系统提示，也不得修改导出策略。
- XML 禁用外部实体和网络解析。
- 压缩文件、PDF 和解析结果受解压比、页数、对象数、文本量和递归深度限制。
- App 对内容执行转义和 CSP 限制，不注入未经净化的 HTML。

### 8.4 人工确认

- “App 只读”表示 App 不直接写存储，不表示界面不能发起受保护工具。
- 所有提交、删除、批量审核、导入覆盖和导出敏感内容操作都在服务端校验确认要求。
- 客户端 UI 的确认提示不是授权依据；服务端必须看到满足契约的明确动作参数和当前 revision。

## 9. 错误模型

所有公共工具错误返回稳定结构，至少包含：

- `status`
- `type`
- `message`
- `retryable`
- `suggestion`
- 可选 `details`

错误类型至少覆盖：

- `invalid_request`
- `unsupported_capability`
- `workspace_boundary_violation`
- `conflict`
- `confirmation_required`
- `source_unavailable`
- `rate_limited`
- `content_rejected`
- `parse_failed`
- `sampling_failed`
- `invalid_model_output`
- `storage_failed`
- `recovery_required`
- `cancelled`

不允许用自然语言解析错误来驱动状态机。重试只由结构化类型和 retryable 字段决定。

## 10. 兼容性闸门

完整业务实现前，先完成一个最小、可丢弃实现的 compatibility spike。它不承诺生产架构，只验证 ADR 的关键前提。

### 10.1 必须验证

1. 找到并固定可安装的 FastMCP 4 与官方 MCP SDK v2 精确版本。
2. 在 CPython 3.11 创建可通过 stdio 启动的最小 MCP server。
3. 用 VS Code Stable 完成真实客户端能力协商。
4. 分别验证 VS Code 协商的 MCP `2025-11-25 sampling/createMessage` 和通过官方 MCP Python SDK v2 使用的 `2026-07-28` MRTR；若 VS Code 仅暴露其中之一，使用基于官方 SDK v2 的 reference client 协议 harness 验证另一条路径。
5. 验证 Sampling 取消、超时、无效结构化输出和客户端拒绝的可观测行为。
6. 验证 MCP App 资源能随 Python wheel 打包并在无外部网络资源时加载。
7. 验证 LadybugDB 在 CPython 3.11/macOS 上安装、建库、事务、索引和最小 Cypher 查询。
8. 验证服务中断后 SQLite checkpoint 可驱动一次有界步骤恢复。

### 10.2 通过标准

- 所有实验都有自动化测试或可重复脚本。
- 记录精确版本、宿主版本、协议能力和已知限制。
- 不依赖未公开补丁、手工修改 site-packages 或不可重现环境。
- 没有阻止产品核心流程的兼容性缺口。

### 10.3 失败处理

如果闸门失败：

- Sampling 路径失败：重开 ADR 0001 和 0009。
- FastMCP/SDK API 不兼容：重开 ADR 0012。
- LadybugDB 不满足平台或事务要求：重开 ADR 0005。
- MCP App 无法可靠打包：App 延后，但 Tools API 仍可继续；重开 ADR 0010 的首发范围。

在相关 ADR 更新前，不用适配器、fallback 或私有补丁掩盖失败。

## 11. 实施切片

每个切片单独形成规格、实现计划、测试和验收记录。

### Slice 0：Product Contract and Compatibility Gate

交付本设计、依赖与宿主 spike、版本矩阵和 Go/No-Go 结论。

### Slice 1：Domain Graph and Provenance

冻结实体、关系、类型前缀 UUIDv7、Identifier 规范、Assertion 投影、冲突优先级、Claim/Evidence、merge/redirect/tombstone。

### Slice 2：Workspace and Security Kernel

冻结 `.noa/` 布局、配置、路径策略、单写者锁、网络策略、密钥边界、解析沙箱接口和资源预算。

### Slice 3：Persistence and Recovery

实现 LadybugDB、SQLite、CAS、migrations、operation journal、lease、故障注入和启动恢复。

### Slice 4：Collection and Source Adapters

实现 Collection Plan、来源接口、分页、速率限制、Source Record、刷新、规范化和实体解析。

### Slice 5：Document Acquisition and Parsing

实现 OA 解析、URL 安全、下载、许可证策略、CAS 发布、PDF/XML/TEI 解析和 Evidence Locator。

### Slice 6：Research Run and Sampling Runtime

实现状态机、有界 `continue`、checkpoint、legacy/MRTR 适配、重试、取消和 evidence packet。

### Slice 7：Enrichment, Review and Audit

实现候选生成、结构化验证、人工审批、revision、批量审核、撤回、重新抽取失效和审计。

### Slice 8：Search, Notes, Lineage and Views

实现全文/属性/图查询、Collection、版本化 Note、技术谱系、快照、只读 Markdown、导入和开放导出。

### Slice 9：MCP Tool Contract

冻结完整工具目录、输入输出 schema、错误、分页、确认、幂等和权限语义。

### Slice 10：MCP App

实现图谱、时间线、证据、候选和结果浏览；所有变更动作通过受保护 Tools。

### Slice 11：Release and Full Validation

完成安装、迁移、弃用旧 Skill、文档、CI、协议矩阵、安全测试、性能基准和 VS Code E2E。

## 12. 测试策略

### 12.1 开发纪律

- 新行为和 bug 修复遵循 TDD：先观察失败，再写最小实现，再重构。
- 领域层使用纯单元测试覆盖不变量。
- 外部适配器使用录制或合成响应，不把公共网络作为普通单元测试前提。
- 每个生产故障状态必须有可重复的故障注入测试。

### 12.2 必需测试类别

- 领域模型和 ID 属性测试。
- Assertion 冲突、撤回、merge、redirect 和 tombstone 测试。
- LadybugDB/SQLite/CAS 集成测试。
- operation journal 全状态故障注入测试。
- legacy/MRTR 协议契约测试。
- VS Code Stable 真实端到端测试。
- 路径穿越、symlink 逃逸和竞态测试。
- SSRF、DNS rebinding、跨域重定向和下载限制测试。
- XXE、压缩炸弹、超大 PDF、解析超时和资源耗尽测试。
- prompt injection、无效模型 schema 和审批绕过测试。
- 来源冲突、刷新、撤回和重新抽取测试。
- schema migration、开放表格格式导出，以及从开放导出重建 LadybugDB 权威图和可派生视图的测试；被导出策略排除的全文、TEI、解析缓存和 CAS 内容字节不属于该重建承诺。
- MCP App CSP、外部网络阻断和真实浏览器交互测试。
- 约 5 万篇文献的导入、索引、查询、重建和导出基准。

### 12.3 完成证据

每个切片完成时必须提供：

- 变更文件列表。
- 已运行的精确命令。
- 测试、静态检查和运行时结果。
- 未运行或受环境限制的检查。
- 对 UI 变更提供新鲜截图和结构化视觉证据。
- 至少一个独立检查：测试套件、审阅代理或人工验收。

## 13. 发布与迁移

- 在 compatibility spike 通过前，不把旧 README 改写为已可用的新产品。
- 新 MCP server 达到首个可安装垂直切片后，更新 README、安装说明和 agent 元数据。
- 明确标记旧 Skill 已弃用，并说明历史研究日志文件不会被自动删除。
- 提供导入旧 Markdown 研究日志的能力不属于首发核心要求；如实现，应作为普通导入适配器，不能破坏新领域模型。
- 发布包必须包含 license、精确锁文件、schema migration、MCP App 静态资源和可重复构建说明。

## 14. 设计取舍

### 14.1 未采用：全量大爆炸实现

它会让协议、存储、安全、领域和 UI 风险在最终集成时叠加，违反小切片和 TDD 原则。

### 14.2 未采用：基础设施一次性优先

它会在没有真实用户流的情况下冻结过多底层抽象，并延迟 Sampling 和宿主风险的发现。

### 14.3 采用：兼容性闸门后的风险优先垂直切片

该路径先证伪最危险的外部前提，再以稳定领域边界和恢复模型支撑采集、模型辅助、审核与 UI。每个切片都能独立验收，并限制返工范围。

## 15. 后续规格约束

后续子规格不得违反以下总约束：

- Sampling-only，不增加直接模型 API fallback。
- 服务端控制工作流和确认。
- 模型输出不创建事实断言。
- LadybugDB、SQLite、CAS 的边界保持明确。
- Markdown 和 App 投影不是权威写入源。
- 不可信内容边界贯穿下载、解析、Sampling、审核和展示。
- 所有恢复、重试和确认基于结构化状态，不解析自然语言。
- 首发优先保证 macOS + VS Code Stable 的可靠路径，不为未承诺平台增加未经验证的复杂度。
