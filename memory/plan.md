# Plan

## 当前目标

把已接受的 12 份 ADR 整合为可实施的 NoA 文献知识图谱 MCP 产品，并按小型垂直切片逐步交付。

## 推荐路径

0. 产品契约与兼容性闸门
1. Domain Graph and Provenance
2. Workspace and Security Kernel
3. Persistence and Recovery
4. Collection and Source Adapters
5. Document Acquisition and Parsing
6. Research Run and Sampling Runtime
7. Enrichment, Review and Audit
8. Search, Notes, Lineage and Views
9. MCP Tool Contract
10. MCP App
11. 发布、迁移和完整验证

## 当前切片

Slice 1 Domain Graph and Provenance 已全部完成（2026-08-23 收尾门通过，见 `memory/verify.md`）：`errors/ids/identifiers/entities/provenance` 生产实现 + 端到端生产 smoke 全绿。

下一步优先级（MCP server 主线）：

1. ~~Slice 9 工具面的回归测试补齐~~ → 已部分补齐（2026-08-24 knowledge 工具 12 项回归）；run/acquire/sampling 工具仍缺。
2. assertion/source_record/projection 入图 + acquire_and_stage 的 commit 路径（打通文献导入完整闭环）。
3. Slice 10 MCP App（ADR 0010 只读渐进式 App）+ 解冻 Task #58 validator 深度缺口。
4. Slice 11 发布验证（等 FastMCP 稳定版 pin）。

以上步骤全部只走开发门（Ruff、`mypy src`、切片测试、import smoke）；发布门条目统一推迟到 release 前集中执行，分层定义见 `memory/verify.md`。

## 已冻结的 Slice 0 状态

Slice 0 compatibility server、Sampling、LadybugDB/SQLite probes、MCP App 与 packaging 基础能力已经存在，但最终审阅仍有已知非阻塞缺口：双截图语义、App validator、gate inventory、报告 crash consistency、cleanup priority 和 wheel closure。按用户要求这些问题暂缓，不得声称 Slice 0 已最终验收。

正式 release 仍被 FastMCP prerelease 和上述 release-gate 工作阻塞；它们不阻塞当前 Slice 1 纯领域生产实现。
