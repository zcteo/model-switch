#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import sys


def format_k(value: int) -> str:
    number = round(value / 1000, 1)
    if number.is_integer():
        return f"{int(number)}k"
    return f"{number:.1f}k"


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
    # 把家目录前缀替换成 ~：/home/<user>/foo → ~/foo
    home = os.path.expanduser("~")
    if project == home:
        project = "~"
    elif project.startswith(home + os.sep):
        project = "~" + project[len(home):]

    # 模型：优先用 statusLine JSON 里的 model 字段（新版 Claude Code 传的是
    # dict，取其中的 id）；取不到则回退到 ANTHROPIC_MODEL（ms 启动时注入，
    # 子进程会继承）。
    raw_model = payload.get("model")
    if isinstance(raw_model, dict):
        model = raw_model.get("id") or raw_model.get("display_name") or ""
    else:
        model = raw_model or os.environ.get("ANTHROPIC_MODEL") or ""
    model = str(model)

    parts = []
    if model:
        parts.append(model)
    if project:
        parts.append(project)
    parts.append(tokens)
    print(" · ".join(parts))


if __name__ == "__main__":
    main()
