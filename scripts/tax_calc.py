#!/usr/bin/env python3
"""Decimal 税费测算；默认情景试算，review 模式要求政策登记与适用性审核。"""
import argparse
import sys
from common import ZERO, cli, dumps, emit, field, money, number, read_json


def amount(d, key, default=0, required=False):
    return field(d, key, default, required=required, minimum=0)


def rate(d, key, default=None, required=False):
    return field(d, key, default, required=required, minimum=0, maximum=1)


def vat(d):
    sales = amount(d, 'sales_excl_tax', None, required=True)
    r = rate(d, 'output_rate', '0.13')
    output = amount(d, 'output_tax') if 'output_tax' in d else money(sales*r)
    inputs = amount(d, 'input_tax', None, required=True)
    transfer, carry = (amount(d, k) for k in ('input_transfer_out', 'opening_credit'))
    net = inputs-transfer
    signed = output-net-carry
    general, credit = max(signed, ZERO), max(-signed, ZERO)
    simple_sales = amount(d, 'simple_sales_excl_tax')
    simple_rate = rate(d, 'simple_rate', '0.03')
    simple = money(simple_sales*simple_rate)
    total = money(general+simple)
    denominator = sales+simple_sales
    return {'output_tax': money(output), 'input_tax': money(inputs), 'input_transfer_out': money(transfer),
            'net_input': money(net), 'opening_credit': money(carry), 'general_payable': money(general),
            'closing_credit': money(credit), 'simple_payable': simple, 'total_payable_before_deduction': total,
            'total_payable': total, 'sales_total_excl_tax': money(denominator),
            'vat_burden_rate': total/denominator if denominator else None,
            'surcharge_base': total+amount(d, 'consumption_tax'),
            'params_used': {'output_rate': r, 'simple_rate': simple_rate},
            'note': '留抵不得抵减简易计税；实际缴纳与免抵额等附加税基桥接由 surcharge 模块单列。'}


def surcharges(d):
    base = amount(d, 'base', None, required=True)
    rates = {k: rate(d, f'{k}_rate', v) for k, v in [('city', '0.07'), ('edu', '0.03'), ('local_edu', '0.02')]}
    reduction = rate(d, 'reduction_ratio', 0)
    items = {k: money(base*r*(1-reduction)) for k, r in rates.items()}
    return {'base': money(base), 'items': items, 'total': sum(items.values(), ZERO),
            'params_used': {**{f'{k}_rate': v for k, v in rates.items()}, 'reduction_ratio': reduction}}


def export_refund(d):
    fob = amount(d, 'fob_rmb', None, required=True)
    levy = rate(d, 'levy_rate', '0.13')
    refund_rate = rate(d, 'refund_rate', required=True)
    if refund_rate > levy:
        raise ValueError('refund_rate 不得大于 levy_rate；特殊口径需独立规则')
    # Net of tax-exempt imported materials must be explicitly supplied when applicable.
    exempt_materials = amount(d, 'exempt_materials')
    if exempt_materials > fob:
        raise ValueError('exempt_materials 不得超过出口额')
    net_fob = fob-exempt_materials
    no_deduct = money(net_fob*(levy-refund_rate))
    signed = amount(d, 'domestic_output_tax')-(amount(d, 'input_tax')-no_deduct)-amount(d, 'opening_credit')
    cap, credit = money(net_fob*refund_rate), money(max(-signed, ZERO))
    refund = min(credit, cap)
    return {'fob_rmb': money(fob), 'non_deductible': no_deduct,
            'current_tax_payable': money(max(signed, ZERO)), 'closing_credit': credit,
            'refund_cap': cap, 'refund': refund, 'exempt_offset': cap-refund,
            'credit_after_refund': credit-refund,
            'params_used': {'levy_rate': levy, 'refund_rate': refund_rate},
            'note': '仅生产企业简化免抵退测算；申报期限与单证条件须按所属期有效文件核验。'}


def super_deduction(d, vat_payable):
    ratio = rate(d, 'ratio', required=True)
    accrued = money(amount(d, 'current_deductible_input')*ratio)
    available = amount(d, 'opening_balance')+accrued-amount(d, 'current_decrease')
    if available < 0:
        raise ValueError('加计抵减调减额超过余额与本期计提，需复核并另行处理补税，不生成负抵减额')
    used = min(max(number(vat_payable), ZERO), available)
    return {'ratio': ratio, 'accrued': accrued, 'available': money(available), 'used': money(used),
            'remaining_balance': money(available-used), 'payable_after': money(max(number(vat_payable)-used, ZERO)),
            'note': '仅抵减一般计税应纳额；资格、政策有效期与比例需审核。'}


