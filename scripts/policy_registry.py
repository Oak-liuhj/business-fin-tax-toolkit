"""Local policy register validation; never claims online verification of legal text."""
import argparse
from datetime import date
from urllib.parse import urlparse
from common import cli, emit, number, read_json


def validate_tax(data, calculated, registry):
    context = data.get('context') or {}
    start, end = context.get('period_start'), context.get('period_end')
    issues, references = [], []
    required_context = ('company_id', 'ledger_id', 'period_start', 'period_end', 'region', 'industry', 'taxpayer_type')
    for key in required_context:
        if not context.get(key):
            issues.append(f'缺少 context.{key}')
    if start and end:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError('政策期间起止倒置')
    policies = registry.get('policies', [])
    if not isinstance(policies, list) or len({x['id'] for x in policies}) != len(policies):
        raise ValueError('政策登记必须为数组且 id 唯一')
    bindings = data.get('policy_bindings') or {}
    params = {k: v['params_used'] for k, v in calculated.items() if isinstance(v, dict) and 'params_used' in v}
    if 'super_deduction' in calculated:
        params['super_deduction'] = {'ratio': calculated['super_deduction']['ratio']}
    for scope, actual in params.items():
        candidates = [p for p in policies if p['id'] == bindings.get(scope)]
        if len(candidates) != 1:
            issues.append(f'{scope} 缺少唯一政策绑定'); continue
        p = candidates[0]
        local_issues = []
        for key in ('document_title', 'document_number', 'article', 'official_url', 'effective_from',
                    'effective_to', 'reviewed_at', 'reviewer', 'evidence_sha256'):
            if not p.get(key):
                local_issues.append(f'缺少 {key}')
        host = urlparse(p.get('official_url', '')).hostname or ''
        if not host.endswith('.gov.cn') or not p.get('official_url', '').startswith('https://'):
            local_issues.append('需明确官方 HTTPS 来源')
        import re
        if not re.fullmatch(r'[a-fA-F0-9]{64}', str(p.get('evidence_sha256', ''))):
            local_issues.append('需归档原文 SHA256')
        if p.get('verification_status') != 'verified':
            local_issues.append('政策未完成人工核验')
        if start and end and p.get('effective_from') and p.get('effective_to'):
            begin, finish = date.fromisoformat(p['effective_from']), date.fromisoformat(p['effective_to'])
            if not begin <= date.fromisoformat(start) <= date.fromisoformat(end) <= finish:
                local_issues.append('政策未覆盖整个所属期，需分期计算')
        if p.get('reviewed_at'):
            reviewed = date.fromisoformat(p['reviewed_at'])
            as_of = date.fromisoformat(context.get('as_of', date.today().isoformat()))
            if reviewed > as_of:
                local_issues.append('核验时间晚于评估日')
        applicability = p.get('applicability') or {}
        for key in ('region', 'industry', 'taxpayer_type'):
            allowed = applicability.get(key)
            if not isinstance(allowed, list) or not allowed or (allowed != ['*'] and context.get(key) not in allowed):
                local_issues.append(f'{key} 适用条件未满足')
        for qualification in p.get('required_qualifications', []):
            proof = (context.get('qualifications') or {}).get(qualification)
            if not isinstance(proof, dict) or proof.get('qualified') is not True or not proof.get('evidence'):
                local_issues.append(f'缺少资格与证据：{qualification}')
        expected = (p.get('parameters') or {}).get(scope) or {}
        for key, value in actual.items():
            if key not in expected or number(expected[key]) != number(value):
                local_issues.append(f'{key} 参数未被已绑定规则覆盖或与规则不符')
        issues += [f'{scope}/{p["id"]}: {s}' for s in local_issues]
        references.append({'scope': scope, 'id': p['id'], 'document_number': p.get('document_number'),
                           'article': p.get('article'), 'official_url': p.get('official_url'),
                           'evidence_sha256': p.get('evidence_sha256'), 'issues': local_issues})
    return {'status': 'verified' if not issues and references else 'unverified',
            'registry_version': registry.get('version'), 'issues': issues, 'references': references,
            'boundary': 'verified 表示本地登记的人工核验及参数/适用性检查通过；不代表程序联网验证法规或申报正确性。'}


def main():
    from tax_calc import calculate
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-i', '--input', required=True); ap.add_argument('--registry', required=True)
    ap.add_argument('-o', '--output')
    a = ap.parse_args(); data = read_json(a.input)
    out = validate_tax(data, calculate(data), read_json(a.registry))
    emit(out, a.output)
    return 0 if out['status'] == 'verified' else 2


if __name__ == '__main__':
    import sys
    sys.exit(cli(main))
