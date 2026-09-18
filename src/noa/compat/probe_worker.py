from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from noa.compat.checkpoint import run_checkpoint_probe
from noa.compat.ladybug_probe import run_ladybug_probe
from noa.compat.models import CheckResult

Probe = Callable[[Path], CheckResult]
_PROBES: dict[str, Probe] = {
    "ladybug": run_ladybug_probe,
    "checkpoint": run_checkpoint_probe,
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one NoA compatibility probe.")
    parser.add_argument("probe", choices=sorted(_PROBES))
    parser.add_argument("path", type=Path)
    return parser.parse_args(argv)


def _envelope(kind: str, **payload: object) -> str:
    return json.dumps({"kind": kind, **payload}, ensure_ascii=False)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = _PROBES[args.probe](args.path)
    except KeyboardInterrupt as exc:
        print(_envelope("base_exception", error_type="KeyboardInterrupt", error=str(exc)))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int | str) or exc.code is None else str(exc.code)
        print(
            _envelope(
                "base_exception",
                error_type="SystemExit",
                error=str(exc),
                code=code,
            )
        )
    except GeneratorExit as exc:
        print(_envelope("base_exception", error_type="GeneratorExit", error=str(exc)))
    except Exception as exc:
        print(
            _envelope(
                "exception",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        )
    else:
        print(_envelope("result", result=result.model_dump(mode="json")))
    return 0


def main(argv: Sequence[str] | None = None) -> NoReturn:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
