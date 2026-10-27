# Python 后端

后端使用 FastAPI 提供账号、文件上传、异步任务、报告和模型用量 API；pandas/NumPy 计算统计量，Plotly 构造图表。SQLite 保存账号、任务和计费记录，文件系统保存上传、结果和密钥引用文件。

从项目根目录创建 Python 3.12 环境并安装依赖：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --find-links deploy/wheels -r backend/requirements-dev.txt
```

按[开发指南](../docs/development.md)配置本地 `.env`，随后显式加载：

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --env-file .env --host 127.0.0.1 --port 8108
```

应用不会自动读取 `.env`。不配置模型密钥也能完成统计分析。创建初始管理员需要 `ADMIN_PASSWORD` 和至少 32 字符的 `SESSION_SECRET`；管理员已经存在时，修改环境变量不会重置其密码。

| 模块 | 职责 |
| --- | --- |
| `app/main.py` | HTTP 路由、访问控制、工作队列与静态资源 |
| `app/auth.py` | 注册、登录、密码校验与管理员初始化 |
| `app/store.py` | SQLite、账号归属与任务持久化 |
| `app/ingest.py` | 格式识别、安全读取、ZIP 检查与行列限制 |
| `app/analysis.py` | 字段画像、质量、EDA 证据与图表 |
| `app/llm.py` | 有界汇总输入、一次推理、输出结构和风险检查 |
| `app/billing.py` | 绑定用户的原子费用预留、结算与不确定费用保留 |
| `app/report.py` | Markdown 与内嵌 Plotly 的独立 HTML 导出 |

从项目根目录运行测试：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```

使用一个应用进程。内置队列是单工作线程，最多一项运行、四项等待；不要直接增加 Uvicorn workers 来扩容。生产需要 HTTPS、持久数据目录和稳定会话密钥。更多内容见[架构](../docs/architecture.md)、[API](../docs/api-contract.md)、[EDA 设计](../docs/eda-design.md)、[计费](../docs/model-and-budget.md)和[部署](../docs/deployment.md)。
