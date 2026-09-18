# NoA Slice 0 Compatibility Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个可安装、可测试的 NoA Python/MCP compatibility spike，验证 FastMCP 4、MCP Python SDK v2、双协议 Sampling、MCP App、LadybugDB、stdio、checkpoint 和 VS Code Stable 的真实可行性，并输出结构化 Go/Conditional-Go/No-Go 报告。

**Architecture:** Slice 0 只建设兼容性探针，不实现 Slice 1–11 的领域业务。生产候选入口使用 FastMCP 4；Sampling 探针在 FastMCP 工具内按协商协议分流：2026-07-28 使用 `InputRequiredResult` MRTR，2025-11-25 使用底层 session 的 `create_message`。所有探针返回统一 `CheckResult`，最终由 CLI 写出 JSON 和 Markdown 证据；任何必需探针失败都形成 No-Go，不用 fallback 掩盖。

**Tech Stack:** CPython 3.11、uv、FastMCP `4.0.0b3`、MCP Python SDK `2.0.0`、LadybugDB `0.19.1`、Pydantic `2.13.4`、AnyIO `4.14.2`、pytest `9.1.1`、pytest-asyncio `1.4.0`、Ruff `0.16.3`、mypy `2.3.1`、Hatchling `1.32.0`。

---

## Scope Boundary

本计划只覆盖设计规格中的 Slice 0：Product Contract and Compatibility Gate。

明确不做：

- 文献领域实体和完整图 schema。
- workspace 安全内核。
- 三存储 operation journal。
- 数据源适配器、下载器、解析器。
- 实际 enrichment、人工审核、搜索或导出。
- 正式 MCP Tool catalog。
- 正式 MCP App UI。

FastMCP 4 在 2026-08-21 仍为 prerelease。该事实本身产生 `conditional_go`，不是自动 No-Go；但正式发布前必须升级到可接受的稳定版本并重跑整个 Slice 0 套件。

## File Map

### Project and verification

- Create: `.python-version` — 固定本地 Python 3.11。
- Create: `.gitignore` — 忽略虚拟环境、构建物、测试缓存和 compatibility 运行产物。
- Create: `pyproject.toml` — 精确直接依赖、构建、测试、lint、typecheck 和 console scripts。
- Create: `uv.lock` — 由 `uv lock` 生成并精确固定传递依赖。
- Create: `agent-md.toml` — 声明确定性的 typecheck/lint/test 命令。

### Package

- Create: `src/noa/__init__.py` — 包版本。
- Create: `src/noa/__main__.py` — stdio MCP 入口。
- Create: `src/noa/server.py` — FastMCP compatibility server、诊断工具和 App 资源。
- Create: `src/noa/compat/__init__.py` — compatibility API 导出。
- Create: `src/noa/compat/models.py` — `CheckResult`、`CompatibilityReport` 和 gate decision。
- Create: `src/noa/compat/runtime.py` — Python、OS 和依赖版本探针。
- Create: `src/noa/compat/ladybug_probe.py` — LadybugDB 安装、事务、持久化和只读重开探针。
- Create: `src/noa/compat/checkpoint.py` — 最小 SQLite checkpoint 可恢复性探针。
- Create: `src/noa/compat/sampling.py` — FastMCP 4 双协议 Sampling 工具和自动化探针。
- Create: `src/noa/compat/runner.py` — 聚合探针并生成报告。
- Create: `src/noa/compat/cli.py` — compatibility CLI。
- Create: `src/noa/compat/app/__init__.py` — 打包静态资源的 Python package marker。
- Create: `src/noa/compat/app/index.html` — 无外部网络依赖的 MCP App 静态探针。

### Host configuration and evidence

- Create: `.vscode/mcp.json` — VS Code Stable stdio server 配置。
- Create: `docs/compatibility/vscode-stable-procedure.md` — 可重复的真实宿主验证步骤。
- Create: `docs/compatibility/README.md` — Slice 0 证据和判定说明。
- Create: `.agent/visual/slice-0-app.md` — MCP App 新鲜截图的结构化证据。
- Generate: `.agent/visual/slice-0-app.png` — FastMCP App 预览或 VS Code 渲染截图。
- Generate: `.noa/compatibility/compatibility.json` — 机器可读报告，不提交。
- Generate: `docs/compatibility/2026-08-21-slice-0.md` — 人类可读报告。

### Tests

- Create: `tests/test_package_metadata.py`
- Create: `tests/compat/test_models.py`
- Create: `tests/compat/test_runtime.py`
- Create: `tests/compat/test_server.py`
- Create: `tests/compat/test_app.py`
- Create: `tests/compat/test_ladybug_probe.py`
- Create: `tests/compat/test_checkpoint.py`
- Create: `tests/compat/test_sampling.py`
- Create: `tests/compat/test_runner.py`
- Create: `tests/compat/test_packaging.py`

## Git Policy

本会话没有收到显式 commit 授权，因此计划中的每个任务以 `git diff --check` 和测试作为 checkpoint，不执行 `git commit`。如果后续用户明确授权提交，再按任务边界补做小提交。

---

### Task 1: Scaffold the pinned Python package

**Files:**
- Create: `.python-version`
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `agent-md.toml`
- Create: `src/noa/__init__.py`
- Test: `tests/test_package_metadata.py`
- Generate: `uv.lock`

- [ ] **Step 1: Write the failing package metadata test**

```python
# tests/test_package_metadata.py
from importlib.metadata import version
import sys


def test_runtime_and_direct_dependency_versions_are_exact() -> None:
    assert sys.version_info[:2] == (3, 11)
    assert version("noa-mcp") == "0.1.0a0"
    assert version("fastmcp") == "4.0.0b3"
    assert version("mcp") == "2.0.0"
    assert version("ladybug") == "0.19.1"
    assert version("pydantic") == "2.13.4"
    assert version("anyio") == "4.14.2"
```

- [ ] **Step 2: Run the test before scaffolding**

Run:

```bash
uv run --python 3.11 --with pytest==9.1.1 pytest tests/test_package_metadata.py -v
```

Expected: FAIL because `noa-mcp` is not installed and the package metadata does not exist.

- [ ] **Step 3: Create the package configuration**

```text
# .python-version
3.11
```

```gitignore
# .gitignore
.venv/
.venv-wheel/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
build/
dist/
*.egg-info/
.noa/
.agent/visual/*.png
.DS_Store
```

