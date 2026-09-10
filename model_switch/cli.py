from __future__ import annotations

import argparse
import json
import os
import sys
import shlex
import shutil
import subprocess
import tempfile
import unicodedata

from . import __version__
from .agents import get_agent, list_agents, refresh_agent_config
from .core import backend_url, fetch_models, pick_model
from .storage import ensure_home, load_config, load_models, save_config, save_models


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _display_width(value: str) -> int:
    """Terminal display width, treating East Asian characters as two cells."""
    return sum(2 if unicodedata.east_asian_width(char) in ("F", "W") else 1 for char in value)


def _pad(value: str, width: int) -> str:
    return value + " " * max(0, width - _display_width(value))


def cmd_config(args: argparse.Namespace) -> None:
    config = load_config()
    if args.base_url is None and args.api_key is None:
        print(json.dumps({**config, "api_key": mask(config.get("api_key"))}, ensure_ascii=False, indent=2))
        return
    if args.base_url is not None:
        config["base_url"] = args.base_url.rstrip("/")
    if args.api_key is not None:
        config["api_key"] = args.api_key
    backend_url(config)
    save_config(config)
    print(json.dumps({**config, "api_key": mask(config.get("api_key"))}, ensure_ascii=False, indent=2))


def cmd_fetch(args: argparse.Namespace) -> None:
    total, remote_count = fetch_models(args.timeout, force=args.force)
    print(f"已保存 {total} 个模型（后端返回 {remote_count} 个）")
    if not args.no_list:
        cmd_models_list()


def cmd_models_list() -> None:
    models = load_models()
    if not models:
        print("本地没有模型；请先运行：ms fetch")
        return

    headers = ("#", "Model", "Context", "Input", "APIs", "Status")
    rows: list[tuple[str, ...]] = []
    for index, model in enumerate(models, 1):
        enabled = "on" if model.get("enabled", True) else "off"
        rows.append(
            (
                f"#{index}",
                str(model.get("id", "")),
                str(model.get("context_window", "-")),
                "text,image" if model.get("capabilities", {}).get("vision", True) else "text",
                ",".join(model.get("supported_apis", [])),
                enabled,
            )
        )

    widths = [
        max(_display_width(headers[column]), *(_display_width(row[column]) for row in rows))
        for column in range(len(headers))
    ]

    for row in (headers, *rows):
        print("  ".join(_pad(value, width) for value, width in zip(row, widths)))


def cmd_models_show(args: argparse.Namespace) -> None:
    print(json.dumps(pick_model(args.model), ensure_ascii=False, indent=2))


def cmd_models_edit(args: argparse.Namespace) -> None:
    models = load_models()
    model = next((m for m in models if m.get("id") == args.model), None)
    if not model:
        raise SystemExit(f"未找到模型：{args.model}")

    before = json.dumps(model, ensure_ascii=False, sort_keys=True)
    editor = os.environ.get("EDITOR", "vi").strip() or "vi"
    fd, path = tempfile.mkstemp(prefix="model-switch-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(model, f, ensure_ascii=False, indent=2)
            f.write("\n")

        subprocess.run([*shlex.split(editor), path], check=True)
        with open(path, "r", encoding="utf-8") as f:
            edited = json.load(f)
        if not isinstance(edited, dict):
            raise SystemExit("编辑结果必须是 JSON 对象")
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    after = json.dumps(edited, ensure_ascii=False, sort_keys=True)
    if after != before:
        models[models.index(model)] = edited
        save_models(models)
        print(f"已保存：{edited.get('id', args.model)}")
    else:
        print("未修改")


def cmd_models_set(args: argparse.Namespace) -> None:
    models = load_models()
    model = next((m for m in models if m.get("id") == args.model), None)
    if not model:
        raise SystemExit(f"未找到模型：{args.model}")

    if args.display_name is not None:
        model["display_name"] = args.display_name
    if args.context_window is not None:
        model["context_window"] = args.context_window
    if args.vision is not None:
        model.setdefault("capabilities", {})["vision"] = args.vision
    if args.reasoning is not None:
        model["reasoning_levels"] = args.reasoning
    if args.apis is not None:
        model["supported_apis"] = args.apis
    if args.enabled is not None:
        model["enabled"] = args.enabled
    if args.tool_call is not None:
        model.setdefault("capabilities", {})["tool_call"] = args.tool_call
    if args.streaming is not None:
        model.setdefault("capabilities", {})["streaming"] = args.streaming
    save_models(models)
    print(f"已保存：{args.model}")


def _refresh_models(timeout: float) -> None:
    try:
        fetch_models(timeout)
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"⚠ 刷新模型列表失败：{exc}", file=sys.stderr)
        raise SystemExit(1)


