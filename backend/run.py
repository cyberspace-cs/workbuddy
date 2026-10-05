"""启动入口：python backend/run.py"""
from app.main import app
from app.config import settings
import uvicorn

if __name__ == "__main__":
    print(f"[WorkBuddy] mock={settings.use_mock} model={settings.MODEL} base={settings.OPENAI_BASE_URL}")
    print(f"[WorkBuddy] 打开 http://localhost:{settings.PORT}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level="info")
