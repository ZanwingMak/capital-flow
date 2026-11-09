"""只读本地授权OHLCV的离线指标报告CLI；不调用富途、不读取账户配置。"""
import argparse
import json
from pathlib import Path

from indicator_service import get_report
from indicator_specs import CATALOG


def main(argv=None):
    """读取显式指定的行情JSON并将严格JSON报告写到显式指定的本地路径。"""
    parser = argparse.ArgumentParser(description='Flowdesk US日线自定义指标离线研究')
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--symbol')
    parser.add_argument('--as-of')
    parser.add_argument('--indicator', choices=list(CATALOG), default='QUSHI-CHANG')
    parser.add_argument('--initial', type=float, default=10000)
    parser.add_argument('--fee-bps', type=float, default=5)
    parser.add_argument('--slippage-bps', type=float, default=5)
    parser.add_argument('--validation-start')
    parser.add_argument('--holdout-start')
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError('输出不能覆盖输入行情。')
        if args.input.stat().st_size > 10_000_000:
            raise ValueError('输入文件不能超过10MB。')
        payload = json.loads(args.input.read_text(encoding='utf-8'))
        metadata = payload if isinstance(payload, dict) else {}
        rows = metadata.get('rows', []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError('输入必须为日线数组或含rows的对象。')
        symbol = args.symbol or metadata.get('symbol')
        as_of = args.as_of or metadata.get('asOf') or (rows[-1].get('date') if rows else None)
        report = get_report(symbol, as_of, 'US', lambda *_: payload, indicator=args.indicator,
                            initial=args.initial, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
                            validation_start=args.validation_start, holdout_start=args.holdout_start)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
        print(json.dumps({'symbol': report['symbol'], 'indicator': args.indicator, 'bars': report['sample']['bars'],
                          'events': len(report['events']), 'metrics': report['backtest']['metrics'] if report['backtest'] else None}, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
