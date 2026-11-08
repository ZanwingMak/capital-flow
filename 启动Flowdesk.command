#!/bin/bash
# 从入口所在目录定位项目，支持 Finder 双击及包含空格的路径。
PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)" || exit 1
export PYTHONDONTWRITEBYTECODE=1
LAUNCH_ARGUMENT_COUNT="$#"

# 只选择可用的 Python 3.10+，优先项目环境，不安装系统软件。
find_python() {
    local candidate
    for candidate in "$PROJECT_DIR/.venv/bin/python" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 "$(command -v python3)"; do
        if [ -x "$candidate" ] && "$candidate" -I -B -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
            PYTHON_BIN="$candidate"
            return 0
        fi
    done
    return 1
}

# 交互失败时保留中文提示供双击用户查看，自动验收不等待输入。
finish() {
    local result="$1"
    if [ "$result" -ne 0 ] && [ "$LAUNCH_ARGUMENT_COUNT" -eq 0 ] && [ -t 0 ] && [ -t 1 ]; then
        read -r -p '按回车关闭此窗口…' _
    fi
    exit "$result"
}

if ! find_python; then
    echo '未找到可用的 Python 3.10 或更新版本。请先自行安装 Python（包含 venv/pip），再双击重试。'
    finish 1
fi
"$PYTHON_BIN" -B "$PROJECT_DIR/launch.py" "$@"
finish "$?"
