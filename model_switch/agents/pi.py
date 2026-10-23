from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..compat import link_or_copy
from ..core import (
    DEFAULT_CONTEXT_WINDOW,
    anthropic_base_url,
    openai_base_url,
)
from ..storage import (
    PI_AGENT_HOME,
    PI_MODELS,
    PI_SETTINGS,
    atomic_write,
    load_models,
    read_json,
    write_json,
)
from .base import AgentAdapter, LaunchPlan

# pi 的 models.json 以 provider 为最小配置单位，一个 provider 只能有一套 api/baseUrl，
# 因此这里按模型声明的 supported_apis 挑一个可用接口，再在模型级别覆盖 api/baseUrl/compat。
# 顺序即优先级：优先走 OpenAI Responses，不支持时回退到 chat completions，
# 最后才是 Anthropic Messages。
API_CHOICES = (
    ("responses", "openai-responses"),
    ("chat", "openai-completions"),
    ("claude_native", "anthropic-messages"),
)

OPENAI_COMPAT = {
    "sendSessionAffinityHeaders": True,
    "sessionAffinityFormat": "openai",
}
ANTHROPIC_COMPAT = {
    "sendSessionAffinityHeaders": True,
}

DEFAULT_REASONING_LEVELS = ["low", "medium", "high"]
PI_THINKING_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
DEFAULT_MAX_TOKENS = 32768

PROVIDER_ID = "model-switch"
API_KEY_ENV = "MODEL_SWITCH_API_KEY"

# 这些是 pi 原生 agent 目录里的用户资源，链接过来后 ms pi 仍能用到既有扩展、
# 技能、主题与登录凭据；settings.json / models.json / sessions 保持隔离。
PI_LINKED_ENTRIES = (
    "extensions",
    "skills",
    "prompts",
    "themes",
    "tools",
    "bin",
    "npm",
    "git",
    "auth.json",
)

PI_DEFAULT_ENV = {
    # 与 Claude/Codex 一致：只保留必要流量，不做版本检查与遥测上报。
    "PI_SKIP_VERSION_CHECK": "1",
    "PI_TELEMETRY": "0",
}


def _ensure_pi_links() -> None:
    """Link the user's native pi resources into the isolated agent directory."""
    native_dir = Path.home() / ".pi" / "agent"
    for name in PI_LINKED_ENTRIES:
        source = native_dir / name
        target = PI_AGENT_HOME / name
        if not source.exists() or target.exists():
            continue
        link_or_copy(source, target)


def _pick_api(model: dict[str, Any]) -> tuple[str, str] | None:
    supported = model.get("supported_apis") or []
    # 名称含 claude 的模型优先走 Anthropic Messages。
    if "claude" in str(model.get("id", "")).lower():
        for agent_api, pi_api in API_CHOICES:
            if agent_api == "claude_native" and agent_api in supported:
                return agent_api, pi_api
    for agent_api, pi_api in API_CHOICES:
        if agent_api in supported:
            return agent_api, pi_api
    return None


def _reasoning_levels(model: dict[str, Any]) -> list[str]:
    levels = model.get("reasoning_levels")
    if levels is None:
        return list(DEFAULT_REASONING_LEVELS)
    return [str(level) for level in levels]


def _thinking_level_map(levels: list[str]) -> dict[str, str | None]:
    """把 pi 的 thinking level 映射到上游取值，未声明的档位标记为不支持。

    `off` 故意不写进映射表：留空表示沿用 pi 默认行为，用户随时可以关闭思考。
    """
    return {level: (level if level in levels else None) for level in PI_THINKING_LEVELS}


def _default_thinking_level(levels: list[str]) -> str:
    if "high" in levels:
        return "high"
    return levels[-1] if levels else "high"


