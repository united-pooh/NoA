---
status: accepted
---

# Replace the Codex Skill with an autonomous Sampling-only MCP server

NoA will be distributed only as a Python MCP server, not as a Codex Skill. Its model reasoning will use the connected client's MCP Sampling capability rather than a direct model API, and the server—not the sampled model—will control the research workflow and validate structured model decisions. VS Code Stable is the first supported host because Codex and Claude Code do not currently expose Sampling.

## Consequences

MCP Sampling was deprecated in MCP 2026-07-28 and new implementations are advised not to adopt it. NoA therefore treats this as an explicit compatibility product: it must detect the negotiated protocol and Sampling capability, fail with a clear diagnostic when they are unavailable, document its tested VS Code range, and reopen this decision before the deprecated capability is removed. NoA will not silently fall back to a direct model API.
