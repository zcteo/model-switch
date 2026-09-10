#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


def format_k(value: int) -> str:
    number = round(value / 1000, 1)
    if number.is_integer():
        return f"{int(number)}k"
    return f"{number:.1f}k"


def basename(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return Path(value.replace("\\", "/")).name


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return

    if not isinstance(payload, dict):
        return

    context = payload.get("context_window") or {}
    if not isinstance(context, dict):
        context = {}

    input_tokens = int(context.get("total_input_tokens") or 0)
    output_tokens = int(context.get("total_output_tokens") or 0)
    total_tokens = int(context.get("context_window_size") or 0)
    used = format_k(input_tokens + output_tokens)
    total = format_k(total_tokens) if total_tokens > 0 else "?k"
    tokens = f"{used}/{total}"

    workspace = payload.get("workspace") or {}
    if not isinstance(workspace, dict):
        workspace = {}
    project = workspace.get("project_dir") or workspace.get("current_dir") or payload.get("cwd") or ""
    project = basename(project)
    parts = [tokens, f" | {project}"] if project else [tokens]
    print("".join(parts))


if __name__ == "__main__":
    main()