class PiAdapter(AgentAdapter):
    id = "pi"
    label = "Pi Agent"
    required_api = "responses"
    endpoint = "/v1/responses"
    default_binary = "pi"
    binary_env = "MODEL_SWITCH_PI_BIN"
    instructions_dir = PI_AGENT_HOME
    instructions_name = "AGENTS.md"
    supported_apis = tuple(agent_api for agent_api, _ in API_CHOICES)

    def supports(self, model: dict[str, Any]) -> bool:
        return _pick_api(model) is not None

    def unsupported_message(self, model: dict[str, Any]) -> str:
        return (
            f"⚠ 跳过 {self.label}：{model.get('id', '')} 不支持 "
            + "/".join(self.supported_apis)
            + " 中的任何接口，已保持当前模型"
        )

    def _runtime_env(self, config: dict[str, Any]) -> dict[str, str]:
        return {
            "PI_CODING_AGENT_DIR": str(PI_AGENT_HOME),
            API_KEY_ENV: config.get("api_key", ""),
            **PI_DEFAULT_ENV,
        }

    def _models_payload(self, config: dict[str, Any], model_ids: list[str]) -> dict[str, Any]:
        by_id = {m.get("id"): m for m in load_models()}
        openai_base = openai_base_url(config)
        anthropic_base = anthropic_base_url(config)

        models: list[dict[str, Any]] = []
        for model_id in model_ids:
            model = by_id.get(model_id)
            if not model:
                continue
            picked = _pick_api(model)
            if not picked:
                continue
            agent_api, pi_api = picked
            context_window = int(model.get("context_window") or DEFAULT_CONTEXT_WINDOW)
            entry: dict[str, Any] = {
                "id": model.get("id", model_id),
                "name": model.get("display_name") or model_id,
                "api": pi_api,
                "baseUrl": anthropic_base if agent_api == "claude_native" else openai_base,
                # 单一 provider 下无法按 api 写不同的 provider 级 compat，
                # 因此在模型级固定声明：OpenAI 两个接口带 openai 格式，
                # Anthropic Messages 只开启会话亲和、不写 format。
                "compat": (
                    ANTHROPIC_COMPAT if agent_api == "claude_native" else OPENAI_COMPAT
                ),
                "input": (
                    ["text", "image"]
                    if model.get("capabilities", {}).get("vision", True)
                    else ["text"]
                ),
                "contextWindow": context_window,
                "maxTokens": min(int(model.get("max_tokens") or DEFAULT_MAX_TOKENS), context_window),
            }
            levels = _reasoning_levels(model)
            if levels:
                entry["reasoning"] = True
                entry["thinkingLevelMap"] = _thinking_level_map(levels)
            models.append(entry)

        return {
            "providers": {
                PROVIDER_ID: {
                    "name": PROVIDER_ID,
                    "baseUrl": openai_base,
                    "apiKey": f"${API_KEY_ENV}",
                    "authHeader": True,
                    "api": "openai-responses",
                    "models": models,
                }
            }
        }

    def switch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        model_ids: list[str],
    ) -> None:
        PI_AGENT_HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ensure_pi_links()
        write_json(PI_MODELS, self._models_payload(config, model_ids))

        settings = read_json(PI_SETTINGS, {}) or {}
        settings["defaultProvider"] = PROVIDER_ID
        settings["defaultModel"] = model["id"]
        levels = _reasoning_levels(model)
        if levels:
            settings["defaultThinkingLevel"] = _default_thinking_level(levels)
        else:
            settings.pop("defaultThinkingLevel", None)
        # 与其它 agent 对齐：不再为项目级信任弹窗，直接信任项目本地资源。
        settings.setdefault("defaultProjectTrust", "always")
        atomic_write(PI_SETTINGS, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

    def launch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        passthrough_args: list[str],
    ) -> LaunchPlan:
        binary = os.environ.get(self.binary_env, self.default_binary)
        return LaunchPlan(
            binary=binary,
            args=self._normalize_resume(passthrough_args),
            env=self._runtime_env(config),
        )

    @staticmethod
    def _normalize_resume(args: list[str]) -> list[str]:
        """把 `resume [session-id]` 改写成 pi 的 `--resume` / `--session`。"""
        if args and args[0] == "resume":
            if len(args) > 1:
                return ["--session", args[1], *args[2:]]
            return ["--resume"]
        return args
