# Flowdesk 桌面客户端

Flowdesk 使用固定提交 `2d2cbbe476d83f7864a7225ae937eb4513995b35` 的 [MyGo](https://github.com/egoist/mygo/tree/2d2cbbe476d83f7864a7225ae937eb4513995b35) 作为原生窗口宿主。Python 服务由 PyInstaller onedir 打包，包含解释器、Futu SDK、pandas、numpy、protobuf、Crypto、simplejson 和 tzdata。安装者无需安装 Python、Go 或 Node。

支持 macOS arm64 和 Windows amd64。Windows 图形窗口依赖系统 Microsoft Edge WebView2 Runtime；行情查询仍需要用户自己启动并登录富途 OpenD。没有 OpenD 时，首页、私有工作区握手与健康接口仍可启动；需要行情的数据请求会明确报错。

## 构建

在目标系统和架构原生构建 Python 运行时。不要使用开发项目的 `.venv` 安装构建工具。构建依赖版本在 `desktop/requirements-build.txt` 固定；MyGo 与 `golang.org/x/sys` 在 `desktop/go.mod` 固定，Go 工具链为 **1.27.3**。

macOS：

```sh
python3.14 -m venv desktop/.build/venv
desktop/.build/venv/bin/python -m pip install -r desktop/requirements-build.txt
(cd desktop && GOTOOLCHAIN=go1.27.3 go mod download && GOTOOLCHAIN=go1.27.3 go test ./...)
desktop/.build/venv/bin/python -B desktop/build.py
```

Windows PowerShell：

```powershell
py -3.14 -m venv "$env:TEMP\flowdesk-build-venv"
& "$env:TEMP\flowdesk-build-venv\Scripts\python.exe" -m pip install -r desktop/requirements-build.txt
$env:GOTOOLCHAIN = 'go1.27.3'
Push-Location desktop
go mod download
go test ./...
Pop-Location
& "$env:TEMP\flowdesk-build-venv\Scripts\python.exe" -B desktop/build.py
```

`--sidecar-only` 只构建和验证服务运行时。macOS 的 `--skip-dmg` 跳过磁盘映像。Windows 自动使用已安装的 NSIS；`--installer` 显式要求 MyGo 构建安装程序，必要时由 MyGo 下载 NSIS。无 NSIS 时仍生成完整便携 ZIP。

构建依次执行：明确清单暂存公开资产、PyInstaller 构建、资源文件名审计、真实 sidecar 协议/HTTP/EOF 验证、MyGo 原生构建、最终宿主无界面验证、归档，以及实际解压到含空格和中文的目录后再次运行宿主。解压验证的 PATH 不包含用户 Python。

`desktop/release/` 的固定产物名称：

| 平台 | 下载文件 |
| --- | --- |
| macOS arm64 | `Flowdesk-macOS-arm64.zip`、`Flowdesk-macOS-arm64.dmg` |
| Windows amd64 | `Flowdesk-Windows-amd64.zip`；有 NSIS 时另有 `Flowdesk-Windows-amd64-Setup.exe` |
| 两个平台 | `SHA256SUMS.txt` |

`.github/workflows/desktop.yml` 在 macOS arm64 与 Windows amd64 runner 原生构建，上传 `Flowdesk-macOS-arm64` 和 `Flowdesk-Windows-amd64` 两个 Actions artifact。分支 push、PR 和手动运行仅产生 Actions artifact；推送与 `desktop/mygo.json` 版本精确一致的稳定 tag（当前为 `v0.1.0`）时，两平台测试和构建全部成功后，由单一 `release` job 下载两份 artifact、逐个核对 SHA256、合并一份 `SHA256SUMS.txt`，再创建 GitHub Release。平台 job 无发布权限，不会并发改写 Release；已有同名 Release 会使创建失败，不会覆盖既有资产。macOS runner 的 `macos-15` arm64 标签依据 [GitHub 官方 runner 列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

## 统一图标与发布

原创图标以深蓝圆角底、三段资金柱及青绿色流线表达观察资金的变化；没有文字或细线。`dist/brand/flowdesk.svg`、1024/512/192/32 PNG、`dist/favicon.ico` 及 `desktop/icons/` 原生 ICO/ICNS 由同一几何定义生成。网页及 README 引用 SVG，兼容 favicon 引用多尺寸 ICO。静态服务返回真实图标内容，资源清单将全部图标列为必需项。

重新生成时创建独立工具环境（不要改应用 venv）：

```sh
python3 -m venv "$TMPDIR/flowdesk-icon-tools"
"$TMPDIR/flowdesk-icon-tools/bin/python" -m pip install Pillow==12.2.0
"$TMPDIR/flowdesk-icon-tools/bin/python" scripts/generate_icons.py
```

请先把 `TMPDIR`、`PYINSTALLER_CONFIG_DIR`、`GOCACHE` 配置到自己的构建暂存目录。MyGo 的通用 `icon` 读取 1024 PNG，并将多尺寸图标嵌入 Windows EXE 和可选 NSIS 安装程序；`macos.icon` 指向生成的 ICNS，写入 `.app` 的图标与 Info.plist。ICNS 使用现代 PNG 条目，避免旧 `icp4/icp5` 条目被 IconServices 误解码。

完成代码审查、合并和 CI 验证后，维护者才执行发布命令：

```sh
git tag -a v0.1.0 -m "Flowdesk v0.1.0"
git push <remote> v0.1.0
```

后续版本需先修改 `desktop/mygo.json`，tag 必须为 `v` 加该稳定版本。tag 构建失败不会发布部分平台；修复后应使用新的版本 tag。Release 包含两平台便携包、macOS DMG、存在时的 Windows NSIS 安装程序，以及合并校验文件。`desktop/release-notes.md` 明确运行依赖与未公证/未商业签名限制。这里配置了自动化，不表示任何版本已经发布。

## 本机数据与配置

| 用途 | macOS | Windows |
| --- | --- | --- |
| 用户根目录 | `~/Library/Application Support/Flowdesk` | `%APPDATA%\Flowdesk` |
| 日级/分钟/Alpaca/筹码缓存 | 用户根目录下 `data/` | 用户根目录下 `data\` |
| 私有台账与研究数据库 | 用户根目录下 `private/` | 用户根目录下 `private\` |
| Alpaca 配置 | 用户根目录下 `config/.env` | 用户根目录下 `config\.env` |
| 宿主和子进程诊断 | 用户根目录下 `logs/desktop.log` | 用户根目录下 `logs\desktop.log` |

Alpaca 用户配置文件只支持 `APCA_API_KEY_ID` 与 `APCA_API_SECRET_KEY`；也支持用户显式设置的同名环境变量。不会读取、复制或迁移开发项目已有 `.env`、缓存、数据库或持仓。Futu SDK 自身的日志仍遵循 SDK 的系统用户目录规则，位于应用资源之外。

网页源码模式保持默认项目 `.data/` 和 `dist/` 路径。需要隔离部署时，可显式设置绝对路径 `FLOWDESK_DATA_DIR`、`FLOWDESK_STATIC_DIR`、`FLOWDESK_CONFIG_DIR`；私有目录继续使用 `FLOWDESK_PRIVATE_DIR`。冻结桌面运行时由宿主设置受管用户目录，静态页面默认位于只读 `_MEIPASS/dist`。

资源由 `desktop/resources.json` 明确列举。新增页面脚本时同时更新该清单和服务端静态白名单。不会整体复制项目或 `dist/`；旧网页下载包 `windows-package.zip` 不进入桌面包。资源审计拒绝 `.env`、`.data`、数据库、CSV、账户目录等文件名，包括隐藏配置。

## 协议与退出

宿主先取得 MyGo 单实例锁，再通过绝对路径启动 `Resources/sidecar/flowdesk-server/flowdesk-server`（Windows 为 `.exe`，Resources 为宿主可执行文件目录）。不会探测、复用或终止 8788 上的其他服务。

初始 stdin JSON 行携带协议版本、随机实例 ID、256-bit challenge 和用户根目录。子进程一次性绑定 `127.0.0.1:0`，更新服务实际端口，仅将自己的精确 origin 加入行情白名单。stdout 只回显受限的 ready JSON；普通 Python、SDK 和原生 stdout 转到 stderr。宿主校验版本、实例、challenge、端口和报文大小；初始握手超时 10 秒，宿主启动等待上限 30 秒。

窗口的 URL 是该服务的 `http://127.0.0.1:<实际端口>`，HTML 与 API 同源。`PageOptions.Untrusted=true`，不绑定 Go 服务，不开放任意文件、命令执行或代理。拒绝新窗口、跨 origin 导航和系统权限。私有 API 原有 peer、Host、Origin、FLOW_TOKEN 与会话令牌保护保持有效。

stdin EOF 或正确的 shutdown JSON 让控制线程停止 HTTP 服务，只清理本进程的行情连接和工作线程。没有 HTTP shutdown API。宿主退出与启动失败共享幂等清理：等待 4 秒正常退出，必要时只终止 macOS 自己的进程组或 Windows 自己的 Job Object，并再等待最多 2 秒。Windows Job 设置 kill-on-close。

## 验证与限制

```sh
python -B -m unittest discover -s tests -p 'test_*.py'
NODE_PATH=/path/to/test-dependencies/node_modules node --test tests/*.js
(cd desktop && GOTOOLCHAIN=go1.27.3 go test ./... && GOTOOLCHAIN=go1.27.3 go vet ./...)
python -B desktop/smoke.py --sidecar /absolute/path/to/flowdesk-server
```

前端指标测试需要 `jsdom@27.0.1`，CI 将其安装到独立测试目录，不写入产品资源。无界面宿主验证也可以直接运行：

```sh
/Applications/Flowdesk.app/Contents/MacOS/Flowdesk --smoke-test --data-dir "$PWD/desktop/.build/合成 Flowdesk User"
```

Windows 使用 `Flowdesk.exe --headless --data-dir "C:\Temp\Synthetic Flowdesk User"`。两种模式共享正式子进程生命周期，必须显式传入合成目录，不访问默认私有台账。验证真实页面及其脚本/CSS、健康 API、未知资源拒绝、私有接口跨源和未授权拒绝、退出码及端口释放。额外 sidecar 冒烟覆盖 EOF 与错误 challenge。

macOS 默认只有 ad-hoc 签名，**未使用 Developer ID 签名或 Apple 公证**；Windows 未使用 Authenticode 签名。下载后的 Gatekeeper/SmartScreen 提示与组织策略限制仍可能出现。这里不宣称签名或公证完成，也不实现绕过系统安全策略的安装脚本。客户端未启用自动更新或自动更新联网。

受限沙箱可能禁止 loopback 绑定或下载 Go 模块。这类环境只能完成允许的单元验证；真实打包 HTTP 冒烟需要在本机父进程或原生 CI 执行。打包脚本要求这些验证成功，失败不应发布成品。
