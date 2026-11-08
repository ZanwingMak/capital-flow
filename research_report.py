"""确定性的私有JSON/Markdown报告；事实、判断与条件式观察分开。"""
import html
import json
import re
from urllib.parse import quote
from research_store import event_url


def markdown_text(value):
    """转义HTML和Markdown控制字符，阻止用户内容注入链接或结构。"""
    text = html.escape('未知' if value is None else str(value), quote=True)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])', r'\\\1', text).replace('\r', '').replace('\n', ' / ')


def markdown_url(value):
    """重新校验来源URL，以受控自动链接输出，仅编码可突破链接边界的字符。"""
    return '<' + quote(event_url(value), safe=":/?#[]@!$&'()*+,;=%._~-") + '>'


def export_report(record, format='json'):
    """导出冻结内容，不重新估值、不生成胜率、评分或买卖操作。"""
    if format == 'json':
        return json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if format != 'markdown':
        from private_common import LedgerError
        raise LedgerError('导出格式仅支持json或markdown。')
    m = markdown_text
    snap = record['snapshot']
    lines = ['# 私有持仓研究记录', '', f"持仓日期：{m(snap['asOf'])}；账户版本：{snap['revision']}；USD。",
             f"研究截止：{m(record['as_of'])}；保存时间：{m(record['saved_at'])}。", '', '## 数据与证据缺口', '',
             '持仓按当前更正后的账本版本重放，不声称恢复历史当时已记录的账户版本。',
             '账面成本采用移动加权方法，非税务口径；未提供实时估值、完整账户权益或总回报。',
             f"持仓质量：{m(' / '.join(snap['quality']))}。"]
    lines += [f"- {m(g.get('id', ''))} {m(g['reason'])}" for g in record['evidence_gaps']]
    for gap in snap.get('position_gaps', []):
        # 这些ID在固定句子内展示；保留连字符便于逐条复制核查审计原文。
        uncertain_ids = m(', '.join(gap['uncertain_event_ids'])).replace('\\-', '-')
        dependent_ids = m(', '.join(gap['dependent_event_ids'])).replace('\\-', '-')
        lines += [f"- {m(gap['symbol'])}：截止总量未知；仅已知部分 {m(gap['known_partial_quantity'])} 股，不能当作完整持仓。",
                  f"  日期精度不确定事件：{uncertain_ids}；连同排除的后续依赖：{dependent_ids}。"]
    if snap.get('totals_status') == 'known_partial':
        lines.append('现金、损益、分红及费用汇总未知；仅已知部分保留于JSON的 known_partial_totals，不代表账户总额。')
    lines += ['', '## 事实：账本快照', '', '| 正股 | 数量 | 账面总成本 USD | 分组 |', '| --- | --- | --- | --- |']
    lines += [f"| {m(p['symbol'])} | " +
              (f"截止总量未知（仅已知部分 {m(p['known_partial_quantity'])}）" if p.get('quantity_status') == 'known_partial' else m(p['quantity'])) +
              f" | {m(p['cost'])} | {m(p['group'])} |" for p in snap['positions']]
    lines += ['', f"现金余额：{m(snap['cash_balance'])}；账本现金变化：{m(snap['ledger_cash_delta'])}。",
              f"已实现账面损益：{m(snap['realized_pnl'])}；分红：{m(snap['dividend_income'])}；费用：{m(snap['fees'])}。",
              '', '## 判断（人工论点）', '', m(record['thesis'])]
    for side, title in (('support', '支持证据'), ('against', '反面证据')):
        lines += ['', '## ' + title, '']
        if not record[side]:
            lines.append('未提供；不代表不存在。')
        for item in record[side]:
            e = item['event']
            lines += [f"- {m(e['title'])} · v{e['version']} · {m(e['id'])}",
                      f"  人工录入、未自动核实；{'时间满足截止条件' if item['eligible'] else '仅作线索，不是截止日已知事实'}。",
                      f"  来源：{m(e['source'])}；URL：{markdown_url(e['url'])}。",
                      f"  发布：{m(e['published_at'])}；声称首次可知：{m(e['available_at'])}。",
                      f"  实际首次记录：{m(e['first_seen_at'])}；本版本抓取/录入：{m(e['captured_at'])}。",
                      f"  实际值：{m(e['actual'])}；预期：{m(e['expected'])}；前值：{m(e['previous'])}；修订：{m(e['revised'])}；期间：{m(e['period'])}；单位：{m(e['unit'])}。",
                      f"  备注：{m(e['notes'])}。"]
    lines += ['', '## 条件式观察', '', '触发条件：' + m(record['trigger'] or '未填写'),
              '', '失效条件：' + m(record['invalidation'] or '未填写'), '',
              '事件由人工录入，未接入BLS、IR或新闻自动抓取与自动核验；本报告不生成LLM胜率或自动买卖。', '']
    return '\n'.join(lines)
