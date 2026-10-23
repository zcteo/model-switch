from __future__ import annotations

import json
import os
from typing import Any

try:
    import tomllib  # Python >= 3.11
except ImportError:  # Python < 3.11
    try:
        import tomli as tomllib  # 第三方 backport
    except ImportError:
        tomllib = None

from ..core import openai_base_url, default_reasoning_level
from ..storage import (
    CODEX_CATALOG,
    CODEX_CONFIG,
    CODEX_HOME,
    atomic_write,
    load_models,
    write_json,
)
from .base import AgentAdapter, LaunchPlan

# Codex TUI 状态栏默认展示的条目：模型+思考档位、当前目录、上下文剩余百分比、
# 上下文窗口总大小（tokens）。最后一项让用户能直接看到模型的总上下文容量。
DEFAULT_STATUS_LINE = [
    "model-with-reasoning",
    "current-dir",
    "context-remaining",
    "context-window-size",
]
# 旧版本 ms 生成的默认值，重新生成时自动升级；用户自定义的其它组合保持不动。
LEGACY_STATUS_LINE = ["model-with-reasoning", "current-dir", "context-remaining"]


def _toml_key(key: str) -> str:
    if key and all(c.isalnum() or c in "-_" for c in key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return '""'
    if isinstance(value, (str, int, float)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"不支持的 TOML 标量类型：{type(value)}")


def _toml_table(table: dict[str, Any], prefix: str = "") -> list[str]:
    lines: list[str] = []
    for key, value in table.items():
        if isinstance(value, dict):
            continue
        if isinstance(value, list) and any(isinstance(v, dict) for v in value):
            continue
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")

    for key, value in table.items():
        if isinstance(value, dict):
            name = f"{prefix}.{_toml_key(key)}" if prefix else _toml_key(key)
            lines.append("")
            lines.append(f"[{name}]")
            lines.extend(_toml_table(value, name))
        elif isinstance(value, list) and any(isinstance(v, dict) for v in value):
            name = f"{prefix}.{_toml_key(key)}" if prefix else _toml_key(key)
            for item in value:
                lines.append("")
                lines.append(f"[[{name}]]")
                lines.extend(_toml_table(item, name))
    return lines


def dump_toml(data: dict[str, Any]) -> str:
    return "\n".join(_toml_table(data)).rstrip() + "\n"


def _write_catalog(model_ids: list[str]) -> None:
    by_id = {m.get("id"): m for m in load_models()}
    models = []
    for model_id in model_ids:
        m = by_id[model_id]
        levels = m.get("reasoning_levels") or ["low", "medium", "high"]
        vision = m.get("capabilities", {}).get("vision", True)
        models.append(
            {
                "slug": m.get("id", model_id),
                "display_name": m.get("display_name") or model_id,
                "description": "model-switch local catalog",
                "default_reasoning_level": default_reasoning_level(m),
                "supported_reasoning_levels": [{"effort": x, "description": f"{x} effort"} for x in levels],
                "shell_type": "shell_command",
                "visibility": "list",
                "supported_in_api": True,
                "priority": 0,
                "base_instructions": "",
                "supports_reasoning_summaries": True,
                "default_reasoning_summary": "auto",
                "support_verbosity": False,
                "truncation_policy": {"mode": "tokens", "limit": 10000},
                "supports_parallel_tool_calls": m.get("capabilities", {}).get("tool_call", True),
                "supports_image_detail_original": vision,
                "context_window": m.get("context_window", 1_000_000),
                "max_context_window": m.get("context_window", 1_000_000),
                "effective_context_window_percent": 95,
                "experimental_supported_tools": [],
                "prefer_websockets": False,
            }
        )
    write_json(CODEX_CATALOG, {"models": models})


class CodexAdapter(AgentAdapter):
    id = "codex"
    label = "Codex"
    required_api = "responses"
    endpoint = "/v1/responses"
    default_binary = "codex"
    binary_env = "MODEL_SWITCH_CODEX_BIN"
    instructions_dir = CODEX_HOME
    instructions_name = "AGENTS.md"

    def _runtime_env(self, config: dict[str, Any]) -> dict[str, str]:
        return {
            "CODEX_HOME": str(CODEX_HOME),
            "MODEL_SWITCH_API_KEY": config.get("api_key", ""),
        }

    def switch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        model_ids: list[str],
    ) -> None:
        _write_catalog(model_ids)
        base = openai_base_url(config)
        data: dict[str, Any] = {}
        if CODEX_CONFIG.exists():
            if tomllib is None:
                raise RuntimeError("解析 config.toml 需要 tomllib（Python>=3.11）或 tomli；请安装 tomli")
            with CODEX_CONFIG.open("rb") as f:
                data = tomllib.load(f)
        CODEX_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)

        data["model"] = model["id"]
        data["model_provider"] = "model-switch"
        data["model_catalog_json"] = str(CODEX_CATALOG)
        data["model_context_window"] = int(model.get("context_window", 1_000_000))
        data["openai_base_url"] = base
        data.setdefault("sandbox_mode", "danger-full-access")
        data.setdefault("approval_policy", "never")
        tui = dict(data.get("tui") or {})
        status_line = tui.get("status_line")
        if status_line is None or status_line == LEGACY_STATUS_LINE:
            tui["status_line"] = list(DEFAULT_STATUS_LINE)
        data["tui"] = tui
        providers = data.get("model_providers") or {}
        providers["model-switch"] = {
            "name": "model-switch",
            "base_url": base,
            "env_key": "MODEL_SWITCH_API_KEY",
            "wire_api": "responses",
        }
        data["model_providers"] = providers
        atomic_write(CODEX_CONFIG, dump_toml(data))

    def launch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        passthrough_args: list[str],
    ) -> LaunchPlan:
        binary = os.environ.get(self.binary_env, self.default_binary)
        # 显式锁死模型：Codex 会把 cwd 所在目录的配置当项目级配置加载，
        # 例如在 home 目录启动时 ~/.codex/config.toml 里的 model 会覆盖
        # ms 写入的 CODEX_HOME/config.toml。用 --model 命令行参数兜底，
        # 换启动目录也不会失效；不用 -c 是因为配置覆盖会强制 embedded
        # 模式，从而弹出 “Running without the shared background server” 警告。
        args = ["--model", model["id"], *passthrough_args]
        return LaunchPlan(binary=binary, args=args, env=self._runtime_env(config))
