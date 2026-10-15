"""TypeSafe · Jev（System One）客户端：把「类型化判断」当编程原语用。

API（非 OpenAI 兼容，是独立的结构化判断接口）：
    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer <API_KEY>
    body: { state, model, questions: { id: {type, instructions, criteria} } }
    resp: { model, answers: { id: {type, choice|noul|score, probabilities, confidence} }, usage }

设计原则（来自 TypeSafe skill）：
  - 代码掌控流程，模型只提供「可编程的常识」判断。
  - 相互独立的判断放在同一次请求里并行问，看不见彼此答案。
  - 用概率与置信度驱动行为；置信度表示分布集中度，不是"是否允许执行"。
  - 区分：缺证据 / 模型错误 / 代码错误 / 服务失败，失败要能优雅降级。
  - 密钥只留在服务端。
"""
from __future__ import annotations

import httpx

from .config import settings


class TypeSafeError(Exception):
    """TypeSafe 服务或请求层面的错误（调用方应据此降级）。"""


def available() -> bool:
    return bool(settings.TYPESAFE_API_KEY) and bool(settings.TYPESAFE_BASE_URL)


async def judge(state: str | dict | list, questions: dict) -> tuple[dict, str]:
    """向 Jev 提交一次判断请求，返回 (answers, model)。

    questions 形如:
      {"expert": {"type": "choice", "instructions": "...", "criteria": {...}},
       "needs_collab": {"type": "noul", "instructions": "..."}}
    """
    if not available():
        raise TypeSafeError("TypeSafe 未配置密钥")

    url = f"{settings.TYPESAFE_BASE_URL}/systemone"
    payload = {
        "state": state,
        "model": settings.TYPESAFE_MODEL,
        "questions": questions,
    }
    headers = {
        "Authorization": f"Bearer {settings.TYPESAFE_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as e:
        raise TypeSafeError(f"网络失败: {e}") from e

    if resp.status_code >= 400:
        raise TypeSafeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    return data.get("answers", {}), data.get("model", settings.TYPESAFE_MODEL)


# ---------------------------------------------------------------------------
# 意图路由：用 Jev 的 Choice 选专家 + Noul 判断是否需要智囊团（一次请求并行）
# ---------------------------------------------------------------------------

_EXPERT_CRITERIA = {
    "general": "日常闲聊、简单问答、打招呼，或不需要专门能力的通用任务",
    "researcher": "需要检索资料、做调研综述、查定义、对比方案或找案例",
    "coder": "要写代码、改 bug、实现功能、运行脚本或做技术落地",
    "critic": "要评审某个方案、挑风险与逻辑漏洞、评估可行性或靠不靠谱",
    "planner": "要把一个模糊目标拆解成步骤、计划、路线图或排期",
}


async def route_intent(query: str) -> dict:
    """判断请求该交给哪个专家，以及是否需要多位专家协作。

    返回:
      {"agent": str, "probabilities": {...}, "confidence": float,
       "needs_collab": float|None, "model": str}
    调用方应在 TypeSafeError 时降级到关键词路由。
    """
    questions = {
        "expert": {
            "type": "choice",
            "instructions": (
                "下面这条用户请求，最适合交给哪一个专家来处理？"
                "只根据请求本身表达的意图判断，不要考虑执行成本。"
            ),
            "criteria": _EXPERT_CRITERIA,
        },
        # 推测性问题（speculative）：并行问，代码按需消费
        "needs_collab": {
            "type": "noul",
            "instructions": (
                "回答这条请求，是否需要多位专家从彼此不同的角度共同评估，"
                "才能得到让用户满意的答复？（例如需要同时兼顾调研、实现与风险评审）"
            ),
            "criteria": {
                "true": "单一专家的视角不够，需要综合多方意见或做权衡比较",
                "false": "某一个专家单独就能完整回答",
            },
        },
    }

    answers, model = await judge(query, questions)

    expert = answers.get("expert", {})
    agent = expert.get("choice") or "general"
    if agent not in _EXPERT_CRITERIA:
        agent = "general"
    confidence = float(expert.get("confidence", 0.0))
    probabilities = expert.get("probabilities", {}) or {}

    collab = answers.get("needs_collab", {})
    needs_collab = collab.get("noul") if isinstance(collab.get("noul"), (int, float)) else None

    return {
        "agent": agent,
        "probabilities": {k: round(float(v), 3) for k, v in probabilities.items()},
        "confidence": round(confidence, 3),
        "needs_collab": None if needs_collab is None else round(float(needs_collab), 3),
        "model": model,
    }
