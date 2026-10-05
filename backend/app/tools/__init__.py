"""工具包入口：注册全部内置工具。"""
from .registry import Tool, ToolRegistry, registry
from .web_search import WebSearchTool, register as _reg_search
from .code_exec import CodeExecTool, register as _reg_code
from .file_ops import FileOpsTool, register as _reg_file

__all__ = ["Tool", "ToolRegistry", "registry", "WebSearchTool", "CodeExecTool", "FileOpsTool"]


def init() -> None:
    _reg_search()
    _reg_code()
    _reg_file()
