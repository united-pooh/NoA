---
status: accepted
---

# Support both legacy and MRTR Sampling during the compatibility window

NoA will use client-provided MCP Sampling only and will not fall back to a direct model API. The first release supports VS Code's negotiated 2025-11-25 `sampling/createMessage` path and the 2026-07-28 MRTR form through the official Python MCP SDK. The server selects the path from the negotiated protocol and advertised capabilities and fails clearly when neither is available.

Sampling is deprecated in MCP 2026-07-28. This decision must be reopened if VS Code Stable stops advertising Sampling, the MCP specification or Python SDK removes the required compatibility path, or by 2027-07-28 at the latest. Codex and Claude Code are not supported hosts while they lack Sampling.
