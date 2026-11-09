"""Flowdesk桌面HTTP子进程：受管道控制，不提供HTTP退出或任意执行入口。"""
import hmac
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import traceback

VERSION = 1
MAX_MESSAGE = 16384
INIT_TIMEOUT = 10


def read_message(stream):
    """按字节限制一行JSON并拒绝重复字段、非对象或非有限数值。"""
    line = stream.readline(MAX_MESSAGE + 1)
    if not line:
        return None
    if len(line) > MAX_MESSAGE or not line.endswith(b'\n'):
        raise ValueError('控制报文过长或不完整。')
    message = json.loads(line, object_pairs_hook=unique_fields, parse_constant=invalid_constant)
    if not isinstance(message, dict):
        raise ValueError('控制报文必须是对象。')
    return message


def unique_fields(pairs):
    """拒绝重复JSON字段，避免宿主与子进程解释不一致。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('控制报文含重复字段。')
        result[key] = value
    return result


def invalid_constant(value):
    """拒绝JSON标准以外的数值常量。"""
    raise ValueError('控制报文含非法数值。')


def initial_message(stream):
    """用守护读取线程实现跨平台stdin握手超时。"""
    result = queue.Queue(maxsize=1)

    def read():
        """将读取结果或异常交给带超时的主线程。"""
        try:
            result.put(read_message(stream))
        except Exception as error:
            result.put(error)

    threading.Thread(target=read, daemon=True).start()
    try:
        message = result.get(timeout=INIT_TIMEOUT)
    except queue.Empty:
        raise ValueError('等待桌面宿主握手超时。') from None
    if isinstance(message, Exception):
        raise message
    if not isinstance(message, dict) or set(message) != {'type', 'version', 'instanceId', 'challenge', 'userData'}:
        raise ValueError('初始控制报文格式无效。')
    if message['type'] != 'init' or type(message['version']) is not int or message['version'] != VERSION:
        raise ValueError('不支持的桌面协议版本。')
    if not isinstance(message['challenge'], str) or not re.fullmatch('[0-9a-f]{64}', message['challenge']):
        raise ValueError('桌面挑战码无效。')
    if not isinstance(message['instanceId'], str) or not re.fullmatch('[0-9a-f]{32}', message['instanceId']):
        raise ValueError('桌面实例标识无效。')
    if not isinstance(message['userData'], str) or not Path(message['userData']).is_absolute():
        raise ValueError('用户数据目录必须是绝对目录。')
    return message


def configure(message):
    """仅使用宿主管理的用户目录，清除继承的网页监听与认证配置。"""
    directory = Path(message['userData']).resolve()
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).resolve()
    if directory == resources or resources in directory.parents or directory in resources.parents:
        raise ValueError('用户目录必须与应用资源分离。')
    for name in ('FLOW_HOST', 'FLOW_PORT', 'FLOW_TOKEN', 'FLOW_ALLOWED_ORIGINS', 'FLOWDESK_STATIC_DIR'):
        os.environ.pop(name, None)
    os.environ.update(FLOW_HOST='127.0.0.1', FLOW_PORT='0', FLOWDESK_USER_DATA_DIR=str(directory),
        FLOWDESK_DATA_DIR=str(directory / 'data'), FLOWDESK_PRIVATE_DIR=str(directory / 'private'),
        FLOWDESK_CONFIG_DIR=str(directory / 'config'))
    for name in ('data', 'config', 'logs'):
        (directory / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chdir(directory)


def control(stream, message, httpd, outcome):
    """EOF或受验证的shutdown结束自身服务，非法消息按失败关闭处理。"""
    try:
        command = read_message(stream)
        if command is not None:
            if set(command) != {'type', 'version', 'instanceId', 'challenge'} or command.get('type') != 'shutdown' \
                    or type(command.get('version')) is not int or command.get('version') != VERSION \
                    or not hmac.compare_digest(str(command.get('instanceId', '')), message['instanceId']) \
                    or not hmac.compare_digest(str(command.get('challenge', '')), message['challenge']):
                raise ValueError('退出控制报文无效。')
    except Exception:
        outcome.append(2)
        print('桌面控制协议中断，已停止本实例。', file=sys.stderr, flush=True)
    finally:
        # 宿主异常结束时，活跃SDK工作线程也不能无限延长本进程寿命。
        watchdog = threading.Timer(6, os._exit, args=(2,))
        watchdog.daemon = True
        watchdog.start()
        httpd.shutdown()


def run(protocol, stream):
    """原子绑定loopback随机端口并回显挑战；不探测或复用任何已有服务。"""
    message = initial_message(stream)
    configure(message)
    import server
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    httpd.daemon_threads = True
    httpd.block_on_close = False
    server.PORT = httpd.server_address[1]
    server.ALLOWED_ORIGINS.add(f'http://127.0.0.1:{server.PORT}')
    outcome = []
    collector = threading.Thread(target=server.collect_watch_minutes, daemon=True)
    try:
        protocol.write(json.dumps({'type': 'ready', 'version': VERSION, 'instanceId': message['instanceId'],
                                  'challenge': message['challenge'], 'port': server.PORT}) + '\n')
        protocol.flush()
        threading.Thread(target=control, args=(stream, message, httpd, outcome), daemon=True).start()
        collector.start()
        httpd.serve_forever(poll_interval=0.1)
    finally:
        server.COLLECTOR_STOP.set()
        server.WORKER.shutdown(wait=False, cancel_futures=True)
        httpd.server_close()
        if server.QUOTE_CONTEXT is not None:
            server.QUOTE_CONTEXT.close()
    return outcome[0] if outcome else 0


def main():
    """保留独立协议FD，Python与SDK的普通stdout全部重定向到stderr。"""
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    # 无缓冲FD不会在握手超时退出时被守护读取线程持有解释器缓冲锁。
    stream = os.fdopen(os.dup(sys.stdin.fileno()), 'rb', buffering=0)
    try:
        return run(protocol, stream)
    except Exception as error:
        print('Flowdesk桌面服务启动失败：' + type(error).__name__, file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 2
    finally:
        protocol.close()
        stream.close()


if __name__ == '__main__':
    raise SystemExit(main())
