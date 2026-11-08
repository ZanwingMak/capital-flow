"""供本机Hermes读取的只读CLI；不创建数据库，不写导出文件。"""
import argparse
import json
import sqlite3
import sys
from portfolio_store import PortfolioStore
from private_common import LedgerError
from research_store import ResearchStore
from research_report import export_report


def main(argv=None):
    """以只读URI打开私有库，只将用户指定结果输出到stdout。"""
    parser = argparse.ArgumentParser(description='Flowdesk 私有台账只读导出；输出可能含私人数据。')
    parser.add_argument('--directory', help='仓库外私有数据目录；默认沿用FLOWDESK_PRIVATE_DIR')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('accounts', help='账户列表')
    portfolio = commands.add_parser('portfolio', help='最新账本数量、成本与质量')
    portfolio.add_argument('--account', required=True)
    portfolio.add_argument('--as-of', help='交易日期截止，YYYY-MM-DD；非历史时点已知版本')
    records = commands.add_parser('research', help='冻结研究历史')
    records.add_argument('--account', required=True)
    report = commands.add_parser('export-report', help='冻结研究JSON或Markdown')
    report.add_argument('--id', required=True)
    report.add_argument('--format', choices=['json', 'markdown'], default='json')
    args = parser.parse_args(argv)
    try:
        store = PortfolioStore(args.directory, readonly=True)
        if args.command == 'export-report':
            output = export_report(ResearchStore(store).report(args.id), args.format)
        else:
            if args.command == 'accounts':
                result = store.accounts()
            elif args.command == 'portfolio':
                result = store.snapshot(args.account, args.as_of)
            else:
                result = ResearchStore(store).records(args.account)
            output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        sys.stdout.write(output)
        return 0
    except (LedgerError, OSError, sqlite3.Error):
        print('私有只读导出失败；请确认库已存在、记录ID和本机配置有效。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
