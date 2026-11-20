"""Synthetic fixtures for public context; never use account data."""
import importlib
import unittest


class PositioningTests(unittest.TestCase):
    def test_public_csv_uses_latest_eligible_date_without_rescaling(self):
        mc = importlib.import_module('market_context')
        text = ('date,price,dix,gex\n2026-11-19,123.0,0.12,-300.0\n'
                '2026-11-17,111.0,0.23,200.0\n'
                '2026-11-18,122.0,0.34,100.0\n')
        result = mc.parse_positioning(text, '2026-11-18')
        self.assertEqual(result['observationDate'], '2026-11-18')
        self.assertEqual(result['dix'], .34)
        self.assertEqual(result['gex'], 100.0)
        self.assertEqual(result['spx'], 122.0)
        self.assertEqual(result['status'], 'available')
        self.assertFalse(result['pointInTime'])

    def test_positioning_before_history_explains_absence(self):
        import market_context as mc
        result = mc.parse_positioning('date,price,dix,gex\n2026-11-17,7000,.4,0\n', '2026-11-01')
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('No observation', result['reason'])
        self.assertIsNone(result['observationDate'])

    def test_positioning_rejects_invalid_ratio_and_nonfinite_values(self):
        import market_context as mc
        for dix, gex, spx in (('43', '0', '7000'), ('.4', 'NaN', '7000'), ('.4', '0', 'inf')):
            result = mc.parse_positioning('date,price,dix,gex\n2026-11-17,' + ','.join((spx, dix, gex)) + '\n', '2026-11-18')
            self.assertEqual(result['status'], 'unavailable')
        result = mc.parse_positioning('date,price,dix,gex\n2026-11-17,7000,0,0\n', '2026-11-18')
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['gex'], 0)


def synthetic_page(series='DGS10', day='2020-01-02', value='1.23'):
    return (f'<link rel="canonical" href="https://fred.stlouisfed.org/series/{series}">'
            f'<div class="default-text"><span class="series-meta-value">{day}:</span>'
            f'<span class="series-meta-observation-value">{value}</span></div>')


class LatestPageTests(unittest.TestCase):
    def test_monthly_period_uses_fred_first_day_convention_and_index_units(self):
        import market_context as mc
        result = mc.parse_macro_page('CPIAUCSL', synthetic_page('CPIAUCSL', 'Feb 2020', '123.456'), '2020-02-02')
        self.assertEqual(result['observationDate'], '2020-02-01')
        self.assertEqual(result['observationPeriod'], 'Feb 2020')
        self.assertEqual(result['units'], 'Index 1982-1984=100')
        with self.assertRaises(ValueError):
            mc.parse_macro_page('DGS10', synthetic_page(day='Feb 2020'), '2020-02-02')

    def test_fallback_pairs_widget_date_value_and_never_invents_history(self):
        import market_context as mc
        result = mc.parse_macro_page('DGS10', synthetic_page(), '2020-01-03')
        self.assertEqual((result['value'], result['observationDate']), (1.23, '2020-01-02'))
        self.assertEqual(result['retrievalMode'], 'latest-page')
        self.assertFalse(result['pointInTime'])
        result = mc.parse_macro_page('DGS10', synthetic_page(), '2020-01-01')
        self.assertIsNone(result['value'])
        self.assertIsNone(result['observationDate'])
        self.assertIn('historical', result['reason'])

    def test_rejects_wrong_identity_split_widgets_and_missing_values(self):
        import market_context as mc
        for page in (synthetic_page('DGS2'),
                     synthetic_page().replace('</span><span', '</span></div><div class="default-text"><span'),
                     synthetic_page(value='.'), synthetic_page(day='2020-02-30'),
                     synthetic_page() + synthetic_page(value='8.88')):
            with self.assertRaises(ValueError):
                mc.parse_macro_page('DGS10', page, '2020-01-03')

    def test_csv_failure_falls_back_to_official_page(self):
        from unittest.mock import patch
        import market_context as mc
        with patch.object(mc, '_download', side_effect=[ValueError('bad CSV'), synthetic_page()]) as download:
            text = mc._fetch('DGS10')
        self.assertEqual(download.call_count, 2)
        self.assertEqual(download.call_args.args[0], 'https://fred.stlouisfed.org/series/DGS10')
        self.assertEqual(mc.parse_macro_page('DGS10', text, '2020-01-03')['value'], 1.23)


