# 测试与验证

本仓库保留可重复执行的测试与冒烟脚本。这里说明如何验证当前代码，不引用私人部署的通过记录、发行号、账单或备份流水。

## 自动测试与构建

完成[本地开发环境](development.md)后，从项目根目录运行：

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
```

测试覆盖读取、ZIP 安全、统计边界、账号与拥有者隔离、报告转义、队列恢复、模型结构及用户计费状态机。外部模型与账单使用模拟 HTTP 响应，不需要真实 API key，不应触发付费推理。测试通过不代表所有真实数据或模型解释均正确。

```bash
cd frontend
npm ci
npm run build
npm audit
```

生产构建包含 TypeScript 检查。依赖审计依赖当前索引和公告，重新运行才能获得当前结果。浏览器交互和图形的正确性需要另外验证，不能由构建成功代替。

## 免费 API 冒烟

在自己运行的实例创建独立测试账号，将其访问配置保存到忽略的本地私有文件。脚本支持的参数以各自 `--help` 为准，不将密码写在命令行或提交到 Git：

```bash
.venv/bin/python scripts/smoke.py --help
.venv/bin/python scripts/accounts-smoke.py --help
.venv/bin/python scripts/deep-eda-smoke.py --help
```

常规验证应包括登录、上传与选表、六步进度、EDA 覆盖说明、Markdown/HTML 下载、明确免费重试、删除引用和两个账号间隔离。深度 EDA 冒烟可保留 demo、导出预览目录，并验证统计操作前后模型账本完全一致。指定旧模型任务升级时必须显式关闭模型，不因原任务启用模型而隐式再次付费。

## Kaggle 案例复现

```bash
.venv/bin/python scripts/real-kaggle-case.py
```

默认只在缺失时从官方固定 version 3 下载，并验证公开原始 CSV 哈希；不会提交分析或推理。数据未随代码仓库分发。`--submit` 才提交任务，默认免费统计；例如：

```bash
.venv/bin/python scripts/real-kaggle-case.py --submit --url http://127.0.0.1:8108 --access-file .local/access.json --output-dir .local/kaggle-statistical
```

`--submit --with-agent --confirm-paid-call` 才允许显式可能收费的验证。先确认密钥配置、当前账户、余额与真实数据传输范围。脚本在提交前保存 intent 防重复；后续使用同一输出目录的 `--resume` 取回原任务，不自动再推理。公共截图采用已有模型文本离线重放，不能把截图视为此处新推理已成功的证明。

案例正确性需核对挂牌价、日期分桶、分位数、组支持数及业务边界，见[案例来源](real-data-provenance.md)。

## 容量与界面

`scripts/model-smoke.py` 同样需要 `--confirm-paid-call` 才能新建付费推理；默认健康检查不要使用它。

`scripts/benchmark-eda.py` 对合成内存 DataFrame 测量分析与导出。它不是 50 MiB 上传测试，也不能证明某台服务器的服务并发能力。记录环境、行列、耗时和峰值内存后再比较，不复用其他主机的历史数值。

界面检查建议覆盖桌面、平板和手机宽度：无整页横向溢出、最多六张图挂载、专题/字段/类型组合筛选、分页、键盘标签页、弹窗焦点、Escape、在途禁用、退出和账号切换。确认这些阅读操作前后账本不变。离线 HTML 需要验证延迟绘图、打印准备、转义和无外链脚本。

## 实际验证记录

本轮在独立公共副本实际执行：

| 项目 | 实际结果 | 范围 |
| --- | --- | --- |
| 后端全量测试 | 137 passed，23.22 s，157 条上游依赖弃用警告 | `PYTHONPATH=backend pytest backend/tests -q`；模拟模型，不付费 |
| 前端 | `npm ci`、`npm run build` 通过 | TypeScript 与 Vite 生产构建 |
| 免费 API 冒烟 | 基础、账号隔离、深度 EDA 通过 | 新本地实例；深度 demo 47 图；用量未增加 |
| 真实 Kaggle 全流程统计 | 48,895×16，全量，49 图 | 原 CSV 哈希一致；零新推理、零新费用 |
| 部署静态检查 | shell 语法、Python AST、CLI 帮助、URL 边界、发行包排除规则与三个 wheel 哈希通过 | 未在本轮执行真实云部署、Caddy 或 Docker |

这些结果是本次公共副本的验证记录，不是私人生产服务流水或持续集成的永久保证。CI 配置使用 Python 3.12、Node.js 24，并检查补丁 wheel 和 Git 历史中的秘密；远端 CI 的实际结果以提交后的运行记录为准。
