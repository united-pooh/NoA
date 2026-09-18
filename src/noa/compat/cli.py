from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from noa.compat.models import GateDecision
from noa.compat.runner import run_compatibility_gate, write_report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the NoA Slice 0 compatibility gate.")
    parser.add_argument("--workspace", type=Path, default=Path(".noa/compatibility/workspace"))
    parser.add_argument("--host-evidence-root", type=Path, default=Path("."))
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(".noa/compatibility/compatibility.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("docs/compatibility/2026-08-21-slice-0.md"),
    )
    args = parser.parse_args(argv)
    if args.json.expanduser().resolve(strict=False) == args.markdown.expanduser().resolve(
        strict=False
    ):
        parser.error("--json and --markdown must use different paths")
    return args


async def _run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = await run_compatibility_gate(
        args.workspace,
        host_evidence_root=args.host_evidence_root,
    )
    write_report(report, json_path=args.json, markdown_path=args.markdown)
    print(report.model_dump_json(indent=2))
    return 1 if report.decision is GateDecision.NO_GO else 0


def main(argv: Sequence[str] | None = None) -> NoReturn:
    raise SystemExit(asyncio.run(_run(argv)))
