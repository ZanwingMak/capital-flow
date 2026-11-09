# 节点12：工作台导航与任务布局

日期：2026-11-09。前端实现基于`40baf97`。本节点完成首页任务层级与私有弹窗导航，沿用原有行情、研究、台账和会话逻辑。

## 实现范围

- 首页标题调整为“行情观察与研究工作台”；三个有效锚点连接行情、事件研究与私有工作台入口。行情控件与研究动作分开，研究入口按问题分组。
- 私有弹窗拆为账户概览、记录操作、CSV导入、事件证据、研究档案和压力实验室；账户、连接状态与操作消息保持可见，仅当前任务内容滚动。
- 原生ARIA页签支持左右循环、Home、End和漫游焦点。非当前面板同时hidden/inert；切页保留原输入与预览，从新任务顶部开始。
- 未开启会话时工作区隐藏，流程明确。长规则改用details渐进展示，未知成本、费用和已成交事实等语义保留。
- 关闭沿用既有watchDialogClosure的close与open属性观察，清理私有内容并重置概览；不增加网络、存储或地址写入。
- 延续现有配色、品牌和系统字体，主要点击目标40–44px；新增过渡150ms，减少动态效果时停用。

本节点文件：`dist/index.html`、`dist/styles.css`、`dist/private.css`、`dist/workspace-nav.js`、`dist/private.js`、`tests/test_workspace_nav.js`、`docs/ui-workbench.md`和本文。private.js仅增加可选挂载、会话展示和关闭重置三处导航接线。原有154个ID、74个输入/选择/文本字段及其所属表单和约束全部保留，无重复ID或嵌套表单。

## 实际离线验证

先增加七项测试，执行`node --test tests/test_workspace_nav.js`：七项全部红灯，六项因缺少实际导航模块失败，一项因缺少首页任务锚点失败。实现后七项通过，再补充线上页面真实绑定用例，最终新增八项通过。

测试从生产index.html建立内存DOM边界，加载实际导航、private-research与private.js，使用Node EventTarget派发真实监听事件；核对点击、方向键、Home/End、唯一Tab入口、hidden/inert、切页不修改值、滚动归零、会话说明显隐、旧DOM兼容、原生关闭和后台open移除清理、线上主动提交也不发私有请求。它们不是浏览器布局或原生表单校验测试。

| 检查 | 实际结果 |
| --- | --- |
| `node --test tests/test_*.js` | 45项通过：既有37项 + 本节点8项 |
| 指定Python解释器全量unittest | 144项通过：原有141项基线 + 工作区并行新增3项 |
| JS语法检查 | 全部dist与tests下的JS通过 |
| HTML独立结构与基线对照 | 全部原ID、字段/约束保留，结构闭合，无重复或嵌套表单 |
| `git diff --check` | 通过 |

Python使用`$HOME/Code/my_project/capital-flow/.venv/bin/python`；TMPDIR与tempfile.tempdir固定到`$HOME/.hermes/cache/scratch/flowdesk-review/portfolio-tests`。审计钩子禁止socket.connect/socket.bind、敏感配置及该目录外数据库。首次运行时运行器误将合法SQLite只读file: URI当普通路径，导致一项失败；修正运行器URI解析后全量通过，未修改业务代码。测试中的启动/安装文字来自现有Mock。

可在约定隔离环境复跑：

