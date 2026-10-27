# 自托管部署

部署目标由你显式提供。仓库没有预置服务器、可用管理员密码或公开服务地址。推荐在专用 Linux 主机使用一个应用进程、systemd 与 Caddy，域名解析到该主机，TCP 80/443 可达。

## 原生 Linux 部署

本地需要 Python、Node.js 24、npm、SSH 和 tar。远端需要 root 权限的 SSH 账户，并已安装 Python 3.12、venv、Caddy、systemd、tar 和 curl。脚本不会替你创建云资源或修改 DNS。

从项目根目录运行：

```bash
DEPLOY_HOST=root@server.example.com SITE_URL=https://analysis.example.com bash scripts/deploy.sh
```

这里的主机和域名是占位示例，必须替换。`SITE_URL` 只接受 HTTPS DNS 域名，不含路径或非默认端口。脚本从 shell 环境读取这两个值，不自动 source `.env`。默认先运行 `npm ci` 与生产构建；已有且确认有效的 `frontend/dist` 可传 `--skip-build`。

脚本管理这台专用主机的 `/etc/caddy/Caddyfile`，首次覆盖前保留 `.before-insight` 备份；若主机已有其他站点，先审查并自行合并配置，避免直接运行覆盖站点。可预先渲染检查：

```bash
python3 deploy/render-caddy.py --site-url https://analysis.example.com --output /tmp/Caddyfile
```

部署创建非 root 应用用户 `insight-studio`，将发行包放入 `/srv/insight-studio/releases/`，通过 `current` 符号链接切换。应用监听 `127.0.0.1:8108`；Caddy 反向代理并自动管理该域名 HTTPS。这里不需要 IP 证书或自定义 Certbot 续期任务。

## 配置与凭据

持久配置位于 `/srv/insight-studio/shared/.env`，数据位于 `shared/data/`。首次部署生成随机管理员密码及会话密钥，后续不覆盖已有值；账号已存在时数据库密码也不会被环境变量重置。

初始访问凭据通过 SSH 写入本地 `.local/access.json`，目录 700、文件 600，脚本不打印密码。此文件和服务端环境配置均不得提交或公开。需要读取时在自己的安全终端查看，不粘贴到 Issue 或日志。

默认不配置 `LLM_API_KEY`，统计分析可正常工作。使用外部模型时，在服务端配置密钥、模型、唯一端点和单价上限，再重启应用。普通用户使用共享后端密钥但不能读取；管理员也可在界面经验证后更换。详见[模型与费用](model-and-budget.md)。

生产需 `COOKIE_SECURE=true`、至少 32 字符且稳定的 `SESSION_SECRET`。数据与模型密钥目录需要持久保存；不要将一次性容器文件系统作为唯一账本。

## Docker Compose

项目提供 app-only Compose，应用端口只发布在本地回环，使用持久卷保存 `/data`。先配置 `.env` 中的 `ADMIN_PASSWORD` 和 `SESSION_SECRET`，再运行：

```bash
docker compose up -d --build
```

默认 Secure Cookie 需要通过 HTTPS 访问，宿主可使用 Caddy 代理 `127.0.0.1:8108`。Compose 不包含域名或证书管理。仅在可信本地 HTTP 试用时显式将 `COOKIE_SECURE=false`；公开服务启用 HTTPS。

## 验证与运维

```bash
curl --fail https://analysis.example.com/api/health
```

随后在浏览器验证登录、普通注册、免费示例、导出、跨账号隔离与用量页。避免将真实付费推理作为默认健康检查。API 冒烟方法见[验证指南](testing.md)。

`insight-studio.service` 使用单应用进程，不要直接增加 Uvicorn workers。应用队列有界，重启时未完成任务失败；用户可明确免费重新分析。已保存报告与费用账本需要跨部署保留。

部署脚本保留上一发行路径，`scripts/rollback.sh` 可回切兼容的版本。含账号及用户账本结构的数据库不能回到不支持这些结构的旧版；脚本会拒绝不安全回退。回滚代码不会退回账单或撤销提供商费用。

## 备份与恢复

`scripts/backup.sh` 通过 `DEPLOY_HOST` 指定目标，停服取得一致快照后恢复服务，完整成功才将 `.partial` 改为正式包。备份包含持久数据与环境配置，因此是敏感凭据载体，应限制为 600、保留在私有存储，并定期验证 tar 完整性与恢复能力。

```bash
DEPLOY_HOST=root@server.example.com bash scripts/backup.sh
```

应用备份不等于整机备份；Caddy 配置、证书存储、DNS 和其他主机配置由部署者另行备份。恢复时同时恢复数据库、源文件、结果、密钥文件及一致环境，使用兼容代码启动。先在隔离环境检查用户归属与费用，再开放访问。不要把真实备份交给公共仓库或用于公开截图。