def cit(d):
    ledger_summary = None
    if 'carryforward_ledger' in d:
        from carryforward_ledger import summarize
        year = d.get('tax_year')
        ledger_summary = summarize(d['carryforward_ledger'], year)
        if ledger_summary['pending']:
            raise ValueError('跨年台账含待核实余额，先复核资格与证据')
        if 'loss_carryforward' in d or 'prior_carryforwards' in d:
            raise ValueError('使用逐年台账时不得同时传入手工结转汇总，避免重复扣除')
        d = dict(d)
        balances = ledger_summary['eligible_balances']
        d['loss_carryforward'] = balances.get('loss', ZERO)
        d['prior_carryforwards'] = {k: balances.get(k, ZERO) for k in ('advertising', 'education', 'donation')}
    profit = field(d, 'accounting_profit', required=True)
    revenue = amount(d, 'revenue', None, required=True)
    salary = amount(d, 'salary_total')
    ent = amount(d, 'entertainment_expense')
    ad, wel, edu, don = (amount(d, k) for k in ('advertising_expense', 'welfare_expense', 'education_expense', 'donation'))
    if (wel or edu) and ('salary_total' not in d or d['salary_total'] is None):
        raise ValueError('计算福利/教育经费限额必须提供 salary_total，不能将缺失视为零')
    ratios = {'advertising_ratio': rate(d, 'advertising_ratio', '0.15'),
              'welfare_ratio': rate(d, 'welfare_ratio', '0.14'),
              'education_ratio': rate(d, 'education_ratio', '0.08'),
              'donation_ratio': rate(d, 'donation_ratio', '0.12'),
              'entertainment_expense_ratio': rate(d, 'entertainment_expense_ratio', '0.60'),
              'entertainment_revenue_ratio': rate(d, 'entertainment_revenue_ratio', '0.005'),
              'rd_super_ratio': field(d, 'rd_super_ratio', 1, minimum=0, maximum=3),
              'tax_rate': rate(d, 'tax_rate', '0.25')}
    bases = [('entertainment', ent, min(ent*ratios['entertainment_expense_ratio'], revenue*ratios['entertainment_revenue_ratio']), False),
             ('advertising', ad, revenue*ratios['advertising_ratio'], True),
             ('welfare', wel, salary*ratios['welfare_ratio'], False),
             ('education', edu, salary*ratios['education_ratio'], True),
             ('donation', don, max(profit, ZERO)*ratios['donation_ratio'], True)]
    limits = {}
    prior_cf = d.get('prior_carryforwards') or {}
    for name, actual, limit, can_carry in bases:
        limit = money(limit)
        allowed, added = min(actual, limit), max(actual-limit, ZERO)
        item = {'actual': money(actual), 'limit': limit, 'deductible_current': money(allowed), 'add_back': money(added)}
        if can_carry:
            opening = amount(prior_cf, name)
            used = min(opening, max(limit-actual, ZERO))
            item.update(opening_carryforward=money(opening), used_prior=money(used),
                        carryforward=money(opening-used+added))
        limits[name] = item
    rd = money(amount(d, 'rd_expense')*ratios['rd_super_ratio'])
    adds = sum((x['add_back'] for x in limits.values()), ZERO)+amount(d, 'other_add')
    prior_used = sum((x.get('used_prior', ZERO) for x in limits.values()), ZERO)
    before_loss = profit+adds-amount(d, 'other_less')-rd-prior_used
    loss_opening = amount(d, 'loss_carryforward')
    loss_used = min(loss_opening, max(before_loss, ZERO))
    taxable = money(max(before_loss-loss_used, ZERO))
    tax = money(taxable*ratios['tax_rate'])
    return {'accounting_profit': money(profit), 'limits': limits, 'rd_super_deduction': rd,
            'carryforward_ledger': ledger_summary,
            'total_add_back': money(adds), 'prior_carryforward_deduction': money(prior_used),
            'taxable_before_loss': money(before_loss), 'loss_used': money(loss_used),
            'loss_remaining': money(loss_opening-loss_used), 'new_tax_loss': money(max(-before_loss, ZERO)),
            'taxable_income': taxable, 'tax_rate': ratios['tax_rate'], 'tax_payable': tax,
            'effective_rate': tax/profit if profit > 0 else None, 'params_used': ratios,
            'parameter_sources': {k: 'input' if k in d else 'simulation_default' for k in ratios},
            'caveats': ['结转余额必须由逐年台账排除失效与不适用金额后提供。',
                        '研发资格、小微分段优惠、境外抵免、递延所得税须使用专项底稿，本脚本不自动判定。']}


