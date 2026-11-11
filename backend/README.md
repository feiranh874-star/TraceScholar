# Backend

当前后端只有可运行的 FastAPI 入口和健康检查，用来确认本地开发环境正常。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 <http://127.0.0.1:8000/health> 验证服务。

后续按 `docs/ARCHITECTURE.md` 增加论文、版本、解析任务、文本块、证据和引用等领域对象。
