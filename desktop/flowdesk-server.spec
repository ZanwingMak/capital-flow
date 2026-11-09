# -*- mode: python ; coding: utf-8 -*-
"""只收集应用模块、明确列出的页面和依赖，不复制项目根目录。"""
import json
from importlib.metadata import distribution
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata

desktop = Path(SPECPATH)
project = desktop.parent
manifest = json.loads((desktop / 'resources.json').read_text(encoding='utf-8'))
datas = [(str(desktop / '.build' / 'assets' / 'dist'), 'dist')]
binaries = []
hiddenimports = manifest['applicationModules'] + ['sqlite3', 'zoneinfo', 'pandas', 'numpy', 'google.protobuf', 'dateutil']
futu_distribution = distribution('futu-api')
futu_pb = Path(futu_distribution.locate_file('futu/common/pb'))
# Futu导入会创建SDK日志；依据已安装发行包的文件表收集，构建时不导入SDK。
for file in futu_distribution.files:
    path = Path(str(file))
    if path.parts[0] == 'futu' and path.suffix == '.py':
        parts = path.with_suffix('').parts
        hiddenimports.append('.'.join(parts[:-1] if parts[-1] == '__init__' else parts))
        if path.parent.as_posix() == 'futu/common/pb' and path.stem != '__init__':
            # SDK生成的protobuf以Common_pb2等顶层名称相互导入。
            hiddenimports.append(path.stem)
datas += collect_data_files('futu', include_py_files=False)
binaries += collect_dynamic_libs('futu')
for package in ('Crypto', 'simplejson', 'tzdata'):
    package_data, package_binaries, package_imports = collect_all(package, include_py_files=False)
    datas += package_data
    binaries += package_binaries
    hiddenimports += [name for name in package_imports if '.SelfTest' not in name and '.tests' not in name]
for distribution in ('futu-api', 'pandas', 'numpy', 'protobuf', 'pycryptodome', 'simplejson', 'tzdata'):
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(project / 'desktop_sidecar.py')], pathex=[str(project), str(futu_pb)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    # launch.py的现有只读探测依赖unittest.mock，须保留该标准库模块。
    excludes=['pytest', 'tkinter', 'matplotlib', 'IPython', 'notebook'],
    noarchive=False, optimize=1,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name='flowdesk-server', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, contents_directory='_internal',
)
collection = COLLECT(executable, analysis.binaries, analysis.datas,
                     strip=False, upx=False, name='flowdesk-server')
