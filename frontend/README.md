# Frontend

当前前端是无需构建步骤的中文单页工作台，由 FastAPI 直接提供静态文件。正式入口为 `/`，开发者接口文档仍保留在 `/docs`。

现有真实功能：论文统计、PDF 选择/拖放上传、中文成功/失败提示、论文库搜索、论文详情、逐页文本阅读和待 OCR 提醒。样式与交互分别位于 `assets/app.css` 和 `assets/app.js`，不依赖外部 CDN。

失败恢复行为测试（在项目根目录运行，需要 Node.js）：

```bash
node --test frontend/tests/answer-failure.test.cjs
```

覆盖单篇回答、多篇比较在 HTTP 和网络失败后停止加载状态并允许重试。
