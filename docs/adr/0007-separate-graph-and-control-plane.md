---
status: accepted
---

# Separate the research graph from the workflow control plane

LadybugDB stores committed research knowledge. SQLite stores Research Run state, plans, approval revisions, operation journals, leases, and audit events. Content-addressed objects hold raw API payloads, documents, parser output, and temporary staged artifacts.

Cross-store changes use a recoverable operation journal rather than pretending to provide distributed ACID: stage and hash artifacts, record a prepared operation, commit the LadybugDB transaction, atomically publish objects, then rebuild affected views. Startup recovery completes or rolls back interrupted operations by immutable operation ID.
