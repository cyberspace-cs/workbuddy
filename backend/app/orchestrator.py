"""编排器：路由决策 + 单 Agent ReAct 推理循环 + Artifact 抽取。

流程（集中式 Orchestrator-Worker）：
  route()  -> 决定 agent / swarm / plan
  run_agent() -> 带工具的推理循环（think -> tool -> observe -> answer）
  run() -> 顶层生成器，统一产出 SSE 事件
"""
from __future__ import annotations

import re
import uuid

from .agents.registry import registry
from .config import settings
from .llm import stream_chat
from .schemas import SSE
from .tools.registry import registry as tool_registry
from . import typesafe
from .typesafe import TypeSafeError

MAX_TOOL_ROUNDS = 4

# 关键词 -> 专家路由
_ROUTES = {
    "coder": ["代码", "函数", "脚本", "实现", "写一段", "跑", "python", "算法", "bug", "报错"],
    "researcher": ["搜索", "查", "资料", "调研", "文献", "找", "是什么", "对比"],
    "critic": ["评审", "风险", "审查", "挑刺", "漏洞", "靠谱吗", "可行吗"],
    "planner": ["规划", "拆解", "计划", "步骤", "怎么做", "路线图", "排期"],
}
_SWARM_TRIGGERS = ["综合", "对比", "方案", "和", "与", "还是", "评估", "多角度", "智囊团"]


def _pick_agent(query: str) -> str:
    q = query.lower()
    best, best_score = "general", 0
    for tag, kws in _ROUTES.items():
        score = sum(1 for k in kws if k in q)
        if score > best_score:
            best, best_score = tag, score
    return best


def _top_agents(probabilities: dict, k: int = 3) -> list[str]:
    """按 Jev 给出的概率分布取前 k 个专家（已知 tag 才保留）。"""
    ranked = sorted(probabilities.items(), key=lambda kv: -kv[1])
    tags = [t for t, _ in ranked if registry.get(t)][:k]
    return tags or ["researcher", "coder", "critic"]


async def route(
    query: str,
    forced_mode: str = "auto",
    forced_agent: str | None = None,
    forced_agents: list[str] | None = None,
) -> dict:
    """路由决策。

    auto 模式下优先用 TypeSafe(Jev) 做「意图路由 + 置信度门控」：
      - Choice 选出最合适的专家，并给出概率分布与置信度；
      - Noul 判断是否需要多角度协作；
      - 置信度低于阈值 或 协作需求高 -> 升级为智囊团。
    Jev 不可用（未配置 / 服务失败 / 区域限制）时自动降级到关键词路由。
    """
    if forced_mode == "agent" and forced_agent and registry.get(forced_agent):
        return {"mode": "agent", "agent": forced_agent,
                "routing": {"source": "forced"}}
    if forced_mode == "swarm":
        tags = [t for t in (forced_agents or []) if registry.get(t)]
        if not tags:
            tags = ["researcher", "coder", "critic"]
        return {"mode": "swarm", "agents": tags, "routing": {"source": "forced"}}

    # ---- auto：Jev 意图路由 ----
    routing: dict = {"source": "keyword"}
    if settings.USE_TYPESAFE_ROUTER and typesafe.available():
        try:
            r = await typesafe.route_intent(query)
            routing = {
                "source": "typesafe",
                "model": r["model"],
                "agent": r["agent"],
                "confidence": r["confidence"],
                "probabilities": r["probabilities"],
                "needs_collab": r["needs_collab"],
            }
            needs = r["needs_collab"] or 0.0
            # 置信度门控 + 协作需求：任一触发即升级为智囊团
            if needs >= settings.TYPESAFE_SWARM_NOUL:
                return {"mode": "swarm", "agents": _top_agents(r["probabilities"]),
                        "routing": routing, "reason": "needs_collab"}
            if r["confidence"] < settings.TYPESAFE_ROUTE_MIN_CONF:
                return {"mode": "swarm", "agents": _top_agents(r["probabilities"]),
                        "routing": routing, "reason": "low_confidence"}
            return {"mode": "agent", "agent": r["agent"], "routing": routing}
        except TypeSafeError as e:
            # 服务/模型层面的失败：记录原因并降级，不让请求整体失败
            routing = {"source": "keyword", "fallback_reason": str(e)}
        except Exception as e:  # 兜底：任何异常都不要打断对话
            routing = {"source": "keyword", "fallback_reason": f"{type(e).__name__}: {e}"}

    # ---- 关键词兜底 ----
    if len(query) > 40 or any(t in query for t in _SWARM_TRIGGERS):
        return {"mode": "swarm", "agents": ["researcher", "coder", "critic", "planner"],
                "routing": routing}
    return {"mode": "agent", "agent": _pick_agent(query), "routing": routing}