class MacroTests(unittest.TestCase):
    def test_fred_skips_missing_observations_and_preserves_units(self):
        import market_context as mc
        result = mc.parse_macro('DGS10',
            'observation_date,DGS10\n2026-11-17,4.3\n2026-11-18,.\n2026-11-19,9.9\n',
            '2026-11-18')
        self.assertEqual(result['value'], 4.3)
        self.assertEqual(result['observationDate'], '2026-11-17')
        self.assertEqual(result['units'], 'Percent')
        self.assertFalse(result['pointInTime'])
        self.assertEqual(result['vintageMode'], 'latest-revised')

    def test_invalid_and_empty_data_never_become_zero(self):
        import market_context as mc
        for value in ('.', '', 'NaN', 'inf', '-inf', 'nonsense'):
            result = mc.parse_macro('DGS10', 'DATE,DGS10\n2026-11-17,' + value + '\n', '2026-11-18')
            self.assertIsNone(result['value'])
            self.assertIsNone(result['observationDate'])
            self.assertEqual(result['status'], 'unavailable')
        for day in ('2026-11-01', '2026-11-18'):
            result = mc.parse_positioning('date,price,dix,gex\n2026-11-17,7000,NaN,0\n', day)
            self.assertEqual(result['status'], 'unavailable')
            self.assertIsNone(result['dix'])
        with self.assertRaises(ValueError):
            mc.parse_macro('DGS10', '<html>blocked</html>', '2026-11-18')


class AuthorizationTests(unittest.TestCase):
    def test_only_explicit_one_authorizes_and_revocation_hides_cached_values(self):
        from unittest.mock import patch
        import market_context as mc
        for flag in ('', 'true', 'yes', '0', '1'):
            with patch.dict('os.environ', {'FLOW_SQUEEZEMETRICS_AUTHORIZED': flag}):
                self.assertEqual(mc._squeeze_authorized(), flag == '1')
                if flag == '1':
                    with patch.object(mc, '_download', return_value='synthetic') as fetch:
                        self.assertEqual(mc._fetch('SQUEEZEMETRICS'), 'synthetic')
                        fetch.assert_called_once()

    def test_default_never_schedules_or_fetches_squeezemetrics(self):
        from unittest.mock import patch
        import market_context as mc
        with patch.dict('os.environ', {'FLOW_SQUEEZEMETRICS_AUTHORIZED': ''}):
            with patch.object(mc, '_fetch', return_value='synthetic') as fetch:
                mc._cache.clear()
                mc._collect()
                self.assertNotIn('SQUEEZEMETRICS', [call.args[0] for call in fetch.call_args_list])
            with patch.object(mc.urllib.request, 'build_opener') as opener:
                with self.assertRaises(PermissionError):
                    mc._fetch('SQUEEZEMETRICS')
                opener.assert_not_called()
            values = {key: ('DATE,' + key + '\n2020-01-02,1.23\n', None) for key in mc.FRED_SERIES}
            values['SQUEEZEMETRICS'] = ('date,price,dix,gex\n2020-01-02,123,.34,100\n', None)
            with patch.object(mc, '_collect', return_value=values):
                report = mc.get_report('2020-01-03')
                self.assertIsNone(report['positioning']['dix'])
                self.assertEqual(report['positioning']['status'], 'manual-or-licensed')
        mc._cache.clear()


