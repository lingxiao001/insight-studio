# 本地开发

## 环境与依赖

需要 Python 3.12、Node.js 24 和 npm。前端锁文件要求现代 Node 运行时（Vite 8 至少 Node 22.12），推荐统一使用 Node 24。React、TypeScript 等实际版本以 `frontend/package-lock.json` 为准，Python 锁定版本见 `backend/requirements.txt`。

在项目根目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --find-links deploy/wheels -r backend/requirements-dev.txt
```

仓库保留三个官方依赖补丁 wheel，供索引版本不一致时从本地解析；`deploy/wheels/SHA256SUMS` 可校验内容。它们属于依赖分发，不是模型、案例数据或私有凭据。依赖许可见根目录第三方说明。

```bash
cp .env.example .env
```

本地修改：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace-with-your-own-long-password
SESSION_SECRET=replace-with-a-random-secret-of-at-least-32-characters
COOKIE_SECURE=false
DATA_DIR=./data
STATIC_DIR=
LLM_API_KEY=
```

替换密码与会话密钥；示例字符串不是可公开使用的默认凭据。可以用 `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` 在自己终端生成随机值。`.env` 不应提交。应用不会隐式加载 `.env`；下面通过 Uvicorn 显式加载，生产则由 systemd `EnvironmentFile` 提供。

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --env-file .env --host 127.0.0.1 --port 8108
```

已有管理员时更改 `ADMIN_PASSWORD` 不会覆盖数据库密码。请使用独立测试数据目录，不要用删除或覆盖真实数据库的方式尝试配置。

另开终端：

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

访问 `http://localhost:5173`。开发代理转发 `/api` 到 8108，Cookie 身份随同源请求传递。若只打开后端且没有配置 `STATIC_DIR`，不会出现 Vite 界面。

## 构建与检查

```bash
cd frontend
npm run build
npm audit
```

从项目根目录运行后端测试：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```

依赖审计需要连接公开包索引，结果随时间变化，不把历史零漏洞视为永久保证。更改统计或计费逻辑时，补充能识别边界错误的回归；不通过真实收费调用替代单元测试。完整验证方法见 [testing.md](testing.md)。

## 代码结构

```text
backend/app/       API、账号、读取、统计、模型、账本与导出
backend/tests/     统计、安全、接口、模型与计费测试
frontend/src/      登录、工作区、专题探索、Plotly 与弹窗
scripts/           部署、备份、免费冒烟与公开案例复现
deploy/            容器、systemd、Caddy 模板与补丁依赖
docs/              使用、实现、案例与自托管文档
```

配置模型是独立步骤，至少需要密钥、非空模型、提供商 allowlist 和两项正数单价上限。使用 [model-and-budget.md](model-and-budget.md) 的安全边界；普通账号额度不能靠修改环境或更换密钥恢复。开发模型逻辑优先使用测试中的 HTTP 模拟响应，不提交实际密钥或供应商原始响应。

## 常见问题

| 现象 | 排查 |
| --- | --- |
| 无法创建管理员 | 密码长度及 `SESSION_SECRET` 至少 32 字符，且首次数据库已正确配置 |
| HTTP 本地登录后状态丢失 | 本地 `COOKIE_SECURE=false`，生产 HTTPS 则设 true |
| 模型开关不可用 | 核对完整服务端配置与用量读取，不用前端变量绕过锁定 |
| 文件被拒绝 | 检查大小、列数、格式、ZIP 成员安全与 XLSX 首表是否有数据 |
| 任务队列满 | 等待当前任务完成；当前为单进程有界队列 |
| 重启后任务失败 | 未完成任务不会自动推理重试，需明确重新分析 |

提交 PR 时同步相关 API/统计文档，不加入数据目录、数据库、构建缓存、备份、访问凭据或个人操作日志。
