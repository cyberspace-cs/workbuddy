"""全局配置：从环境变量 / .env 读取多 provider 的 LLM 端点、密钥、模型与运行参数。

支持的 provider（OpenAI 兼容）：
  - openai   : 官方 / 任意兼容网关（OPENAI_*）
  - deepseek : DeepSeek（DEEPSEEK_*）
  - qwen     : 阿里通义千问 DashScope（QWEN_*）
  - ark      : 火山方舟 Volcengine（ARK_*）
  - jev      : 自定义兼容端点（JEV_*，需自填 BASE_URL）
未配置密钥的 provider 不会出现在可用列表；MOCK_MODE=auto 时默认走 mock。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根（backend/ 的上一级）与 backend/ 目录
ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]  # backend/
load_dotenv(ROOT / ".env")
# 也尝试 backend/.env
load_dotenv(BACKEND_DIR / ".env")


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _csv(v: str) -> list[str]:
    return [s.strip() for s in v.split(",") if s.strip()]


class Provider:
    def __init__(self, pid: str, name: str, base_url: str, api_key: str, models: list[str]):
        self.id = pid
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.models = models

    @property
    def available(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "models": self.models,
            "available": self.available,
        }


class Settings:
    # ---- 默认 / 兜底（OpenAI 兼容）----
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    MODEL: str = os.getenv("MODEL", "gpt-4o-mini")

    # auto: 有可用 provider 且未强制则走真实；true/false 强制
    MOCK_MODE: str = os.getenv("MOCK_MODE", "auto").lower()

    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.7"))
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2000"))

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))
    if not DATA_DIR.is_absolute():
        DATA_DIR = ROOT / DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 多 provider 定义 ----
    PROVIDERS: dict[str, Provider] = {}
    PROVIDERS["openai"] = Provider(
        "openai", "OpenAI 兼容", OPENAI_BASE_URL, OPENAI_API_KEY,
        _csv(os.getenv("OPENAI_MODELS", MODEL)),
    )
    PROVIDERS["deepseek"] = Provider(
        "deepseek", "DeepSeek", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        os.getenv("DEEPSEEK_API_KEY", ""),
        _csv(os.getenv("DEEPSEEK_MODELS", "deepseek-v4-flash,deepseek-v4.1-flash")),
    )
    PROVIDERS["qwen"] = Provider(
        "qwen", "通义千问 Qwen", os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        os.getenv("QWEN_API_KEY", ""),
        _csv(os.getenv("QWEN_MODELS", "qwen3.8-max,qwen3.8-flash")),
    )
    PROVIDERS["ark"] = Provider(
        "ark", "火山方舟 Ark", os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        os.getenv("ARK_API_KEY", ""),
        _csv(os.getenv("ARK_MODELS", "ark-model-id")),  # 真实模型 ID 在 backend/.env 的 ARK_MODELS 配置，勿硬编码进源码
    )
    # 注意：TypeSafe 的 Jev 不是 chat 模型，而是「类型化判断」API（/v1/systemone），
    # 因此不作为 OpenAI 兼容 chat provider 出现在模型选择器里，改由 app/typesafe.py 使用。

    # ---- TypeSafe（Jev · System One）----
    TYPESAFE_API_KEY: str = os.getenv("TYPESAFE_API_KEY", os.getenv("JEV_API_KEY", ""))
    TYPESAFE_BASE_URL: str = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1").rstrip("/")
    TYPESAFE_MODEL: str = os.getenv("TYPESAFE_MODEL", "jev-latest")
    # 是否用 Jev 做意图路由（1=启用，失败自动降级到关键词路由）
    USE_TYPESAFE_ROUTER: bool = _truthy(os.getenv("USE_TYPESAFE_ROUTER", "1"))
    # 路由置信度低于此阈值 -> 升级为智囊团（多专家）
    TYPESAFE_ROUTE_MIN_CONF: float = float(os.getenv("TYPESAFE_ROUTE_MIN_CONF", "0.55"))
    # noul「需要多角度协作」高于此值 -> 升级为智囊团
    TYPESAFE_SWARM_NOUL: float = float(os.getenv("TYPESAFE_SWARM_NOUL", "0.5"))

    @property
    def use_mock(self) -> bool:
        if self.MOCK_MODE == "true":
            return True
        if self.MOCK_MODE == "false":
            return False
        # auto：没有任一可用 provider 时走 mock
        return not any(p.available for p in self.PROVIDERS.values())

    def list_providers(self) -> list[dict]:
        """返回前端可用的 provider 列表（不含密钥）。"""
        out = []
        for p in self.PROVIDERS.values():
            out.append(p.public())
        out.append({"id": "mock", "name": "Mock（离线演示）", "models": ["mock"], "available": True})
        return out

    def resolve(self, provider_id: str | None, model: str | None) -> dict | None:
        """解析 provider+model 为 (base_url, api_key, model)。返回 None 表示走 mock。"""
        if provider_id in (None, "", "mock"):
            return None
        p = self.PROVIDERS.get(provider_id)
        if not p or not p.available:
            return None
        return {"base_url": p.base_url, "api_key": p.api_key, "model": model or (p.models[0] if p.models else "")}


settings = Settings()
