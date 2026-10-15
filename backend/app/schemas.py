"""请求/响应数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(default="default")
    message: str
    # auto: 由 Router 决定；agent: 指定单个专家；swarm: 强制智囊团
    mode: str = Field(default="auto")
    agent: str | None = None          # mode=agent 时指定 tag
    agents: list[str] | None = None   # mode=swarm 时指定专家 tag 列表
    provider: str | None = None       # LLM provider id（见 config.PROVIDERS），mock 或空走 Mock
    model: str | None = None          # 具体模型名


class AgentInfo(BaseModel):
    tag: str
    name: str
    role: str
    tools: list[str]
    color: str


class SSE:
    """SSE 事件类型常量（前端按 type 渲染）。"""

    META = "meta"                 # 运行元信息 {mode, agents:[]}
    AGENT_START = "agent_start"   # {agent, name, role, color}
    THOUGHT = "thought"           # {agent, text}  思考/过程
    TOOL_CALL = "tool_call"       # {agent, id, tool, args}
    TOOL_RESULT = "tool_result"   # {agent, id, ok, result}
    TOKEN = "token"               # {text}  最终答案流
    ARTIFACT = "artifact"         # {id, type, title, content}
    SWARM_VIEW = "swarm_view"     # {agent, name, confidence, text}
    DONE = "done"                 # {usage}
    ERROR = "error"               # {message}
