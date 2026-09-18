---
status: accepted
---

# Provide a progressively enhanced MCP App

NoA will expose workflow-oriented MCP Tools as the complete functional API and bundle a read-only MCP App inside the Python wheel for graph exploration and evidence-batch review. Clients without MCP Apps retain collection, search, review, note, lineage, import, and export capabilities through tools.

The App renders bounded subgraphs, timelines, search results, evidence, and pending candidates. It has a deny-by-default CSP, no external assets or network access, and cannot modify the database directly. Approval, download, deletion, and export actions invoke the same protected server tools used outside the App.
