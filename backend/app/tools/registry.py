"""工具注册表与基类。

工具统一形态：
  - name / description
  - parameters: OpenAI function-calling 的 JSON Schema
  - async run(**kwargs) -> str
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str = ""
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    async def run(self, **kwargs) -> str:
        ...

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self, names: list[str] | None = None) -> list[dict]:
        if names is None:
            names = list(self._tools.keys())
        return [t.to_schema() for n, t in self._tools.items() if n in names]

    async def execute(self, name: str, arguments: str) -> dict:
        """解析参数并执行，返回 {ok, result}。"""
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "result": f"未知工具: {name}"}
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return {"ok": False, "result": f"参数不是合法 JSON: {arguments}"}
        try:
            result = await tool.run(**args)
            return {"ok": True, "result": result}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "result": f"工具执行异常: {type(e).__name__}: {e}"}


registry = ToolRegistry()
