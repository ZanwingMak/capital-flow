v0.1.1 修复历史资金缓存命中后仍逐只限频等待的问题。12只股票、同一历史日期及现有磁盘缓存的冷进程实测由12.51秒降至0.66秒；首次无缓存和实时上游查询仍遵守富途限频，不能承诺同等速度。

Flowdesk 桌面客户端内置 Python 运行时，无需另装 Python、Go 或 Node。统一资金流图标用于项目、网页及原生应用。

- **macOS Apple Silicon**：下载 `Flowdesk-macOS-arm64.dmg` 或 ZIP。最低 macOS 12；仅 ad-hoc 完整性签名，未使用 Developer ID，未经过 Apple 公证。
- **Windows x64**：下载完整便携 ZIP，解压后运行 `Flowdesk.exe`；若该次构建提供 NSIS 安装包，也可下载 `Flowdesk-Windows-amd64-Setup.exe`。需要系统 Microsoft Edge WebView2 Runtime；未使用 Authenticode 签名。
- 行情需要自行安装并登录富途 OpenD、确认市场权限；Alpaca 属可选用户配置。程序不包含用户账户、持仓、密钥或历史缓存。
- `SHA256SUMS.txt` 覆盖本次两平台所有安装和便携产物。macOS 可用 `shasum -a 256 -c SHA256SUMS.txt`（仅下载部分产物时请核对对应行）；Windows 可用 `Get-FileHash -Algorithm SHA256 <下载文件>` 对照。

详细构建、数据目录和功能边界见仓库 `docs/desktop-client.md`。当前没有自动更新。
