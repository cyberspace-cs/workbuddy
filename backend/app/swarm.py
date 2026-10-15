"""智囊团 / 专家团 Swarm：扇出并行专家 -> 置信度加权综合（扇入）。

算法：
  1. fan-out：把同一问题并发派发给 N 个专家（asyncio 并行）。
  2. 每个专家产出 {text, confidence∈[0,1]}。
  3. fan-in：综合者（Synthesizer）按置信度加权组织最终结论，
     并标注共识与分歧；同时给出整体「共识度」。
"""
from __future__ import annotations

import asyncio
import re

from .agents.registry import registry
from .config import settings
from .llm import stream_chat
from .orchestrator import build_messages
from .schemas import SSE

_MOCK_CONF = {"researcher": 0.82, "coder": 0.90, "critic": 0.70, "planner": 0.85, "general": 0.60}


def _parse_confidence(text: str) -> float:
    m = re.search(r"CONFIDENCE:\s*([0-9](?:\.\d+)?)", text, re.IGNORECASE)
    if not m:
        return 0.6
    return max(0.0, min(1.0, float(m.group(1))))


async def _expert_answer(agent_tag: str, history: list[dict], user_msg: str, provider=None, model=None):
    agent = registry.get(agent_tag) or registry.get("general")
    sys_prompt = (
        agent.system_prompt
        + "\n最后单独用一行给出 CONFIDENCE: <0到1的数字>，表示你对此回答的把握。"
    )
    messages = build_messages(sys_prompt, history, user_msg)
    parts: list[str] = []
    async for ev in stream_chat(messages, agent_tag=agent.tag, provider=provider, model=model):
        if ev["type"] == "token":
            parts.append(ev["text"])
        elif ev["type"] == "error":
            return "[专家出错]", 0.3
    text = "".join(parts)
    text = re.sub(r"\n?CONFIDENCE:\s*[0-9.](?:\.\d+)?\s*$", "", text, flags=re.IGNORECASE).strip()
    conf = _MOCK_CONF.get(agent.tag, 0.6) if settings.use_mock else _parse_confidence(text)
    return text, conf


async def run_swarm(agent_tags: list[str], history: list[dict], user_msg: str, provider=None, model=None):
    """智囊团协作，产出 SSE 事件。"""
    experts = [registry.get(t) for t in agent_tags if registry.get(t)]
    if not experts:
        experts = [registry.get("general")]

    # fan-out：并行求解
    tasks = [_expert_answer(a.tag, history, user_msg, provider, model) for a in experts]
    results = await asyncio.gather(*tasks)

    # 展示各专家观点
    for a, (text, conf) in zip(experts, results):
        yield SSE.SWARM_VIEW, {
            "agent": a.tag, "name": a.name, "color": a.color,
            "confidence": round(conf, 2), "text": text,
        }

    # 共识度 = 置信度均值（加权一致性的简化度量）
    consensus = round(sum(c for _, c in results) / len(results), 2)
    yield "swarm_consensus", {"value": consensus}

    # fan-in：综合者加权综合
    synth = registry.get("synthesizer")
    blocks = "\n".join(
        f"- {a.name}（置信度 {c:.2f}）：{t}" for (a, (t, c)) in zip(experts, results)
    )
    synth_user = (
        f"原始问题：{user_msg}\n\n"
        f"各位专家观点与置信度：\n{blocks}\n\n"
        f"请综合上述观点，按置信度加权突出高把握专家的意见，标注共识与分歧，"
        f"给出最终结论与可执行建议。"
    )
    messages = build_messages(synth.system_prompt, [], synth_user)

    async for ev in stream_chat(messages, agent_tag="synthesizer", provider=provider, model=model):
        if ev["type"] == "token":
            yield SSE.TOKEN, {"text": ev["text"]}
        elif ev["type"] == "error":
            yield SSE.ERROR, {"message": ev["message"]}
            return
