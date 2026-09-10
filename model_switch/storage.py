from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("MODEL_SWITCH_HOME", Path.home() / ".model-switch"))
CONFIG_FILE = HOME / "config.json"
MODELS_FILE = HOME / "models.json"
CODEX_HOME = HOME / "codex"
CODEX_CATALOG = CODEX_HOME / "models.json"
CODEX_CONFIG = CODEX_HOME / "config.toml"
CLAUDE_HOME = HOME / "claude"
CLAUDE_SETTINGS = CLAUDE_HOME / "settings.json"
CLAUDE_STATUSLINE = CLAUDE_HOME / "statusline.py"
CLAUDE_JSON = CLAUDE_HOME / ".claude.json"


def ensure_home() -> Path:
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    return HOME


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def write_json(path: Path, data: Any) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_config() -> dict[str, Any]:
    return read_json(CONFIG_FILE, {}) or {}


def save_config(config: dict[str, Any]) -> None:
    write_json(CONFIG_FILE, config)


def load_models() -> list[dict[str, Any]]:
    data = read_json(MODELS_FILE, {"models": []}) or {}
    return list(data.get("models", []))


def save_models(models: list[dict[str, Any]]) -> None:
    write_json(MODELS_FILE, {"models": models})


def find_model(model_id: str) -> dict[str, Any] | None:
    return next((m for m in load_models() if m.get("id") == model_id), None)
