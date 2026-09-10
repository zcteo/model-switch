from __future__ import annotations

import json
import urllib.request
from typing import Any

from .storage import find_model, load_config, load_models, save_models

DEFAULT_CONTEXT_WINDOW = 1_000_000
DEFAULT_SUPPORTED_APIS = ["chat", "responses", "claude_native"]

API_MAP = {
    "openai": "chat",
    "openai-chat": "chat",
    "chat": "chat",
    "openai-response": "responses",
    "openai-responses": "responses",
    "responses": "responses",
    "anthropic": "claude_native",
    "anthropic-messages": "claude_native",
    "claude_native": "claude_native",
}


def backend_url(config: dict[str, Any]) -> str:
    url = str(config.get("base_url", "")).strip().rstrip("/")
    if not url:
        raise SystemExit("后端未配置；请运行：ms config --base-url https://... --api-key sk-...")
    return url


def openai_base_url(config: dict[str, Any]) -> str:
    url = backend_url(config)
    return url if url.endswith("/v1") else f"{url}/v1"


def anthropic_base_url(config: dict[str, Any]) -> str:
    url = backend_url(config)
    return url[:-3] if url.endswith("/v1") else url


def _as_list(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _normalize_apis(raw: Any) -> list[str]:
    result: list[str] = []
    for item in raw or []:
        if isinstance(item, dict):
            item = item.get("id")
        if item in API_MAP:
            result.append(API_MAP[item])
    return list(dict.fromkeys(result))


def inferred_supported_apis(model_id: str) -> list[str]:
    """Infer API compatibility when the aggregator does not publish it."""
    name = model_id.split("/")[-1].strip().lower()
    if name.startswith("gpt"):
        return ["chat", "responses"]
    if name.startswith("claude"):
        return ["claude_native"]
    return list(DEFAULT_SUPPORTED_APIS)


def normalize_model(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Normalize one backend model while preserving fields it did not return."""
    model_id = str(raw.get("id") or raw.get("model") or raw.get("name") or "").strip()
    if not model_id:
        return None

    # The backend list is authoritative, but that only means fields it returns
    # overwrite local values. Fields absent from this response stay local.
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged["id"] = model_id

    if "display_name" in raw:
        merged["display_name"] = raw.get("display_name") or model_id
    else:
        merged.setdefault("display_name", model_id)

    # 上下文长度：优先用上游返回的值，缺失时落到默认值（100 万），
    # 这样 fetch 落盘的模型记录一定会带 context_window 字段。
    if "context_window" in raw:
        merged["context_window"] = int(raw["context_window"])
    else:
        merged.setdefault("context_window", DEFAULT_CONTEXT_WINDOW)

    if "support_apis" in raw:
        merged["supported_apis"] = _normalize_apis(raw["support_apis"])
    elif "openai_api" in raw:
        merged["supported_apis"] = _normalize_apis(raw["openai_api"])
    else:
        merged.setdefault("supported_apis", ["chat"])

    # Input modality is deliberately not persisted as a list. We only derive
    # the functional vision capability from the backend when it reports it.
    capabilities = dict(merged.get("capabilities") or {})
    capabilities.setdefault("tool_call", True)
    capabilities.setdefault("streaming", True)
    capabilities.setdefault("vision", False)
    if "supports_tool_call" in raw:
        capabilities["tool_call"] = bool(raw["supports_tool_call"])
    if "supports_streaming" in raw:
        capabilities["streaming"] = bool(raw["supports_streaming"])
    merged["capabilities"] = capabilities
    return merged


def fetch_models(timeout: float = 15.0, force: bool = False) -> tuple[int, int]:
    config = load_config()
    request = urllib.request.Request(
        f"{openai_base_url(config)}/models",
        headers={
            "Authorization": f"Bearer {config.get('api_key', '')}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    raw_models = payload.get("data", payload.get("models", []))
    if not isinstance(raw_models, list):
        raise ValueError("后端返回的模型列表格式无效")

    old = {} if force else {m.get("id"): m for m in load_models()}
    merged: dict[str, dict[str, Any]] = {}
    for raw in raw_models:
        model = normalize_model(raw, old.get(raw.get("id")))
        if model:
            merged[model["id"]] = model

    models = sorted(merged.values(), key=lambda m: m["id"].lower())
    save_models(models)
    return len(models), len(raw_models)


def pick_model(value: str) -> dict[str, Any]:
    models = load_models()
    if not models:
        raise SystemExit("本地没有模型；请先运行：ms fetch")
    if value.startswith("#"):
        try:
            return models[int(value[1:]) - 1]
        except (ValueError, IndexError):
            raise SystemExit(f"序号无效：{value}") from None
    model = find_model(value)
    if not model:
        raise SystemExit(f"未找到模型：{value}；请先运行：ms fetch")
    return model


def default_reasoning_level(model: dict[str, Any]) -> str:
    levels = model.get("reasoning_levels") or []
    if "high" in levels:
        return "high"
    return str(levels[-1]) if levels else "high"
