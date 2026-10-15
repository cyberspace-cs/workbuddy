"""LLM 客户端：统一流式接口，支持真实 OpenAI 兼容端点与 Mock 模式。

事件约定（yield 的 dict）：
  {"type": "token", "text": "..."}
  {"type": "tool_calls", "calls": [{"id", "name", "arguments": "<json string>"}]}
  {"type": "done", "usage": {...}}
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator, Iterable

import httpx

from .config import settings

JSON_HEADERS = {"Content-Type": "application/json"}


def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _tokenize(text: str) -> list[str]:
    """把文本切成近似 token 的片段，用于流式演示。"""
    return re.findall(r"\S+\s*", text)


async def _real_stream(
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
    max_tokens: int,
    base_url: str,
    api_key: str,
    model: str,
) -> AsyncIterator[dict]:
    url = f"{base_url}/chat/completions"
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    usage: dict = {}
    tool_acc: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload, headers=_auth_headers(api_key)) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield {"type": "error", "message": f"LLM HTTP {resp.status_code}: {body[:300]}"}
                return
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    yield {"type": "error", "message": str(chunk["error"])}
                    return
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    if content := delta.get("content"):
                        yield {"type": "token", "text": content}
                    for tc in delta.get("tool_calls", []) or []:
                        idx = tc.get("index", 0)
                        slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                if u := chunk.get("usage"):
                    usage = u

    if tool_acc:
        calls = []
        for slot in tool_acc.values():
            calls.append({
                "id": slot["id"] or f"call_{len(calls)}",
                "name": slot["name"],
                "arguments": slot["arguments"],
            })
        yield {"type": "tool_calls", "calls": calls}
    yield {"type": "done", "usage": usage}


# ---------------------------------------------------------------------------
# Mock 模式：无密钥也能跑通编排 / Swarm / 工具 / 前端全链路
# ---------------------------------------------------------------------------

_MOCK_PLANS = {
    "researcher": "我将先检索相关资料，再给出带出处的综述。",
    "coder": "我先明确需求，再用代码实现并自测。",
    "critic": "我会从风险、逻辑漏洞与可替代方案三个角度审视。",
    "planner": "我先把目标拆解为可执行的子任务序列。",
    "general": "我直接为你解答。",
    "synthesizer": "我综合各专家意见，按置信度加权给出结论。",
}


def _should_use_tool(agent_tag: str | None, query: str, tools: list[dict] | None) -> dict | None:
    if not tools:
        return None
    names = {t["function"]["name"] for t in tools}
    q = query.lower()
    if agent_tag == "researcher" and "web_search" in names and any(
        k in q for k in ["搜索", "查", "资料", "search", "找"]
    ):
        return {"name": "web_search", "arguments": json.dumps({"query": query}, ensure_ascii=False)}
    if agent_tag == "coder" and "code_exec" in names and any(
        k in q for k in ["代码", "函数", "脚本", "跑", "code", "python", "写一段"]
    ):
        return {"name": "code_exec", "arguments": json.dumps(
            {"code": "print('hello from mock code executor')\n"}, ensure_ascii=False)}
    return None


async def _mock_stream(
    messages: list[dict],
    tools: list[dict] | None,
    agent_tag: str | None,
) -> AsyncIterator[dict]:
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = m["content"]
            break

    plan = _MOCK_PLANS.get(agent_tag or "general", _MOCK_PLANS["general"])

    # 1) 思考过程
    for tok in _tokenize(plan + " "):
        yield {"type": "thought", "text": tok}
        await asyncio.sleep(0.006)

    # 2) 可能触发一次工具调用（演示 ReAct 循环）
    tool = _should_use_tool(agent_tag, last_user, tools)
    if tool:
        call_id = "call_mock_1"
        yield {"type": "tool_call", "id": call_id, "tool": tool["name"], "args": tool["arguments"]}
        await asyncio.sleep(0.15)
        if tool["name"] == "web_search":
            res = (f"[mock 搜索] 关于「{last_user}」找到 3 条结果：\n"
                   "1. 入门指南：核心概念与最佳实践\n"
                   "2. 深度对比：不同方案的取舍\n"
                   "3. 社区案例：真实落地经验")
        else:
            res = "[mock 代码执行] stdout: hello from mock code executor"
        yield {"type": "tool_result", "id": call_id, "ok": True, "result": res}
        await asyncio.sleep(0.1)

    # 3) 最终答案（流式 token）
    answer = _mock_answer(agent_tag, last_user, bool(tool))
    for tok in _tokenize(answer):
        yield {"type": "token", "text": tok}
        await asyncio.sleep(0.012)

    yield {"type": "done", "usage": {"mock": True}}


def _mock_answer(agent_tag: str | None, query: str, used_tool: bool) -> str:
    if agent_tag == "researcher":
        return (f"关于「{query}」的研究综述：\n\n"
                "**核心结论**：该主题的关键在于先建立清晰的定义，再分层推进。\n\n"
                "**要点**\n"
                "- 概念层：明确边界与术语。\n"
                "- 方法层：优先采用已被验证的做法。\n"
                "- 风险层：注意成本与失败扩散。\n\n"
                "（已通过工具检索到相关资料，详见上方工具结果。）" if used_tool else
                f"关于「{query}」，建议从定义、方法、风险三个维度系统梳理，"
                "再结合具体场景落地。")
    if agent_tag == "coder":
        if "html" in query.lower():
            return ("下面是你要的欢迎页面（完整 HTML，可直接预览）：\n\n"
                    "```html\n"
                    "<!DOCTYPE html>\n"
                    "<html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">\n"
                    "<style>body{font-family:system-ui;margin:0;height:100vh;display:grid;place-items:center;"
                    "background:linear-gradient(135deg,#5b8def,#16a085);color:#fff}\n"
                    "h1{font-size:42px;margin:0}.sub{opacity:.85}</style></head>\n"
                    "<body><div style=\"text-align:center\"><h1>👋 欢迎使用 WorkBuddy</h1>\n"
                    "<p class=\"sub\">手搓版 · 多智能体编排引擎</p></div></body></html>\n"
                    "```\n\n"
                    "把它交给前端 Artifact 面板即可实时预览。")
        return (f"针对「{query}」，下面给出一个最小可运行示例（已执行验证）：\n\n"
                "```python\n"
                "def greet(name: str) -> str:\n"
                '    return f"Hello, {name}!"\n\n'
                'if __name__ == "__main__":\n'
                '    print(greet("WorkBuddy"))\n'
                "```\n\n"
                "运行后将输出 `Hello, WorkBuddy!`。需要我补充单元测试或扩展功能吗？")
    if agent_tag == "critic":
        return (f"对「{query}」的评审意见：\n\n"
                "1. **风险**：方案在边界条件下可能失效，需补充异常处理。\n"
                "2. **逻辑漏洞**：未明确失败重试与熔断策略，可能成本失控。\n"
                "3. **替代方案**：可先用轻量原型验证，再决定是否全量投入。")
    if agent_tag == "planner":
        return (f"针对「{query}」的任务分解：\n\n"
                "1. 明确目标与验收标准。\n"
                "2. 调研现有方案，确定技术选型。\n"
                "3. 搭建最小骨架并跑通主链路。\n"
                "4. 分模块实现，逐块验证。\n"
                "5. 联调、压测与上线。")
    if agent_tag == "synthesizer":
        return (f"综合各专家意见后，对「{query}」的结论如下：\n\n"
                "多数专家认同应先定义再分层推进；其中工程实现路径置信度最高，"
                "研究侧资料充分，评审侧提示需补充失败重试与成本控制。建议按"
                "「规划→调研→骨架→分模块→联调」的顺序执行。")
    return (f"收到：{query}\n\n"
            "这是一个手搓版 WorkBuddy。我已接入编排引擎，可以单 Agent 作答，"
            "也可以切换到智囊团模式让多个专家并行协作。试着问我「搜索一下多智能体编排」"
            "或打开智囊团开关体验专家团协作。")


async def stream_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    agent_tag: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AsyncIterator[dict]:
    """统一入口：根据 provider/model 走真实或 Mock 流式。

    - provider="mock" 或该 provider 未配置密钥 -> Mock
    - 否则用解析到的 base_url/api_key/model 走真实流式
    """
    resolved = settings.resolve(provider, model)
    if resolved is None:
        async for ev in _mock_stream(messages, tools, agent_tag):
            yield ev
        return
    async for ev in _real_stream(
        messages,
        tools,
        temperature if temperature is not None else settings.TEMPERATURE,
        max_tokens if max_tokens is not None else settings.MAX_TOKENS,
        resolved["base_url"],
        resolved["api_key"],
        resolved["model"],
    ):
        yield ev
