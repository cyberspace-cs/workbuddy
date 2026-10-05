"""file_ops：在沙箱目录内读写/列举文件。"""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from .registry import Tool


def _safe_path(name: str) -> Path:
    sandbox = settings.DATA_DIR / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    p = (sandbox / name).resolve()
    if not str(p).startswith(str(sandbox.resolve())):
        raise ValueError("路径越界")
    return p


class FileOpsTool(Tool):
    name = "file_ops"
    description = "在沙箱中读取、写入或列举文件。参数 action: read|write|list；name 为文件名；content 为写入内容。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write", "list"], "description": "操作类型"},
            "name": {"type": "string", "description": "文件名（list 时可省略）"},
            "content": {"type": "string", "description": "write 时的内容"},
        },
        "required": ["action"],
    }

    async def run(self, action: str, name: str | None = None, content: str | None = None) -> str:
        if action == "list":
            sandbox = settings.DATA_DIR / "sandbox"
            files = [p.name for p in sandbox.iterdir()] if sandbox.exists() else []
            return f"沙箱文件：{files or '（空）'}"
        if not name:
            return "缺少参数 name"
        p = _safe_path(name)
        if action == "read":
            if not p.exists():
                return f"文件不存在：{name}"
            return p.read_text(encoding="utf-8", errors="replace")
        if action == "write":
            p.write_text(content or "", encoding="utf-8")
            return f"已写入 {name}（{len(content or '')} 字符）"
        return f"未知 action：{action}"


def register() -> None:
    from .registry import registry
    registry.register(FileOpsTool())
