from __future__ import annotations

import hashlib
from pathlib import Path

# importlib.resources.files（以及 pathlib 风格 API）是 Python 3.9+ 才有的；
# 3.8 退回到等价的 read_text，保证包内 AGENTS.md 在旧版本也能读取。
try:  # Python >= 3.9
    from importlib.resources import files as _resources_files

    def _read_bundled() -> str:
        return (
            _resources_files(PACKAGE)
            .joinpath(INSTRUCTIONS_RESOURCE)
            .read_text(encoding="utf-8")
        )

except ImportError:  # Python 3.8
    from importlib import resources as _resources

    def _read_bundled() -> str:
        return _resources.read_text(PACKAGE, INSTRUCTIONS_RESOURCE)

from ..storage import atomic_write
from .registry import list_agents

# 共享指令的唯一真源：仓库根的 AGENTS.md，随包分发（根目录保留一个指向它的软链）。
INSTRUCTIONS_RESOURCE = "AGENTS.md"
PACKAGE = "model_switch"


def source_text() -> str | None:
    """读取包内共享指令；包被裁剪掉该文件时返回 None。"""
    try:
        return _read_bundled()
    except (FileNotFoundError, IsADirectoryError, ModuleNotFoundError, OSError, TypeError):
        return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str | None:
    try:
        return _digest(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def sync_agent_instructions() -> list[Path]:
    """把共享指令写进每个 agent 的隔离目录，返回本次实际写入的文件。

    隔离目录归 model-switch 所有，因此同名文件（含指向别处的软链）一律覆写，
    内容已一致的普通文件则跳过，保证重复运行不会反复改动 mtime。
    """
    text = source_text()
    if text is None:
        return []

    digest = _digest(text)
    written: list[Path] = []
    for adapter in list_agents():
        target = adapter.instructions_path()
        if target is None:
            continue
        if not target.is_symlink() and _file_digest(target) == digest:
            continue
        atomic_write(target, text)
        written.append(target)
    return written
