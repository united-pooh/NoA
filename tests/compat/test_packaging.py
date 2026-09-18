from __future__ import annotations

import configparser
import hashlib
import stat
import subprocess
import tarfile
import tomllib
from email.parser import BytesParser
from importlib.resources import files
from pathlib import Path
from zipfile import ZipFile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SDIST_NAME = "noa_mcp-0.1.0a0.tar.gz"
_WHEEL_NAME = "noa_mcp-0.1.0a0-py3-none-any.whl"
_LOCAL_RUNTIME_SENTINELS = (
    ".paw/git-check-ignore-sentinel",
    ".playwright-cli/git-check-ignore-sentinel",
)
_REQUIRED_DEPENDENCIES = {
    "anyio==4.14.2",
    "fastmcp==4.0.0b3",
    "ladybug==0.19.1",
    "mcp==2.0.0",
    "packaging==26.3",
    "pydantic==2.13.4",
    "uuid6==2025.0.1",
}
_EXPECTED_SDIST_FILES = {
    ".gitignore",
    "PKG-INFO",
    "README.md",
    "SKILL.md",
    "agents/openai.yaml",
    "docs/package/README.md",
    "pyproject.toml",
    "src/noa/__init__.py",
    "src/noa/__main__.py",
    "src/noa/compat/__init__.py",
    "src/noa/compat/app/__init__.py",
    "src/noa/compat/app/index.html",
    "src/noa/compat/app_validation.py",
    "src/noa/compat/checkpoint.py",
    "src/noa/compat/cli.py",
    "src/noa/compat/ladybug_probe.py",
    "src/noa/compat/models.py",
    "src/noa/compat/probe_worker.py",
    "src/noa/compat/runner.py",
    "src/noa/compat/runtime.py",
    "src/noa/compat/sampling.py",
    "src/noa/domain/__init__.py",
    "src/noa/domain/entities.py",
    "src/noa/domain/errors.py",
    "src/noa/domain/ids.py",
    "src/noa/domain/identifiers.py",
    "src/noa/domain/provenance.py",
    "src/noa/acquisition.py",
    "src/noa/adapters.py",
    "src/noa/review.py",
    "src/noa/runtime.py",
    "src/noa/server.py",
    "src/noa/trajectory.py",
    "src/noa/trajectory_guard.py",
    "src/noa/trajectory_store.py",
    "src/noa/views.py",
    "src/noa/storage.py",
    "src/noa/workspace.py",
    "tests/compat/test_app.py",
    "tests/compat/test_checkpoint.py",
    "tests/compat/test_ladybug_probe.py",
    "tests/compat/test_models.py",
    "tests/compat/test_packaging.py",
    "tests/compat/test_runner.py",
    "tests/compat/test_runtime.py",
    "tests/compat/test_sampling.py",
    "tests/compat/test_knowledge_tools.py",
    "tests/compat/test_server.py",
    "tests/compat/test_trajectory_guard_tools.py",
    "tests/compat/test_trajectory_acceptance.py",
    "tests/compat/test_trajectory_tools.py",
    "tests/domain/test_entities.py",
    "tests/domain/test_errors.py",
    "tests/domain/test_identifiers.py",
    "tests/domain/test_ids.py",
    "tests/test_package_metadata.py",
    "tests/test_trajectory.py",
    "tests/test_trajectory_guard.py",
    "tests/test_trajectory_runtime.py",
    "tests/test_trajectory_store.py",
    "uv.lock",
}
_EXPECTED_WHEEL_FILES = {
    "noa/__init__.py",
    "noa/__main__.py",
    "noa/compat/__init__.py",
    "noa/compat/app/__init__.py",
    "noa/compat/app/index.html",
    "noa/compat/app_validation.py",
    "noa/compat/checkpoint.py",
    "noa/compat/cli.py",
    "noa/compat/ladybug_probe.py",
    "noa/compat/models.py",
    "noa/compat/probe_worker.py",
    "noa/compat/runner.py",
    "noa/compat/runtime.py",
    "noa/compat/sampling.py",
    "noa/domain/__init__.py",
    "noa/domain/entities.py",
    "noa/domain/errors.py",
    "noa/domain/ids.py",
    "noa/domain/identifiers.py",
    "noa/domain/provenance.py",
    "noa/acquisition.py",
    "noa/adapters.py",
    "noa/review.py",
    "noa/runtime.py",
    "noa/server.py",
    "noa/trajectory.py",
    "noa/trajectory_guard.py",
    "noa/trajectory_store.py",
    "noa/views.py",
    "noa/storage.py",
    "noa/workspace.py",
    "noa_mcp-0.1.0a0.dist-info/METADATA",
    "noa_mcp-0.1.0a0.dist-info/RECORD",
    "noa_mcp-0.1.0a0.dist-info/WHEEL",
    "noa_mcp-0.1.0a0.dist-info/entry_points.txt",
}


