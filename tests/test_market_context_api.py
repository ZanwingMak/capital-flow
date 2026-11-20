"""Public context uses its own source, with the same origin/token boundary."""
import unittest
from email.message import Message
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import server


class MarketContextAPITests(unittest.TestCase):
    def request(self, params=None, headers=None, token='', submission_error=None):
        handler = server.Handler.__new__(server.Handler)
        handler.path = '/api/market-context?' + urlencode(
            {'asOf': '2000-01-03', **(params or {})}, doseq=True)
        handler.headers = Message()
        for name, value in (headers or {}).items():
            handler.headers[name] = value
        handler.respond = Mock()
        with patch.object(server, 'TOKEN', token), \
                patch.object(server, 'submit_job', return_value='synthetic', side_effect=submission_error) as submit, \
                patch.object(server, 'job_result', return_value=(202, {'jobId': 'synthetic'})):
            handler.do_GET()
        return handler.respond.call_args.args, submit

    def test_context_is_an_independent_dated_job_without_opend(self):
        response, submit = self.request()
        self.assertEqual(response, (202, {'jobId': 'synthetic'}))
        key, worker, args = submit.call_args.args
        self.assertEqual(key[:2], ('market-context', '2000-01-03'))
        self.assertIs(worker, server.market_context.get_report)
        self.assertEqual(args, ('2000-01-03',))

    def test_invalid_duplicate_future_and_foreign_inputs_never_schedule(self):
        for params in ({'asOf': ''}, {'asOf': '2000-1-3'}, {'asOf': '2000-02-30'},
                       {'asOf': '9999-01-01'}, {'asOf': ['2000-01-03', '2000-01-04']},
                       {'market': 'HK'}, {'market': ['US', 'US']},
                       {'url': 'http://127.0.0.1/'}, {'api_key': 'synthetic'}):
            with self.subTest(params=params):
                response, submit = self.request(params)
                self.assertEqual(response[0], 400)
                submit.assert_not_called()

    def test_origin_and_token_checks_precede_scheduling(self):
        for headers, token, expected in (
                ({'Origin': 'https://synthetic.invalid'}, '', 403),
                ({}, 'synthetic', 401),
                ({'Authorization': 'Bearer wrong'}, 'synthetic', 401)):
            response, submit = self.request(headers=headers, token=token)
            self.assertEqual(response[0], expected)
            submit.assert_not_called()
        response, submit = self.request(headers={'Authorization': 'Bearer synthetic'}, token='synthetic')
        self.assertEqual(response[0], 202)
        submit.assert_called_once()

    def test_busy_queue_does_not_echo_internal_error(self):
        response, _ = self.request(submission_error=RuntimeError('synthetic private path'))
        self.assertEqual(response[0], 503)
        self.assertNotIn('private', str(response))


if __name__ == '__main__':
    unittest.main()
