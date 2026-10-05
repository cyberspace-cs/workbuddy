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


@app.post("/api/reset")
async def reset_session(req: dict):
    sid = req.get("session_id", "default")
    memory.reset(sid)
    return {"ok": True}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = memory.snapshot(req.session_id)
    decision = route(req.message, req.mode, req.agent, req.agents)
    mode = decision["mode"]
    involved = decision.get("agents") if mode == "swarm" else [decision.get("agent")]
    meta_agents = [
        a.to_info() for t in involved if (a := agent_registry.get(t))
    ]

    async def event_stream():
        yield sse(SSE.META, {"mode": mode, "agents": meta_agents, "mock": settings.use_mock})
        answer = ""
        gen = (
            run_swarm(decision["agents"], history, req.message)
            if mode == "swarm"
            else run_agent(decision["agent"], history, req.message)
        )
        async for et, data in gen:
            if et == SSE.TOKEN:
                answer += data.get("text", "")
            yield sse(et, data)
        # 落盘记忆
        memory.append(req.session_id, "user", req.message)
        memory.append(req.session_id, "assistant", answer)
        yield sse(SSE.DONE, {"usage": {"mock": settings.use_mock}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# 静态托管前端（显式 API 路由已先注册，优先匹配）
app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
