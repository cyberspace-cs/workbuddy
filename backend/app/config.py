"""全局配置：从环境变量 / .env 读取 LLM 端点、密钥、模型与运行参数。"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根（backend/ 的上一级）
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
# 也尝试 backend/.env
load_dotenv(Path(__file__).resolve().parent / ".env")


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    MODEL: str = os.getenv("MODEL", "gpt-4o-mini")

    # auto: 有 key 走真实，无 key 走 mock；true/false 强制
    MOCK_MODE: str = os.getenv("MOCK_MODE", "auto").lower()

    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.7"))
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2000"))

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))
    # 绝对化：若相对，则相对项目根
    if not DATA_DIR.is_absolute():
        DATA_DIR = ROOT / DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def use_mock(self) -> bool:
        if self.MOCK_MODE == "true":
            return True
        if self.MOCK_MODE == "false":
            return False
        # auto
        return not bool(self.OPENAI_API_KEY)


settings = Settings()
