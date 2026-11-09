"""指标端点及共享异步错误边界；仅使用合成行情与内存任务。"""
import concurrent.futures
import unittest
from unittest.mock import patch

import server


class IndicatorAPITests(unittest.TestCase):
    def test_async_provider_errors_never_return_exception_body(self):
        for error_type, status in ((ValueError, 400), (RuntimeError, 503), (OSError, 502)):
            with self.subTest(error=error_type.__name__):
                future = concurrent.futures.Future()
                future.set_exception(error_type('Authorization=Bearer SYNTHETIC_SECRET /synthetic/private/config'))
                with patch.dict(server.JOBS, {'synthetic': {'future': future, 'progress': {}}}, clear=True):
                    actual, payload = server.job_result('synthetic')
                self.assertEqual(actual, status)
                self.assertNotIn('SYNTHETIC_SECRET', str(payload))
                self.assertNotIn('/synthetic/private', str(payload))
                self.assertTrue(payload['error'])

    def test_loader_only_requests_completed_daily_bars(self):
        params = {'symbol': 'TEST', 'as_of': '2026-11-09', 'market': 'US'}
        captured = {}

        def report(loader, **values):
            captured.update(values)
            return loader(values['symbol'], values['as_of'], values['market'])

        with patch.object(server, 'intelligence_date', return_value='2026-11-06'), \
                patch.object(server, 'intelligence_daily', return_value=[]) as daily, \
                patch.object(server.indicator_service, 'get_report', side_effect=report):
            result = server.fetch_indicators(params)
        daily.assert_called_once_with('TEST', '2026-11-06', 'US')
        self.assertEqual(captured['as_of'], '2026-11-09')
        self.assertEqual(result['timezone'], 'America/New_York')
        self.assertEqual(result['adjustment'], 'QFQ/current-vintage')


if __name__ == '__main__':
    unittest.main()
