"""Agent 基类：角色 + 系统提示 + 可用工具 + 展示色。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Agent:
    tag: str
    name: str
    role: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    color: str = "#5b8def"

    def to_info(self) -> dict:
        return {
            "tag": self.tag,
            "name": self.name,
            "role": self.role,
            "tools": self.tools,
            "color": self.color,
        }
