"""Public descriptive context. Observation dates are not publication timestamps."""
import csv
import http.client
import re
import socket
import subprocess
import tempfile
import io
import math
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any

FRED_SERIES = {
    'DGS10': ('10-Year Treasury Constant Maturity Rate', 'Percent', 'Daily'),
    'DGS2': ('2-Year Treasury Constant Maturity Rate', 'Percent', 'Daily'),
    'T10Y2Y': ('10-Year Treasury Minus 2-Year Treasury', 'Percentage Points', 'Daily'),
    'DFII10': ('10-Year Treasury Inflation-Indexed Security, Constant Maturity', 'Percent', 'Daily'),
    'BAMLH0A0HYM2': ('ICE BofA US High Yield Index Option-Adjusted Spread', 'Percent', 'Daily'),
    'FEDFUNDS': ('Effective Federal Funds Rate', 'Percent', 'Monthly'),
    'CPIAUCSL': ('Consumer Price Index for All Urban Consumers: All Items', 'Index 1982-1984=100', 'Monthly'),
    'PCEPILFE': ('Personal Consumption Expenditures Excluding Food and Energy', 'Index 2017=100', 'Monthly'),
}
FRED_REASON = ('Latest-revised FRED observations, filtered by observation date only. '
               'Release dates and historical vintages are not verified; descriptive context only, '
               'not suitable for point-in-time backtests.')


def parse_macro(series_id, text, as_of):
    """Read an allowlisted series without treating missing values as observations."""
    _date(as_of)
    name, units, frequency = FRED_SERIES[series_id]
    result: dict[str, Any] = dict(id=series_id, name=name, value=None, observationDate=None,
                  units=units, frequency=frequency, status='unavailable',
                  sourceUrl='https://fred.stlouisfed.org/series/' + series_id,
                  reason=FRED_REASON, vintageMode='latest-revised', pointInTime=False, retrievalMode='csv')
    header = next(csv.reader(io.StringIO(text.lstrip('\ufeff'))), [])
    date_column = 'observation_date' if 'observation_date' in header else 'DATE'
    for day, row in _rows(text, (date_column, series_id), as_of, date_column):
        value = _number(row[series_id])
        if value is not None:
            result.update(value=value, observationDate=day, status='available')
            break
    if result['value'] is None:
        result['reason'] += ' No valid observation on or before requested date.'
    return result

class _LatestObservationParser(HTMLParser):
    """Accept paired date/value spans from the official observation widget."""
    def __init__(self):
        super().__init__()
        self.canonicals, self.observations, self.stack = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs.get('href'))
        if tag in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            return
        self.stack.append(dict(tag=tag, classes=(attrs.get('class') or '').split(), text='', dates=[], values=[]))

    def handle_data(self, data):
        if self.stack:
            self.stack[-1]['text'] += data

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1]['tag'] != tag:
            return
        node = self.stack.pop()
        if node['tag'] == 'div' and 'default-text' in node['classes']:
            if len(node['dates']) == len(node['values']) == 1:
                self.observations.append((node['dates'][0], node['values'][0]))
        if self.stack:
            parent = self.stack[-1]
            parent['text'] += node['text']
            if node['tag'] == 'span' and 'series-meta-value' in node['classes']:
                parent['dates'].append(node['text'].strip())
            if node['tag'] == 'span' and 'series-meta-observation-value' in node['classes']:
                parent['values'].append(node['text'].strip())


