---
status: accepted
---

# Bound every NoA run to one explicit workspace

The server will start with one explicit workspace root. All database files, content-addressed objects, generated views, imports, exports, and temporary artifacts must resolve inside that root after symlink resolution. Runtime state lives under `.noa/`; NoA does not expose a general command-execution capability.

## Consequences

Client Roots are not an authorization boundary. NoA rejects traversal, workspace-external absolute paths, and symlinks that escape the root. Network access is limited to configured scholarly-source adapters and approved open-access document downloads. Evidence sent through Sampling is minimized, treated as untrusted source text, and filtered for sensitive content.
