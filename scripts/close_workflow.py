"""Reproducible month-end -> draft statements -> reconciliation -> analysis run."""
import argparse
import hashlib
import shutil
import copy
from datetime import date
from pathlib import Path
from common import VERSION, cli, dumps, emit, read_json
from data_ingest import ingest, source_info
from statement_builder import build
from reconcile_check import run as reconcile, to_markdown as reconcile_md
from fin_ratios import compute, to_markdown as analysis_md
from cashflow_builder import build_bank_cashflow


def execute(config_path, output_dir):
    config_path, output_dir = Path(config_path).resolve(), Path(output_dir).resolve()
    config = read_json(config_path)
    context = config.get('context') or {}
    for key in ('company_id', 'ledger_id', 'company', 'period', 'period_start', 'period_end',
                'currency', 'unit', 'accounting_standard', 'scope', 'profit_state'):
        if not context.get(key):
            raise ValueError(f'缺少 context.{key}')
    start, end = date.fromisoformat(context['period_start']), date.fromisoformat(context['period_end'])
    if start > end or (end-start).days >= 366:
        raise ValueError('期间应为1至366天')
    if context['unit'] != '元':
        raise ValueError('共享工作底稿统一为元；原始导入单位用 input_unit 指定')
    base = config_path.parent
    paths = {'config': config_path}
    for key in ('trial_balance', 'support', 'mapping', 'bank'):
        if not config.get(key):
            raise ValueError(f'缺少 {key} 文件路径')
        paths[key] = (base/config[key]).resolve()
    # Preserve all input bytes, avoid clobbering earlier runs and outputs inside input files.
    if output_dir.exists():
        raise ValueError('输出目录已存在；请使用新的运行目录，保留既有结果')
    for source in paths.values():
        if source == output_dir or output_dir in source.parents:
            raise ValueError('输出目录不得包含输入文件')
        if not source.is_file():
            raise ValueError(f'输入文件不存在：{source}')
    output_dir.mkdir(parents=True)
    snapshots = output_dir/'inputs'; snapshots.mkdir()
    originals = {k: source_info(v) for k, v in paths.items()}
    copies = {}
    for key, path in paths.items():
        target = snapshots/f'{key}{path.suffix}'
        shutil.copyfile(path, target)
        if source_info(target)['sha256'] != originals[key]['sha256']:
            raise ValueError('输入在复制期间发生变化，请重新运行')
        copies[key] = target
    code_hashes = {p.name: source_info(p)['sha256'] for p in Path(__file__).parent.glob('*.py')}
    fingerprint = hashlib.sha256(dumps({'inputs': originals, 'code': code_hashes, 'version': VERSION}).encode()).hexdigest()
    manifest = {'version': VERSION, 'run_id': fingerprint[:20], 'context': context,
                'sources': originals, 'code_sha256': code_hashes,
                'status': 'blocked', 'artifacts': {}, 'tasks': [], 'errors': []}
    raw_support = read_json(copies['support'])
    support = copy.deepcopy(raw_support)
    for key in ('company_id', 'ledger_id', 'period_start', 'period_end', 'currency', 'unit'):
        if (support.get('context') or {}).get(key) != context[key]:
            manifest['errors'].append(f'辅助底稿 context.{key} 与任务不一致')
    def import_or_error(key, **kwargs):
        try:
            return ingest(copies[key], **kwargs)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return {'ready': False, 'source': source_info(copies[key]), 'records': [], 'errors': [{'error': str(exc)}]}
    imported = import_or_error('trial_balance', unit=config.get('input_unit', '元'),
                               sheet=config.get('sheet'), header_row=config.get('header_row'))
    imported['source']['original_file'] = originals['trial_balance']['file']
    emit(imported, output_dir/'normalized.json')
    manifest['errors'] += [f"导入第{x.get('row', '?')}行：{x['error']}" for x in imported['errors']]
    bank = import_or_error('bank', profile='bank', unit=config.get('bank_input_unit', '元'),
                  sheet=config.get('bank_sheet'), period_start=context['period_start'], period_end=context['period_end'])
    bank['source']['original_file'] = originals['bank']['file']
    emit(bank, output_dir/'bank_normalized.json')
    manifest['errors'] += [f"流水第{x.get('row', '?')}行：{x['error']}" for x in bank['errors']]
    statements, checks, analysis = None, None, None
    cashflow_lineage = {}
    if not manifest['errors']:
        try:
            cf, cf_detail, cashflow_lineage = build_bank_cashflow(bank, support)
            for key, value in cf.items():
                if key in (support.get('cashflow') or {}) and support['cashflow'][key] is not None:
                    from common import number
                    if abs(number(support['cashflow'][key])-value) > number('0.01'):
                        raise ValueError(f'现金流辅助底稿 {key} 与银行分类结果不一致')
            support['cashflow'] = {**(support.get('cashflow') or {}), **cf}
            support['cashflow_direct_detail'] = cf_detail
            statements = build(imported, read_json(copies['mapping']), context, support)
        except (ValueError, TypeError, KeyError) as exc:
            manifest['errors'].append(str(exc))
    mapping_review = support.get('mapping_review') or {}
    approved_mapping_hash = mapping_review.get('mapping_sha256')
    if not mapping_review.get('reviewer') or not mapping_review.get('evidence') or approved_mapping_hash != originals['mapping']['sha256']:
        manifest['tasks'].append({'id': 'mapping_review', 'status': 'pending', 'action': '复核科目映射，记录复核人、证据及映射SHA256'})
    else:
        manifest['tasks'].append({'id': 'mapping_review', 'status': 'completed', 'reviewer': mapping_review['reviewer'], 'evidence': mapping_review['evidence']})
    cf_review = support.get('cashflow_review') or {}
    if not cf_review.get('reviewer') or not cf_review.get('evidence') or cf_review.get('bank_sha256') != originals['bank']['sha256']:
        manifest['tasks'].append({'id': 'cashflow_review', 'status': 'pending', 'action': '确认银行账户完整性及现金流分类，记录复核人与流水SHA256'})
    else:
        manifest['tasks'].append({'id': 'cashflow_review', 'status': 'completed', 'reviewer': cf_review['reviewer'], 'evidence': cf_review['evidence']})
    if statements:
        emit(statements, output_dir/'statements.json')
        emit(statements['reconciliation_input'], output_dir/'reconcile_input.json')
        checks = reconcile(statements['reconciliation_input'])
        emit(checks, output_dir/'checks.json')
        emit(checks, output_dir/'checks.md', reconcile_md(checks))
        if not checks['ready_for_analysis']:
            manifest['errors'] += [f"{x['item']}：{x['status']} {x['hint']}" for x in checks['results'] if x['status'] != '通过']
        if not manifest['errors'] and all(t['status'] == 'completed' for t in manifest['tasks']):
            analysis_input = {'company': context['company'], 'period': context['period'], 'unit': '元',
                              'period_days': (end-start).days+1, 'annualize': config.get('annualize', False),
                              'current': {k: statements[k] for k in ('balance', 'income', 'cashflow')},
                              'prior': {'balance': statements['opening_balance']}}
            emit(analysis_input, output_dir/'analysis_input.json')
            analysis = compute(analysis_input)
            emit(analysis, output_dir/'analysis.json')
            emit(analysis, output_dir/'analysis.md', analysis_md(analysis))
            manifest['status'] = 'ready_for_review'
    manifest['tasks'].append({'id': 'final_review', 'status': 'pending',
                              'action': '负责人复核异常、凭证截止与现金流分类；实际锁账由授权ERP/宿主执行'})
    # JSON pointers retain every supporting raw value; generated field lineage is separate.
    provenance = {'trial_balance': imported['records'], 'derived': statements['lineage'] if statements else {},
                  'bank': bank['records'], 'cashflow_derived': cashflow_lineage,
                  'support': {'source': originals['support'], 'values': raw_support},
                  'formula_catalog': {
                      'total_assets': 'Σ资产期末净额 - Σ抵减资产期末净额',
                      'net_profit': 'Σ收入本期净发生 - Σ费用本期净发生',
                      'total_equity': 'Σ权益期末 + 未结转本期净利润',
                      'dso': '期间天数 × (期初应收+期末应收)/2 ÷ 本期收入',
                      'free_cash_flow': 'support#/cashflow/operating_cash_flow - support#/cashflow/capex'},
                  'metric_inputs': 'analysis_input.json；balance字段追溯statements.json及derived；cashflow追溯support的JSON指针'}
    emit(provenance, output_dir/'provenance.json')
    lines = [f"# {context['company']} · {context['period']}月结工作底稿", '',
             f"状态：{manifest['status']}；运行编号：{manifest['run_id']}", '',
             '本次输出为复核底稿；最终复核、账套锁定与归档尚需负责人完成。', '',
             '## 自动处理结果', '',
             f"- 导入：{len(imported['records'])} 条；异常：{len(imported['errors'])} 条",
             f"- 勾稽：{checks['passed'] if checks else 0}/9 通过",
             f"- 分析：{'已生成，待最终复核' if analysis else '已阻止，待补全数据或解除异常'}", '',
             '## 待办与异常', '']
    lines += [f'- {e}' for e in manifest['errors']]
    lines += [f"- {t['id']}：{t['status']}；{t.get('action', t.get('evidence', ''))}" for t in manifest['tasks']]
    if statements:
        lines += ['', '## 报表关键结果（元）', '', f"资产：{statements['balance']['total_assets']}；负债：{statements['balance']['total_liabilities']}；权益：{statements['balance']['total_equity']}",
                  f"净利润：{statements['income']['net_profit']}", '', '## 编制边界', '']+statements['limitations']
    (output_dir/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    for p in output_dir.iterdir():
        if p.is_file():
            manifest['artifacts'][p.name] = source_info(p)['sha256']
    emit(manifest, output_dir/'manifest.json')
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-i', '--input', required=True); ap.add_argument('-o', '--output', required=True)
    a = ap.parse_args()
    manifest = execute(a.input, a.output)
    emit({'status': manifest['status'], 'run_id': manifest['run_id'], 'output': str(Path(a.output).resolve()), 'errors': manifest['errors']})
    return 0 if manifest['status'] == 'ready_for_review' else 2


if __name__ == '__main__':
    import sys
    sys.exit(cli(main))
