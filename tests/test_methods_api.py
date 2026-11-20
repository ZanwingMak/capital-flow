"""Methods API boundaries use synthetic quotes and in-memory jobs only."""
import unittest
from email.message import Message
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import server
from test_market_methods import flat_rows, setup_rows


class MethodsAPITests(unittest.TestCase):
    def request(self, changes=None, headers=None):
        handler = server.Handler.__new__(server.Handler)
        query = {'symbol': 'TEST', 'asOf': '2000-04-09', **(changes or {})}
        handler.path = '/api/methods?' + urlencode(query, doseq=True)
        handler.headers = Message()
        for key, value in (headers or {}).items():
            handler.headers[key] = value
        handler.respond = Mock()
        with patch.object(server, 'TOKEN', ''), \
                patch.object(server, 'submit_job', return_value='synthetic-job') as submit, \
                patch.object(server, 'job_result', return_value=(202, {'job': 'synthetic-job'})):
            handler.do_GET()
        return handler.respond.call_args.args, submit

    def test_valid_request_submits_canonical_isolated_job(self):
        response, submit = self.request({'symbol': ' test ', 'feeBps': '0', 'slippageBps': '1'})
        self.assertEqual(response, (202, {'job': 'synthetic-job'}))
        key, worker, args = submit.call_args.args
        self.assertEqual(key[0], 'methods')
        self.assertIs(worker, server.fetch_methods)
        self.assertEqual(args, ({'symbol': 'TEST', 'as_of': '2000-04-09', 'market': 'US',
                                 'initial': 10000.0, 'fee_bps': 0.0, 'slippage_bps': 1.0},))
        _, changed = self.request({'slippageBps': '2'})
        self.assertNotEqual(key, changed.call_args.args[0])

    def test_invalid_requests_never_submit_jobs(self):
        for changes in ({'symbol': ['TEST', 'OTHER']}, {'asOf': ''}, {'market': 'HK'},
                        {'feeBps': 'nan'}, {'timeframe': '1m'}, {'formula': 'C'}):
            with self.subTest(changes=changes):
                response, submit = self.request(changes)
                self.assertEqual(response[0], 400)
                submit.assert_not_called()

    def test_foreign_origin_and_wrong_token_do_not_submit_jobs(self):
        response, submit = self.request(headers={'Origin': 'https://synthetic.invalid'})
        self.assertEqual(response[0], 403)
        submit.assert_not_called()
        handler = server.Handler.__new__(server.Handler)
        handler.path = '/api/methods?symbol=TEST&asOf=2000-04-09'
        handler.headers = Message()
        handler.respond = Mock()
        with patch.object(server, 'TOKEN', 'synthetic-token'), patch.object(server, 'submit_job') as submit:
            handler.do_GET()
        self.assertEqual(handler.respond.call_args.args[0], 401)
        submit.assert_not_called()

    def test_fetch_uses_completed_calendar_and_same_day_archives(self):
        rows = setup_rows('PA')
        completed = rows[-1]['date']
        params = dict(symbol='TEST', as_of='2000-04-15', market='US', initial=10000,
                      fee_bps=0, slippage_bps=0)
        with patch.object(server, 'intelligence_date', return_value=completed), \
                patch.object(server, 'intelligence_daily', return_value=rows) as daily, \
                patch.object(server.methods_service, 'archived_orderflow', return_value={'status': 'unavailable', 'rows': []}) as archive:
            result = server.fetch_methods(params)
        daily.assert_called_once_with('TEST', completed, 'US')
        archive.assert_called_once_with(server.DATA, 'TEST', completed)
        self.assertEqual(result['expectedCompletedAsOf'], completed)
        self.assertEqual(result['effectiveAsOf'], completed)
        self.assertEqual(result['data']['adjustment'], 'QFQ/current-vintage')
        self.assertEqual(result['methods']['PA']['backtest']['metrics']['closedTrades'], 1)

    def test_stale_daily_data_never_reads_a_different_day_archive(self):
        rows = flat_rows()
        with patch.object(server, 'intelligence_date', return_value='2000-04-15'), \
                patch.object(server, 'intelligence_daily', return_value=rows), \
                patch.object(server.methods_service, 'archived_orderflow') as archive:
            result = server.fetch_methods(dict(symbol='TEST', as_of='2000-04-15', market='US'))
        archive.assert_not_called()
        self.assertTrue(result['quality']['stale'])
        self.assertEqual(result['methods']['ORDERFLOW']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
