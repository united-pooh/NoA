# Slice 0 Compatibility Evidence

The machine-readable report is generated at `.noa/compatibility/compatibility.json`. The checked-in human-readable report is `docs/compatibility/2026-08-21-slice-0.md`.

A release decision requires:

- exact dependency and platform checks;
- FastMCP in-memory and stdio checks;
- modern MRTR Sampling;
- legacy `sampling/createMessage`;
- invalid-output and cancellation behavior;
- LadybugDB transaction and persistence;
- SQLite checkpoint reopen;
- reproducible private wheel and sdist installation;
- VS Code Stable model authorization plus separate Sampling request/response and inline App screenshots, each with a hash-bound independent semantic review.

`conditional_go` is acceptable for Slice 1 specification work only when every functional and host check passes and the remaining condition is the pinned FastMCP 4 prerelease. Any required `fail` or `blocked` check produces `no_go` and prevents Slice 1 implementation.
