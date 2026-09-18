"""Workspace layout, path safety, single-writer lock, network policy,
and resource budgets (product contract sections 7.1, 8.1, 8.2)."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict


class WorkspaceError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, str]) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def _error(code: str, message: str, **context: str) -> WorkspaceError:
    return WorkspaceError(code=code, message=message, context=context)


RUNTIME_DIRNAME = ".noa"


@dataclass(frozen=True)
class ResourceBudgets:
    max_document_bytes: int = 64 * 1024 * 1024
    max_text_bytes: int = 16 * 1024 * 1024
    download_timeout_seconds: float = 60.0
    max_redirects: int = 5
    max_object_bytes: int = 128 * 1024 * 1024


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed_schemes: tuple[str, ...] = ("https",)
    allowed_hosts: tuple[str, ...] = ()
    denied_hosts: tuple[str, ...] = (
        "169.254.169.254",
        "metadata.google.internal",
    )
    deny_private_addresses: bool = True

    def with_explicit_host_allowance(self, host: str) -> NetworkPolicy:
        """Test/dev escape hatch: allow one literal host even if private."""
        return (
            NetworkPolicy(
                allowed_schemes=self.allowed_schemes,
                allowed_hosts=self.allowed_hosts,
                denied_hosts=self.denied_hosts,
                deny_private_addresses=False,
            )
            if host in self.allowed_hosts
            else self
        )

    def assert_url_allowed(self, url: str) -> None:
        try:
            parts = urlsplit(url)
        except ValueError as error:
            raise _error("invalid_url", f"URL {url!r} cannot be parsed") from error
        if parts.scheme.lower() not in self.allowed_schemes:
            raise _error(
                "url_scheme_denied",
                f"URL scheme {parts.scheme!r} is not allowed",
                scheme=parts.scheme,
            )
        host = (parts.hostname or "").lower()
        if not host:
            raise _error("invalid_url", f"URL {url!r} has no hostname")
        if host in self.denied_hosts:
            raise _error("url_host_denied", f"Host {host!r} is denied", host=host)
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise _error(
                "url_host_not_allowed",
                f"Host {host!r} is not in the configured allowlist",
                host=host,
            )
        if self.deny_private_addresses:
            try:
                address = ip_address(host)
            except ValueError:
                address = None
            if address is not None and (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            ):
                raise _error(
                    "url_host_denied",
                    f"Address {host!r} resolves to a private or reserved range",
                    host=host,
                )


class WorkspaceLock:
    """Advisory single-writer lock backed by flock on `.noa/writer.lock`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    @property
    def is_acquired(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            raise _error("workspace_lock_held", "This process already holds the writer lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            raise _error(
                "workspace_locked",
                "Another writer holds the workspace lock",
                path=str(self._path),
            ) from error
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime = self.root / RUNTIME_DIRNAME
        self.graph_dir = self.runtime / "graph"
        self.control_dir = self.runtime / "control"
        self.objects_dir = self.runtime / "objects"
        self.runs_dir = self.runtime / "runs"
        self.journal_path = self.runtime / "journal.sqlite3"
        self.lock = WorkspaceLock(self.runtime / "writer.lock")
        self.budgets = ResourceBudgets()
        self.network_policy = NetworkPolicy()

    @classmethod
    def open(cls, root: Path, *, create: bool = True) -> Workspace:
        workspace = cls(root)
        if not workspace.root.is_dir():
            if not create:
                raise _error(
                    "workspace_missing",
                    f"Workspace root {workspace.root!s} does not exist",
                    root=str(workspace.root),
                )
            workspace.root.mkdir(parents=True, exist_ok=True)
        for directory in (
            workspace.runtime,
            workspace.graph_dir,
            workspace.control_dir,
            workspace.objects_dir,
            workspace.runs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        resolved_runtime = workspace.runtime.resolve()
        if workspace.root not in resolved_runtime.parents:
            raise _error(
                "workspace_root_escape",
                f".noa/ resolves outside the workspace root: {resolved_runtime!s}",
                root=str(workspace.root),
            )
        return workspace

    def resolve_member(self, candidate: Path, *, must_exist: bool = False) -> Path:
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise _error(
                "path_escapes_workspace",
                f"Path {candidate!s} resolves outside the workspace root",
                candidate=str(candidate),
                resolved=str(resolved),
            )
        if must_exist and not resolved.exists():
            raise _error(
                "path_not_found",
                f"Path {candidate!s} does not exist inside the workspace",
                candidate=str(candidate),
            )
        if resolved.is_symlink() or any(part.is_symlink() for part in resolved.parents):
            probe: Path | None = resolved
            while probe is not None and probe != self.root:
                if probe.is_symlink():
                    target = probe.resolve()
                    if target != self.root and self.root not in target.parents:
                        raise _error(
                            "symlink_escapes_workspace",
                            f"Path {candidate!s} traverses a symlink leaving the workspace",
                            candidate=str(candidate),
                            symlink=str(probe),
                        )
                probe = probe.parent
        return resolved

    def close(self) -> None:
        self.lock.release()


__all__ = [
    "NetworkPolicy",
    "ResourceBudgets",
    "Workspace",
    "WorkspaceError",
    "WorkspaceLock",
]
