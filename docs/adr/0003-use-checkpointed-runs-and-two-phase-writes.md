---
status: accepted
---

# Use checkpointed research runs and explicit commit steps

A NoA research run is a durable state machine stored under `.noa/`. Each `continue` call performs one bounded step while an MCP request is active, may request Sampling, saves a checkpoint, and returns the next state. Long-lived inference is not assumed to remain available after a tool call returns.

Actions that change the confirmed knowledge graph are staged before commit. Collection plans, fuzzy merges, semantic claims and relationships, refresh changes, and destructive maintenance must expose their scope and evidence before a separate approved commit step. Generated Markdown views are rebuilt from the committed graph rather than edited as a second source of truth.

## Consequences

Runs can pause for plan approval or evidence-batch review, survive server restarts, and expose an auditable event history. The client or user must invoke the next step; this advances the server-owned workflow but does not delegate NoA's research reasoning to the host assistant.
