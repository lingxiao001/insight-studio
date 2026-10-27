# 随源码携带的安全补丁

这些纯 Python wheel 从官方 Python 包仓库下载，用于消除本机与服务器索引版本不一致时的安全更新缺口。没有修改第三方包代码；许可证和归属信息保留在 wheel 的 `.dist-info` 目录中。

| 包 | 版本 | 用途 |
| --- | --- | --- |
| anyio | 4.15.1 | 异步网络与线程工具 |
| certifi | 2026.10.23 | 更新的 CA 根证书集合 |
| python-multipart | 0.0.32 | 上传表单解析与边界修复 |

校验和见 `SHA256SUMS`。从项目根目录运行 `shasum -a 256 -c deploy/wheels/SHA256SUMS`（macOS）或 `sha256sum -c deploy/wheels/SHA256SUMS`（Linux）。安装使用 `--find-links deploy/wheels`；各包版本仍以 `backend/requirements.txt` 为准。

维护时从可信官方包仓库取得新版本、重新生成校验和，完整回归并重跑依赖审计后再更新。不要只替换文件而不更新依赖锁。
