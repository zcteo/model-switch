from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from ..compat import agent_shell_command, is_root, link_or_copy
from ..core import anthropic_base_url, default_reasoning_level
from ..storage import (
    CLAUDE_HOME,
    CLAUDE_JSON,
    CLAUDE_SETTINGS,
    atomic_write,
    load_models,
    read_json,
)
from .base import AgentAdapter, LaunchPlan

CLAUDE_DEFAULT_ENV = {
    # 0 = 不发送归属头（Claude Code 把 0/false/no/off 视为 opt-out）。
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_HARBOR_KITE": "1",
}

CLAUDE_SUBCOMMANDS = {
    "agents",
    "config",
    "mcp",
    "migrate-installer",
    "setup-token",
    "doctor",
    "install",
    "update",
    "plugin",
    "plugins",
}


def _copy_claude_base_if_needed(path: Path, native_path: Path) -> dict[str, Any]:
    data = read_json(path, None)
    if data is not None:
        return data
    return read_json(native_path, {}) or {}


def _ensure_claude_links() -> None:
    CLAUDE_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    native_dir = Path.home() / ".claude"
    for name in ("projects", "plugins", "todos", "shell-snapshots", "statsig"):
        source = native_dir / name
        target = CLAUDE_HOME / name
        if not source.exists() or target.exists():
            continue
        link_or_copy(source, target)


def _claude_statusline() -> dict[str, Any]:
    script = Path(__file__).parent.parent / "statusline.py"
    return {
        "type": "command",
        # Windows 上 Claude Code 用 Git Bash 执行，命令里用正斜杠路径。
        "command": agent_shell_command([sys.executable, str(script)]),
        "refreshInterval": 1,
        "padding": 0,
    }


def _trust_current_project(claude_json: dict[str, Any], allow: list[str]) -> None:
    """把当前工作目录标记为已信任。

    model-switch 是自动化环境（--dangerously-skip-permissions +
    skipDangerousModePermissionPrompt），不会弹信任对话框。若不加信任，
    Claude Code 会把 settings.json 里的 permissions.allow 视为「工作区未信任」
    而忽略并打印警告。
    """
    root = os.path.realpath(os.getcwd())
    project = claude_json.setdefault("projects", {}).setdefault(root, {})
    project["hasTrustDialogAccepted"] = True
    project.setdefault("trustDialogAcceptedAt", int(time.time() * 1000))
    allowed = set(project.get("allowedTools") or [])
    allowed.update(a for a in allow if isinstance(a, str))
    project["allowedTools"] = sorted(allowed)


class ClaudeAdapter(AgentAdapter):
    id = "claude"
    label = "Claude Code / cc"
    required_api = "claude_native"
    endpoint = "/v1/messages"
    default_binary = "claude"
    binary_env = "MODEL_SWITCH_CLAUDE_BIN"
    # Claude Code 只认 CLAUDE.md，不读 AGENTS.md。
    instructions_dir = CLAUDE_HOME
    instructions_name = "CLAUDE.md"

    def _runtime_env(self, config: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
        env = {
            "CLAUDE_CONFIG_DIR": str(CLAUDE_HOME),
            "ANTHROPIC_BASE_URL": anthropic_base_url(config),
            "ANTHROPIC_AUTH_TOKEN": config.get("api_key", ""),
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(model.get("context_window", 1_000_000)),
        }
        # 显式固定所选模型：ANTHROPIC_MODEL 的优先级高于 settings.json 的
        # model 字段，若不覆盖，shell 里继承下来的 ANTHROPIC_MODEL（例如
        # 用户手动 export 的其它模型）会让 Claude Code 忽略 ms 的选择。
        env["ANTHROPIC_MODEL"] = model["id"]
        env.update(CLAUDE_DEFAULT_ENV)
        if not is_root():
            env.setdefault("CLAUDE_CODE_SANDBOXED", "1")
        return env

    def switch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        model_ids: list[str],
    ) -> None:
        _ensure_claude_links()
        native_settings = Path.home() / ".claude" / "settings.json"
        native_json = Path.home() / ".claude.json"
        settings = _copy_claude_base_if_needed(CLAUDE_SETTINGS, native_settings)

        env = dict(settings.get("env") or {})
        env.update(self._runtime_env(config, model))
        settings["env"] = env
        settings["model"] = model["id"]
        settings["availableModels"] = model_ids
        settings.setdefault("skipDangerousModePermissionPrompt", not is_root())
        settings.setdefault("showThinkingSummaries", True)
        settings.setdefault("alwaysThinkingEnabled", True)
        settings.setdefault("crossSessionInbound", "accept")
        settings["effortLevel"] = default_reasoning_level(model)
        settings["statusLine"] = _claude_statusline()
        atomic_write(CLAUDE_SETTINGS, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

        by_id = {m.get("id"): m for m in load_models()}
        claude_json = _copy_claude_base_if_needed(CLAUDE_JSON, native_json)
        claude_json["additionalModelOptionsCache"] = [
            {
                "value": model_id,
                "label": model_id,
                "description": (
                    f"[model-switch] ctx={by_id.get(model_id, {}).get('context_window', '-')} "
                    f"input={'text,image' if by_id.get(model_id, {}).get('capabilities', {}).get('vision', True) else 'text'}"
                ),
            }
            for model_id in model_ids
        ]
        _trust_current_project(
            claude_json,
            list((settings.get("permissions") or {}).get("allow") or []),
        )
        atomic_write(CLAUDE_JSON, json.dumps(claude_json, ensure_ascii=False, indent=2) + "\n")

    def launch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        passthrough_args: list[str],
    ) -> LaunchPlan:
        binary = os.environ.get(self.binary_env, self.default_binary)
        passthrough_args = self._normalize_resume(passthrough_args)
        args = ["--settings", str(CLAUDE_SETTINGS), *passthrough_args]
        if (
            not is_root()
            and not self._is_managed_subcommand(passthrough_args)
            and "--dangerously-skip-permissions" not in passthrough_args
        ):
            args.insert(2, "--dangerously-skip-permissions")
        return LaunchPlan(binary=binary, args=args, env=self._runtime_env(config, model))

    @staticmethod
    def _normalize_resume(args: list[str]) -> list[str]:
        """Rewrite the `resume` subcommand into the `--resume` flag."""
        if args and args[0] == "resume":
            return ["--resume", *args[1:]]
        return args

    @staticmethod
    def _is_managed_subcommand(args: list[str]) -> bool:
        return bool(args) and not args[0].startswith("-") and args[0] in CLAUDE_SUBCOMMANDS
