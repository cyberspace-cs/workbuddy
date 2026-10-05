"""Agent 包入口。"""
from .base import Agent
from .registry import AgentRegistry, registry
from .experts import (
    CODER,
    CRITIC,
    GENERAL,
    PLANNER,
    RESEARCHER,
    SYNTHESIZER,
    register as register_experts,
)

__all__ = [
    "Agent",
    "AgentRegistry",
    "registry",
    "GENERAL",
    "RESEARCHER",
    "CODER",
    "CRITIC",
    "PLANNER",
    "SYNTHESIZER",
    "register_experts",
]


def init() -> None:
    register_experts()