def cmd_use(args: argparse.Namespace) -> None:
    _refresh_models(args.timeout)
    from .ui import interactive_config
    interactive_config()


def cmd_launch(args: argparse.Namespace) -> None:
    adapter = get_agent(args.command)
    model = refresh_agent_config(adapter.id)
    config = load_config()
    passthrough_args = args.args[1:] if args.args and args.args[0] == "--" else args.args

    plan = adapter.launch(config, model, passthrough_args)
    if shutil.which(plan.binary) is None:
        raise SystemExit(f"未找到可执行文件：{plan.binary}")

    env = os.environ.copy()
    env.update(plan.env)
    print(f"✔ {adapter.id} model: {model['id']} (ctx={model.get('context_window', '-')})")
    raise SystemExit(subprocess.call([plan.binary, *plan.args], env=env))


def cmd_status() -> None:
    config = load_config()
    models = load_models()
    model_by_id = {model.get("id"): model for model in models}
    selected = config.get("agents", {})
    agents_status = {}
    for adapter in list_agents():
        model = model_by_id.get(selected.get(adapter.id))
        agents_status[adapter.id] = {
            "model": selected.get(adapter.id),
            "context_window": model.get("context_window") if model else None,
        }

    status = {
        "backend": config.get("base_url"),
        "api_key": mask(config.get("api_key")),
        "local_models": len(models),
        "agents": agents_status,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ms", description="从聚合后端获取模型，并一键切换/启动已接入的 Agent")
    parser.add_argument("--version", action="store_true")
    subs = parser.add_subparsers(dest="command")

    p = subs.add_parser("config", help="配置唯一聚合后端")
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.set_defaults(func=cmd_config)

    p = subs.add_parser("fetch", help="从后端获取模型列表")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("-f", "--force", action="store_true", help="不保留本地任何模型信息")
    p.add_argument("--no-list", action="store_true")
    p.set_defaults(func=cmd_fetch)

    p = subs.add_parser("models", help="查看本地模型")
    p.add_argument("--list", action="store_true")
    p.set_defaults(func=lambda _args: cmd_models_list())

    p = subs.add_parser("model", help="model 子命令")
    msub = p.add_subparsers(dest="model_cmd", required=True)
    msub.add_parser("list").set_defaults(func=lambda _args: cmd_models_list())
    edit = msub.add_parser("edit", help="编辑单个模型数据")
    edit.add_argument("model")
    edit.set_defaults(func=cmd_models_edit)
    show = msub.add_parser("show")
    show.add_argument("model")
    show.set_defaults(func=cmd_models_show)
    st = msub.add_parser("set")
    st.add_argument("model")
    st.add_argument("--display-name")
    st.add_argument("--context-window", type=int)
    st.add_argument("--vision", action=argparse.BooleanOptionalAction)
    st.add_argument("--reasoning", nargs="+")
    st.add_argument("--apis", nargs="+", choices=["chat", "responses", "claude_native"])
    st.add_argument("--enabled", action=argparse.BooleanOptionalAction)
    st.add_argument("--tool-call", action=argparse.BooleanOptionalAction)
    st.add_argument("--streaming", action=argparse.BooleanOptionalAction)
    st.set_defaults(func=cmd_models_set)

    p = subs.add_parser("use", help="交互式选择并切换模型")
    p.add_argument("--timeout", type=float, default=15.0)
    p.set_defaults(func=cmd_use)

    for agent in list_agents():
        p = subs.add_parser(agent.id, help=f"注入并启动 {agent.label}")
        p.add_argument("args", nargs=argparse.REMAINDER)
        p.set_defaults(func=cmd_launch)

    subs.add_parser("status", help="查看当前状态").set_defaults(func=lambda _args: cmd_status())
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        print(__version__)
        return
    if not getattr(args, "command", None):
        parser.print_help()
        return
    ensure_home()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n✔ 已取消", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