```toml
# pyproject.toml
[build-system]
requires = ["hatchling==1.32.0"]
build-backend = "hatchling.build"

[project]
name = "noa-mcp"
version = "0.1.0a0"
description = "NoA literature graph MCP compatibility spike"
readme = "README.md"
requires-python = "==3.11.*"
dependencies = [
  "anyio==4.14.2",
  "fastmcp==4.0.0b3",
  "ladybug==0.19.1",
  "mcp==2.0.0",
  "packaging==26.3",
  "pydantic==2.13.4",
]

[dependency-groups]
dev = [
  "build==1.5.0",
  "mypy==2.3.1",
  "pytest==9.1.1",
  "pytest-asyncio==1.4.0",
  "ruff==0.16.3",
]

[tool.uv]
constraint-dependencies = ["fastmcp-slim==4.0.0b3"]

[tool.hatch.build.targets.wheel]
packages = ["src/noa"]

[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["noa"]
mypy_path = "src"

[[tool.mypy.overrides]]
module = "ladybug"
ignore_missing_imports = true
```


```toml
# agent-md.toml
[verify]
typecheck = "uv run mypy src"
lint = "uv run ruff check . && uv run ruff format --check ."
test = "uv run pytest"
lint_file = "uv run ruff check {file}"
```

```python
# src/noa/__init__.py
__version__ = "0.1.0a0"
```

- [ ] **Step 4: Resolve and lock exact dependencies**

Run:

```bash
uv lock --python 3.11
uv sync --python 3.11 --all-groups --frozen
```

Expected: PASS. `uv.lock` records `fastmcp==4.0.0b3`, `fastmcp-slim==4.0.0b3`, `mcp==2.0.0`, and `ladybug==0.19.1`.

- [ ] **Step 5: Run the package test**

Run:

```bash
uv run pytest tests/test_package_metadata.py -v
```

Expected: PASS.

- [ ] **Step 6: Check formatting and the task diff**

Run:

```bash
uv run ruff check tests/test_package_metadata.py src/noa/__init__.py
git diff --check
```

Expected: both commands exit 0.

---

### Task 2: Define structured compatibility results

**Files:**
- Create: `src/noa/compat/__init__.py`
- Create: `src/noa/compat/models.py`
- Test: `tests/compat/test_models.py`

- [ ] **Step 1: Write the failing gate-decision tests**

```python
# tests/compat/test_models.py
from noa.compat.models import (
    CheckResult,
    CheckStatus,
    CompatibilityReport,
    GateDecision,
)


def test_required_failure_makes_report_no_go() -> None:
    report = CompatibilityReport.from_checks(
        [CheckResult(name="sampling-modern", status=CheckStatus.FAIL, required=True)]
    )
    assert report.decision is GateDecision.NO_GO


def test_warning_without_failure_makes_report_conditional_go() -> None:
    report = CompatibilityReport.from_checks(
        [CheckResult(name="fastmcp-stability", status=CheckStatus.WARN, required=True)]
    )
    assert report.decision is GateDecision.CONDITIONAL_GO


def test_optional_failure_does_not_block_go() -> None:
    report = CompatibilityReport.from_checks(
        [CheckResult(name="optional-observation", status=CheckStatus.FAIL, required=False)]
    )
    assert report.decision is GateDecision.GO
```

- [ ] **Step 2: Run the tests and observe the import failure**

Run:

```bash
uv run pytest tests/compat/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'noa.compat'`.

- [ ] **Step 3: Implement the result models**

```python
# src/noa/compat/models.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

from pydantic import BaseModel, Field


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    BLOCKED = "blocked"


class GateDecision(StrEnum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    NO_GO = "no_go"


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    required: bool = True
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class CompatibilityReport(BaseModel):
    generated_at: datetime
    decision: GateDecision
    checks: list[CheckResult]

    @classmethod
    def from_checks(cls, checks: Iterable[CheckResult]) -> CompatibilityReport:
        materialized = list(checks)
        blocking = any(
            check.required and check.status in {CheckStatus.FAIL, CheckStatus.BLOCKED}
            for check in materialized
        )
        warning = any(check.status is CheckStatus.WARN for check in materialized)
        decision = (
            GateDecision.NO_GO
            if blocking
            else GateDecision.CONDITIONAL_GO
            if warning
            else GateDecision.GO
        )
        return cls(
            generated_at=datetime.now(timezone.utc),
            decision=decision,
            checks=materialized,
        )
```

```python
# src/noa/compat/__init__.py
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport, GateDecision

__all__ = ["CheckResult", "CheckStatus", "CompatibilityReport", "GateDecision"]
```

- [ ] **Step 4: Run tests and static checks**

Run:

```bash
uv run pytest tests/compat/test_models.py -v
uv run ruff check src/noa/compat tests/compat/test_models.py
uv run mypy src/noa/compat/models.py
```

Expected: all PASS.

- [ ] **Step 5: Check the task diff**

Run:

```bash
git diff --check
```

Expected: exit 0.

---

### Task 3: Probe Python, platform, and exact dependency versions

**Files:**
- Create: `src/noa/compat/runtime.py`
- Test: `tests/compat/test_runtime.py`

- [ ] **Step 1: Write the failing runtime probe tests**

```python
# tests/compat/test_runtime.py
from noa.compat.models import CheckStatus
from noa.compat.runtime import build_runtime_checks


def test_runtime_checks_match_slice_zero_contract() -> None:
    checks = {check.name: check for check in build_runtime_checks()}
    assert checks["python"].status is CheckStatus.PASS
    assert checks["platform"].status is CheckStatus.PASS
    assert checks["fastmcp"].status is CheckStatus.PASS
    assert checks["mcp-sdk"].status is CheckStatus.PASS
    assert checks["ladybug"].status is CheckStatus.PASS
    assert checks["fastmcp-stability"].status is CheckStatus.WARN
    assert checks["fastmcp-stability"].required is True
```

- [ ] **Step 2: Run the test and observe the missing module**

Run:

```bash
uv run pytest tests/compat/test_runtime.py -v
```

Expected: FAIL because `noa.compat.runtime` does not exist.

- [ ] **Step 3: Implement exact runtime checks**