def parse_macro_page(series_id, text, as_of):
    result = parse_macro(series_id, 'DATE,' + series_id + '\n', as_of)
    parser = _LatestObservationParser()
    parser.feed(text)
    if set(parser.canonicals) != {result['sourceUrl']} or len(set(parser.observations)) != 1:
        raise ValueError('FRED page identity or observation widget mismatch')
    raw_day, raw_value = parser.observations[0]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}:', raw_day):
        day = _date(raw_day[:-1])
    elif FRED_SERIES[series_id][2] == 'Monthly' and re.fullmatch(r'[A-Z][a-z]{2} \d{4}:', raw_day):
        months = dict(zip(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), range(1, 13)))
        month, year = raw_day[:-1].split()
        if month not in months:
            raise ValueError('Invalid FRED observation month')
        day = date(int(year), months[month], 1).isoformat()
        result['observationPeriod'] = raw_day[:-1]
    else:
        raise ValueError('Invalid FRED observation date')
    value = _number(raw_value.replace(',', ''))
    if value is None:
        raise ValueError('Invalid FRED observation value')
    result.update(retrievalMode='latest-page', reason=FRED_REASON +
                  ' Official series page exposes only the latest observation; historical availability is not assumed.')
    if day <= as_of:
        result.update(value=value, observationDate=day, status='available')
    else:
        result['reason'] += ' Latest observation is newer than requested asOf; no historical observation retrieved.'
    return result


DIX_URL = 'https://squeezemetrics.com/monitor/static/DIX.csv'
SQUEEZE_TERMS_REASON = ('Official terms (https://squeezemetrics.com/monitor/terms) prohibit '
    'systematic retrieval to compile a database without written permission. '
    'Automatic retrieval requires FLOW_SQUEEZEMETRICS_AUTHORIZED=1 after obtaining authorization.')


def _squeeze_authorized():
    return os.environ.get('FLOW_SQUEEZEMETRICS_AUTHORIZED') == '1'

POSITIONING_REASON = ('S&P 500 aggregate daily DIX ratio and GEX dollar estimate; '
                      'not QQQ or individual-stock positioning. Observation date is not '
                      'a publication timestamp; not verified point-in-time data.')


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('as_of must be YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('as_of must be YYYY-MM-DD')
    return value


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _rows(text, columns, as_of, date_column):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames or not set(columns).issubset(reader.fieldnames):
        raise ValueError('Unexpected CSV columns')
    rows = []
    for row in reader:
        try:
            day = _date(row.get(date_column))
        except (ValueError, TypeError):
            continue
        if day <= as_of:
            rows.append((day, row))
    return sorted(rows, key=lambda item: item[0], reverse=True)


def parse_positioning(text, as_of):
    """Select the latest dated row; missing values never become zero."""
    _date(as_of)
    result: dict[str, Any] = dict(status='unavailable', observationDate=None, dix=None, gex=None,
                  spx=None, sourceUrl=DIX_URL, reason=POSITIONING_REASON,
                  pointInTime=False)
    rows = _rows(text, ('date', 'price', 'dix', 'gex'), as_of, 'date')
    if rows:
        day, row = rows[0]
        values = dict(dix=_number(row['dix']), gex=_number(row['gex']), spx=_number(row['price']))
        if values['dix'] is not None and not 0 <= values['dix'] <= 1:
            values['dix'] = None
        if values['spx'] is not None and values['spx'] <= 0:
            values['spx'] = None
        result.update(values, observationDate=day)
        if all(value is not None for value in values.values()):
            result['status'] = 'available'
        else:
            result['reason'] += ' Latest eligible row contains missing or invalid values.'
    else:
        result['reason'] += ' No observation on or before requested date.'
    return result


FETCH_URLS = {'SQUEEZEMETRICS': DIX_URL, **{
    key: 'https://fred.stlouisfed.org/graph/graph.csv?id=' + key for key in FRED_SERIES}}
FETCH_TIMEOUT = 6
CSV_TIMEOUT = 2
REPORT_TIMEOUT = 13
MAX_RESPONSE_BYTES = 2_000_000
CACHE_TTL = 600
FAILURE_TTL = 30
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix='public-context')
_lock = threading.Lock()
_cache = {}
_retrieved_at = {}
_inflight = {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A fixed public URL must never redirect into an arbitrary host.
        raise ValueError('Public source redirect rejected')


def _ipv4_connection(address, timeout=6, source_address=None):
    """Resolve per connection; HTTPSConnection retains hostname for TLS/SNI."""
    host, port = address
    last_error = OSError('No IPv4 address available')
    deadline = time.monotonic() + float(timeout)
    for family, kind, proto, _, target in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(max(.001, deadline - time.monotonic()))
            if source_address:
                sock.bind(source_address)
            sock.connect(target)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
            if time.monotonic() >= deadline:
                break
    raise last_error


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _ipv4_connection


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=getattr(self, '_context', None))


