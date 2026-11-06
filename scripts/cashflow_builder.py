"""Build direct cash flow from reviewed categories on all bank movements."""
from common import ZERO, field, money, number

CATEGORIES = {
    '经营收款': ('operating_cash_flow', 1), '经营付款': ('operating_cash_flow', -1),
    '投资收款': ('investing_cash_flow', 1), '投资付款': ('investing_cash_flow', -1),
    '筹资收款': ('financing_cash_flow', 1), '筹资付款': ('financing_cash_flow', -1),
    '销售收款': ('operating_cash_flow', 1), '供应商付款': ('operating_cash_flow', -1),
    '职工付款': ('operating_cash_flow', -1), '税费付款': ('operating_cash_flow', -1)}


def build_bank_cashflow(imported, support):
    if not imported.get('ready'):
        raise ValueError('银行流水导入存在异常')
    opening = {k: number(v) for k, v in (support.get('bank_opening_balances') or {}).items()}
    if not opening:
        raise ValueError('缺少逐账户期初银行余额')
    running = dict(opening)
    totals = {k: ZERO for k in ('operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow')}
    detail, lineage = {}, {}
    rows = sorted(imported['records'], key=lambda r: (r['values']['date'], r['provenance']['date']['row']))
    used = set()
    for record in rows:
        v = record['values']; account = v['bank_account']; used.add(account)
        if account not in running:
            raise ValueError(f'{account} 缺少期初余额')
        incoming, outgoing = number(v['incoming']), number(v['outgoing'])
        if incoming and outgoing:
            raise ValueError('同笔流水同时有收入和支出，需拆分确认')
        category = v.get('cashflow_category')
        if category not in CATEGORIES:
            raise ValueError(f"流水 {record['id']} 缺少明确现金流分类；内部划转及外币业务应先单独核对")
        section, sign = CATEGORIES[category]
        if (incoming > 0 and sign < 0) or (outgoing > 0 and sign > 0):
            raise ValueError('流水收支方向与现金流分类冲突')
        delta = incoming-outgoing
        running[account] += delta
        if v.get('balance') is None or abs(running[account]-number(v['balance'])) > number('0.01'):
            raise ValueError(f"银行账户 {account} 流水余额不连续：{record['id']}")
        totals[section] += delta
        detail[category] = detail.get(category, ZERO)+delta
        lineage.setdefault(section, []).append({'record_id': record['id'], 'source_cells': record['provenance']})
    # Accounts with no movements are permitted when listed in opening balances.
    out = {**{k: money(v) for k, v in totals.items()}, 'opening_cash': money(sum(opening.values(), ZERO)),
           'closing_cash': money(sum(running.values(), ZERO)), 'fx_effect': ZERO,
           'net_increase': money(sum(totals.values(), ZERO)), 'cash_from_sales': money(detail.get('销售收款', ZERO))}
    if '销售收款' not in detail:
        out.pop('cash_from_sales')
    return out, detail, lineage