def build_messages(system_prompt: str, history: list[dict], user_msg: str) -> list[dict]:
    msgs = [{"role": "system", "content": system_prompt}]
    for m in history:
        if m["role"] in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": user_msg})
    return msgs


def extract_artifacts(text: str) -> list[dict]:
    """从最终答案中抽取代码/HTML 块作为 Artifact。"""
    out = []
    for m in re.finditer(r"```(\w+)?\n(.*?)```", text, re.DOTALL):
        lang = (m.group(1) or "").lower()
        code = m.group(2).strip()
        if not code:
            continue
        if lang in ("html", "htm"):
            atype = "html"
        elif lang in ("md", "markdown"):
            atype = "md"
        else:
            atype = "code"
        first = code.splitlines()[0] if code.splitlines() else "片段"
        out.append({
            "id": f"art_{uuid.uuid4().hex[:8]}",
            "type": atype,
            "language": lang or "text",
            "title": first[:40],
            "content": code,
        })
    return out


def _append_tool_turn(messages: list[dict], call: dict, result: str) -> None:
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call["id"],
            "type": "function",
            "function": {"name": call["name"], "arguments": call["arguments"]},
        }],
    })
    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})


async def run_agent(agent_tag: str, history: list[dict], user_msg: str, provider=None, model=None):
    """单 Agent 推理循环，产出 SSE 事件。"""
    agent = registry.get(agent_tag) or registry.get("general")
    yield SSE.AGENT_START, {
        "agent": agent.tag, "name": agent.name, "role": agent.role, "color": agent.color,
    }
    messages = build_messages(agent.system_prompt, history, user_msg)
    tool_schemas = tool_registry.schemas(agent.tools) if agent.tools else None

    answer_parts: list[str] = []
    for _ in range(MAX_TOOL_ROUNDS):
        followup = False
        async for ev in stream_chat(messages, tool_schemas, agent_tag=agent.tag, provider=provider, model=model):
            t = ev["type"]
            if t == "thought":
                yield SSE.THOUGHT, {"agent": agent.tag, "text": ev["text"]}
            elif t == "tool_call":  # mock 内联工具调用
                call = {"id": ev["id"], "name": ev["tool"], "arguments": ev["args"]}
                yield SSE.TOOL_CALL, {"agent": agent.tag, **call}
                res = await tool_registry.execute(call["name"], call["arguments"])
                yield SSE.TOOL_RESULT, {"agent": agent.tag, "id": call["id"], **res}
                _append_tool_turn(messages, call, res["result"])
            elif t == "tool_calls":  # real 聚合工具调用
                for c in ev["calls"]:
                    yield SSE.TOOL_CALL, {"agent": agent.tag, **c}
                    res = await tool_registry.execute(c["name"], c["arguments"])
                    yield SSE.TOOL_RESULT, {"agent": agent.tag, "id": c["id"], **res}
                    _append_tool_turn(messages, c, res["result"])
                followup = True
            elif t == "token":
                yield SSE.TOKEN, {"text": ev["text"]}
                answer_parts.append(ev["text"])
            elif t == "error":
                yield SSE.ERROR, {"message": ev["message"]}
                return
            # done: 忽略（循环自然结束）
        if not followup:
            break

    final = "".join(answer_parts)
    for art in extract_artifacts(final):
        yield SSE.ARTIFACT, art
