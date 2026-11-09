"""在目标平台构建含完整Python运行时的MyGo桌面包，并执行原生冒烟验证。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

DESKTOP = Path(__file__).resolve().parent
PROJECT = DESKTOP.parent
BUILD = DESKTOP / '.build'
MANIFEST = json.loads((DESKTOP / 'resources.json').read_text(encoding='utf-8'))


def run(command, cwd=DESKTOP, timeout=1800):
    """执行参数数组并继承构建输出，失败立即结束当前构建。"""
    environment = dict(os.environ, GOTOOLCHAIN='go1.27.3', PYTHONDONTWRITEBYTECODE='1')
    subprocess.run([str(part) for part in command], cwd=cwd, env=environment, check=True, timeout=timeout)


def stage_assets(source=PROJECT / 'dist', destination=BUILD / 'assets' / 'dist'):
    """按清单复制公开资产，拒绝路径穿越、符号链接和缺失的必要文件。"""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    source = source.resolve()
    for name in MANIFEST['requiredStatic'] + MANIFEST['optionalStatic']:
        relative = Path(name)
        if relative.is_absolute() or any(part in {'.', '..'} or part.startswith('.') for part in relative.parts):
            raise ValueError('资源清单包含非法路径：' + name)
        path = source / relative
        if not path.exists() and name in MANIFEST['optionalStatic']:
            continue
        if not path.is_file() or path.resolve() != path or any(parent.is_symlink() for parent in path.parents if parent != source.parent):
            raise ValueError('资源缺失或不允许的符号链接：' + name)
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output)
    return destination


def audit_resources(directory):
    """打包前后检查敏感文件名，绝不读取.env、数据库或账户记录内容。"""
    for path in directory.rglob('*'):
        name = path.name.lower()
        if name in {'.data', '.git', 'accounts', 'holdings', 'portfolio-tests'} or name.startswith('.env') \
                or name.endswith(('.sqlite', '.sqlite3', '.db', '.sqlite3-wal', '.sqlite3-shm', '.csv')):
            raise ValueError('打包资源含禁止文件：' + str(path.relative_to(directory)))


def build_sidecar():
    """PyInstaller onedir包含解释器、SDK、原生依赖和时区，不要求用户安装Python。"""
    stage_assets()
    target = DESKTOP / 'staging' / 'sidecar'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
         '--distpath', target, '--workpath', BUILD / 'pyinstaller', DESKTOP / 'flowdesk-server.spec'])
    license_dir = target / 'licenses'
    shutil.copytree(DESKTOP / 'licenses', license_dir)
    audit_resources(target)
    executable = target / 'flowdesk-server' / ('flowdesk-server.exe' if sys.platform == 'win32' else 'flowdesk-server')
    run([sys.executable, DESKTOP / 'smoke.py', '--sidecar', executable], timeout=90)


def archive_windows(source, output):
    """生成保留完整sidecar目录结构的Windows可下载便携包。"""
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file() and not path.name.startswith('flowdesk-setup-'):
                archive.write(path, Path('Flowdesk') / path.relative_to(source))


def sha256_file(path):
    """流式校验成品并立即关闭文件，兼容Windows独占文件语义。"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_archive(archive, target):
    """实际解压下载包并在无用户Python的PATH下运行原生宿主。"""
    with tempfile.TemporaryDirectory(prefix='Flowdesk extracted 中文 ') as temporary:
        root = Path(temporary)
        if target.startswith('darwin/'):
            run(['ditto', '-x', '-k', archive, root])
            host = root / 'Flowdesk.app/Contents/MacOS/Flowdesk'
            resource_dir = root / 'Flowdesk.app/Contents/Resources'
        else:
            with zipfile.ZipFile(archive) as package:
                package.extractall(root)
            host = root / 'Flowdesk/Flowdesk.exe'
            resource_dir = root / 'Flowdesk/sidecar'
        audit_resources(resource_dir)
        environment = dict(os.environ)
        environment['PATH'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32') if sys.platform == 'win32' else '/usr/bin:/bin'
        subprocess.run([str(host), '--headless', '--data-dir', str(root / '合成 User Data')],
                       cwd=root, env=environment, check=True, timeout=60)


def build_host(target, skip_dmg=False, installer=False):
    """使用固定MyGo模块构建宿主，再对最终native可执行文件做无界面验证。"""
    command = ['go', 'run', 'github.com/egoist/mygo/cmd/mygo', 'build', '-platform', target, '-skip-notarize']
    if skip_dmg:
        command.append('-skip-dmg')
    if not installer:
        command.append('-skip-installer')
    run(command)
    folder = DESKTOP / 'build' / target.replace('/', '-')
    host = folder / ('Flowdesk.app/Contents/MacOS/Flowdesk' if target.startswith('darwin/') else 'Flowdesk.exe')
    if not host.is_file():
        raise FileNotFoundError('MyGo未生成最终原生宿主：' + str(host))
    audit_resources(folder / 'Flowdesk.app/Contents/Resources' if target.startswith('darwin/') else folder / 'sidecar')
    # Put smoke data in a fresh directory; never reuse default user holdings.
    with tempfile.TemporaryDirectory(prefix='flowdesk packaged 中文 ') as temporary:
        run([host, '--smoke-test', '--data-dir', Path(temporary) / 'Synthetic Data'], timeout=60)
    release = DESKTOP / 'release'
    release.mkdir(exist_ok=True)
    if target.startswith('darwin/'):
        output = release / 'Flowdesk-macOS-arm64.zip'
        run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', folder / 'Flowdesk.app', output])
        if not skip_dmg:
            images = list(folder.glob('*.dmg'))
            if len(images) != 1:
                raise FileNotFoundError('MyGo没有生成唯一的macOS磁盘映像。')
            shutil.copy2(images[0], release / 'Flowdesk-macOS-arm64.dmg')
    else:
        output = release / 'Flowdesk-Windows-amd64.zip'
        archive_windows(folder, output)
        installers = list(folder.glob('flowdesk-setup-*.exe'))
        if installer and len(installers) != 1:
            raise FileNotFoundError('MyGo没有生成Windows安装程序。')
        if installers:
            shutil.copy2(installers[0], release / 'Flowdesk-Windows-amd64-Setup.exe')
    verify_archive(output, target)
    artifacts = sorted(path for path in release.iterdir() if path.is_file() and path.name != 'SHA256SUMS.txt')
    (release / 'SHA256SUMS.txt').write_text(''.join(
        sha256_file(path) + '  ' + path.name + '\n' for path in artifacts), encoding='utf-8')


def main():
    """只允许在本机目标架构构建原生Python侧车，避免伪装为交叉构建成品。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sidecar-only', action='store_true')
    parser.add_argument('--skip-dmg', action='store_true')
    parser.add_argument('--installer', action='store_true', help='Windows上启用MyGo NSIS安装包构建')
    args = parser.parse_args()
    target = {('darwin', 'arm64'): 'darwin/arm64', ('win32', 'amd64'): 'windows/amd64'}.get((sys.platform, platform.machine().lower()))
    if target is None:
        parser.error('仅支持原生macOS arm64或Windows amd64构建。')
    if sys.prefix == sys.base_prefix:
        parser.error('请在单独的构建venv中安装requirements-build.txt后运行。')
    nsis_available = shutil.which('makensis') or any(
        (Path(os.getenv(variable) or 'C:/missing') / 'NSIS/makensis.exe').is_file()
        for variable in ('ProgramFiles', 'ProgramFiles(x86)'))
    build_sidecar()
    if not args.sidecar_only:
        build_host(target, args.skip_dmg, args.installer or bool(nsis_available))


if __name__ == '__main__':
    main()
