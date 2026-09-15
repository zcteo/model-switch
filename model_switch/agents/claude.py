from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

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
        try:
            target.symlink_to(source, target_is_directory=source.is_dir())
        except OSError:
            pass


def _claude_statusline() -> dict[str, Any]:
    script = Path(__file__).parent.parent / "statusline.py"
    return {
        "type": "command",
        "command": f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}",
        "refreshInterval": 1,
        "padding": 0,
    }


class ClaudeAdapter(AgentAdapter):
    id = "claude"
    label = "Claude Code / cc"
    required_api = "claude_native"
    endpoint = "/v1/messages"
    default_binary = "claude"
    binary_env = "MODEL_SWITCH_CLAUDE_BIN"

    def _runtime_env(self, config: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
        env = {
            "CLAUDE_CONFIG_DIR": str(CLAUDE_HOME),
            "ANTHROPIC_BASE_URL": anthropic_base_url(config),
            "ANTHROPIC_AUTH_TOKEN": config.get("api_key", ""),
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(model.get("context_window", 1_000_000)),
        }
        env.update(CLAUDE_DEFAULT_ENV)
        if os.geteuid() != 0:
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
        settings.setdefault("skipDangerousModePermissionPrompt", os.geteuid() != 0)
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
            os.geteuid() != 0
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
