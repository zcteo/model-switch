from __future__ import annotations

import locale
import os
import select
import sys
import termios
import unicodedata
from typing import Any

from .agents import (
    agent_choices,
    all_agent_ids,
    compatible_models,
    get_agent,
    switch_model,
)
from .storage import load_config, load_models


def _mask(value: str | None) -> str:
    if not value:
        return "-"
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _model_by_id(model_id: str | None) -> dict[str, Any] | None:
    if not model_id:
        return None
    return next((m for m in load_models() if m.get("id") == model_id), None)


def _context_label(model: dict[str, Any] | None) -> str:
    if not model:
        return "-"
    value = model.get("context_window")
    return f"{value:,}" if isinstance(value, int) else str(value or "-")


def print_status_table() -> None:
    config = load_config()
    agents = config.get("agents", {})
    print("┌  Configure model")
    print("│")
    print("◇  当前配置")
    print("│")
    print("│  Agent              Current model        Context")
    print("│  -----------------  ------------------  ---------")
    for agent in get_agent_choices():
        model_id = agents.get(agent[0], "-")
        model = _model_by_id(model_id)
        print(f"│  {agent[1]:<18}  {model_id:<20}  {_context_label(model)}")
    print("")


def _model_rows(models: list[dict[str, Any]]) -> list[str]:
    rows = []
    for model in models:
        input = "text,image" if model.get("capabilities", {}).get("vision", True) else "text"
        rows.append(f"{model['id']:<38} ctx={_context_label(model):<10} input={input}")
    return rows


def _terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _display_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        for char in text
    )


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    result = ""
    result_width = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        if result_width + char_width > width - 1:
            return result + "…"
        result += char
        result_width += char_width
    return result


def _read_key() -> str:
    """Read one key, including ANSI arrow-key sequences."""
    data = os.read(sys.stdin.fileno(), 1)
    if data != b"\x1b":
        return data.decode(errors="ignore")

    readable, _, _ = select.select([sys.stdin.fileno()], [], [], 0.05)
    if not readable:
        return "\x1b"

    sequence = os.read(sys.stdin.fileno(), 32)
    if sequence in (b"[A", b"OA"):
        return "\x1b[A"
    if sequence in (b"[B", b"OB"):
        return "\x1b[B"
    return ""


def _render_menu(
    title: str,
    rows: list[str],
    index: int,
    selected: set[int] | None,
    footer: str = "",
    previous_lines: int = 0,
) -> int:
    if previous_lines:
        sys.stdout.write(f"\x1b[{previous_lines}A\r\x1b[0J")
    width = _terminal_width()
    if selected is not None:
        print("Select agent (\u2191/\u2193 pick one, enter to confirm)")
    else:
        print("Select model (\u2191/\u2193 pick one, enter to confirm)")
    print()
    for row_index, row in enumerate(rows):
        if selected is None:
            marker = "  "
        else:
            marker = "◼ " if row_index in selected else "◻ "

        if row_index == index:
            sys.stdout.write("\x1b[7m")
        sys.stdout.write(marker + _truncate(row, width))
        sys.stdout.write("\x1b[0m\n")

    printed_lines = 2 + len(rows)
    if footer:
        printed_lines += 2
        print()
        print(footer)
    sys.stdout.flush()
    return printed_lines


def _enter_cbreak(fd: int) -> None:
    attr = termios.tcgetattr(fd)
    attr[3] &= ~(termios.ECHO | termios.ICANON)
    termios.tcsetattr(fd, termios.TCSADRAIN, attr)


def select_one(title: str, rows: list[str], footer: str = "") -> int | None:
    if not rows:
        return None
    if not sys.stdin.isatty():
        raise SystemExit("需要交互式终端；请直接在 TTY 中运行")

    fd = sys.stdin.fileno()
    old_termios = termios.tcgetattr(fd)
    index = 0
    rendered_lines = 0
    try:
        _enter_cbreak(fd)
        sys.stdout.write("\x1b[?25l")
        while True:
            rendered_lines = _render_menu(title, rows, index, None, footer, rendered_lines)
            key = _read_key()
            if key == "\x1b[A":
                index = (index - 1) % len(rows)
            elif key == "\x1b[B":
                index = (index + 1) % len(rows)
            elif key in ("\r", "\n"):
                return index
            elif key in ("\x1b", "q"):
                return None
    finally:
        sys.stdout.write("\x1b[?1003l\x1b[?25h\n")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_termios)


def select_many(title: str, rows: list[str], selected_indexes: set[int], footer: str = "") -> set[int] | None:
    if not rows:
        return None
    if not sys.stdin.isatty():
        raise SystemExit("需要交互式终端；请直接在 TTY 中运行")

    fd = sys.stdin.fileno()
    old_termios = termios.tcgetattr(fd)
    index = 0
    rendered_lines = 0
    selected = set(range(len(rows)))
    try:
        _enter_cbreak(fd)
        sys.stdout.write("\x1b[?25l")
        while True:
            rendered_lines = _render_menu(title, rows, index, selected, footer, rendered_lines)
            key = _read_key()
            if key == "\x1b[A":
                index = (index - 1) % len(rows)
            elif key == "\x1b[B":
                index = (index + 1) % len(rows)
            elif key in ("\r", "\n"):
                return selected
            elif key in ("\x1b", "q"):
                return None

            if index == 0:
                selected = set(range(len(rows)))
            else:
                selected = {index}
    finally:
        sys.stdout.write("\x1b[?25h\n")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_termios)


def get_agent_choices() -> list[tuple[str, str]]:
    return agent_choices()


def interactive_config() -> None:
    locale.setlocale(locale.LC_ALL, "")
    if not load_models():
        raise SystemExit("本地没有模型；请先运行：ms fetch")
    config = load_config()
    if not config.get("base_url") or not config.get("api_key"):
        raise SystemExit("后端未配置；请运行：ms config --base-url https://... --api-key sk-...")

    print_status_table()
    choices = get_agent_choices()
    labels = [label for _, label in choices]
    configured = config.get("agents", {})
    defaults = {i for i, (agent_id, _) in enumerate(choices) if agent_id in configured}
    selected_rows = select_many("Select agent", labels, defaults)
    if not selected_rows:
        print("已取消")
        return

    agents = [choices[i][0] for i in selected_rows]
    if 0 in agents:
        agents = all_agent_ids()

    if len(agents) > 1:
        models = [m for m in load_models() if m.get("enabled", True)]
        models.sort(key=lambda m: str(m.get("id", "")).lower())
        rows = _model_rows(models)
        index = select_one("Select model for All agents", rows)
        if index is None:
            print("已取消")
            return
        result = switch_model(models[index]["id"], set(agents))
        for agent_id, model_id in result["applied"].items():
            print(f"✔ {agent_id} -> {model_id}")
    else:
        agent_id = agents[0]
        models = compatible_models(agent_id)
        if not models:
            print(f"{agent_id} 没有可用模型")
            return
        rows = _model_rows(models)
        label = get_agent(agent_id).label
        index = select_one(f"Select model for {label}", rows)
        if index is None:
            print("已取消")
            return
        result = switch_model(models[index]["id"], {agent_id})
        print(f"✔ {agent_id} -> {result['applied'][agent_id]}")

    print("✓ 完成")