```sh
node --test tests/test_*.js
TMPDIR=$HOME/.hermes/cache/scratch/flowdesk-review/portfolio-tests PYTHONDONTWRITEBYTECODE=1 $HOME/Code/my_project/capital-flow/.venv/bin/python - <<'PY'
import os, sys, tempfile, unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit
root = Path(os.environ['TMPDIR']).resolve()
tempfile.tempdir = str(root)
def guard(event, args):
    """仅允许合成数据库，并拒绝网络、服务和敏感配置读取。"""
    if event in {'socket.connect', 'socket.bind'}:
        raise AssertionError('禁止网络或服务')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0]))
        if path.name.startswith('.env') or path.name in {'credentials', 'credentials.json'}:
            raise AssertionError('禁止读取敏感配置')
        if path.suffix in {'.db', '.sqlite', '.sqlite3'} and root not in path.resolve().parents:
            raise AssertionError('禁止测试根外数据库')
    if event == 'sqlite3.connect' and args[0] != ':memory:':
        value = os.fsdecode(args[0])
        path = Path(unquote(urlsplit(value).path) if value.startswith('file:') else value).resolve()
        if root not in path.parents:
            raise AssertionError('禁止测试根外数据库')
sys.addaudithook(guard)
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
sys.exit(not result.wasSuccessful())
PY
for file in dist/*.js tests/*.js; do node --check "$file" || exit 1; done
git diff --check
```

本轮未启动真实服务或浏览器，未联网、读取凭据/真实财务文件或安装依赖。未修改后端、desktop或README；工作区并行出现的后端与日历测试改动不属于本节点交付。

## 父代理独立浏览器验收

父代理使用独立8794服务、固定已发布后端与本节点前端副本，以及既有合成账户验收，避免并行桌面后端开发干扰。1440px与390px下页面均无整体横向溢出；账户在任务切换中保持可见，证据草稿切页后保留。真实键盘End切换到压力实验室，后台关闭清空私有内容并重置概览。

发现并修复窄屏焦点问题：只调用focus时后台页不保证滚动至选中页签，现显式调整页签条scrollLeft，避免滚动外层页面。新增用例先以0不等于240失败，修复后导航9项通过；真实390px复验活动页签完整可见，关闭后导航和私有内容正确清理。滚动取整处理亚像素边界。

## 父任务接入与浏览器检查清单

1. 将`/workspace-nav.js`映射到`dist/workspace-nav.js`并加入静态资源允许列表；确认带版本查询参数的脚本返回JS，既有私有路径保护仍生效。HTML中顺序为private-research、stress-lab、workspace-nav、private。本节点未修改服务端允许列表。
2. 在父任务控制的合成环境验收360、768、1440px宽度，检查主页面无整体横向滚动，行情表、CSV预览、压力表只在自身区域滚动，六个页签可横向查看。检查短窗口、200%缩放与移动端键盘弹起后关闭按钮、账户和当前任务仍可操作。
3. 不连接数据时核对空态、缺失值、连接提示；再用合成响应核对加载、错误、重试、禁用控件。验证市场选择、自选添加、日期、表格筛选排序和导出；逐个打开分组研究按钮，确认没有失效入口。
4. 打开私有弹窗，确认只有流程说明，未自动开启会话或读取数据库。显式开启合成会话后，选择/创建账户；每个任务页签始终显示账户与连接状态。用Tab、左右键、Home、End验收焦点可见、ARIA关系及隐藏面板不进入键盘遍历。
5. 在记录、证据和研究表单填写合成草稿，来回切页确认原值、CSV冻结状态和账户选择保留，且不增加API请求；实际提交任一表单，确认隐藏面板中的required输入不影响原生校验。展开规则说明，核对费用、未知成本、更正和截止时间含义仍可获取。
6. 运行既有合成台账追加、CSV预览导入、证据版本、冻结研究、压力实验流程。确认忙碌时账户、页签与任务都受原fieldset inert约束，状态消息仍可读。
7. 分别用关闭按钮、Esc和后台标签页移除dialog.open关闭；重开时回到账户概览，令牌、表单、CSV原文、报告和压力输入均已清空。切页不改变URL或持久存储，开启/关闭安全边界与既有私有API保持一致。
8. 验收GitHub Pages打开和手动提交均不能访问本机私有接口；检查减少动态效果、触控目标、长文本、中文系统字体及数字列。父任务记录实际浏览器结果后再进行最终发布。
