# VS Code Stable Compatibility Procedure

1. Run `code --version` and record the complete output.
2. Open this repository as the VS Code workspace.
3. Run `MCP: List Servers`, select `noa`, and start the server.
4. Select `Show Output`; verify startup contains no traceback and the server remains running.
5. Invoke `compatibility_ping` with `{"value":"vscode"}`; verify the result is `{"status":"pass","value":"vscode"}`.
6. Invoke `sampling_compatibility` with `{"question":"Return compatibility"}`.
7. Approve model access when VS Code prompts; verify the tool returns `status=pass` and a non-empty answer.
8. Run `MCP: List Servers > Show Sampling Requests`; verify both the `noa` Sampling request and its response are visible, then capture that view as `.agent/visual/slice-0-sampling.png`.
9. Invoke `show_compatibility_app`; verify the inline sandboxed App visibly contains the `NoA Compatibility` heading, the bordered App card, and the wrapped `ui://noa/compatibility.html` URI.
10. Capture the inline App view separately as `.agent/visual/slice-0-app.png`. Do not reuse the Sampling screenshot for the App artifact or reverse the filenames.
11. Record both artifacts in `.agent/visual/slice-0-host-evidence.json` and in the validator manifest inside `.agent/visual/slice-0-app.md`, including each file's exact path, byte count, pixel dimensions, and SHA-256 digest.
12. For each artifact, record its fixed `semantic_kind` and a `semantic_review` containing `reviewer_type: independent_agent`, `reviewed_at`, the hash-bound `artifact_sha256`, and the expected non-empty `observed_result`. The App review must state that the inline heading, card, and URI are visible; the Sampling review must state that the request and response are visible. Do not describe this as user or human approval.
13. Treat PNG decoding and hash checks only as integrity validation. They do not automatically determine screenshot semantics; semantic acceptance depends on the independent review record matching the artifact hash.
14. If GUI access, model authorization, either screenshot, or independent semantic review is unavailable, record the host check as `blocked`; do not infer success from local clients or the browser preview.
