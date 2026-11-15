# TraceScholar

可信科研助手 Agent，面向论文 PDF 的解析、版本识别、可溯源问答和多论文比较。

> 已完成上传、基础解析与可信问答主线，第五轮补充版本选择、真实 OCR、原版阅读/段落翻译和科研工具基础版。跨论文比较要求每篇所选论文都提供有效原文引用。这些开发轮次不等于比赛六模块已经完成；最新实现、验证与边界见 [第五轮记录](docs/PHASE5_PROGRESS.md)。

## MVP 演示主线

1. 上传 Transformer v7、CLIP 和深度学习教材 PDF。
2. 解析页面、章节和文本块，并保留论文与页码来源。
3. 针对单篇论文提问，查看带页码的原文证据和回答。
4. 选择 Transformer 与 CLIP，比较它们的注意力和图文对比学习机制。
5. 查看每篇来源的引用，跳回对应页码的原版版式与提取文本，并选择本页片段翻译；坐标高亮待补齐。
6. 在“研究工具”中查看库内引用图谱、相似论文推荐，整理带来源的提纲，或上传 CSV 生成图表。

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
- [x] 带论文名、版本、章节、页码和原文片段的本地证据检索
- [x] 原文片段默认折叠；展开后可查看证据并跳转到对应页码的提取文本
- [x] 常见科研术语的中文问题检索英文论文（离线术语桥接，非通用翻译）
- [x] 回答提示词优先用文字解释公式；前端隐藏常见 LaTeX 数学块
- [ ] 论文版本差异分析
- [x] 严格基于证据的模型回答生成（模拟测试和本地真实 API 调用通过）
- [x] 最小科研 Agent：意图路由、证据检查、意图适配回答、引用验证与执行步骤展示
- [x] 官方 Transformer v7 中英检索评测集（22 题；当前 BM25 Hit@1 与 Recall@3 均为 100%）
- [x] BM25 检索与 TF-IDF 稀疏向量相似度/排名融合
- [ ] 稠密语义 embedding 与神经重排
- [x] 2–5 篇论文证据比较（逐篇检索、证据门禁、每篇来源引用校验）
- [x] CLIP、Transformer 与深度学习教材官方材料回归题集
- [x] 正文近重复比对与版本取消/保留/确认替换（片段哈希，不是稠密语义去重）
- [x] 扫描页真实 OCR、实际进度、失败页重试及已保存页面恢复
- [x] 原版版式逐页阅读、章节切页与有原文校验的段落翻译
- [x] 本地可解释推荐与带参考文献证据的库内引用图谱
- [x] arXiv 题名检索/确认导入接口（模拟测试通过；公网下载端到端仍待验证）
- [x] 带来源提纲、CSV 图表/图注/复现脚本及固定流程 Mermaid 示例
- [ ] 长文档资源评测、完整 CRUD、引用双向跳转及全文双语联动
- [ ] 定时论文追踪、20 篇图谱验证、Future Work 查证与定制架构图

2026-11-15 配置官方样例目录后，后端测试 110 项通过，前端失败恢复测试 4 项通过。另实际完成官方 15 页扫描样例 OCR，以及 DeepSeek 段落翻译/提纲调用；它们只覆盖选定场景，不代表官方六模块全部通过。复现方法与指标范围见 [验收记录](docs/OFFICIAL_ACCEPTANCE.md)。

## 本地启动

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

复制 `.env.example` 为 `.env`。本地证据检索无需模型配置；如需生成回答，请自行填写 `LLM_API_KEY`，并使用 `LLM_PROVIDER=deepseek`、`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-flash`。本地启动后端需加 `--env-file ../.env` 才会读取该文件；Render 部署应在 Environment 中分别添加这四个变量。`.env` 和真实密钥不得提交到 GitHub，也不要发送到聊天中。模型输出不等于事实核验，回答中的引用会映射到本地原文，但仍应核对关键结论。

## 公网演示

已提供 Dockerfile、Compose、演示账号保护、上传限流和存储配额；用户已在 Render 部署并确认线上问答和比较可用，云端数据持久性与评审期间可用性仍需单独验收。
生产模式必须设置 APP_ENV=production 和至少 16 字符的 DEMO_PASSWORD；默认关闭接口文档。
部署步骤与持久磁盘配置见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。
演示账号共享论文库，不应上传私密资料；本地开发默认保持不要求登录。

## 开发规则

- 先保证官方测试 PDF 的主流程能运行，再扩展可选功能。
- 任何回答都要保留可追溯证据：论文、版本、页码、章节和原文片段。
- 证据不足时明确返回资料不足，不编造结论。
- 官方 PDF、个人数据、模型密钥、数据库和运行时索引不进入仓库。
- 毕设平台只复用通用工程能力，不直接复制业务页面和数据库。

前两轮总结见 [第一轮](docs/PHASE1_SUMMARY.md) 和 [第二轮](docs/PHASE2_SUMMARY.md)；后续见 [第三轮记录](docs/PHASE3_PROGRESS.md)、[第四轮总结](docs/PHASE4_SUMMARY.md)、[第四轮历史](docs/PHASE4_PROGRESS.md) 和 [第五轮记录](docs/PHASE5_PROGRESS.md)。原始 32 项任务及第四轮结束时的差距见 [比赛复盘](docs/COMPETITION_GAP_REVIEW.md)，详细路线见 [ROADMAP](docs/ROADMAP.md)，系统边界见 [ARCHITECTURE](docs/ARCHITECTURE.md)。
组委会样例回归结果见 [docs/OFFICIAL_ACCEPTANCE.md](docs/OFFICIAL_ACCEPTANCE.md)。
