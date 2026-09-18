# Agents and Tooling

## 当前阶段

- 主会话：产品规格整合与兼容性闸门设计
- 只读探索：已完成，确认仓库仍处于新 MCP 产品的绿地实现阶段

## 已决技术约束

- Python：CPython 3.11
- MCP：FastMCP 4 + 官方 MCP SDK v2，精确固定版本
- 模型能力：仅通过客户端 MCP Sampling
- 首个宿主：VS Code Stable
- 图存储：LadybugDB
- 控制平面：SQLite
- 二进制对象：内容寻址对象库（CAS）
- 并发模型：单工作区、单写者

## 工作约束

- 先完成兼容性 spike，再冻结业务实现计划
- 新行为采用 TDD
- 每个垂直切片独立验证，不混入无关重构
- 不推送远端，除非用户明确要求

## LadybugDB 0.19.1 实测

- `ladybug.Database`、`ladybug.Connection` 和查询结果均提供显式 `close()`；连接与数据库还提供 `is_closed`
- 写连接按 QueryResult → Connection → Database 顺序显式关闭后，可在同一进程以 `Database(path, read_only=True)` 稳定重开
- `BEGIN TRANSACTION`/`ROLLBACK` 和 `BEGIN TRANSACTION`/`COMMIT` 的最小 on-disk 探针已通过
- 每次 probe 在 root 内生成唯一 `compatibility-<uuid>.lbdb`，保留数据库证据且允许同一 root 安全重复运行
- 每个 phase 保存已创建资源并在 `finally` 中逆序 best-effort `close()`；执行错误保持为 primary error，清理错误记录到 `cleanup_errors`
- KeyboardInterrupt、SystemExit、GeneratorExit 等非 Exception 中断不会被 probe 吞掉；清理阶段先尝试关闭全部资源，再重新抛出首个中断

## SQLite checkpoint 实测

- `compatibility_run` 以 SQLite CHECK 约束保证 `0 <= current_step <= total_steps` 且 `total_steps > 0`
- `start` 与 `advance` 使用连接事务提交；重复 run_id、非法 total_steps、未知或已完成 run 的失败不会覆盖已持久化 checkpoint
- 关闭并重开后可恢复 `slice-0` 的 1/3 状态并推进到 2/3；`close()` 幂等
- 每次 probe 在 root 内生成唯一 `compatibility-<uuid>.sqlite3` 并保留证据；普通异常返回结构化 FAIL，BaseException 中断在 `finally` 关闭后传播

## FastMCP 4 / MCP 2 Sampling 实测

- `Client(..., mode="auto")` 协商 `2026-07-28`，FastMCP 自动驱动 `InputRequiredResult` 的 MRTR 重试；`mode="legacy"` 协商 `2025-11-25` 并通过 `ctx.session.create_message(...)` 完成 standalone `sampling/createMessage`
- 发起任何新 Sampling 请求前检查公开的 `ctx.session.client_capabilities.sampling`；未声明能力时 modern/legacy 都正常返回 `{"status":"unsupported_capability","answer":null}`，不生成 MRTR request，也不调用 standalone Sampling
- modern 首次响应的 `input_requests` 使用 `answer` key 与 `CreateMessageRequest(method="sampling/createMessage")`；SDK 会把工具给出的 opaque `request_state` 封装为受保护的 `v1.*` token，并能用该状态完成重试；工具在解析 `input_responses` 前还需校验解封后的 `ctx.request_state`，拒绝省略 state 的伪造 response
- FastMCP client sampling handler 的公开 `RequestContext` 在 4.0.0b3 是 typing shim，运行时 context 不提供 `protocol_version`；协议断言应使用已连接 client 的公开 `client.protocol_version`
- legacy deprecation 类为公开的 `mcp.MCPDeprecationWarning`，其基类是 `UserWarning` 而非 `DeprecationWarning`；只按 SDK 的精确 message 和 `noa.compat.sampling` 调用点 module 抑制，并且过滤 scope 只包住同步创建 coroutine 的调用，实际 `await` 在 scope 外，避免吞 handler 告警或并发污染 filters
- modern continuation 对 state 和 response shape fail-closed；SDK 自身还会把受保护 token 绑定到 tool arguments，因此单字符篡改或改 question 都返回 `-32602` 与 `data.reason=invalid_request_state`
