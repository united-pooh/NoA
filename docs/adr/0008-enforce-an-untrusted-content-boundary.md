---
status: accepted
---

# Treat literature as untrusted data and require human commits

All abstracts, PDFs, TEI, metadata, citations, URLs, and generated text are untrusted data. They cannot alter NoA's instructions, initiate network access, obtain credentials, call tools, approve candidates, or change export policy. Sampling receives only bounded evidence packets and must return schema-validated data.

PDF and XML parsing occurs only in a networkless low-privilege sandbox with resource limits and external-entity processing disabled. Downloads accept only adapter-issued HTTPS URLs, revalidate every redirect and resolved address, and reject private or non-allowlisted targets. All semantic candidates and fuzzy merges remain pending until a protected, always-confirmed tool records a named human review event.
