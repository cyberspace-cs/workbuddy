"""会话记忆（Blackboard）：内存态 + JSON 落盘，重启可恢复。

每条消息形如 {"role": "user"|"assistant"|"system"|"tool", "content": str}。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import settings

_SESSIONS_FILE = settings.DATA_DIR / "sessions.json"


class MemoryStore:
    def __init__(self, path: Path = _SESSIONS_FILE):
        self.path = path
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def get(self, session_id: str) -> list[dict[str, Any]]:
        return self._data.setdefault(session_id, [])

    def append(self, session_id: str, role: str, content: str) -> None:
        self.get(session_id).append({"role": role, "content": content})
        self._save()

    def reset(self, session_id: str) -> None:
        self._data[session_id] = []
        self._save()

    def snapshot(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.get(session_id))


memory = MemoryStore()
