---
status: accepted
---

# Build the server with FastMCP 4 on the official MCP SDK v2

NoA will use FastMCP 4 as its Python application framework, backed by the official MCP Python SDK v2. The exact FastMCP, MCP SDK, and MCP types versions that pass NoA's compatibility suite are pinned rather than expressed as open-ended compatible ranges.

## Consequences

Dependency upgrades require the full protocol and behavior suite: VS Code's 2025-11-25 Sampling path, 2026-07-28 MRTR Sampling through a reference client, MCP Apps, protected approval tools, cancellation, and interrupted-operation recovery. NoA targets CPython 3.11 because the chosen LadybugDB wheel currently constrains the supported interpreter range.
