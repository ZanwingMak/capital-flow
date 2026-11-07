"""直接调用HTTP处理方法的合成API测试，不绑定端口或启动后台服务。"""
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import server


class ResearchAPITests(unittest.TestCase):
    """验证新模式验证、默认兼容和异步作业参数隔离。"""

    def request(self, **params):
        """创建无socket的处理器，只捕获响应并模拟任务提交结果。"""
        handler = server.Handler.__new__(server.Handler)
        query = {'symbol': 'TEST', 'date': '2026-11-02', **params}
        handler.path = '/api/research?'+urlencode(query, doseq=True)
        handler.headers = {}
        handler.respond = Mock()
        with patch.object(server, 'TOKEN', ''), \
                patch.object(server, 'history_bounds', return_value=('2026-01-01', '2026-11-06')), \
                patch.object(server, 'submit_job', return_value='synthetic-job') as submit, \
                patch.object(server, 'job_result', return_value=(202, {'synthetic': True})):
            handler.do_GET()
        return handler.respond.call_args.args, submit

    def test_default_mode_is_retrospective(self):
        """旧接口不传mode时显式传递兼容复盘口径。"""
        response, submit = self.request()
        self.assertEqual(response[0], 202)
        self.assertEqual(submit.call_args.args[2][-1], 'retrospective')

    def test_strict_mode_has_distinct_job_key(self):
        """严格模式必须传到计算层，并与默认模式使用不同任务键。"""
        response, strict = self.request(mode='strict-as-of')
        _, default = self.request()
        self.assertEqual(response[0], 202)
        self.assertEqual(strict.call_args.args[2][-1], 'strict-as-of')
        self.assertNotEqual(strict.call_args.args[0], default.call_args.args[0])

    def test_invalid_and_ambiguous_modes_are_400(self):
        """未知、空白和重复模式不能静默退回复盘。"""
        for mode in ('bad', '', ['retrospective', 'strict-as-of']):
            with self.subTest(mode=mode):
                response, submit = self.request(mode=mode)
                self.assertEqual(response[0], 400)
                submit.assert_not_called()

    def test_existing_numeric_and_kind_validation(self):
        """新参数不能削弱原有数值和事件类型边界。"""
        for invalid in ({'percentile': 'nan'}, {'percentile': 'inf'}, {'minimum': 'nan'},
                        {'days': '0'}, {'kind': 'tail30'}, {'direction': 'wrong'}):
            with self.subTest(invalid=invalid):
                response, submit = self.request(**invalid)
                self.assertEqual(response[0], 400)
                submit.assert_not_called()

    def test_fetch_pipeline_passes_strict_mode(self):
        """模拟采集依赖确认真实fetch入口将严格模式传入构建层。"""
        with patch.object(server, 'get_context', return_value=object()), \
                patch.object(server, 'trading_dates', return_value=['2026-11-02']), \
                patch.object(server, 'daily_record', return_value={'synthetic': True}), \
                patch.object(server, 'history_bounds', return_value=('2026-01-01', '2026-11-06')), \
                patch.object(server, 'collect_symbol_minutes', return_value=[]), \
                patch.object(server.research, 'build_research', return_value={}) as build:
            server.fetch_research('TEST', '2026-11-02', 20, 1, 90, 0, 20, 'daily', 'out', 'US', mode='strict-as-of')
        self.assertEqual(build.call_args.args[-1], 'strict-as-of')