def _build_distributions(output: Path) -> tuple[Path, Path]:
    subprocess.run(
        ["uv", "build", "--out-dir", str(output)],
        cwd=_PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return output / _SDIST_NAME, output / _WHEEL_NAME


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_local_runtime_state_is_ignored(project_root: Path) -> None:
    for sentinel in _LOCAL_RUNTIME_SENTINELS:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", sentinel],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"{sentinel} is not ignored by Git in {project_root}: {result.stderr.strip()}"
        )


def test_mcp_app_html_is_available_as_package_data() -> None:
    resource = files("noa.compat.app").joinpath("index.html")
    assert resource.is_file()
    assert "NoA Compatibility" in resource.read_text(encoding="utf-8")


def test_repository_gitignore_excludes_local_runtime_state() -> None:
    _assert_local_runtime_state_is_ignored(_PROJECT_ROOT)


def test_repository_gitignore_check_detects_late_negation(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    (repository / ".gitignore").write_text(
        ".paw/\n.playwright-cli/\n!.paw/\n",
        encoding="utf-8",
    )
    for sentinel in _LOCAL_RUNTIME_SENTINELS:
        path = repository / sentinel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    with pytest.raises(
        AssertionError,
        match=r"\.paw/git-check-ignore-sentinel is not ignored by Git",
    ):
        _assert_local_runtime_state_is_ignored(repository)


def test_sdist_uses_an_explicit_publishable_file_allowlist() -> None:
    with Path("pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)

    project = pyproject["project"]
    assert project["classifiers"] == ["Private :: Do Not Upload"]
    assert project["readme"]["file"] == "docs/package/README.md"
    build = pyproject["tool"]["hatch"]["build"]
    assert build["ignore-vcs"] is True
    sdist = build["targets"]["sdist"]
    assert sdist["ignore-vcs"] is True
    assert set(sdist["include"]) == {
        "/.gitignore",
        "/README.md",
        "/SKILL.md",
        "/agents/openai.yaml",
        "/docs/package/README.md",
        "/pyproject.toml",
        "/src",
        "/tests",
        "/uv.lock",
    }


def test_built_distributions_are_reproducible_and_publishable(tmp_path: Path) -> None:
    first_sdist, first_wheel = _build_distributions(tmp_path / "first")
    second_sdist, second_wheel = _build_distributions(tmp_path / "second")

    assert _sha256(first_sdist) == _sha256(second_sdist)
    assert _sha256(first_wheel) == _sha256(second_wheel)

    prefix = "noa_mcp-0.1.0a0/"
    with tarfile.open(first_sdist, "r:gz") as archive:
        members = archive.getmembers()
        assert all(member.isfile() or member.isdir() for member in members)
        sdist_files = {member.name.removeprefix(prefix) for member in members if member.isfile()}
        gitignore_member = archive.extractfile(f"{prefix}.gitignore")
        assert gitignore_member is not None
        packaged_gitignore = gitignore_member.read().decode()
    assert sdist_files == _EXPECTED_SDIST_FILES
    assert not any(path.startswith((".paw/", ".playwright-cli/")) for path in sdist_files)
    assert {".paw/", ".playwright-cli/"} <= set(packaged_gitignore.splitlines())

    with ZipFile(first_wheel) as archive:
        wheel_files = set(archive.namelist())
        assert wheel_files == _EXPECTED_WHEEL_FILES
        assert not any(path.startswith((".paw/", ".playwright-cli/")) for path in wheel_files)
        for item in archive.infolist():
            mode = item.external_attr >> 16
            assert not item.is_dir()
            assert stat.S_IFMT(mode) in {0, stat.S_IFREG}

        entry_points = configparser.ConfigParser()
        entry_points.read_string(
            archive.read("noa_mcp-0.1.0a0.dist-info/entry_points.txt").decode()
        )
        assert dict(entry_points["console_scripts"]) == {
            "noa": "noa.server:run",
            "noa-compat": "noa.compat.cli:main",
        }

        metadata = BytesParser().parsebytes(archive.read("noa_mcp-0.1.0a0.dist-info/METADATA"))
        assert set(metadata.get_all("Requires-Dist") or []) == _REQUIRED_DEPENDENCIES
        assert metadata.get_all("Classifier") == ["Private :: Do Not Upload"]
        description = metadata.get_payload()
        assert "NoA is a pre-alpha Python MCP server" in description
        assert "not approved for public distribution" in description
        assert "~/.codex/skills/noa" not in description
        assert "Codex research log skill" not in description