class ReportTests(unittest.TestCase):
    def test_cache_keeps_actual_retrieval_time_separate_from_report_assembly(self):
        from unittest.mock import patch
        import market_context as mc
        mc._cache.clear()
        mc._inflight.clear()
        def fetch(key):
            return 'DATE,' + key + '\n2020-01-02,1.23\n'
        with patch.dict('os.environ', {'FLOW_SQUEEZEMETRICS_AUTHORIZED': ''}), patch.object(mc, '_fetch', side_effect=fetch) as transport:
            first = mc.get_report('2020-01-03')
            second = mc.get_report('2020-01-03')
            self.assertEqual(transport.call_count, len(mc.FRED_SERIES))
        self.assertTrue(first['macro'][0]['retrievedAt'].endswith('Z'))
        self.assertEqual(first['macro'][0]['retrievedAt'], second['macro'][0]['retrievedAt'])
        self.assertNotEqual(first['collectedAt'], second['collectedAt'])
        self.assertEqual(second['collectedAtMeaning'], 'report-assembly-time')
        self.assertEqual(second['cacheTtlSeconds'], 600)
        mc._cache.clear()

    def test_report_contract_has_gated_metadata_and_honest_failures(self):
        from unittest.mock import patch
        import market_context as mc
        with patch.object(mc, '_collect', return_value={key: (None, 'Public fetch failed: TimeoutError') for key in mc.FETCH_URLS}):
            result = mc.get_report('2026-11-18')
        self.assertEqual(result['source'], 'flowdesk-market-context')
        self.assertEqual(result['schemaVersion'], 1)
        self.assertEqual(result['asOf'], '2026-11-18')
        self.assertTrue(result['collectedAt'].endswith('Z'))
        self.assertEqual(len(result['macro']), len(mc.FRED_SERIES))
        self.assertEqual({s['id'] for s in result['sources']}, {'SQUEEZEMETRICS', 'FRED', 'FINANCIALJUICE', 'WEBULL'})
        statuses = {s['id']: s['status'] for s in result['sources']}
        self.assertEqual(statuses['FINANCIALJUICE'], 'manual-or-licensed')
        self.assertEqual(statuses['WEBULL'], 'manual-or-licensed')
        self.assertEqual(statuses['SQUEEZEMETRICS'], 'manual-or-licensed')
        self.assertIn('https://squeezemetrics.com/monitor/terms', result['positioning']['reason'])
        self.assertEqual(statuses['FRED'], 'unavailable')
        self.assertIsNone(result['positioning']['dix'])
        for item in result['macro']:
            self.assertIsNone(item['value'])
            self.assertIn('TimeoutError', item['reason'])
        self.assertTrue(result['warnings'])
        with patch.object(mc, '_collect') as fetch:
            for value in ('http://localhost', '2026-1-01', '2026-02-30', 123):
                with self.assertRaises(ValueError):
                    mc.get_report(value)
            fetch.assert_not_called()

    def test_report_parse_failure_is_isolated_from_other_sources(self):
        from unittest.mock import patch
        import market_context as mc
        values = {key: ('DATE,' + key + '\n2026-11-17,0\n', None) for key in mc.FRED_SERIES}
        values['SQUEEZEMETRICS'] = ('<html>blocked</html>', None)
        with patch.object(mc, '_collect', return_value=values):
            result = mc.get_report('2026-11-18')
        self.assertEqual(result['positioning']['status'], 'manual-or-licensed')
        self.assertTrue(all(item['value'] == 0 for item in result['macro']))
        self.assertTrue(all(item['status'] == 'available' for item in result['macro']))


