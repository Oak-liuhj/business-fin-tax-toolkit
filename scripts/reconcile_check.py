#!/usr/bin/env python3
"""九项勾稽：0=全部通过，1=校验失败，2=缺数据/待复核/非法输入。"""
import argparse
import sys
from common import ZERO, cli, emit, field, number, read_json


def run(data):
    if not isinstance(data, dict):
        raise ValueError('输入必须为 JSON 对象')
    b, inc, cf = (data.get(k) or {} for k in ('balance', 'income', 'cashflow'))
    bridge, ledger, previous, ec = (data.get(k) or {} for k in
                                   ('bridges', 'ledger', 'prior_closing', 'equity_change'))
    tol = field(data, 'tolerance', '0.01', minimum=0)
    res = []

    def compare(no, title, values, formula, hint, manual=False):
        if any(v is None for v in values):
            status, detail, diff = ('待人工复核' if manual else '缺数据'), '未取得完整比较双方数据', None
        else:
            diff = formula(*values)
            status, detail = ('通过' if abs(diff) <= tol else '未通过'), f'差额 {diff}'
        res.append({'no': no, 'item': title, 'status': status, 'difference': diff,
                    'detail': detail, 'hint': hint if status != '通过' else ''})

    n = field
    compare(1, '资产 = 负债 + 所有者权益',
            [n(b, k) for k in ('total_assets', 'total_liabilities', 'total_equity')],
            lambda a, l, e: a-l-e, '检查未结转损益、归类和漏记凭证')
    compare(2, '净利润 ↔ 未分配利润变动（含桥接）',
            [n(b, 'undistributed_profit'), n(b, 'opening_undistributed_profit'), n(inc, 'net_profit'),
             n(bridge, 'profit_distribution', 0), n(bridge, 'reserve_transfer', 0),
             n(bridge, 'prior_adjustment', 0)],
            lambda c, o, p, d, r, a: c-o-(p-d-r+a), '核实分红、公积提取和前期调整')
    cash_values = [n(cf, k) for k in ('net_increase', 'opening_cash', 'closing_cash')]
    cash_values += [n(b, 'cash'), n(bridge, 'restricted_cash', 0), n(bridge, 'cash_equivalents_extra', 0)]
    compare(3, '现金净增加额及现金等价物口径桥接', cash_values,
            lambda ni, o, c, cash, restricted, extra: max(abs(ni-(c-o)), abs(c-(cash-restricted+extra))),
            '核对受限资金、现金等价物及汇率影响')
    compare(4, '现金流补充资料净利润 = 利润表净利润',
            [n(cf, 'net_profit'), n(inc, 'net_profit')], lambda a, b: a-b, '核对补充资料起点')
    compare(5, '折旧摊销 = 总账本期计提',
            [n(cf, 'depreciation_amortization'), n(ledger, 'depreciation_amortization')],
            lambda a, b: a-b, '取得总账计提额，区分处置、外币折算及其他变动', manual=True)
    compare(6, '所得税费用 = 当期 + 递延所得税费用',
            [n(inc, k) for k in ('income_tax', 'current_tax', 'deferred_tax')],
            lambda a, b, c: a-b-c, '递延项仅含计入本期损益的部分')
    items = (data.get('detail') or {}).get('line_items') or {}
    if not items:
        compare(7, '各小计 = 明细之和', [None], lambda a: a, '取得明细')
    else:
        differences = []
        for key, values in items.items():
            if not isinstance(values, list) or len(values) < 2:
                raise ValueError(f'line_items.{key} 须包含小计和至少一项明细')
            values = [number(v, f'line_items.{key}') for v in values]
            differences.append(values[0]-sum(values[1:], ZERO))
        compare(7, '各小计 = 明细之和', differences, lambda *v: max(abs(x) for x in v), '逐栏检查明细')
    pairs = [(n(b, f'opening_{key}'), n(previous, key)) for key in
             ('total_assets', 'total_liabilities', 'total_equity')]
    compare(8, '本期期初 = 上期期末（资产/负债/权益）',
            [v for pair in pairs for v in pair],
            lambda *v: max(abs(v[i]-v[i+1]) for i in (0, 2, 4)), '取得上期已报资产负债表', manual=True)
    compare(9, '权益变动表 = 资产负债表权益',
            [n(ec, 'closing_total'), n(b, 'total_equity')], lambda a, b: a-b, '核对同一主体的权益表')
    counts = {status: sum(x['status'] == status for x in res)
              for status in ('通过', '未通过', '缺数据', '待人工复核')}
    ready = counts['通过'] == 9
    return {'period': data.get('period', ''), 'total_checks': 9,
            'passed': counts['通过'], 'failed': counts['未通过'], 'missing': counts['缺数据'],
            'pending_review': counts['待人工复核'],
            'coverage': (counts['通过']+counts['未通过'])/9, 'ready_for_analysis': ready,
            'conclusion': '全部通过' if ready else '校验未完成或未通过，不得发布正式分析结论', 'results': res}


def to_markdown(out):
    lines = [f"# 勾稽校验 · {out['period']}", '', out['conclusion'],
             f"通过 {out['passed']}/9；失败 {out['failed']}；缺数据 {out['missing']}；待复核 {out['pending_review']}", '',
             '| # | 校验项 | 状态 | 差额 | 排查建议 |', '|---|---|---|---|---|']
    lines += [f"| {x['no']} | {x['item']} | {x['status']} | {x['difference']} | {x['hint']} |" for x in out['results']]
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-i', '--input'); ap.add_argument('-o', '--output')
    ap.add_argument('--example', action='store_true'); ap.add_argument('--md', action='store_true')
    a = ap.parse_args()
    if a.example:
        from pathlib import Path
        emit(read_json(Path(__file__).resolve().parents[1]/'assets/samples/reconcile_input_sample.json')); return 0
    if not a.input:
        ap.error('需要 -i 输入文件')
    out = run(read_json(a.input))
    emit(out, a.output, to_markdown(out) if a.md else None)
    return 0 if out['ready_for_analysis'] else (1 if out['failed'] else 2)


if __name__ == '__main__':
    sys.exit(cli(main))