def _download(url, deadline):
    timeout = max(.001, deadline - time.monotonic())
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Flowdesk-PublicContext/1.0', 'Accept': 'text/csv,text/html',
        'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(_NoRedirect(), _IPv4HTTPSHandler())
    with opener.open(request, timeout=timeout) as response:
        length = response.headers.get('Content-Length')
        if length and int(length) > MAX_RESPONSE_BYTES:
            raise ValueError('Public response exceeds size limit')
        chunks, size = [], 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Public fetch deadline exceeded')
            if getattr(response, 'fp', None) and getattr(response.fp, 'raw', None):
                response.fp.raw._sock.settimeout(max(.001, deadline - time.monotonic()))
            chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError('Public response exceeds size limit')
            chunks.append(chunk)
    return b''.join(chunks).decode('utf-8-sig')


def _download_page(url, deadline):
    """Use system curl when the Python TLS stack cannot reach the official page."""
    try:
        return _download(url, min(deadline, time.monotonic() + .75))
    except ValueError:
        raise
    except Exception:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Public fetch deadline exceeded')
        # No shell, redirects, credentials, or persistent source files. curl also
        # enforces payload/deadline limits; read only the bounded output afterward.
        with tempfile.TemporaryFile() as output:
            process = subprocess.run([
                'curl', '--disable', '-4', '--silent', '--show-error', '--fail',
                '--proto', '=https', '--max-redirs', '0',
                '--max-time', str(remaining), '--max-filesize', str(MAX_RESPONSE_BYTES),
                url], stdout=output, stderr=subprocess.DEVNULL, timeout=remaining)
            if process.returncode:
                raise OSError('Official page transport failed')
            output.seek(0)
            payload = output.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError('Public response exceeds size limit')
        return payload.decode('utf-8-sig')


def _fetch(key):
    """Allowlisted URLs only; CSV and page share a per-series deadline."""
    if key == 'SQUEEZEMETRICS' and not _squeeze_authorized():
        raise PermissionError(SQUEEZE_TERMS_REASON)
    url = FETCH_URLS[key]
    deadline = time.monotonic() + FETCH_TIMEOUT
    if key == 'SQUEEZEMETRICS':
        return _download(url, deadline)
    try:
        text = _download(url, min(deadline, time.monotonic() + CSV_TIMEOUT))
        parse_macro(key, text, '9999-12-31')
        return text
    except Exception:
        if time.monotonic() >= deadline:
            raise TimeoutError('Public fetch deadline exceeded')
        text = _download_page('https://fred.stlouisfed.org/series/' + key, deadline)
        parse_macro_page(key, text, '9999-12-31')
        return text


def _fetch_cached(key):
    try:
        result = (_fetch(key), None)
    except Exception as exc:
        # Only the exception type is exposed; upstream text can contain unsafe content.
        result = (None, 'Public fetch failed: ' + type(exc).__name__)
    with _lock:
        _cache[key] = (time.monotonic(), result)
        _retrieved_at[key] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z') if result[1] is None else None
        _inflight.pop(key, None)
    return result


def _collect():
    """Coalesce overlapping requests; bound concurrency, payloads, wait and cache size."""
    results, pending = {}, {}
    with _lock:
        now = time.monotonic()
        for key in FETCH_URLS:
            if key == 'SQUEEZEMETRICS' and not _squeeze_authorized():
                results[key] = (None, SQUEEZE_TERMS_REASON)
                continue
            cached = _cache.get(key)
            if cached and now - cached[0] < (FAILURE_TTL if cached[1][1] else CACHE_TTL):
                results[key] = cached[1]
                continue
            _cache.pop(key, None)
            if key not in _inflight:
                _inflight[key] = _pool.submit(_fetch_cached, key)
            pending[key] = _inflight[key]
    if pending:
        done, _ = wait(pending.values(), timeout=REPORT_TIMEOUT)
        for key, future in pending.items():
            results[key] = future.result() if future in done else (None, 'Public fetch report deadline exceeded')
    return results


