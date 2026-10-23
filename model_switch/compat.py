"""跨平台差异的集中封装。

项目原本只跑在 Linux 上，这里把 Windows 与 POSIX 的分叉收在一处：
权限判断、命令行拆分/拼接、原生资源链接、以及 npm 生成的 .cmd 启动。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# `ms model edit` 在没有设置 EDITOR 时使用的编辑器。
DEFAULT_EDITOR = "notepad" if IS_WINDOWS else "vi"


def is_root() -> bool:
    """是否以 root 身份运行；Windows 没有 root 概念，恒为 False。"""
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid is not None and geteuid() == 0)


def agent_shell_command(parts: list[str]) -> str:
    """拼出交给 agent shell 执行的命令行字符串。

    Windows 上 Claude Code 通过 Git Bash 执行 statusLine 等命令，未加引号的
    反斜杠路径会被 bash 当作转义符吃掉（`C:/Users` 变成 `C:Users`），因此
    Windows 分支统一转成正斜杠并加双引号；这种写法在 Git Bash、cmd 和
    PowerShell 下都能执行。POSIX 分支用 shlex.quote。
    """
    if IS_WINDOWS:
        return " ".join(f'"{Path(part).as_posix()}"' for part in parts)
    return " ".join(shlex.quote(part) for part in parts)


def split_command(value: str) -> list[str]:
    """按当前平台规则拆分用户提供的命令行（例如 $EDITOR）。"""
    if not IS_WINDOWS:
        return shlex.split(value)
    # posix=False 会保留引号，这里再去掉成对的首尾引号，
    # 让 `"C:\Program Files\...\code.exe" -w` 这类写法可用。
    parts = shlex.split(value, posix=False)
    return [
        part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'"
        else part
        for part in parts
    ]


def link_or_copy(source: Path, target: Path) -> bool:
    """把原生资源接入隔离目录，成功返回 True。

    优先软链。Windows 普通用户未开启开发者模式时无法创建软链：
    目录退回 junction（无需特权），文件退回复制一份。目录连 junction
    也创建失败时放弃链接，避免把体积很大的 npm/ 等目录整份复制。
    """
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
        return True
    except OSError:
        pass

    if IS_WINDOWS and source.is_dir():
        try:
            import _winapi

            _winapi.CreateJunction(str(source), str(target))
            return True
        except (ImportError, OSError):
            return False

    try:
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        return True
    except OSError:
        return False


def enable_windows_ansi() -> None:
    """打开旧版 conhost 的 VT 处理，让光标/反显等 ANSI 序列生效。"""
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # 拿不到控制台句柄时保持原样即可
        pass


def configure_stdio() -> None:
    """Windows 控制台重定向到文件/管道时用 locale 编码，✔、⚠ 等符号会编码失败。

    保留原编码，只把错误处理改成替换，避免 CLI 因为输出字符直接崩掉。
    """
    if not IS_WINDOWS:
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def replace_file(tmp: str, target: Path) -> None:
    """原子替换目标文件。

    Windows 上目标文件可能正被其它进程（例如正在运行的 agent）打开，
    此时 os.replace 会抛 PermissionError；短暂重试几次通常就能成功。
    """
    attempts = 5 if IS_WINDOWS else 1
    for attempt in range(attempts):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1)


def launch_argv(binary: str, args: list[str]) -> list[str]:
    """构造真正交给 subprocess 的 argv。

    npm 在 Windows 上安装的是 .cmd 批处理包装，CreateProcess 不能直接
    执行，必须经由 cmd.exe；用 `call` 作为第一个词可以避开 cmd 对
    `/c ""...""` 的引号剥离规则。
    """
    if IS_WINDOWS and binary.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/d", "/c", "call", binary, *args]
    return [binary, *args]