```python
# src/noa/compat/runtime.py
from __future__ import annotations

from importlib.metadata import version
import platform
import sys

from packaging.version import Version

from noa.compat.models import CheckResult, CheckStatus


EXPECTED_DISTRIBUTIONS = {
    "fastmcp": "4.0.0b3",
    "mcp": "2.0.0",
    "ladybug": "0.19.1",
    "pydantic": "2.13.4",
    "anyio": "4.14.2",
}


def _version_check(name: str, distribution: str, expected: str) -> CheckResult:
    actual = version(distribution)
    status = CheckStatus.PASS if actual == expected else CheckStatus.FAIL
    return CheckResult(
        name=name,
        status=status,
        summary=f"{distribution} {actual}",
        details={"expected": expected, "actual": actual},
    )


def build_runtime_checks() -> list[CheckResult]:
    python_ok = sys.version_info[:2] == (3, 11)
    mac_version = platform.mac_ver()[0]
    platform_ok = platform.system() == "Darwin" and bool(mac_version) and Version(mac_version) >= Version("15")
    checks = [
        CheckResult(
            name="python",
            status=CheckStatus.PASS if python_ok else CheckStatus.FAIL,
            summary=platform.python_version(),
            details={"required": "3.11.x"},
        ),
        CheckResult(
            name="platform",
            status=CheckStatus.PASS if platform_ok else CheckStatus.FAIL,
            summary=f"{platform.system()} {mac_version}",
            details={"required": "macOS >= 15"},
        ),
        _version_check("fastmcp", "fastmcp", EXPECTED_DISTRIBUTIONS["fastmcp"]),
        _version_check("mcp-sdk", "mcp", EXPECTED_DISTRIBUTIONS["mcp"]),
        _version_check("ladybug", "ladybug", EXPECTED_DISTRIBUTIONS["ladybug"]),
        _version_check("pydantic", "pydantic", EXPECTED_DISTRIBUTIONS["pydantic"]),
        _version_check("anyio", "anyio", EXPECTED_DISTRIBUTIONS["anyio"]),
    ]
    fastmcp_version = Version(version("fastmcp"))
    checks.append(
        CheckResult(
            name="fastmcp-stability",
            status=CheckStatus.WARN if fastmcp_version.is_prerelease else CheckStatus.PASS,
            summary=(
                "FastMCP 4 is prerelease; release remains blocked on a stable validated pin."
                if fastmcp_version.is_prerelease
                else "FastMCP 4 pin is stable."
            ),
            details={"version": str(fastmcp_version)},
        )
    )
    return checks
```

- [ ] **Step 4: Run the runtime tests**

Run:

```bash
uv run pytest tests/compat/test_runtime.py -v
```

Expected: PASS on the declared macOS/CPython 3.11 environment.

- [ ] **Step 5: Run static checks**

Run:

```bash
uv run ruff check src/noa/compat/runtime.py tests/compat/test_runtime.py
uv run mypy src/noa/compat/runtime.py
```

Expected: PASS.

---

### Task 4: Build a real FastMCP stdio server

**Files:**
- Create: `src/noa/server.py`
- Create: `src/noa/__main__.py`
- Modify: `pyproject.toml`
- Test: `tests/compat/test_server.py`

- [ ] **Step 1: Write failing in-memory and stdio tests**

```python
# tests/compat/test_server.py
from __future__ import annotations

import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from noa.server import mcp


@pytest.mark.asyncio
async def test_fastmcp_server_works_in_memory() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("compatibility_ping", {"value": "ok"})
    assert result.data == {"status": "pass", "value": "ok"}


@pytest.mark.asyncio
async def test_fastmcp_server_works_over_stdio() -> None:
    transport = StdioTransport(command=sys.executable, args=["-m", "noa"])
    async with Client(transport) as client:
        result = await client.call_tool("compatibility_ping", {"value": "stdio"})
    assert result.data == {"status": "pass", "value": "stdio"}
```

- [ ] **Step 2: Run the tests and observe the missing server module**

Run:

```bash
uv run pytest tests/compat/test_server.py -v
```

Expected: FAIL because `noa.server` does not exist.

- [ ] **Step 3: Implement the minimal server and entrypoint**

```python
# src/noa/server.py
from fastmcp import FastMCP

from noa.compat.runtime import build_runtime_checks


mcp = FastMCP("NoA Compatibility", mask_error_details=True)


@mcp.tool()
def compatibility_ping(value: str = "pong") -> dict[str, str]:
    """Verify that the NoA MCP server can execute a tool."""
    return {"status": "pass", "value": value}


@mcp.tool()
def compatibility_runtime() -> list[dict[str, object]]:
    """Return exact runtime and dependency compatibility checks."""
    return [check.model_dump(mode="json") for check in build_runtime_checks()]


def run() -> None:
    mcp.run(transport="stdio")
```

```python
# src/noa/__main__.py
from noa.server import run


if __name__ == "__main__":
    run()
```

Add this section to `pyproject.toml`:

```toml
[project.scripts]
noa = "noa.server:run"
```

- [ ] **Step 4: Re-lock and run server tests**

Run:

```bash
uv lock
uv sync --all-groups --frozen
uv run pytest tests/compat/test_server.py -v
```

Expected: both tests PASS, including a real child process over stdio.

- [ ] **Step 5: Run static checks**

Run:

```bash
uv run ruff check src/noa/server.py src/noa/__main__.py tests/compat/test_server.py
uv run mypy src/noa/server.py src/noa/__main__.py
```

Expected: PASS.

---

### Task 5: Package a deny-by-default MCP App resource

**Files:**
- Create: `src/noa/compat/app/__init__.py`
- Create: `src/noa/compat/app/index.html`
- Modify: `src/noa/server.py`
- Test: `tests/compat/test_app.py`

- [ ] **Step 1: Write the failing App resource test**

```python
# tests/compat/test_app.py
import pytest
from fastmcp import Client

from noa.server import COMPATIBILITY_APP_URI, mcp


@pytest.mark.asyncio
async def test_compatibility_app_is_bundled_and_network_free() -> None:
    async with Client(mcp) as client:
        contents = await client.read_resource(COMPATIBILITY_APP_URI)
    assert len(contents) == 1
    assert contents[0].mime_type == "text/html;profile=mcp-app"
    html = contents[0].text
    assert "NoA Compatibility" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<script src=" not in html
```

- [ ] **Step 2: Run the test and observe the missing resource**

Run:

```bash
uv run pytest tests/compat/test_app.py -v
```

Expected: FAIL because `COMPATIBILITY_APP_URI` and the resource do not exist.

- [ ] **Step 3: Add the bundled HTML**

```python
# src/noa/compat/app/__init__.py
```

```html
<!-- src/noa/compat/app/index.html -->
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NoA Compatibility</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; padding: 24px; background: Canvas; color: CanvasText; }
    main { max-width: 720px; margin: 0 auto; }
    .status { border: 1px solid color-mix(in srgb, CanvasText 25%, transparent); border-radius: 12px; padding: 20px; }
    code { font-family: ui-monospace, monospace; }
  </style>
</head>
<body>
  <main>
    <section class="status">
      <h1>NoA Compatibility</h1>
      <p id="message">MCP App compatibility probe loaded.</p>
      <p><code>ui://noa/compatibility.html</code></p>
    </section>
  </main>
</body>
</html>
```

- [ ] **Step 4: Register the App tool and resource**

Add to `src/noa/server.py`:

