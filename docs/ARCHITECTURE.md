# 系统边界与数据契约

## 分层

- `backend/app/`：HTTP API、任务编排和鉴权边界。
- `backend/domain/`：论文领域对象和业务规则。
- `backend/pipeline/`：PDF 解析、OCR、切块、版本识别和索引任务。
- `backend/retrieval/`：关键词、向量、重排和证据筛选。
- `backend/agent/`：意图识别、工具选择、重试和回答编排。
- `frontend/`：上传、论文库、阅读器、问答和比较界面。
- `data/`：本地运行数据，不纳入 Git。

## 证据元数据契约

每一条可用于回答的证据至少保留：

```json
{
  "paper_id": "internal-id",
  "version_id": "v7",
  "page": 3,
  "section": "3.1 Attention",
  "text": "原文片段",
  "bbox": [0, 0, 0, 0],
  "source": "pdf"
}
```

`page` 从 1 开始；`bbox` 没有可靠坐标时必须为 `null`，不能伪造定位。

## 关键边界

1. 论文原文件和解析产物分开保存。
2. 同一论文的不同版本不能互相覆盖。
3. 检索结果必须携带证据元数据，生成器不能凭空补页码。
4. 证据不足时返回“当前资料不足”，并记录缺口。
5. 比较结果应能回指到参与比较的具体版本和证据。

## 可复用能力

毕业设计平台中的上传任务、模型 Provider、混合检索、Agent 重试、PDF 定位和长任务 UI 可以择需迁移；毕业论文审核规则、DOCX/LaTeX 流程、AI 率页面和旧数据库不属于本项目领域模型。
