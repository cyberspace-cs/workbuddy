"""Agent 注册表。"""
from __future__ import annotations

from .base import Agent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.tag] = agent

    def get(self, tag: str) -> Agent | None:
        return self._agents.get(tag)

    def list(self) -> list[Agent]:
        return list(self._agents.values())

    def list_info(self) -> list[dict]:
        return [a.to_info() for a in self._agents.values()]


registry = AgentRegistry()
