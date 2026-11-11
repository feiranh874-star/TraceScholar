# Backend

当前后端提供健康检查、PDF 上传、分页文本抽取和论文元数据查询。上传处理目前是同步的；后续会将长文档解析移入后台任务。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 <http://127.0.0.1:8000/health> 验证服务。

上传 PDF：`POST /api/papers`，multipart 字段名为 `file`。支持最大 50 MiB、最多 2000 页和最多 2000 万提取字符；扫描页会标记 `needs_ocr`，本阶段不会执行 OCR。完全相同的 PDF 会按 SHA-256 去重，arXiv 文件名或首页标识会用于关联同一论文的不同版本。

论文列表、元数据和单页文本分别见 `GET /api/papers`、`GET /api/papers/{paper_id}`、`GET /api/papers/{paper_id}/pages/{page_number}`。章节结构与可分页文本块分别见 `GET /api/papers/{paper_id}/structure` 和 `GET /api/papers/{paper_id}/chunks`；每个文本块保留论文、版本、页码、章节与坐标来源字段。

当前上传大小限制在 multipart 解包后执行。公网部署时还需在反向代理或网关设置请求体上限，避免超大请求占用解析阶段的临时磁盘。

运行测试：

```bash
pip install -r requirements-dev.txt
pytest
```

如需运行组委会 PDF 回归，将目录指向材料包的 `pdf/` 文件夹：

```bash
TRACESCHOLAR_SAMPLE_DIR="/path/to/科研小助手/pdf" pytest -q
```

后续按 `docs/ARCHITECTURE.md` 增加论文、版本、解析任务、文本块、证据和引用等领域对象。
