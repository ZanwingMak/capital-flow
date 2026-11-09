# 节点19：统一项目、网页与原生应用图标及 tag 发布

## 原因与结果

项目此前使用字符占位标识，浏览器 favicon 请求返回 204，桌面包没有品牌图标，也没有从原生构建到 GitHub Release 的完整发布步骤。

本节点设计原创 Flowdesk 图标：深蓝圆角底、三段资金柱和青绿色流线。保留大块几何轮廓，无字母或细节文字；适用于网页页签、README、macOS Finder/Dock 与 Windows 应用图标。`scripts/generate_icons.py` 使用固定 Pillow 12.2.0 和共享几何参数生成 SVG、1024/512/192/32 PNG、多尺寸 ICO 与现代 ICNS；无需下载素材或字体。README 保留完整项目概览，只新增 logo 和节点入口。

主页与教程使用统一 SVG 标识、SVG/ICO favicon 和 PNG touch icon。服务端公开白名单加入明确图标路径，移除 `/favicon.ico` 的空响应；桌面清单将图标列为必须资源，不整体复制项目。MyGo 配置依据固定源码的 schema：通用 `icon` 指向方形 1024 PNG，由 MyGo 转为 Windows 原生图标；`macos.icon` 指向生成的 ICNS，实际嵌入 `.app`。不改变用户数据或账户目录。

## 发布行为与兼容性

现有 macOS arm64 与 Windows amd64 原生构建、完整运行时、便携 ZIP 及自动检测 NSIS 的行为保留。推送 `v*` tag 会触发构建，tag 必须精确匹配 `desktop/mygo.json` 的稳定版本，当前为 `v0.1.0`。普通分支、PR、手动运行只生成 Actions artifact。

两个平台 job 仅具有只读仓库权限；单独的 `release` job 依赖整个 native matrix 成功，只对 tag push 生效，再下载两个平台的 artifact。`desktop/prepare_release.py` 先检查必需产物、白名单、重复项与逐项 SHA256，保留可选 NSIS，合并一份 SHA256SUMS 后才允许上传。缺平台、缺 DMG、被篡改的包或未知文件均阻止汇总。Release 创建使用 `--verify-tag`，不会由两平台并发发布或覆盖已有版本。

发布说明列明 OpenD / WebView2 依赖、数据边界及签名限制。macOS 只有 ad-hoc 完整性签名，没有 Developer ID 签名或 Apple 公证；Windows 没有 Authenticode 签名。没有自动更新功能。

## 实际验证

- Python 全量回归：202 项通过，含新的 Release 汇总验证（合并两平台校验、可选 NSIS、缺失、篡改、未知路径和版本不一致拒绝）。夹具仅验证汇总逻辑，不是 Windows 构建产物。
- Node 前端回归：64 项通过；原生 Go `go test -race ./...` 与 `go vet ./...` 通过。
- `actionlint v1.7.7` 校验工作流通过；`git diff --check` 通过。
- 在独立构建环境实际执行完整 macOS arm64 PyInstaller + MyGo 构建，真实 sidecar 协议、EOF、错误 challenge、首次报文期限、私有 HTTP 边界、最终宿主及中文空格路径解压验证均通过；解压后的 PATH 不含用户 Python。
- `.app/Contents/Info.plist` 版本为 0.1.0，引用的 ICNS 与源文件逐字节一致；`iconutil` 实际解码通过；`codesign --verify --deep --strict` 通过。此处只验证 ad-hoc 完整性，不等于开发者签名或公证。
- `hdiutil verify` 验证实际 DMG 通过。冻结 sidecar 的 favicon、SVG 和四种 PNG 全部返回 HTTP 200，MIME 正确且字节与源资产一致；favicon 不再返回 204。

本地成品（位于忽略的 `desktop/release/`）：

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `Flowdesk-macOS-arm64.dmg` | 33842176 | `affce52d64fbfd02d3680b61108f478b82e31224260f8fa5ffb4270b792f038d` |
| `Flowdesk-macOS-arm64.zip` | 41377120 | `10e6aa3d3d14ec3f11ff49a802acfc8e0f20b8ea46e2c1d73a886acd3cdead1a` |

当前节点未提交代码、创建 PR、推送 tag 或创建 Release。Windows 新图标的原生运行和 tag 发布仍须由后续 GitHub Actions 验证；本机 Mac 成品与离线汇总夹具不能替代 Windows 原生验收或已发布版本证明。
