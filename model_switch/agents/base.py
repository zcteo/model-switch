from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LaunchPlan:
    binary: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class AgentAdapter(ABC):
    """Common interface for all injectable coding agents."""

    id: str
    label: str
    required_api: str
    endpoint: str
    default_binary: str
    binary_env: str
    # 隔离目录里承载共享指令的文件（agent 启动时默认读取的全局指令文件）。
    instructions_dir: Path
    instructions_name: str = "AGENTS.md"

    def instructions_path(self) -> Path | None:
        return self.instructions_dir / self.instructions_name

    def supports(self, model: dict[str, Any]) -> bool:
        return self.required_api in model.get("supported_apis", [])

    def unsupported_message(self, model: dict[str, Any]) -> str:
        return (
            f"⚠ 跳过 {self.label}：{model.get('id', '')} 不支持 {self.endpoint}，"
            "已保持当前模型"
        )

    @abstractmethod
    def switch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        model_ids: list[str],
    ) -> None:
        """Write isolated config for the selected model."""

    @abstractmethod
    def launch(
        self,
        config: dict[str, Any],
        model: dict[str, Any],
        passthrough_args: list[str],
    ) -> LaunchPlan:
        """Return the command and environment used to launch the agent."""
