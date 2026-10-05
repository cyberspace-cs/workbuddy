"""web_search：返回结构化检索片段。演示用 Mock，预留真实检索接入点。"""
from __future__ import annotations

from .registry import Tool


class WebSearchTool(Tool):
    name = "web_search"
    description = "联网检索资料，返回与查询相关的若干条结果摘要。适合找定义、对比、案例。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"}
        },
        "required": ["query"],
    }

    async def run(self, query: str) -> str:
        # 演示实现：生成拟真片段。生产可替换为 SerpAPI / Bing / Tavily 等。
        return (
            f"[检索] 关键词：{query}\n"
            "1. 入门指南 — 核心定义、适用场景与最小实践。\n"
            "2. 深度对比 — 不同方案的取舍与性能差异。\n"
            "3. 社区案例 — 真实落地经验与踩坑记录。\n"
            "（此为 Mock 检索结果；接入真实搜索引擎后此处返回真实摘要。）"
        )


def register() -> None:
    from .registry import registry
    registry.register(WebSearchTool())
