---
status: accepted
---

# Use LadybugDB as the authoritative literature graph

NoA's literature graph will use an on-disk embedded LadybugDB database as its authoritative store. The graph models research works, publications, documents, claims, evidence passages, people, venues, topics, methods, tasks, datasets, source records, and their relationships. Generated Markdown files are read-only views, not a second writable source of truth.

## Consequences

The implementation will use portable Cypher and avoid Ladybug-specific semantics where practical. Schema migrations and periodic exports to open tabular formats are required so the graph can be rebuilt or moved if the relatively new LadybugDB project becomes unsuitable. Kuzu is not used because it was archived in 2025; Neo4j was rejected for the first release because its separate service and Java lifecycle conflict with the local single-workspace product.