class TransportTests(unittest.TestCase):
    def test_curl_fallback_is_bounded_and_uses_only_official_page(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import patch
        mc = self.mc
        def run(args, **kwargs):
            self.assertEqual(args[:2], ['curl', '--disable'])
            self.assertIn('--max-filesize', args)
            self.assertIn('--max-time', args)
            self.assertIn('--proto', args)
            self.assertNotIn('--location', args)
            self.assertLessEqual(kwargs['timeout'], 2)
            kwargs['stdout'].write(synthetic_page().encode())
            return SimpleNamespace(returncode=0)
        with patch.object(mc, '_download', side_effect=TimeoutError), patch.object(mc.subprocess, 'run', side_effect=run):
            text = mc._download_page('https://fred.stlouisfed.org/series/DGS10', time.monotonic() + 2)
        self.assertEqual(mc.parse_macro_page('DGS10', text, '2020-01-03')['value'], 1.23)

    def setUp(self):
        import market_context as mc
        self.mc = mc
        mc._cache.clear()
        mc._inflight.clear()

    def tearDown(self):
        self.mc._cache.clear()
        self.mc._inflight.clear()

    def test_cache_hit_expiry_and_failure_do_not_reuse_old_success(self):
        import time
        from unittest.mock import patch
        mc = self.mc
        with patch.object(mc, '_fetch', return_value='synthetic') as fetch:
            first = mc._collect()
            self.assertEqual(len(first), len(mc.FETCH_URLS))
            mc._collect()
            self.assertEqual(fetch.call_count, len(mc.FRED_SERIES))
        with mc._lock:
            for key in mc._cache:
                mc._cache[key] = (time.monotonic() - mc.CACHE_TTL - 1, ('synthetic', None))
        with patch.object(mc, '_fetch', side_effect=TimeoutError('secret upstream text')) as fetch:
            result = mc._collect()
            self.assertTrue(all(text is None and 'TimeoutError' in error for text, error in (result[key] for key in mc.FRED_SERIES)))
            self.assertNotIn('secret', str(result))
            mc._collect()
            self.assertEqual(fetch.call_count, len(mc.FRED_SERIES))

    def test_concurrent_reports_coalesce_and_limit_fetch_workers(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        mc = self.mc
        lock = threading.Lock()
        counts = {'active': 0, 'maximum': 0, 'calls': 0}
        def fetch(key):
            with lock:
                counts['calls'] += 1
                counts['active'] += 1
                counts['maximum'] = max(counts['maximum'], counts['active'])
            time.sleep(.02)
            with lock:
                counts['active'] -= 1
            return 'synthetic'
        with patch.object(mc, '_fetch', side_effect=fetch), ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: mc._collect(), range(3)))
        self.assertEqual(counts['calls'], len(mc.FRED_SERIES))
        self.assertLessEqual(counts['maximum'], 6)
        self.assertTrue(all(len(result) == len(mc.FETCH_URLS) for result in results))

    def test_report_deadline_returns_null_without_waiting_for_pending_fetches(self):
        from concurrent.futures import Future
        from unittest.mock import patch
        import time
        mc = self.mc
        mc._inflight.update({key: Future() for key in mc.FETCH_URLS})
        with patch.object(mc, 'REPORT_TIMEOUT', .01):
            start = time.monotonic()
            result = mc.get_report('2026-11-18')
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(result['positioning']['status'], 'manual-or-licensed')
        self.assertTrue(all(item['value'] is None for item in result['macro']))
        self.assertIn('deadline', result['macro'][0]['reason'])

    def test_transport_limits_size_rejects_redirects_and_arbitrary_urls(self):
        import io
        from unittest.mock import patch
        mc = self.mc
        class Response(io.BytesIO):
            headers = {}
        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return Response(b'x' * 17)
        opener = Opener()
        with patch.object(mc.urllib.request, 'build_opener', return_value=opener), patch.object(mc, 'MAX_RESPONSE_BYTES', 16):
            with self.assertRaises(ValueError):
                import time
                mc._download(mc.FETCH_URLS['DGS10'], time.monotonic() + mc.FETCH_TIMEOUT)
            self.assertLessEqual(opener.timeout, mc.FETCH_TIMEOUT)
            self.assertEqual(opener.request.full_url, mc.FETCH_URLS['DGS10'])
        with self.assertRaises(KeyError):
            mc._fetch('http://localhost/')
        with self.assertRaises(ValueError):
            mc._NoRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost/')


if __name__ == '__main__':
    unittest.main()
