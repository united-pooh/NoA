---
status: accepted
---

# Preserve scholarly provenance as assertions

NoA will preserve immutable raw source payloads in the content-addressed object store and represent normalized metadata and factual relationships through source-attributed assertions. Current entity fields and visible factual edges are rebuildable projections; human corrections are higher-priority assertions rather than destructive overwrites.

## Consequences

Conflicting titles, dates, identifiers, citations, and version links remain explainable. Refreshing a source adds or retracts its assertions without deleting history. Model output cannot create factual assertions. Claim and semantic relationship candidates require evidence locations, model and prompt versions, structured-output hashes, and an explicit human review event before entering the confirmed graph.
