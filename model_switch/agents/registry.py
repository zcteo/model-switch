from __future__ import annotations

from typing import Any

from ..storage import load_models
from .base import AgentAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter

_AGENTS: dict[str, AgentAdapter] = {
    adapter.id: adapter for adapter in (ClaudeAdapter(), CodexAdapter())
}


def list_agents() -> list[AgentAdapter]:
    return list(_AGENTS.values())


def get_agent(agent_id: str) -> AgentAdapter:
    try:
        return _AGENTS[agent_id]
    except KeyError:
        raise SystemExit(f"未知的 agent：{agent_id}") from None


def all_agent_ids() -> list[str]:
    return [adapter.id for adapter in _AGENTS.values()]


def agent_choices() -> list[tuple[str, str]]:
    return [("all", "All agents")] + [(adapter.id, adapter.label) for adapter in _AGENTS.values()]


def compatible_models(agent_id: str, models: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    adapter = get_agent(agent_id)
    if models is None:
        models = load_models()
    compatible = [m for m in models if m.get("enabled", True) and adapter.supports(m)]
    return sorted(compatible, key=lambda m: str(m.get("id", "")).lower())
