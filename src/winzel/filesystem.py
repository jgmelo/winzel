"""Disk and file access for checks (injectable through the Context)."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

GB = 1024**3


@dataclass(frozen=True)
class DiskUsage:
    total: int
    free: int

    @property
    def free_pct(self) -> float:
        return 100.0 * self.free / self.total if self.total else 0.0


@dataclass(frozen=True)
class ClearResult:
    removed: int
    failed: int


@dataclass(frozen=True)
class DirSize:
    bytes: int
    files: int
    unreadable: int = 0


class FileSystem(Protocol):
    def disk_usage(self, path: str) -> DiskUsage:
        """Raises FileNotFoundError when the drive does not exist."""
        ...

    def file_size(self, path: str) -> int:
        """Raises FileNotFoundError when the file does not exist."""
        ...

    def dir_size(self, path: str) -> DirSize:
        """Total size of the files below `path`. Raises FileNotFoundError if missing."""
        ...

    def expand(self, path: str) -> str:
        """Expands environment variables such as %TEMP%."""
        ...

    def temp_path(self, name: str) -> str: ...

    def read_text(self, path: str) -> str: ...

    def remove(self, path: str) -> None: ...

    def exists(self, path: str) -> bool: ...

    def list_dirs(self, path: str) -> list[str]:
        """Names of the direct subfolders. Raises FileNotFoundError if missing."""
        ...

    def clear_dir(self, path: str) -> ClearResult:
        """Delete everything inside `path` (not the folder itself); files in use are skipped."""
        ...


class RealFileSystem:
    def disk_usage(self, path: str) -> DiskUsage:
        import psutil

        if not os.path.exists(path):
            raise FileNotFoundError(path)
        usage = psutil.disk_usage(path)
        return DiskUsage(total=usage.total, free=usage.free)

    def file_size(self, path: str) -> int:
        return os.stat(path).st_size

    def dir_size(self, path: str) -> DirSize:
        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        total = files = unreadable = 0
        pending = [path]
        while pending:
            current = pending.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                unreadable += 1
                continue
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                        files += 1
                except OSError:
                    unreadable += 1
        return DirSize(bytes=total, files=files, unreadable=unreadable)

    def expand(self, path: str) -> str:
        return os.path.expandvars(path)

    def temp_path(self, name: str) -> str:
        return str(Path(tempfile.gettempdir()) / name)

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")

    def remove(self, path: str) -> None:
        Path(path).unlink(missing_ok=True)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def list_dirs(self, path: str) -> list[str]:
        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        return sorted(e.name for e in os.scandir(path) if e.is_dir(follow_symlinks=False))

    def clear_dir(self, path: str) -> ClearResult:
        import shutil

        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        removed = failed = 0
        for entry in os.scandir(path):
            try:
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path)
                else:
                    os.unlink(entry.path)
                removed += 1
            except OSError:
                failed += 1
        return ClearResult(removed=removed, failed=failed)


def gb(value: float) -> float:
    return value / GB


def format_number(value: float, decimals: int = 1) -> str:
    """Portuguese decimal comma: 5.25 -> '5,3'."""
    return f"{value:.{decimals}f}".replace(".", ",")


def format_gb(value_bytes: float) -> str:
    giga = gb(value_bytes)
    return f"{format_number(giga, 0 if giga >= 100 else 1)} GB"
