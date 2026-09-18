# NoA（生盐诺亚）

一个面向 Codex 的研究轨迹 MCP kernel 与研究日志 skill：把实验笔记、代码改动、运行结果和失败路径整理成可复现、可追踪、可决策的研究记录。

NoA 不负责美化结果，也不是逐分钟流水账。它持续追问：

> Is the evidence strong enough to change the current research or engineering decision?

## 它能做什么

- 创建或维护 Markdown 研究日志与实验日志
- 在写作前检查代码、日志、run 输出、notebook 和结果文件
- 同时保留原始证据与研究决策
- 区分直接观察、当前解释和未验证推测
- 把负面、无显著差异和混合结果作为正式研究产出
- 比较质量、墙钟时间、吞吐量、显存、成本和维护复杂度
- 自动选择简短记录、标准实验或深度复盘
- 记录 commit、命令、run ID、数据版本、随机种子和实验环境
- 持续更新“进行中”的条目，而不提前宣布成功或失败

NoA 使用的研究闭环是：

```text
问题或灵感
→ 可证伪假设
→ 基线与实验设计
→ 实现、变体和踩坑
→ 定量与定性结果
→ 观察、解释与推测
→ 收益和复杂度权衡
→ 采用、回退或继续验证
→ 可迁移经验与下一步
```

## 轨迹控制 kernel

研究过程的运行权威源是 MCP trajectory kernel。它为每个研究目标保留版本、成功标准、依赖关系、分支和 append-only 事件，并从事件重放出进度、证据范围、阻塞项、偏离程度和下一步闸门。`get_research_snapshot` 返回当前状态，`get_research_trajectory` 返回可重放事件；`propose_next_research_step` 在继续工作前检查是否应该回到能力主线、暂停复核或放弃分支。

旧的 Markdown 研究日志仍然是面向人的导入/导出格式，不是运行时事实源。迁移时按下面的语义映射追加事件，并保留无法证明的字段：

| 旧 Skill 记录 | trajectory event | 迁移规则 |
| --- | --- | --- |
| evidence layer 中的命令、配置、run、指标和产物 | `observation_recorded`；有实验生命周期时再加 `experiment_started` / `experiment_finished` | 将可核验事实放入 `result`、`metrics`、`artifacts`，声明 `evidence_scope` 和 `evidence_status` |
| hypothesis、比较、解释、权衡和决定 | `decision_recorded` | 关联目标 criterion、分支和支撑证据；解释仍标为解释，不升级为验证事实 |
| next step、重试条件和失败路径 | `decision_recorded` 或带 `intent` 的事件 | 通过 `propose_next_research_step` 获得结构化闸门结果 |
| 只有 Markdown 文本、缺少时间/父节点/分支的旧 run | 事件导入，缺失字段保持 `unknown`；run 标为 `legacy_unknown` | 禁止合成时间、parent、分支或完成证据 |

导出日志时从 snapshot 和事件生成可读 Markdown；再次读取时以 MCP kernel 重放结果为准。这样可以保留原有研究叙事，同时避免在分支试错后丢失与最初目标的距离。

## 安装

将仓库克隆到 Codex 的个人 skills 目录：

```bash
git clone https://github.com/united-pooh/NoA.git ~/.codex/skills/noa
```

安装后新建一个 Codex 任务或重启 Codex，使技能列表重新加载。

如果已经安装，可以更新：

```bash
git -C ~/.codex/skills/noa pull
```

## 使用

显式调用：

```text
$noa 根据当前仓库的实验结果创建 dev/LOG.md
```

```text
$noa 把今天的运行结果追加到研究日志，区分观察、解释和推测
```

```text
$noa 检查这些 run 和代码改动，判断应该更新旧条目还是创建新条目
```

你也可以直接提出“创建研究日志”“整理负面实验”“复盘 sweep”“维护实验过程”等请求，由 Codex 根据 skill 描述自动路由。

## 日志风格

NoA 默认维护按日期倒序排列的日志：

```markdown
## YYYY-MM-DD：实验主题（状态）
```

状态根据证据选择，例如：

- `进行中`
- `正面结果`
- `负面结果`
- `混合结果`
- `待复现`

条目不会机械填满固定模板。简单实验保持简短；复杂调查才展开背景、实验矩阵、实现难点、结果表格、原因解释和重试条件。

## 文件结构

```text
.
├── SKILL.md
└── agents
    └── openai.yaml
```

- `SKILL.md`：完整行为、写作和验证规则
- `agents/openai.yaml`：Codex 中显示的名称、描述与默认提示

## 核心原则

1. 先检查真实证据，再撰写结论。
2. 不发明缺失的运行信息或因果解释。
3. 负面结果同样需要被完整记录。
4. 结论必须对应预先声明的成功标准。
5. 新证据推翻旧结论时，保留并解释研究路径。
6. 最终记录必须帮助未来的自己避免重复实验并做出下一步决策。
