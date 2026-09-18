---
status: accepted
---

# Use prefixed UUIDv7 identifiers for graph entities

Every graph entity receives an immutable, type-prefixed UUIDv7 identifier such as `wrk_…`, `pub_…`, `doc_…`, or `clm_…`. DOI, arXiv, OpenAlex, ORCID, ROR, ISSN, and other external identifiers are normalized Identifier records with source and uniqueness constraints; they are never filesystem or graph primary keys.

## Consequences

Generated Markdown paths and internal references remain stable when titles, sources, or external identifiers change. Entity merges keep old IDs as redirects, and tombstones preserve references after deletion. External identifier conflicts are handled through assertions and review rather than primary-key rewrites.
