"""Explicit-year carryforward ledger. Expiry/qualification must come from reviewed policies."""
from common import ZERO, field, money

KINDS = {'loss', 'advertising', 'education', 'donation', 'foreign_credit', 'temporary_difference'}


def summarize(records, year):
    if not isinstance(year, int) or isinstance(year, bool):
        raise ValueError('year 必须为整数年度')
    eligible, expired, pending, entries = {}, {}, [], []
    seen = set()
    for record in records:
        identity, kind = record.get('id'), record.get('kind')
        if not identity or identity in seen or kind not in KINDS:
            raise ValueError('台账 id 必须唯一且类型有效')
        seen.add(identity)
        origin, expiry = record.get('origin_year'), record.get('expiry_year')
        if not isinstance(origin, int) or isinstance(origin, bool) or not isinstance(expiry, int) or isinstance(expiry, bool) or expiry < origin:
            raise ValueError('需明确有效起始与到期年度，不推测政策期限')
        original = field(record, 'amount', required=True, minimum=0)
        consumptions = record.get('used_by_year') or {}
        used = ZERO
        for used_year, value in consumptions.items():
            consumed_year = int(used_year)
            if not origin < consumed_year <= expiry or consumed_year > year:
                raise ValueError('台账使用年度不在结转有效期内，或晚于评估年度')
            used += field({'v': value}, 'v', required=True, minimum=0)
        if used > original:
            raise ValueError('累计使用超过原始金额')
        remaining = money(original-used)
        verified = record.get('qualified') is True and record.get('policy_id') and record.get('evidence')
        if origin >= year:
            status = 'not_yet_available'
        elif expiry < year:
            status = 'expired'; expired[kind] = expired.get(kind, ZERO)+remaining
        elif not verified:
            status = 'pending'; pending.append(identity)
        else:
            status = 'eligible'; eligible[kind] = eligible.get(kind, ZERO)+remaining
        entries.append({'id': identity, 'kind': kind, 'remaining': remaining, 'status': status, 'expiry_year': expiry})
    return {'year': year, 'eligible_balances': eligible, 'expired_balances': expired, 'pending': pending,
            'entries': sorted(entries, key=lambda e: (e['expiry_year'], e['id'])),
            'note': '台账不自动更新已使用金额；仅汇总已审核有效余额，使用后须登记used_by_year并复核。'}


def main():
    import argparse
    from common import emit, read_json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-i', '--input', required=True); ap.add_argument('-o', '--output')
    ap.add_argument('--year', type=int, required=True)
    a = ap.parse_args(); out = summarize(read_json(a.input)['records'], a.year)
    emit(out, a.output); return 2 if out['pending'] else 0


if __name__ == '__main__':
    import sys
    from common import cli
    sys.exit(cli(main))
