# NoA MCP

NoA is a pre-alpha Python MCP server for building a provenance-preserving literature knowledge graph. This private package currently contains the Slice 0 compatibility gate rather than the full literature product and is not approved for public distribution.

## Current scope

The compatibility gate verifies:

- CPython 3.11 on macOS;
- FastMCP 4 and MCP Python SDK v2 exact pins;
- MCP `2026-07-28` multi-round-trip Sampling;
- legacy `2025-11-25 sampling/createMessage`;
- LadybugDB transaction and persistence behavior;
- SQLite checkpoint recovery;
- a bundled, network-free MCP App resource;
- wheel installation and stdio execution.

The full literature graph, source adapters, review workflow, search features, and production MCP App are not included yet.

## Commands

Start the local stdio MCP server:

```bash
noa
```

Run the compatibility gate:

```bash
noa-compat
```

The gate intentionally returns a nonzero status until all required host evidence, including VS Code Stable verification, is present.

## Status and constraints

- Target runtime: CPython 3.11.
- First target host: VS Code Stable on macOS.
- Model access: MCP client Sampling only; no direct model-provider fallback.
- FastMCP 4 is currently pinned to a prerelease, so release remains conditional even when functional checks pass.
