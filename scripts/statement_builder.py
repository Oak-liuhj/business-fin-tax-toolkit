"""CAS single-entity draft from validated leaf trial balance and separate supporting schedules."""
from common import ZERO, field, money, number


def build(imported, mapping, context, support):
    if not imported.get('ready'):
        raise ValueError('导入异常未解决，不得编表')
    if context.get('accounting_standard') != 'CAS' or context.get('scope') != 'single' or context.get('currency') != 'CNY':
        raise ValueError('自动编制当前支持 CAS/单体/CNY，IFRS及合并应另建专项底稿')
    if context.get('profit_state') != 'unclosed':
        raise ValueError('当前编表要求损益未结转；已结转账套须另供剔除结转分录的利润明细')
    records = imported['records']
    codes = [x['values']['account_code'] for x in records]
    if any(a != b and b.startswith(a) for a in codes for b in codes):
        raise ValueError('同时存在父级与子级科目，可能重复汇总；请导出末级科目')
    rules = mapping['rules']
    if len({r['prefix'] for r in rules}) != len(rules):
        raise ValueError('映射前缀重复')
    buckets, lineage, errors = {}, {}, []
    totals = {k: ZERO for k in ('opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit')}
    for record in records:
        v, code = record['values'], record['values']['account_code']
        for key in totals:
            totals[key] += number(v[key])
        opening = number(v['opening_debit'])-number(v['opening_credit'])
        closing = number(v['closing_debit'])-number(v['closing_credit'])
        if (number(v['opening_debit']) and number(v['opening_credit'])) or (number(v['closing_debit']) and number(v['closing_credit'])):
            errors.append(f'{code} 末级余额同时有借方和贷方，需确认导出层级')
        movement = number(v['debit'])-number(v['credit'])
        if abs(opening+movement-closing) > number('0.01'):
            errors.append(f'{code} 期初+发生不等于期末')
        candidates = sorted((r for r in rules if code.startswith(r['prefix'])), key=lambda r: len(r['prefix']), reverse=True)
        if not candidates:
            errors.append(f'{code} 无科目映射'); continue
        rule = candidates[0]
        key, nature = rule['field'], rule['nature']
        if nature not in ('asset', 'contra_asset', 'liability', 'equity', 'income', 'expense'):
            raise ValueError(f'{code} 未知科目性质')
        if nature in ('income', 'expense') and abs(opening) > number('0.01'):
            errors.append(f'{code} 损益存在期初余额，与当期未结转假设不符')
        if nature in ('asset', 'liability') and ((nature == 'asset' and closing < 0) or (nature == 'liability' and closing > 0)):
            errors.append(f'{code} 余额方向异常，需按明细重分类后编表')
        bucket = buckets.setdefault(key, {'nature': nature, 'opening': ZERO, 'closing': ZERO, 'movement': ZERO})
        if bucket['nature'] != nature:
            raise ValueError(f'{key} 映射性质冲突')
        sign = -1 if nature in ('liability', 'equity', 'income', 'contra_asset') else 1
        for period, value in [('opening', opening), ('closing', closing), ('movement', movement)]:
            bucket[period] += sign*value
        lineage.setdefault(key, []).append({'record_id': record['id'], 'account_code': code,
                                           'sign': sign, 'source_cells': record['provenance']})
    for debit, credit in [('opening_debit', 'opening_credit'), ('debit', 'credit'), ('closing_debit', 'closing_credit')]:
        if abs(totals[debit]-totals[credit]) > number('0.01'):
            errors.append(f'{debit}/{credit} 试算不平：{totals[debit]-totals[credit]}')
    if errors:
        raise ValueError('；'.join(errors))

    def amount(key, period='closing'):
        return buckets.get(key, {}).get(period, ZERO)

    income = {key: money(v['movement']) for key, v in buckets.items() if v['nature'] in ('income', 'expense')}
    income['profit_before_tax'] = money(sum((v['movement']*(1 if v['nature'] == 'income' else -1)
                                          for key, v in buckets.items() if v['nature'] in ('income', 'expense') and key != 'income_tax'), ZERO))
    income['net_profit'] = money(income['profit_before_tax']-income.get('income_tax', ZERO))
    income['interest_expense'] = field(support.get('income') or {}, 'interest_expense')
    income['ebit'] = income['profit_before_tax']+income['interest_expense'] if income['interest_expense'] is not None else None
    ledger = support.get('ledger') or {}
    income['depreciation'] = field(ledger, 'depreciation')
    income['amortization'] = field(ledger, 'amortization')
    income['current_tax'] = field(support.get('income') or {}, 'current_tax')
    income['deferred_tax'] = field(support.get('income') or {}, 'deferred_tax')

    def balance(period):
        result = {k: money(v[period]) for k, v in buckets.items() if v['nature'] not in ('income', 'expense')}
        result['current_assets'] = money(sum((amount(k, period) for k in
            ('cash', 'accounts_receivable', 'prepayments', 'other_receivables', 'inventory')), ZERO)-amount('receivable_allowance', period))
        result['total_assets'] = money(sum((v[period]*(1 if v['nature'] == 'asset' else -1)
            for v in buckets.values() if v['nature'] in ('asset', 'contra_asset')), ZERO))
        result['current_liabilities'] = money(sum((amount(k, period) for k in
            ('short_term_debt', 'notes_payable', 'accounts_payable', 'contract_liabilities', 'payroll_payable', 'tax_payable', 'other_payables')), ZERO))
        result['total_liabilities'] = money(sum((v[period] for v in buckets.values() if v['nature'] == 'liability'), ZERO))
        pending = income['net_profit'] if period == 'closing' else ZERO
        result['total_equity'] = money(sum((v[period] for v in buckets.values() if v['nature'] == 'equity'), ZERO)+pending)
        result['undistributed_profit'] = money(amount('retained_profit', period)+pending)
        result['interest_bearing_debt'] = money(amount('short_term_debt', period)+amount('long_term_debt', period))
        # Known absent categories are zero only because the complete leaf TB was validated.
        for key in ('cash', 'accounts_receivable', 'inventory', 'accounts_payable'):
            result.setdefault(key, ZERO)
        return result

    b, opening = balance('closing'), balance('opening')
    b.update({f'opening_{k}': opening[k] for k in ('total_assets', 'total_liabilities', 'total_equity', 'undistributed_profit')})
    cashflow = dict(support.get('cashflow') or {})
    if cashflow:
        for k in list(cashflow):
            cashflow[k] = field(cashflow, k)
        components = [cashflow.get(k) for k in ('operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow', 'fx_effect')]
        if all(v is not None for v in components) and cashflow.get('net_increase') is not None:
            if abs(sum(components, ZERO)-cashflow['net_increase']) > number('0.01'):
                raise ValueError('现金流分类净额与净增加额不一致')
    # Controls are supplied independently; never validate a subtotal against total - subtotal.
    controls = support.get('statement_controls') or {}
    items = {}
    groups = [('total_assets', '资产控制总额', ('asset', 'contra_asset'), 'closing'),
              ('total_liabilities', '负债控制总额', ('liability',), 'closing'),
              ('revenue', '收入控制总额', ('income',), 'movement'),
              ('net_profit', '净利润控制总额', ('income', 'expense'), 'movement')]
    for key, title, natures, period in groups:
        if key not in controls:
            continue
        parts = []
        for name, bucket in buckets.items():
            if bucket['nature'] not in natures or (key == 'revenue' and name != 'revenue'):
                continue
            sign = -1 if bucket['nature'] == 'contra_asset' or (key == 'net_profit' and bucket['nature'] == 'expense') else 1
            parts.append(sign*bucket[period])
        items[title] = [field(controls, key, required=True)]+(parts or [ZERO])
    # Require the complete independent control set, rather than silently skipping a missing one.
    detail = {'line_items': items if all(k in controls for k, *_ in groups) else {}}
    reconciliation = {'period': context['period'], 'balance': b, 'income': income, 'cashflow': cashflow,
                      'ledger': ledger, 'prior_closing': support.get('prior_closing') or {},
                      'bridges': support.get('bridges') or {}, 'detail': detail,
                      'equity_change': support.get('equity_change') or {}}
    return {'balance': b, 'opening_balance': opening, 'income': income, 'cashflow': cashflow,
            'reconciliation_input': reconciliation, 'buckets': buckets, 'lineage': lineage,
            'trial_balance_totals': totals, 'mapping_version': mapping.get('version'),
            'limitations': ['CAS单体未结转试算表；现金流来自另行提供的分类底稿，非余额表反推。',
                            '当前类别映射须由企业复核；受限资金及到期重分类须在输入底稿中处理。']}