```python
from importlib.resources import files

from fastmcp.apps import AppConfig, ResourceCSP


COMPATIBILITY_APP_URI = "ui://noa/compatibility.html"


@mcp.tool(app=AppConfig(resource_uri=COMPATIBILITY_APP_URI))
def show_compatibility_app() -> dict[str, str]:
    """Render the bundled NoA MCP App compatibility probe."""
    return {"status": "pass", "resource_uri": COMPATIBILITY_APP_URI}


@mcp.resource(
    COMPATIBILITY_APP_URI,
    app=AppConfig(csp=ResourceCSP()),
)
def compatibility_app() -> str:
    return files("noa.compat.app").joinpath("index.html").read_text(encoding="utf-8")
```

Keep the existing imports and tools; do not replace them.

- [ ] **Step 5: Run App tests and static checks**

Run:

```bash
uv run pytest tests/compat/test_app.py -v
uv run ruff check src/noa/server.py src/noa/compat/app tests/compat/test_app.py
uv run mypy src/noa/server.py
```

Expected: PASS. The resource MIME type is `text/html;profile=mcp-app`, and no external domain is declared.

---

### Task 6: Verify LadybugDB transaction and persistence behavior

**Files:**
- Create: `src/noa/compat/ladybug_probe.py`
- Test: `tests/compat/test_ladybug_probe.py`

- [ ] **Step 1: Write the failing LadybugDB probe test**

```python
# tests/compat/test_ladybug_probe.py
from pathlib import Path

from noa.compat.ladybug_probe import run_ladybug_probe
from noa.compat.models import CheckStatus


def test_ladybug_probe_verifies_rollback_commit_and_reopen(tmp_path: Path) -> None:
    result = run_ladybug_probe(tmp_path)
    assert result.status is CheckStatus.PASS, result.model_dump_json(indent=2)
    assert result.details["rolled_back_rows"] == []
    assert result.details["committed_rows"] == [["committed", "ok"]]
    assert result.details["reopened_rows"] == [["committed", "ok"]]
```

- [ ] **Step 2: Run the test and observe the missing module**

Run:

```bash
uv run pytest tests/compat/test_ladybug_probe.py -v
```

Expected: FAIL because `noa.compat.ladybug_probe` does not exist.

- [ ] **Step 3: Implement the LadybugDB probe**

```python
# src/noa/compat/ladybug_probe.py
from __future__ import annotations

import gc
from pathlib import Path
from typing import cast

import ladybug as lb

from noa.compat.models import CheckResult, CheckStatus


SCHEMA = "CREATE NODE TABLE Probe(id STRING PRIMARY KEY, value STRING)"


def _rows(connection: lb.Connection) -> list[list[object]]:
    result = connection.execute("MATCH (p:Probe) RETURN p.id, p.value ORDER BY p.id")
    return cast(list[list[object]], result.get_all())


def run_ladybug_probe(root: Path) -> CheckResult:
    database_path = root / "compatibility.lbdb"
    try:
        database = lb.Database(str(database_path))
        connection = lb.Connection(database)
        connection.execute(SCHEMA)

        connection.execute("BEGIN TRANSACTION")
        connection.execute("CREATE (p:Probe {id: 'rolled-back', value: 'no'})")
        connection.execute("ROLLBACK")
        rolled_back_rows = _rows(connection)

        connection.execute("BEGIN TRANSACTION")
        connection.execute("CREATE (p:Probe {id: 'committed', value: 'ok'})")
        connection.execute("COMMIT")
        committed_rows = _rows(connection)

        del connection
        del database
        gc.collect()

        reopened_database = lb.Database(str(database_path), read_only=True)
        reopened_connection = lb.Connection(reopened_database)
        reopened_rows = _rows(reopened_connection)

        status = (
            CheckStatus.PASS
            if rolled_back_rows == []
            and committed_rows == [["committed", "ok"]]
            and reopened_rows == [["committed", "ok"]]
            else CheckStatus.FAIL
        )
        return CheckResult(
            name="ladybug-transaction-persistence",
            status=status,
            summary="LadybugDB rollback, commit, and read-only reopen probe completed.",
            details={
                "database_path": str(database_path),
                "rolled_back_rows": rolled_back_rows,
                "committed_rows": committed_rows,
                "reopened_rows": reopened_rows,
            },
        )
    except Exception as exc:
        return CheckResult(
            name="ladybug-transaction-persistence",
            status=CheckStatus.FAIL,
            summary="LadybugDB compatibility probe failed.",
            details={"error_type": type(exc).__name__, "error": str(exc)},
        )
```

- [ ] **Step 4: Run the LadybugDB test**

Run:

```bash
uv run pytest tests/compat/test_ladybug_probe.py -v
```

Expected: PASS using LadybugDB `0.19.1` transaction statements `BEGIN TRANSACTION`, `COMMIT`, and `ROLLBACK`.

- [ ] **Step 5: Run static checks**

Run:

```bash
uv run ruff check src/noa/compat/ladybug_probe.py tests/compat/test_ladybug_probe.py
uv run mypy src/noa/compat/ladybug_probe.py
```

Expected: PASS.

---

### Task 7: Verify SQLite checkpoint recovery

**Files:**
- Create: `src/noa/compat/checkpoint.py`
- Test: `tests/compat/test_checkpoint.py`

- [ ] **Step 1: Write failing checkpoint tests**

```python
# tests/compat/test_checkpoint.py
from pathlib import Path

from noa.compat.checkpoint import CheckpointStore, run_checkpoint_probe
from noa.compat.models import CheckStatus


def test_checkpoint_survives_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "control.sqlite3"
    first = CheckpointStore(path)
    first.start("run-1", total_steps=3)
    first.advance("run-1")
    first.close()

    second = CheckpointStore(path)
    assert second.load("run-1") == (1, 3)
    second.advance("run-1")
    assert second.load("run-1") == (2, 3)
    second.close()


def test_checkpoint_probe_passes(tmp_path: Path) -> None:
    result = run_checkpoint_probe(tmp_path)
    assert result.status is CheckStatus.PASS
    assert result.details["resumed_step"] == 1
    assert result.details["final_step"] == 2
```

- [ ] **Step 2: Run the tests and observe the missing module**

Run:

```bash
uv run pytest tests/compat/test_checkpoint.py -v
```

Expected: FAIL because `noa.compat.checkpoint` does not exist.

- [ ] **Step 3: Implement the minimal checkpoint store**

