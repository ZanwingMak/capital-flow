"""观察池回归测试；除前端静态数组外，所有输入和旧报告均为合成数据。"""
import json
import tempfile
import unittest
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

# 合成SDK占位只隔离导入副作用，采集入口在各测试中单独替换；不读写券商日志。
# 只替换SDK条目；整表patch.dict回滚会移除导入期间加载的numpy等原生模块。
_previous_futu = sys.modules.get('futu')
_synthetic_futu = ModuleType('futu')
for _name in ('AuType', 'KLType', 'OpenQuoteContext', 'PeriodType'):
    setattr(_synthetic_futu, _name, None)
setattr(_synthetic_futu, 'RET_OK', 0)
sys.modules['futu'] = _synthetic_futu
try:
    import analyze
finally:
    if _previous_futu is None:
        sys.modules.pop('futu', None)
    else:
        sys.modules['futu'] = _previous_futu


class UniverseTests(unittest.TestCase):
    """验证真实入口与有界JSON解析，不调用行情接口。"""

    def test_main_reads_real_frontend_universe(self):
        """真实入口必须向采集器传入48个不同代码并包含SPY。"""
        with patch.object(analyze, 'collect', side_effect=RuntimeError('synthetic-stop')) as collect:
            with self.assertRaisesRegex(RuntimeError, 'synthetic-stop'):
                analyze.main()
        symbols = collect.call_args.args[0]
        self.assertEqual(len(symbols), 48)
        self.assertEqual(len(set(symbols)), 48)
        self.assertIn('SPY', symbols)

    def test_real_frontend_array(self):
        """直接解析仓库中真实前端JSON数组。"""
        symbols = analyze.load_symbols(analyze.ROOT / 'dist/app.js')
        self.assertEqual(len(symbols), 48)
        self.assertEqual(symbols[0], 'SPY')

    def test_bounded_array_and_deduplication(self):
        """合成相邻数组不得混入观察池，重复代码按首次顺序去重。"""
        source = 'const usUniverse = ' + json.dumps([
            ['SPY', 'synthetic ] ; 名称', 'etf'], ['TEST', '合成', 'stock'], ['SPY', '重复', 'etf']
        ]) + ';\nconst other = [["WRONG", "合成", "stock"]];'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.js'
            path.write_text(source, encoding='utf-8')
            self.assertEqual(analyze.load_symbols(path), ['SPY', 'TEST'])

    def test_rejects_invalid_or_empty_arrays(self):
        """合成畸形、空池、错类型、缺基准和非JSON输入必须明确失败。"""
        sources = ['const other = [["SPY","合成","etf"]];',
                   'const usUniverse = [];', 'const usUniverse = [["SPY"]];',
                   'const usUniverse = [["TEST","合成","stock"]];',
                   'const usUniverse = [["SPY","合成","unknown"]];',
                   'const usUniverse = [["bad code","合成","stock"]];',
                   'const usUniverse = [["SPY",null,"etf"]];',
                   'const usUniverse = [["SPY","合成","etf"]',
                   "const usUniverse = [['SPY','合成','etf']];",
                   'const usUniverse = [["SPY","合成","etf"]] + other;']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.js'
            for source in sources:
                with self.subTest(source=source):
                    path.write_text(source, encoding='utf-8')
                    with self.assertRaisesRegex(RuntimeError, 'usUniverse'):
                        analyze.load_symbols(path)

    def test_parse_failure_preserves_old_validation(self):
        """入口解析失败必须在采集前停止，合成旧报告保持字节不变。"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'dist').mkdir()
            (root / 'dist/app.js').write_text('const usUniverse = [];', encoding='utf-8')
            data = root / '.data'
            data.mkdir()
            report = data / 'validation.json'
            report.write_bytes(b'{"synthetic": "old-report"}')
            with patch.object(analyze, 'ROOT', root), patch.object(analyze, 'DATA', data), \
                    patch.object(analyze, 'collect', return_value=({}, [])) as collect, \
                    patch.object(analyze, 'save_json') as save:
                with self.assertRaisesRegex(RuntimeError, 'usUniverse'):
                    analyze.main()
                collect.assert_not_called()
                save.assert_not_called()
            self.assertEqual(report.read_bytes(), b'{"synthetic": "old-report"}')