def _empty_positioning(reason):
    result = parse_positioning('date,price,dix,gex\n', '0001-01-01')
    result['reason'] = POSITIONING_REASON + ' ' + reason
    return result


def _empty_macro(key, reason):
    result = parse_macro(key, 'DATE,' + key + '\n', '0001-01-01')
    result['reason'] = FRED_REASON + ' ' + reason
    return result


def get_report(as_of=None) -> dict[str, Any]:
    """Return public context; as_of filters dates, never promises historical knowledge."""
    as_of = _date(as_of) if as_of is not None else datetime.now(timezone.utc).date().isoformat()
    collected_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    collected = _collect()
    with _lock:
        retrieved_at = dict(_retrieved_at)
    text, error = collected['SQUEEZEMETRICS']
    if not _squeeze_authorized():
        text, error = None, SQUEEZE_TERMS_REASON
    try:
        positioning = parse_positioning(text, as_of) if error is None else _empty_positioning(error)
    except (ValueError, TypeError, csv.Error):
        positioning = _empty_positioning('Public CSV could not be parsed.')
    if not _squeeze_authorized():
        positioning['status'] = 'manual-or-licensed'
    positioning['retrievedAt'] = retrieved_at.get('SQUEEZEMETRICS') if text is not None else None
    macro = []
    for key in FRED_SERIES:
        text, error = collected[key]
        try:
            if error is not None:
                item = _empty_macro(key, error)
            elif text.lstrip().startswith('<'):
                item = parse_macro_page(key, text, as_of)
            else:
                item = parse_macro(key, text, as_of)
        except (ValueError, TypeError, csv.Error):
            item = _empty_macro(key, 'Public CSV could not be parsed.')
        item['retrievedAt'] = retrieved_at.get(key) if text is not None else None
        macro.append(item)
    fred_available = sum(item['status'] == 'available' for item in macro)
    sources = [
        dict(id='SQUEEZEMETRICS', name='SqueezeMetrics DIX / GEX',
             url='https://squeezemetrics.com/monitor/dix', status=positioning['status'],
             reason=positioning['reason']),
        dict(id='FINANCIALJUICE', name='FinancialJuice', url='https://www.financialjuice.com/home',
             status='manual-or-licensed', reason='Official WebSocket and REST APIs require an API key '
             '(https://stream.financialjuice.com/docs). No licensed feed is connected.'),
        dict(id='WEBULL', name='Webull', url='https://app.webull.com/',
             status='manual-or-licensed', reason='Official market-data API requires appropriate non-display '
             'subscriptions, separate from desktop access '
             '(https://developer.webull.com/apis/docs/market-data-api/overview.md). No account or feed is connected.'),
        dict(id='FRED', name='Federal Reserve Economic Data', url='https://fred.stlouisfed.org/',
             status='available' if fred_available else 'unavailable',
             reason=f'{fred_available}/{len(macro)} series available. ' + FRED_REASON),
    ]
    warnings = [FRED_REASON, POSITIONING_REASON,
                'Observation dates can lag asOf; consult each series date. No directional thresholds or trade signals are produced.']
    for item in [positioning] + macro:
        if item['status'] != 'available':
            warnings.append(str(item.get('id', 'SQUEEZEMETRICS')) + ': ' + item['reason'])
    return dict(source='flowdesk-market-context', schemaVersion=1, asOf=as_of,
                collectedAt=collected_at, collectedAtMeaning='report-assembly-time',
                cacheTtlSeconds=CACHE_TTL, sources=sources, macro=macro,
                positioning=positioning, warnings=warnings)