```python
# src/noa/compat/checkpoint.py
from __future__ import annotations

from pathlib import Path
import sqlite3

from noa.compat.models import CheckResult, CheckStatus


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS compatibility_run (
                run_id TEXT PRIMARY KEY,
                current_step INTEGER NOT NULL,
                total_steps INTEGER NOT NULL
            )
            """
        )
        self._connection.commit()

    def start(self, run_id: str, total_steps: int) -> None:
        self._connection.execute(
            "INSERT INTO compatibility_run(run_id, current_step, total_steps) VALUES (?, 0, ?)",
            (run_id, total_steps),
        )
        self._connection.commit()

    def advance(self, run_id: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE compatibility_run
            SET current_step = current_step + 1
            WHERE run_id = ? AND current_step < total_steps
            """,
            (run_id,),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"run cannot advance: {run_id}")
        self._connection.commit()

    def load(self, run_id: str) -> tuple[int, int]:
        row = self._connection.execute(
            "SELECT current_step, total_steps FROM compatibility_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return int(row[0]), int(row[1])

    def close(self) -> None:
        self._connection.close()


def run_checkpoint_probe(root: Path) -> CheckResult:
    path = root / "checkpoint.sqlite3"
    run_id = "slice-0"
    first = CheckpointStore(path)
    first.start(run_id, total_steps=3)
    first.advance(run_id)
    first.close()

    second = CheckpointStore(path)
    resumed_step, total_steps = second.load(run_id)
    second.advance(run_id)
    final_step, _ = second.load(run_id)
    second.close()
    status = CheckStatus.PASS if (resumed_step, final_step, total_steps) == (1, 2, 3) else CheckStatus.FAIL
    return CheckResult(
        name="sqlite-checkpoint-recovery",
        status=status,
        summary="SQLite checkpoint survived process-style close and reopen.",
        details={
            "resumed_step": resumed_step,
            "final_step": final_step,
            "total_steps": total_steps,
        },
    )
```

- [ ] **Step 4: Run checkpoint tests and static checks**

Run:

```bash
uv run pytest tests/compat/test_checkpoint.py -v
uv run ruff check src/noa/compat/checkpoint.py tests/compat/test_checkpoint.py
uv run mypy src/noa/compat/checkpoint.py
```

Expected: PASS.

---

### Task 8: Implement dual-era Sampling on FastMCP 4

**Files:**
- Create: `src/noa/compat/sampling.py`
- Modify: `src/noa/server.py`
- Test: `tests/compat/test_sampling.py`

- [ ] **Step 1: Write failing modern and legacy Sampling tests**

```python
# tests/compat/test_sampling.py
from __future__ import annotations

import anyio
import pytest
from fastmcp import Client
from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams

from noa.server import mcp


async def valid_sampling_handler(
    messages: list[SamplingMessage],
    params: SamplingParams,
    context: RequestContext,
) -> str:
    return '{"answer":"compatible"}'


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_sampling_probe_supports_both_protocol_eras(mode: str) -> None:
    async with Client(mcp, mode=mode, sampling_handler=valid_sampling_handler) as client:
        result = await client.call_tool("sampling_compatibility", {"question": "probe"})
    assert result.data == {"status": "pass", "answer": "compatible"}


@pytest.mark.asyncio
async def test_invalid_sampling_output_is_rejected() -> None:
    async def invalid_handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: RequestContext,
    ) -> str:
        return "not-json"

    async with Client(mcp, sampling_handler=invalid_handler) as client:
        result = await client.call_tool("sampling_compatibility", {"question": "probe"})
    assert result.data["status"] == "invalid_model_output"
    assert result.data["answer"] is None


@pytest.mark.asyncio
async def test_sampling_timeout_cancels_the_call() -> None:
    async def blocked_handler(
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: RequestContext,
    ) -> str:
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async with Client(mcp, sampling_handler=blocked_handler) as client:
        with pytest.raises(TimeoutError):
            with anyio.fail_after(0.05):
                await client.call_tool("sampling_compatibility", {"question": "probe"})
```

- [ ] **Step 2: Run the tests and observe the missing tool**

Run:

```bash
uv run pytest tests/compat/test_sampling.py -v
```

Expected: FAIL because `sampling_compatibility` is not registered.

- [ ] **Step 3: Implement deterministic request construction and validation**

```python
# src/noa/compat/sampling.py
from __future__ import annotations

import warnings

from fastmcp import Context
from mcp.types import (
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    InputRequiredResult,
    SamplingMessage,
    TextContent,
)
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ValidationError


class SamplingEnvelope(BaseModel):
    answer: str


def build_sampling_request(question: str) -> CreateMessageRequest:
    return CreateMessageRequest(
        method="sampling/createMessage",
        params=CreateMessageRequestParams(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            "Return one JSON object matching "
                            '{"answer":"<short text>"}. Question: '
                            f"{question}"
                        ),
                    ),
                )
            ],
            max_tokens=80,
        ),
    )


def parse_sampling_result(result: CreateMessageResult) -> dict[str, str | None]:
    if not isinstance(result.content, TextContent):
        return {"status": "invalid_model_output", "answer": None}
    try:
        envelope = SamplingEnvelope.model_validate_json(result.content.text)
    except ValidationError:
        return {"status": "invalid_model_output", "answer": None}
    return {"status": "pass", "answer": envelope.answer}


async def resolve_sampling(question: str, ctx: Context) -> dict[str, str | None] | InputRequiredResult:
    responses = ctx.input_responses or {}
    response = responses.get("answer")
    if isinstance(response, CreateMessageResult):
        return parse_sampling_result(response)

    request_context = ctx.request_context
    if request_context is None:
        raise RuntimeError("sampling requires an established MCP request context")
    protocol_version = request_context.protocol_version
    request = build_sampling_request(question)
    if protocol_version in MODERN_PROTOCOL_VERSIONS:
        return InputRequiredResult(
            result_type="input_required",
            input_requests={"answer": request},
            request_state="noa-sampling-compatibility-v1",
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = await ctx.session.create_message(
            messages=request.params.messages,
            max_tokens=request.params.max_tokens,
        )
    return parse_sampling_result(result)
```

- [ ] **Step 4: Register the Sampling tool**

Add to `src/noa/server.py`:

```python
from fastmcp import Context
from mcp.types import InputRequiredResult

from noa.compat.sampling import resolve_sampling


@mcp.tool()
async def sampling_compatibility(
    question: str,
    ctx: Context,
) -> dict[str, str | None] | InputRequiredResult:
    """Verify caller-model Sampling on both the 2025 and 2026 MCP eras."""
    return await resolve_sampling(question, ctx)
```

- [ ] **Step 5: Run the Sampling tests**

Run:

```bash
uv run pytest tests/compat/test_sampling.py -v
```

Expected:

- `mode="auto"` PASS through 2026-07-28 MRTR.
- `mode="legacy"` PASS through 2025-11-25 `sampling/createMessage`.
- Invalid JSON returns `invalid_model_output`.
- Timeout raises `TimeoutError` and does not hang the client.

