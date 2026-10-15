"""FastAPI 应用：API 路由 + SSE 流式 + 静态托管前端。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import tools, agents
from .agents.registry import registry as agent_registry
from .config import settings
from .memory import memory
from .orchestrator import route, run_agent
from .schemas import ChatRequest, SSE
from .swarm import run_swarm

# 初始化：注册工具与专家
tools.init()
agents.init()

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
app = FastAPI(title="WorkBuddy 手搓版", version="0.1.0")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/agents")
async def list_agents():
    return {"agents": agent_registry.list_info(), "mock": settings.use_mock, "model": settings.MODEL}


@app.get("/api/models")
async def list_models():
    """返回可用 provider / 模型列表（不含密钥），供前端模型选择器使用。"""
    return {"providers": settings.list_providers(), "default_mock": settings.use_mock}


@app.post("/api/reset")
async def reset_session(req: dict):
    sid = req.get("session_id", "default")
    memory.reset(sid)
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = memory.snapshot(req.session_id)
    decision = await route(req.message, req.mode, req.agent, req.agents)
    mode = decision["mode"]
    involved = decision.get("agents") if mode == "swarm" else [decision.get("agent")]
    meta_agents = [
        a.to_info() for t in involved if (a := agent_registry.get(t))
    ]
    # 解析实际使用的 provider/model（None 表示走 mock）
    resolved = settings.resolve(req.provider, req.model)
    used_mock = resolved is None
    used_provider = req.provider if resolved else "mock"
    used_model = (resolved["model"] if resolved else "mock")

    async def event_stream():
        yield sse(SSE.META, {
            "mode": mode, "agents": meta_agents,
            "mock": used_mock,
            "provider": used_provider, "model": used_model,
            # Jev 意图路由的判定明细（置信度 / 概率分布 / 是否降级）
            "routing": decision.get("routing"),
            "route_reason": decision.get("reason"),
        })
        answer = ""
        gen = (
            run_swarm(decision["agents"], history, req.message, req.provider, req.model)
            if mode == "swarm"
            else run_agent(decision["agent"], history, req.message, req.provider, req.model)
        )
        async for et, data in gen:
            if et == SSE.TOKEN:
                answer += data.get("text", "")
            yield sse(et, data)
        # 落盘记忆
        memory.append(req.session_id, "user", req.message)
        memory.append(req.session_id, "assistant", answer)
        yield sse(SSE.DONE, {"usage": {"mock": used_mock}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# 静态托管前端（显式 API 路由已先注册，优先匹配）
app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
