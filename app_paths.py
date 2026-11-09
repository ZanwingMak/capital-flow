"""网页源码与冻结桌面运行时共用的只读资源、可写数据目录。"""
import os
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parent


def configured(name, fallback):
    """只接受绝对目录覆盖，不在解析路径时创建或读取文件。"""
    path = Path(os.getenv(name) or fallback).expanduser()
    if not path.is_absolute():
        raise ValueError(name + ' 必须是绝对目录。')
    return path.resolve()


def user_data_dir():
    """按平台选择桌面应用数据目录，也允许宿主显式指定。"""
    if sys.platform == 'win32':
        fallback = Path(os.getenv('APPDATA') or Path.home() / 'AppData/Roaming') / 'Flowdesk'
    elif sys.platform == 'darwin':
        fallback = Path.home() / 'Library/Application Support/Flowdesk'
    else:
        fallback = Path(os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config') / 'Flowdesk'
    return configured('FLOWDESK_USER_DATA_DIR', fallback)


def data_dir(source_root=None):
    """源码模式保留.data兼容，冻结运行时默认写入用户目录data。"""
    fallback = user_data_dir() / 'data' if getattr(sys, 'frozen', False) else Path(source_root or SOURCE) / '.data'
    return configured('FLOWDESK_DATA_DIR', fallback)


def static_dir():
    """静态页面默认来自打包的只读_MEIPASS/dist资源。"""
    fallback = Path(getattr(sys, '_MEIPASS', SOURCE)) / 'dist'
    return configured('FLOWDESK_STATIC_DIR', fallback)


def config_dir():
    """桌面密钥配置独立保存，源码模式兼容项目.env。"""
    fallback = user_data_dir() / 'config' if getattr(sys, 'frozen', False) else SOURCE
    return configured('FLOWDESK_CONFIG_DIR', fallback)
