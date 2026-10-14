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
from .agents import (
    all_agent_ids,
    get_agent,
    list_agents,
    refresh_agent_config,
    switch_model,
    sync_agent_instructions,
)
from .core import backend_url, fetch_models, pick_model
from .storage import ensure_home, load_config, load_models, save_config, save_models


# argparse.BooleanOptionalAction 是 Python 3.9+ 才有的；在 3.8 上退化成一个
# 手动处理 `--flag/--no-flag` 的 action，保证旧版本也能解析同样的参数。
if hasattr(argparse, "BooleanOptionalAction"):
    _BoolOpt = argparse.BooleanOptionalAction
else:

    class _BoolOpt(argparse.Action):
        def __init__(self, option_strings, dest, default=None, help=None, **kwargs):
            # 模仿官方 BooleanOptionalAction：为每个选项补一个 --no- 前缀的变体，
            # 例如 `--enabled` -> `--enabled` / `--no-enabled`。
            if any(s.startswith("--no-") for s in option_strings):
                raise ValueError("BooleanOptionalAction 不接受额外的 --no- 前缀选项")
            negated = [s.replace("--", "--no-", 1) for s in option_strings if s.startswith("--")]
            option_strings = [*option_strings, *negated]
            super().__init__(option_strings, dest, default=default, nargs=0, help=help, **kwargs)

        def __call__(self, parser, namespace, values, option_string=None):
            setattr(namespace, self.dest, not option_string.startswith("--no-"))


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
    try:
        total, remote_count, stale_count = fetch_models(args.timeout, force=args.force, prune=args.prune)
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"⚠ 获取模型列表失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"已保存 {total} 个模型（后端返回 {remote_count} 个）")
    if stale_count:
        print(f"⚠ {stale_count} 个模型后端已不再返回，已保留并标记为 enabled: false（用 --prune 删除）")
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
        if not model.get("enabled", True):
            status = "stale" if model.get("stale") else "off"
        else:
            status = "on"
        rows.append(
            (
                f"#{index}",
                str(model.get("id", "")),
                str(model.get("context_window", "-")),
                "text,image" if model.get("capabilities", {}).get("vision", True) else "text",
                ",".join(model.get("supported_apis", [])),
                status,
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
        # An explicit choice is no longer the automatic backend-gone marker.
        model.pop("stale", None)
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
    if args.target is not None:
        _use_target(args.target)
        return
    _refresh_models(args.timeout)
    from .ui import interactive_config
    interactive_config()


def _use_target(target: str) -> None:
    """Switch every agent to a model given by `ms models` index or by name.

    Deliberately skips the model refresh: the index refers to what the user
    just read in `ms models`, and re-fetching could shift it. Lookups are
    resolved fully before any agent config is written, so an unknown target
    leaves everything untouched.
    """
    models = load_models()
    if not models:
        raise SystemExit("本地没有模型；请先运行：ms fetch")

    if target.isdigit():
        index = int(target)
        if not 1 <= index <= len(models):
            raise SystemExit(f"序号超出范围：{index}（当前共 {len(models)} 个模型）")
        model = models[index - 1]
    else:
        model = next((m for m in models if m.get("id") == target), None)
        if model is None:
            raise SystemExit(f"未找到模型：{target}；用 ms models 查看本地模型列表")

    result = switch_model(model.get("id", ""), set(all_agent_ids()))
    for agent_id, model_id in result["applied"].items():
        print(f"✔ {agent_id} -> {model_id}")


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
    p.add_argument("-p", "--prune", action="store_true", help="删除后端已不再返回的模型")
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
    st.add_argument("--vision", action=_BoolOpt)
    st.add_argument("--reasoning", nargs="+")
    st.add_argument("--apis", nargs="+", choices=["chat", "responses", "claude_native"])
    st.add_argument("--enabled", action=_BoolOpt)
    st.add_argument("--tool-call", action=_BoolOpt)
    st.add_argument("--streaming", action=_BoolOpt)
    st.set_defaults(func=cmd_models_set)

    p = subs.add_parser("use", help="交互式选择并切换模型")
    p.add_argument(
        "target",
        nargs="?",
        help="直接把所有 agent 切到 ms models 的第 N 个模型，或指定模型 id",
    )
    p.add_argument("--timeout", type=float, default=15.0)
    p.set_defaults(func=cmd_use)

    agent_ids = _register_agent_parsers(subs)
    # agent 子命令在 help 里合并成一条，新增 agent 只会加长这一条，不会撑爆菜单。
    _merge_agent_help(subs, agent_ids)
    subs.add_parser("status", help="查看当前状态").set_defaults(func=lambda _args: cmd_status())
    _collapse_usage_commands(subs)
    return parser


def _register_agent_parsers(subs: argparse._SubParsersAction) -> list[str]:
    """注册每个 agent 的启动子命令，但不在上层 help 里单独列出。"""
    agent_ids: list[str] = []
    for adapter in list_agents():
        # 不传 help：argparse 会据此生成独立的 help 条目，这里只要 description。
        parser = subs.add_parser(
            adapter.id,
            description=f"注入隔离配置并启动 {adapter.label}",
        )
        parser.add_argument("args", nargs=argparse.REMAINDER)
        parser.set_defaults(func=cmd_launch)
        agent_ids.append(adapter.id)
    return agent_ids


def _merge_agent_help(subs: argparse._SubParsersAction, agent_ids: list[str]) -> None:
    """把所有 agent 子命令折叠成一条 help 项，例如 `claude|codex|pi`。

    argparse 没有子命令分组，只能往 `_choices_actions` 里塞一条伪 action；
    该属性缺失时保持静默（此时 agent 命令不显示在 help 里，但依然可用）。
    """
    if not agent_ids:
        return
    pseudo_action = getattr(argparse._SubParsersAction, "_ChoicesPseudoAction", None)
    if pseudo_action is None:
        return
    label = "|".join(agent_ids)
    subs._choices_actions.append(
        pseudo_action(label, [], f"注入隔离配置并启动 agent（{' / '.join(agent_ids)}）")
    )


def _collapse_usage_commands(subs: argparse._SubParsersAction) -> None:
    """让 usage 行也用折叠后的名字，避免 agent 变多时 usage 越写越长。"""
    actions = getattr(subs, "_choices_actions", None)
    labels = [getattr(action, "metavar", None) for action in actions or []]
    labels = [label for label in labels if label]
    if labels:
        subs.metavar = "{" + ",".join(labels) + "}"


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
    # 共享指令的注入与模型无关：每次运行都对齐一次，避免依赖用户先跑过 ms use。
    sync_agent_instructions()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n✔ 已取消", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