If either protocol mode fails with the pinned packages, keep the failing test and classify the Slice 0 report as No-Go. Do not switch to FastMCP 3, direct model APIs, or a second production server inside this task.

- [ ] **Step 6: Run static checks**

Run:

```bash
uv run ruff check src/noa/compat/sampling.py src/noa/server.py tests/compat/test_sampling.py
uv run mypy src/noa/compat/sampling.py src/noa/server.py
```

Expected: PASS.

---

### Task 9: Aggregate probes into JSON and Markdown reports

**Files:**
- Create: `src/noa/compat/runner.py`
- Create: `src/noa/compat/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/compat/test_runner.py`

- [ ] **Step 1: Write failing report-generation tests**

```python
# tests/compat/test_runner.py
from pathlib import Path

import pytest

from noa.compat.models import GateDecision
from noa.compat.runner import run_compatibility_gate, write_report


@pytest.mark.asyncio
async def test_runner_writes_machine_and_human_reports(tmp_path: Path) -> None:
    report = await run_compatibility_gate(tmp_path / "workspace")
    json_path = tmp_path / "compatibility.json"
    markdown_path = tmp_path / "compatibility.md"
    write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json_path.exists()
    assert markdown_path.exists()
    assert '"decision"' in json_path.read_text(encoding="utf-8")
    assert "# NoA Slice 0 Compatibility Report" in markdown_path.read_text(encoding="utf-8")
    assert report.decision in {
        GateDecision.GO,
        GateDecision.CONDITIONAL_GO,
        GateDecision.NO_GO,
    }
```

- [ ] **Step 2: Run the test and observe the missing runner**

Run:

```bash
uv run pytest tests/compat/test_runner.py -v
```

Expected: FAIL because `noa.compat.runner` does not exist.

- [ ] **Step 3: Implement the aggregate runner**

