# TraceScholar 公网演示部署

本轮只准备代码与配置，不会自动创建云服务、上传本地论文、购买套餐或产生付费资源。
平台控制台的套餐、磁盘能力、地区和界面可能变化，创建前必须由本人确认费用。

## 1. 当前已准备的保护

- 生产模式要求至少 16 字符的演示密码；没有密码就拒绝启动。
- 首页、静态资源和论文 API 都需要 HTTP Basic 账号密码；浏览器会弹出登录框。
- 仅健康检查 GET /health 可匿名访问，不返回论文数据。
- 生产模式默认关闭 /docs、/redoc、/openapi.json。
- 请求体上限默认 52 MiB，包含 multipart 开销；单个 PDF 仍限 50 MiB。
- 不声明长度的流式请求也会累计检查大小，超过限制返回 413。
- 生产上传全站合计每分钟 10 次，最多同时处理 2 个上传；超限返回 429。
- 错误登录全站每分钟最多 60 次；正确凭证不受此错误计数锁定。
- 已保存的原文件和解析结果合计限 512 MiB，超额上传返回 507，临时文件会清理。
- 带浏览器 Origin 的跨站写请求会被拒绝。
- Docker 构建上下文使用白名单，不包含 .env、本地数据、官方 PDF 或 Git 元数据。

这只是小范围比赛演示保护，不是多用户账号系统。所有持有演示凭证的人共享同一个论文库。
不要上传个人毕设、未发表论文、私密资料或没有分发权限的资料。
账号密码只能通过 HTTPS 使用，且应通过私密渠道单独发给评委或队友，不要写进 README、Git 提交或视频。
本轮只支持单实例、单 Uvicorn worker；限流计数在内存中，服务重启会清零，不能替代云端防护。

## 2. 在 GitHub Desktop 提交

1. 选择 TraceScholar 仓库，检查 Changes 中没有 .env、PDF、运行数据或虚拟环境。
2. Summary 可以填写：feat: prepare secure Docker deployment
3. 点击 Commit to main，然后 Push origin。

推送代码并不等于已经部署上线。

## 3. 云端通用设置

可使用支持 Docker 和持久化存储的托管平台。后续可在 Render 控制台操作；
如果选择 Railway，也使用本仓库根目录的 Dockerfile，不需要分别部署前后端。
此处不承诺平台免费额度或套餐价格，尤其要核实持久磁盘是否可用及是否收费。

| 配置 | 填写内容 |
| --- | --- |
| 代码来源 | 本人的 GitHub TraceScholar 仓库 |
| 构建上下文 | 仓库根目录，不是 backend/ |
| Dockerfile | ./Dockerfile |
| 环境类型 | Docker |
| 健康检查 | /health |
| 实例数量 | 1 |
| 持久磁盘挂载目录 | /app/data |
| 存储环境变量 | STORAGE_DIR=/app/data |
| 监听端口 | 镜像读取平台提供的 PORT；未提供时默认 8000 |

在平台的环境变量/Secret 面板配置：

| 变量 | 值 |
| --- | --- |
| APP_ENV | production |
| DEMO_USERNAME | viewer，或自行设置一个用户名 |
| DEMO_PASSWORD | 自行生成的随机密码，至少 16 字符，推荐 32 字符以上 |
| ENABLE_API_DOCS | false |
| STORAGE_DIR | /app/data |
| UPLOAD_REQUESTS_PER_MINUTE | 10 |
| MAX_CONCURRENT_UPLOADS | 2 |
| MAX_REQUEST_BYTES | 54525952 |
| MAX_STORAGE_BYTES | 536870912 |

PDF 导入和本地证据检索无需模型密钥。要启用“生成证据回答”，在 Render 的 Environment 中自行增加 `LLM_PROVIDER=deepseek`、`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-flash` 和 `LLM_API_KEY`（真实密钥）。未配置时站点照常启动，只有模型回答按钮提示未配置。调用模型会按 DeepSeek 实际用量计费；不要把密钥写入仓库、截图或聊天。本地真实调用已验证，公网 Render 仍需单独配置和验收；启用前应设置调用限额并评估演示账号共享造成的费用风险。
如果需要生成密码，可以在本机终端运行 openssl rand -hex 24，将结果只放进平台 Secret 面板。
不要把密码发到聊天里，也不要在链接中加入用户名和密码。

镜像用 UID/GID 10001:10001 运行。持久卷必须允许该用户写入；
首次挂载后若出现权限错误，先按平台文档调整卷权限，不要直接把应用改为 root 运行。
没有挂载持久卷时，文件即使上传成功，也可能在重建或迁移后丢失。健康检查通过不能证明持久化成功。

## 4. 正式分享前验收

1. 用无痕窗口访问 HTTPS 链接，未登录时必须出现登录框，不得直接看到论文库。
2. 错误密码不能登录，正确密码可以看到中文工作台。
3. 导入一篇允许公开展示的 PDF，检查详情、分页原文和版本关系。
4. 重启或重新部署服务，再次登录，确认第 3 步资料仍存在。
5. 登录后访问 /docs 和 /openapi.json 都应返回 404。
6. /health 应可匿名返回正常状态，但不带任何论文信息。
7. 确认云端用量上限、告警、费用与演示到期后的关闭方式，再分享链接和凭证。

本地 data/ 里的已有论文不会因部署自动传到服务器。云端论文库初始为空是正常的。
持久卷不等于备份，演示结束前请按需要备份并安全保存资料。

## 5. 可选的本地 Docker 验证

需要先启动 Docker Desktop。首次配置时将 .env.example 复制为 .env，
在本机编辑 .env 的 DEMO_PASSWORD，填入至少 16 字符的随机密码；不要提交这个文件。
Compose 会强制使用 production，其他本地开发启动方式不受影响。

在仓库根目录运行：

    docker compose up --build -d

然后访问 http://127.0.0.1:8000/，只在本机测试。
本地 8000 端口如已占用，改 compose.yaml 左侧端口，例如 127.0.0.1:8002:8000。
这是本机回环地址，不是给他人的公网链接。

停止测试可运行 docker compose down；不要加 -v，否则会删除本地持久卷数据。
Compose 使用的 paper-data 是独立的 Docker 卷，不会自动导入宿主机 data/。

## 6. 本轮验证状态

- 验证日期：2026-11-12。
- 已验证：完整测试 44 passed，含官方 PDF、生产认证/限流/体积限制/配额、应用重建后读取；另通过 Compose 配置解析与 JS 语法检查。
- 待验证：Docker 实际构建与运行、托管平台部署、HTTPS 登录和云端重启后的数据持久化。
- 原因：当前 Docker 引擎未启动；尚未登录并创建云服务。
