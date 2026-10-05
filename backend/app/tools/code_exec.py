"""code_exec：在沙箱目录执行 Python 代码（带超时与基础危险调用拦截）。

安全说明：这是本地演示用的轻量沙箱，并非生产级隔离。生产应放到
容器 / gVisor / seccomp 中执行，并限制网络与文件系统访问。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import settings
from .registry import Tool

# 基础危险调用拦截（演示级）
_FORBIDDEN = ("os.system", "subprocess", "shutil.rmtree", "os.remove", "__import__", "eval(", "exec(")


class CodeExecTool(Tool):
    name = "code_exec"
    description = "执行一段 Python 代码并返回 stdout/stderr。用于验证算法、计算、生成数据。"
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的 Python 代码"}
        },
        "required": ["code"],
    }

    async def run(self, code: str) -> str:
        for bad in _FORBIDDEN:
            if bad in code:
                return f"[被拦截] 检测到危险调用 `{bad}`，出于安全考虑已拒绝执行。"

        sandbox = settings.DATA_DIR / "sandbox"
        sandbox.mkdir(parents=True, exist_ok=True)
        # 使用运行当前进程的解释器，保证跨平台（开发机 / 服务器统一）
        python_exe = sys.executable or "python3"

        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=sandbox, delete=False, encoding="utf-8") as f:
            f.write(code)
            path = Path(f.name)

        try:
            proc = subprocess.run(
                [python_exe, str(path)],
                cwd=str(sandbox),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            return "[超时] 代码执行超过 15 秒，已终止。"
        finally:
            try:
                path.unlink()
            except OSError:
                pass

        out = (proc.stdout or "") + (proc.stderr or "")
        return out.strip() or "[无输出]"


def register() -> None:
    from .registry import registry
    registry.register(CodeExecTool())