```python
# src/noa/compat/runner.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastmcp import Client
from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams

from noa.compat.checkpoint import run_checkpoint_probe
from noa.compat.ladybug_probe import run_ladybug_probe
from noa.compat.models import CheckResult, CheckStatus, CompatibilityReport
from noa.compat.runtime import build_runtime_checks
from noa.server import mcp


async def _sampling_handler(
    messages: list[SamplingMessage],
    params: SamplingParams,
    context: RequestContext,
) -> str:
    return '{"answer":"compatible"}'


async def _sampling_check(mode: Literal["auto", "legacy"]) -> CheckResult:
    name = "sampling-modern" if mode == "auto" else "sampling-legacy"
    try:
        async with Client(mcp, mode=mode, sampling_handler=_sampling_handler) as client:
            result = await client.call_tool("sampling_compatibility", {"question": name})
            protocol_version = client.protocol_version
        passed = result.data == {"status": "pass", "answer": "compatible"}
        return CheckResult(
            name=name,
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            summary=f"Sampling probe completed in {mode} mode.",
            details={"protocol_version": protocol_version, "result": result.data},
        )
    except Exception as exc:
        return CheckResult(
            name=name,
            status=CheckStatus.FAIL,
            summary=f"Sampling probe failed in {mode} mode.",
            details={"error_type": type(exc).__name__, "error": str(exc)},
        )


async def _app_check() -> CheckResult:
    from noa.server import COMPATIBILITY_APP_URI

    try:
        async with Client(mcp) as client:
            contents = await client.read_resource(COMPATIBILITY_APP_URI)
        passed = (
            len(contents) == 1
            and contents[0].mime_type == "text/html;profile=mcp-app"
            and "https://" not in contents[0].text
            and "http://" not in contents[0].text
        )
        return CheckResult(
            name="mcp-app-resource",
            status=CheckStatus.PASS if passed else CheckStatus.FAIL,
            summary="Bundled MCP App resource loaded with a deny-by-default CSP.",
            details={"uri": COMPATIBILITY_APP_URI, "mime_type": contents[0].mime_type},
        )
    except Exception as exc:
        return CheckResult(
            name="mcp-app-resource",
            status=CheckStatus.FAIL,
            summary="MCP App resource probe failed.",
            details={"error_type": type(exc).__name__, "error": str(exc)},
        )


async def run_compatibility_gate(workspace: Path) -> CompatibilityReport:
    workspace.mkdir(parents=True, exist_ok=True)
    checks = build_runtime_checks()
    checks.append(run_ladybug_probe(workspace / "ladybug"))
    checks.append(run_checkpoint_probe(workspace / "checkpoint"))
    checks.append(await _sampling_check("auto"))
    checks.append(await _sampling_check("legacy"))
    checks.append(await _app_check())
    return CompatibilityReport.from_checks(checks)


def _markdown(report: CompatibilityReport) -> str:
    lines = [
        "# NoA Slice 0 Compatibility Report",
        "",
        f"- Decision: `{report.decision.value}`",
        f"- Generated: `{report.generated_at.isoformat()}`",
        "",
        "| Check | Status | Required | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for check in report.checks:
        summary = check.summary.replace("|", "\\|")
        lines.append(
            f"| `{check.name}` | `{check.status.value}` | `{str(check.required).lower()}` | {summary} |"
        )
    lines.extend(["", "## Details", ""])
    for check in report.checks:
        lines.extend(
            [
                f"### {check.name}",
                "",
                "```json",
                json.dumps(check.details, ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def write_report(
    report: CompatibilityReport,
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
```

Before calling the probes, add these two lines inside `run_compatibility_gate` after `workspace.mkdir(...)` so child directories exist:

```python
    (workspace / "ladybug").mkdir(parents=True, exist_ok=True)
    (workspace / "checkpoint").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Implement the CLI**

```python
# src/noa/compat/cli.py
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from noa.compat.runner import run_compatibility_gate, write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the NoA Slice 0 compatibility gate.")
    parser.add_argument("--workspace", type=Path, default=Path(".noa/compatibility/workspace"))
    parser.add_argument("--json", type=Path, default=Path(".noa/compatibility/compatibility.json"))
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("docs/compatibility/2026-08-21-slice-0.md"),
    )
    return parser.parse_args()


async def _run() -> int:
    args = parse_args()
    report = await run_compatibility_gate(args.workspace)
    write_report(report, json_path=args.json, markdown_path=args.markdown)
    print(report.model_dump_json(indent=2))
    return 1 if report.decision.value == "no_go" else 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))
```

Add to `[project.scripts]` in `pyproject.toml`:

```toml
noa-compat = "noa.compat.cli:main"
```

- [ ] **Step 5: Run runner tests and the real CLI**

Run:

```bash
uv lock
uv sync --all-groups --frozen
uv run pytest tests/compat/test_runner.py -v
uv run noa-compat
```

Expected:

- Test PASS.
- CLI writes both report files.
- CLI exits 0 for `go` or `conditional_go`, 1 for `no_go`.
- On the currently known dependency state, `fastmcp-stability` produces a warning, so a fully passing functional suite yields `conditional_go`.

- [ ] **Step 6: Run static checks**

Run:

```bash
uv run ruff check src/noa/compat/runner.py src/noa/compat/cli.py tests/compat/test_runner.py
uv run mypy src/noa/compat/runner.py src/noa/compat/cli.py
```

Expected: PASS.

---

### Task 10: Verify wheel packaging and installed stdio behavior

**Files:**
- Test: `tests/compat/test_packaging.py`
- Generate: `dist/noa_mcp-0.1.0a0-py3-none-any.whl`

- [ ] **Step 1: Write the failing package-resource test**

```python
# tests/compat/test_packaging.py
from importlib.resources import files


def test_mcp_app_html_is_available_as_package_data() -> None:
    resource = files("noa.compat.app").joinpath("index.html")
    assert resource.is_file()
    assert "NoA Compatibility" in resource.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the resource test**

Run:

```bash
uv run pytest tests/compat/test_packaging.py -v
```

Expected: PASS from the source tree. If it fails, fix package placement rather than reading from a repository-relative path.

- [ ] **Step 3: Build the wheel**

Run:

```bash
uv build --out-dir dist
```

Expected: `dist/noa_mcp-0.1.0a0-py3-none-any.whl` and source distribution are created.

- [ ] **Step 4: Install the wheel into a clean Python 3.11 environment**

Run:

```bash
uv venv --python 3.11 .venv-wheel
uv pip install --python .venv-wheel/bin/python dist/noa_mcp-0.1.0a0-py3-none-any.whl
.venv-wheel/bin/python -c 'from importlib.resources import files; p=files("noa.compat.app").joinpath("index.html"); assert p.is_file(); print(p)'
.venv-wheel/bin/noa-compat --workspace .noa/compatibility/wheel-workspace --json .noa/compatibility/wheel.json --markdown .noa/compatibility/wheel.md
```

Expected:

- Package resource assertion PASS.
- Installed `noa-compat` runs without importing from the source tree.
- The installed probe produces JSON and Markdown evidence.

- [ ] **Step 5: Verify installed stdio with FastMCP Client**

Run:

```bash
.venv-wheel/bin/python - <<'PY'
import asyncio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

async def main() -> None:
    transport = StdioTransport(
        command=".venv-wheel/bin/python",
        args=["-m", "noa"],
    )
    async with Client(transport) as client:
        result = await client.call_tool("compatibility_ping", {"value": "wheel"})
    assert result.data == {"status": "pass", "value": "wheel"}

asyncio.run(main())
PY
```

Expected: exit 0.

- [ ] **Step 6: Check build diff and artifact policy**

Run:

```bash
git diff --check
git status --short
```

Expected: generated `dist/`, `.venv-wheel/`, and `.noa/` remain ignored; source and test files are visible changes.

---

### Task 11: Validate VS Code Stable and capture MCP App evidence

**Files:**
- Create: `.vscode/mcp.json`
- Create: `docs/compatibility/vscode-stable-procedure.md`
- Create: `docs/compatibility/README.md`
- Generate: `.agent/visual/slice-0-app.png`
- Create: `.agent/visual/slice-0-app.md`
- Modify: `docs/compatibility/2026-08-21-slice-0.md`

- [ ] **Step 1: Add the exact VS Code workspace MCP configuration**

```json
// .vscode/mcp.json
{
  "inputs": [],
  "servers": {
    "noa": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--frozen", "python", "-m", "noa"]
    }
  }
}
```

- [ ] **Step 2: Write the host procedure with no ambiguous actions**

```markdown
# VS Code Stable Compatibility Procedure

1. Run `code --version` and record all output in the Slice 0 report.
2. Open this repository as the VS Code workspace.
3. Run `MCP: List Servers`, select `noa`, and start the server.
4. Select `Show Output`; verify startup contains no traceback and the server remains running.
5. Invoke `compatibility_ping` with `{"value":"vscode"}`; verify the result is `{"status":"pass","value":"vscode"}`.
6. Invoke `sampling_compatibility` with `{"question":"Return compatibility"}`.
7. Approve model access when VS Code prompts. Verify the tool returns `status=pass` and a non-empty answer.
8. Run `MCP: List Servers > Show Sampling Requests`; verify a request from `noa` is present.
9. Invoke `show_compatibility_app`; verify an inline sandboxed UI displays the heading `NoA Compatibility`.
10. Capture a fresh screenshot as `.agent/visual/slice-0-app.png`.
11. Record the VS Code version, observed protocol path, model authorization result, Sampling request visibility, App rendering result, and screenshot path in `.agent/visual/slice-0-app.md`.
12. If any step cannot be completed, mark the host check `blocked` or `fail`; do not infer success from local tests.
```

- [ ] **Step 3: Add compatibility evidence documentation**

```markdown
# Slice 0 Compatibility Evidence

The machine-readable report is generated at `.noa/compatibility/compatibility.json`.
The checked-in human-readable report is `docs/compatibility/2026-08-21-slice-0.md`.

A release decision requires:

- exact dependency and platform checks;
- FastMCP in-memory and stdio checks;
- modern MRTR Sampling;
- legacy `sampling/createMessage`;
- invalid-output and cancellation behavior;
- LadybugDB transaction and persistence;
- SQLite checkpoint reopen;
- wheel installation and packaged App resource;
- VS Code Stable model authorization, Sampling log, and inline App rendering.

`conditional_go` is acceptable for continued Slice 1 design only when every functional check passes and the only blocker is the pinned FastMCP 4 prerelease status. `no_go` requires reopening the relevant ADR before business implementation.
```

Save this as `docs/compatibility/README.md`.

- [ ] **Step 4: Run the local App preview and capture visual evidence**

Run the preview server:

```bash
uv run fastmcp dev apps src/noa/server.py
```

In a second terminal, capture the page:

```bash
./.agent-md/bin/playwright-capture.sh http://localhost:8080 .agent/visual/slice-0-app.png
```

Expected: a non-empty screenshot showing the NoA compatibility App preview. If the helper is unavailable, use the configured browser screenshot tool against `http://localhost:8080` and preserve the same artifact path.

- [ ] **Step 5: Write structured visual evidence**

```markdown
# Slice 0 MCP App Visual Evidence

- Changed files: `src/noa/server.py`, `src/noa/compat/app/index.html`
- Route or URL: `http://localhost:8080`
- Viewport: `1440x900`
- Artifact: `.agent/visual/slice-0-app.png`
- Observed result: The page renders the `NoA Compatibility` heading and the compatibility probe card without loading external scripts, styles, images, fonts, or network resources.
```

Save as `.agent/visual/slice-0-app.md` after confirming the screenshot is non-empty and current.

- [ ] **Step 6: Execute the real VS Code Stable procedure**

Run:

```bash
code --version
```

Then follow `docs/compatibility/vscode-stable-procedure.md` exactly. Do not substitute MCP Inspector, FastMCP Client, or the browser preview for the VS Code host check.

Expected: all 12 steps complete. If GUI access or model authorization is unavailable, record the check as `blocked`; the final report must be `no_go` until real host evidence exists.

- [ ] **Step 7: Append host evidence to the generated report**

Add a `vs-code-stable` check to `docs/compatibility/2026-08-21-slice-0.md` with:

- exact `code --version` output;
- `status` of `pass`, `fail`, or `blocked`;
- whether Sampling authorization appeared;
- whether `Show Sampling Requests` contained the NoA request;
- whether the MCP App rendered;
- `.agent/visual/slice-0-app.png` artifact path.

If the status is not `pass`, change the report decision to `no_go`.

- [ ] **Step 8: Run final documentation checks**

Run:

```bash
test -s .agent/visual/slice-0-app.png
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
git diff --check
```

Expected: every command exits 0.

---

### Task 12: Final Slice 0 verification and decision handling

**Files:**
- Modify: `memory/plan.md`
- Modify: `memory/progress.md`
- Modify: `memory/verify.md`
- Modify if No-Go: the ADR or ADRs named by the failed check

- [ ] **Step 1: Run the deterministic verification suite**

Run:

```bash
uv sync --python 3.11 --all-groups --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv build
uv run noa-compat
```

Expected:

- Formatting, lint, typecheck, tests, and build PASS.
- `noa-compat` emits a complete report.
- Exit 0 only for `go` or `conditional_go`.

- [ ] **Step 2: Inspect the report rather than guessing the decision**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

path = Path('.noa/compatibility/compatibility.json')
data = json.loads(path.read_text(encoding='utf-8'))
print(data['decision'])
for check in data['checks']:
    print(check['name'], check['status'], check['summary'])
PY
```

Expected: output lists every check and its structured status.

- [ ] **Step 3: Apply the exact decision rule**

- If every functional and VS Code check passes and FastMCP is prerelease: keep `conditional_go`; allow Slice 1 specification work, but keep release blocked on a stable FastMCP 4 pin.
- If every check passes and FastMCP is stable: mark `go`.
- If modern Sampling fails: reopen ADR 0001, ADR 0009, and ADR 0012.
- If legacy Sampling fails: reopen ADR 0009 and ADR 0012.
- If LadybugDB fails: reopen ADR 0005 and ADR 0012.
- If MCP App fails: reopen ADR 0010; Tools-only work may continue, but App is removed from the first release until re-approved.
- If VS Code Stable is blocked or fails: mark `no_go`; do not begin Slice 1 implementation.

- [ ] **Step 4: Update project memory with observed facts**

Update `memory/progress.md` with checked items for:

```markdown
- [x] 完成 Slice 0 compatibility spike
- [x] 验证 FastMCP 4 / MCP SDK v2 精确 pins
- [x] 验证 modern MRTR Sampling
- [x] 验证 legacy sampling/createMessage
- [x] 验证 LadybugDB 事务与持久化
- [x] 验证 MCP App 打包与 VS Code Stable
```

Only mark an item checked when its corresponding report check is `pass`. Use unchecked entries for `warn`, `fail`, or `blocked` states.

Update `memory/plan.md` with the actual gate decision and next allowed slice. Update `memory/verify.md` with the exact commands and any environmental limits observed.

- [ ] **Step 5: Perform an independent review**

Invoke `superpowers:requesting-code-review` or a fresh review agent with this scope:

```text
Review only Slice 0. Verify that the report decision follows structured evidence; both Sampling eras are genuinely exercised; the App has no external network dependency; LadybugDB and checkpoint tests use real persistence; and no Slice 1–11 business behavior was added.
```

Expected: no unresolved correctness finding. Apply verified fixes and rerun Step 1 if findings exist.

- [ ] **Step 6: Final working-tree check**

Run:

```bash
git status --short
git diff --check
```

Expected: all intended source, test, config, docs, and memory changes are visible; generated ignored artifacts are absent from Git status; no commit or push occurs without explicit user authorization.

---

## Plan Self-Review

### Spec coverage

- Exact FastMCP/MCP/Ladybug/Python pins: Tasks 1 and 3.
- Real stdio server: Task 4.
- MCP App packaged and network-free: Tasks 5, 10, and 11.
- LadybugDB install, transaction, persistence, read-only reopen: Task 6.
- SQLite checkpoint close/reopen: Task 7.
- Modern MRTR and legacy Sampling: Task 8.
- Invalid output and cancellation: Task 8.
- Machine and human evidence: Task 9.
- Clean-wheel execution: Task 10.
- VS Code Stable authorization, Sampling log, and App render: Task 11.
- Structured Go/Conditional-Go/No-Go decision and ADR reopening: Task 12.

### Intentional limitation

This plan does not pretend the FastMCP 4 prerelease is production-ready. It verifies whether the architecture can continue to Slice 1 and records prerelease status as an explicit release condition.

### Type and API consistency

- Public check type is always `CheckResult`.
- Final aggregate is always `CompatibilityReport`.
- FastMCP server object is always `noa.server:mcp`.
- App URI is always `ui://noa/compatibility.html`.
- Sampling tool is always `sampling_compatibility`.
- CLI is always `noa-compat`.

## Primary References

- [FastMCP 4 upgrade guide](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3)
- [FastMCP custom HTML Apps](https://gofastmcp.com/apps/low-level)
- [MCP Python SDK v2 dependencies and Sample resolver](https://py.sdk.modelcontextprotocol.io/v2/handlers/dependencies)
- [MCP Python SDK v2 multi-round-trip requests](https://py.sdk.modelcontextprotocol.io/v2/handlers/multi-round-trip/)
- [VS Code MCP developer guide](https://code.visualstudio.com/api/extension-guides/ai/mcp)
- [VS Code MCP configuration reference](https://github.com/microsoft/vscode-docs/blob/main/docs/agents/reference/mcp-configuration.md)
- [LadybugDB Python package](https://pypi.org/project/ladybug/)
- [LadybugDB Python API](https://docs.ladybugdb.com/client-apis/python)
- [LadybugDB connections and concurrency](https://docs.ladybugdb.com/concurrency)
