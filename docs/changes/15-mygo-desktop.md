# 15 — MyGo 原生桌面宿主

- 为 macOS arm64 和 Windows amd64 增加固定提交的 MyGo 宿主；单实例、原生窗口、同源本机页面，无 Go IPC。
- 增加 PyInstaller onedir sidecar，包含 Python 与行情依赖。明确资源清单与文件名审计排除配置、缓存、数据库和账户记录。
- 增加受限 stdin/stdout ready/shutdown 协议、随机 challenge、随机独占端口、启动超时和 EOF 退出。宿主使用 macOS 自有进程组或 Windows kill-on-close Job 清理，保留既有私有 API 认证边界。
- 增加 `app_paths.py`；缓存写用户 `data/`，私有数据写 `private/`，Alpaca 用户配置在 `config/.env`，页面读只读打包资源。源码网页模式保持原默认目录。
- 增加原生双平台 CI、最终宿主与解压下载包的无界面冒烟，以及协议、目录隔离和进程生命周期测试。固定发布文件名见 [桌面客户端说明](../desktop-client.md)。

不启用自动更新。当前 macOS 仅 ad-hoc 签名且未公证，Windows 未签名。macOS arm64 已完成本机实际打包、sidecar 协议验证、宿主与解压 ZIP 后无用户 Python PATH 的无界面冒烟、签名完整性与 DMG 校验；冒烟同时验证指标入口和私有 API 边界。Windows 已通过交叉编译，原生运行由 Windows CI 继续验证；图形界面交互需单独验收。