def calculate(data, part='all'):
    if not isinstance(data, dict):
        raise ValueError('输入必须为对象')
    if data.get('unit', '元') != '元':
        raise ValueError('税费计算金额统一为元，请先按原始单位标准化，避免分位舍入错误')
    out = {'schema_version': '0.2.0', 'period': data.get('period'), 'unit': data.get('unit', '元')}
    selected = [k for k in ('vat', 'surcharge', 'export', 'cit') if k in data and (part == 'all' or part == k)]
    if not selected:
        raise ValueError(f'未提供 {part} 对应数据，拒绝按空数据算零')
    if 'vat' in selected:
        out['vat'] = vat(data['vat'])
        if data.get('super_deduction') is not None:
            sd = super_deduction(data['super_deduction'], out['vat']['general_payable'])
            out['super_deduction'] = sd
            v = out['vat']
            v['general_payable_after_deduction'] = sd['payable_after']
            v['total_payable'] = money(sd['payable_after']+v['simple_payable'])
            denominator = v['sales_total_excl_tax']
            v['vat_burden_rate'] = v['total_payable']/denominator if denominator else None
            v['surcharge_base'] = v['total_payable']+amount(data['vat'], 'consumption_tax')
    if 'export' in selected:
        out['export'] = export_refund(data['export'])
    if 'surcharge' in selected:
        s = dict(data['surcharge'])
        adjustments = s.get('adjustments') or {}
        adjustment = sum((field(adjustments, k, required=True) for k in adjustments), ZERO)
        if 'vat' in out:
            computed = out['vat']['surcharge_base']+adjustment
            source = '抵减后增值税 + 消费税 + 已列明税基调整'
            previous_base = s.get('base')
            s['base'] = computed
        else:
            previous_base = None
            if adjustment:
                s['base'] = amount(s, 'base', None, required=True)+adjustment
            source = '独立输入税基；未关联增值税模块'
        out['surcharge'] = surcharges(s)
        out['surcharge'].update(base_source=source, adjustments=adjustments)
        if previous_base is not None and number(previous_base) != number(s['base']):
            out['surcharge']['input_base_difference'] = number(previous_base)-number(s['base'])
    if 'cit' in selected:
        out['cit'] = cit(data['cit'])
    return out


def to_markdown(out):
    lines = ['# 税费测算', '', f"模式：{out.get('mode', 'simulation')}；政策：{out.get('policy_validation', {}).get('status', '未核验')}", '']
    for section in ('vat', 'super_deduction', 'surcharge', 'export', 'cit', 'policy_validation', 'provenance'):
        if section in out:
            lines += [f'## {section}', '', '```json', dumps(out[section]), '```', '']
    return '\n'.join(lines)


def main():
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-i', '--input'); ap.add_argument('-o', '--output')
    ap.add_argument('--example', action='store_true'); ap.add_argument('--md', action='store_true')
    ap.add_argument('--part', choices=['all', 'vat', 'surcharge', 'export', 'cit'], default='all')
    ap.add_argument('--mode', choices=['simulation', 'review'], default='simulation')
    ap.add_argument('--registry', default=str(Path(__file__).resolve().parents[1]/'references/policy-registry.json'))
    a = ap.parse_args()
    if a.example:
        emit(read_json(Path(__file__).resolve().parents[1]/'assets/samples/tax_input_sample.json')); return 0
    if not a.input:
        ap.error('需要 -i 输入文件')
    data = read_json(a.input)
    out = calculate(data, a.part)
    from policy_registry import validate_tax
    out['mode'] = a.mode
    out['policy_validation'] = validate_tax(data, out, read_json(a.registry))
    from data_ingest import source_info
    from common import VERSION
    out['provenance'] = {'input': source_info(a.input), 'policy_registry': source_info(a.registry), 'engine_version': VERSION}
    emit(out, a.output, to_markdown(out) if a.md else None)
    return 2 if a.mode == 'review' and out['policy_validation']['status'] != 'verified' else 0


if __name__ == '__main__':
    sys.exit(cli(main))
