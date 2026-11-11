# TraceScholar

可信科研助手 Agent，面向论文 PDF 的解析、版本识别、可溯源问答和多论文比较。

> 当前仓库处于基础骨架阶段。路线文档中的功能是开发计划，不代表已经完成。

## MVP 演示主线

1. 上传 `1706.03762v7.pdf` 和较旧版本 `v1`。
2. 解析页面、章节和文本块，并识别为同一论文的不同版本。
3. 针对论文提问，回答必须附带论文名、页码和原文证据。
4. 选择两个版本，比较方法、实验和结论的变化。
5. 点击证据回到对应 PDF 页面。

## 仓库结构

```text
backend/       后端 API、论文解析和 Agent 编排
frontend/      中文 Web 工作台（无需前端构建步骤）
data/          本地运行数据，仅保留目录占位，不提交论文和密钥
docs/          路线、架构和验收记录
tests/         自动化测试与人工验收记录
```

## 当前状态

- [x] 独立比赛仓库和远程地址
- [x] 基础目录、环境变量模板和路线文档
- [x] 后端健康检查
- [x] PDF 上传、分页文本抽取与论文详情查询
- [x] 中文科研工作台、论文库、拖放导入与分页阅读
- [x] arXiv 论文族与版本识别，章节/文本块/证据来源数据契约
- [ ] 论文版本差异分析
- [ ] 带页码证据的问答
- [ ] 多论文比较和最小 Agent

## 本地启动（当前骨架）

需要 Python 3.10 或更高版本：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

启动后访问 <http://127.0.0.1:8000/> 使用中文工作台；<http://127.0.0.1:8000/docs> 仅作开发者调试入口，<http://127.0.0.1:8000/health> 用于检查服务状态。

## 配置

复制 `.env.example` 为 `.env`，再填写自己的模型配置。`.env` 不得提交到 GitHub。

## 开发规则

- 先保证官方测试 PDF 的主流程能运行，再扩展可选功能。
- 任何回答都要保留可追溯证据：论文、版本、页码、章节和原文片段。
- 证据不足时明确返回资料不足，不编造结论。
- 官方 PDF、个人数据、模型密钥、数据库和运行时索引不进入仓库。
- 毕设平台只复用通用工程能力，不直接复制业务页面和数据库。

详细计划见 [docs/ROADMAP.md](docs/ROADMAP.md)，系统边界见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
组委会样例回归结果见 [docs/OFFICIAL_ACCEPTANCE.md](docs/OFFICIAL_ACCEPTANCE.md)。
