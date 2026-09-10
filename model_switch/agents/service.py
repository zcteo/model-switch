from __future__ import annotations

from typing import Any

from ..core import pick_model
from ..storage import find_model, load_config, load_models, save_config
from .registry import get_agent, list_agents


def switch_model(value: str, agent_ids: set[str]) -> dict[str, Any]:
    if not agent_ids:
        raise SystemExit("没有选择 agent")

    config = load_config()
    if not config.get("base_url") or not config.get("api_key"):
        raise SystemExit("后端未配置；请运行：ms config --base-url https://... --api-key sk-...")

    model = pick_model(value)
    enabled = [m for m in load_models() if m.get("enabled", True)]

    applied: dict[str, str] = {}
    for adapter in list_agents():
        if adapter.id not in agent_ids:
            continue
        if not adapter.supports(model):
            print(adapter.unsupported_message(model))
            continue
        model_ids = [m.get("id", "") for m in enabled if adapter.supports(m)]
        adapter.switch(config, model, model_ids)
        applied[adapter.id] = model["id"]

    if not applied:
        raise SystemExit("没有写入任何 agent 配置")

    selected = config.setdefault("agents", {})
    for agent_id, applied_model in applied.items():
        selected[agent_id] = applied_model
    save_config(config)

    return {"model": model["id"], "applied": applied}


def selected_model_id(agent_id: str) -> str:
    config = load_config()
    model_id = config.get("agents", {}).get(agent_id)
    if not model_id:
        agent = get_agent(agent_id)
        raise SystemExit(f"{agent.label} 尚未选择模型；请运行：ms use")
    return model_id


def refresh_agent_config(agent_id: str) -> dict[str, Any]:
    """Refresh isolated config for the currently selected agent model."""
    config = load_config()
    if not config.get("base_url") or not config.get("api_key"):
        raise SystemExit("后端未配置；请运行：ms config --base-url https://... --api-key sk-...")

    adapter = get_agent(agent_id)
    model_id = selected_model_id(agent_id)
    model = find_model(model_id)
    if not model:
        raise SystemExit(f"本地模型不存在：{model_id}；请重新运行 ms fetch")
    if not adapter.supports(model):
        raise SystemExit(f"当前模型 {model_id} 不支持 {adapter.endpoint}")

    enabled = [m for m in load_models() if m.get("enabled", True)]
    adapter.switch(config, model, [m.get("id", "") for m in enabled if adapter.supports(m)])
    return model
