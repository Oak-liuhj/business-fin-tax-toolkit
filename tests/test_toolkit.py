import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.dont_write_bytecode = True
from common import number, money, read_json, dumps
import reconcile_check as rc
import tax_calc as tax
import fin_ratios as ratios
import zscore_eva as ze
import variance_decompose as variance
from policy_registry import validate_tax
from data_ingest import ingest
from close_workflow import execute
from carryforward_ledger import summarize
from statement_builder import build


def sample(name):
    return read_json(ROOT/'assets/samples'/f'{name}.json')


class NumericTests(unittest.TestCase):
    def test_accounting_and_percent_strings(self):
        self.assertEqual(number('(1,234.50)'), number('-1234.5'))
        self.assertEqual(number('13%'), number('.13'))
        self.assertEqual(money('1.005'), number('1.01'))

    def test_invalid_is_not_zero(self):
        for value in (True, 'NaN', float('inf'), 'unknown', '1,2', {}, None):
            with self.subTest(value=value), self.assertRaises(ValueError): number(value)

    def test_precision_in_json(self):
        self.assertIn('9999999999999999.99', dumps({'money': money('9999999999999999.99')}))

    def test_duplicate_json_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'input.json'
            for text in ('{"a": 1, "a": 2}', '{"a": NaN}'):
                p.write_text(text)
                with self.assertRaises(ValueError): read_json(p)


class ReconcileTests(unittest.TestCase):
    def test_empty_never_passes(self):
        out = rc.run({})
        self.assertFalse(out['ready_for_analysis']); self.assertEqual(out['passed'], 0)
        self.assertEqual(out['coverage'], 0)

    def test_complete_comparisons(self):
        self.assertTrue(rc.run(sample('reconcile_input_sample'))['ready_for_analysis'])

    def test_manual_data_not_assumed_passed(self):
        d = sample('reconcile_input_sample'); d.pop('ledger'); d.pop('prior_closing')
        out = rc.run(d)
        self.assertEqual(out['pending_review'], 2); self.assertFalse(out['ready_for_analysis'])

    def test_distribution_and_restricted_cash_bridge(self):
        d = sample('reconcile_input_sample')
        d['balance']['undistributed_profit'] -= 100
        d['balance']['cash'] += 200
        d['bridges'] = {'profit_distribution': 100, 'restricted_cash': 200}
        self.assertTrue(rc.run(d)['ready_for_analysis'])

    def test_wrong_prior_period_detected(self):
        d = sample('reconcile_input_sample'); d['prior_closing']['total_liabilities'] += 1
        self.assertEqual(rc.run(d)['results'][7]['status'], '未通过')

    def test_bad_detail_not_skipped(self):
        d = sample('reconcile_input_sample'); d['detail']['line_items'] = {'broken': [1]}
        with self.assertRaises(ValueError): rc.run(d)


class TaxTests(unittest.TestCase):
    def test_loss_donation_nonnegative_limit(self):
        d = {'accounting_profit': -1000000, 'revenue': 0, 'donation': 10000}
        out = tax.cit(d)
        self.assertEqual(out['limits']['donation']['limit'], 0)
        self.assertEqual(out['limits']['donation']['add_back'], 10000)

    def test_zero_revenue_entertainment(self):
        out = tax.cit({'accounting_profit': 0, 'revenue': 0, 'entertainment_expense': 100})
        self.assertEqual(out['limits']['entertainment']['add_back'], 100)

    def test_negative_deduction_balance_rejected(self):
        with self.assertRaises(ValueError): tax.super_deduction({'ratio': '.05', 'current_decrease': 100}, 1000)

    def test_vat_linked_after_deduction(self):
        out = tax.calculate(sample('tax_input_sample'))
        self.assertEqual(out['vat']['total_payable'], 64000)
        self.assertEqual(out['surcharge']['base'], 64000)
        self.assertEqual(out['surcharge']['total'], 7680)
        self.assertIn('super_deduction', tax.calculate(sample('tax_input_sample'), 'vat'))
        self.assertIn('64000.00', tax.to_markdown(out))

    def test_simple_tax_is_not_offset_by_credit(self):
        out = tax.vat({'sales_excl_tax': 0, 'input_tax': 100, 'simple_sales_excl_tax': 1000})
        self.assertEqual(out['closing_credit'], 100); self.assertEqual(out['total_payable'], 30)
        self.assertEqual(out['vat_burden_rate'], number('.03'))

    def test_explicit_surcharge_adjustments(self):
        d = sample('tax_input_sample'); d['surcharge']['adjustments'] = {'paid_export_offset': 1000, 'eligible_refund': -200}
        self.assertEqual(tax.calculate(d)['surcharge']['base'], 64800)

    def test_annual_loss_not_overused(self):
        out = tax.cit({'accounting_profit': 100, 'revenue': 100, 'loss_carryforward': 200})
        self.assertEqual(out['loss_used'], 100); self.assertEqual(out['loss_remaining'], 100)

    def test_round_half_up_and_rate_validation(self):
        self.assertEqual(tax.vat({'sales_excl_tax': '0.05', 'output_rate': '.1', 'input_tax': 0})['output_tax'], number('.01'))
        for d in ({'sales_excl_tax': 100, 'output_rate': 13}, {'sales_excl_tax': 'bad'}):
            with self.assertRaises(ValueError): tax.vat(d)
        with self.assertRaises(ValueError): tax.calculate({})
        with self.assertRaises(ValueError): tax.vat({'sales_excl_tax': 100})
        with self.assertRaises(ValueError): tax.calculate({'unit': '万元', 'vat': {'sales_excl_tax': 100, 'input_tax': 0}})

    def test_export_refund_balance(self):
        out = tax.export_refund(sample('tax_input_sample')['export'])
        self.assertEqual(out['refund'], 18000)
        self.assertEqual(out['refund']+out['exempt_offset'], out['refund_cap'])
        with self.assertRaises(ValueError): tax.export_refund({'fob_rmb': 100})

    def test_carryforward_ledger_filters_expired_and_tracks_usage(self):
        records = sample('carryforward_ledger_sample')['records']
        out = summarize(records, 2026)
        self.assertEqual(out['eligible_balances']['loss'], 80000)
        self.assertEqual(out['expired_balances']['donation'], 5000)
        d = {'accounting_profit': 100000, 'revenue': 100000, 'tax_year': 2026, 'carryforward_ledger': records}
        self.assertEqual(tax.cit(d)['loss_used'], 80000)
        records[0]['used_by_year']['2025'] = 200000
        with self.assertRaises(ValueError): summarize(records, 2026)


class AnalysisTests(unittest.TestCase):
    def test_missing_working_capital_does_not_crash(self):
        out = ratios.compute({'current': {'income': {'revenue': 100}, 'balance': {'accounts_receivable': 100}}})
        self.assertIsNone(out['metrics']['ccc'])

    def test_month_days_and_no_implicit_closing_average(self):
        d = {'period': '2026年1月', 'period_days': 31, 'current': {'income': {'revenue': 100, 'cogs': 50},
             'balance': {'accounts_receivable': 100}}, 'prior': {'balance': {'accounts_receivable': 100}}}
        self.assertEqual(ratios.compute(d)['metrics']['dso'], 31)
        d.pop('prior'); self.assertIsNone(ratios.compute(d)['metrics']['dso'])
        d.pop('period_days')
        with self.assertRaises(ValueError): ratios.compute(d)

    def test_monthly_ebitda_not_compared_with_annual_debt(self):
        d = sample('fin_data_sample'); d.update(period='2026年1月', period_days=31)
        self.assertIsNone(ratios.compute(d)['metrics']['debt_to_ebitda'])
        d['annualize'] = True
        self.assertIsNotNone(ratios.compute(d)['metrics']['debt_to_ebitda'])

    def test_industry_thresholds_change_warnings(self):
        d = sample('fin_data_sample')
        d['thresholds'] = {'debt_ratio_max': '.1'}
        self.assertTrue(any('资产负债率' in w for w in ratios.compute(d)['warning']))
        d['thresholds']['debt_ratio_max'] = '1'
        self.assertFalse(any('资产负债率' in w for w in ratios.compute(d)['warning']))

    def test_dupont_uses_unrounded_factors(self):
        out = ratios.compute(sample('fin_data_sample'))
        self.assertEqual(out['dupont']['roe'], out['dupont']['check_roe'])

    def test_zero_liability_is_model_error(self):
        d = copy.deepcopy(ze.EXAMPLE['zscore_input']); d['total_liabilities'] = 0
        self.assertIn('error', ze.zscore(d, 'private_1983'))

    def test_z2_does_not_need_unused_revenue(self):
        d = copy.deepcopy(ze.EXAMPLE['zscore_input']); d.pop('revenue')
        self.assertIn('z_score', ze.zscore(d, 'emerging_z2'))

    def test_three_factor_bridge_and_cost_activity(self):
        out = variance.decompose_revenue(variance.EXAMPLE['revenue']['items'])
        self.assertEqual(out['volume_effect']+out['price_effect']+out['mix_effect'], out['total_diff'])
        c = variance.decompose_cost([{'budget_qty': 100, 'budget_price': 10, 'actual_qty': 130,
                                    'actual_price': 11, 'standard_qty_for_actual_output': 120}])['rows'][0]
        self.assertEqual(c['activity_variance'], 200)
        self.assertEqual(c['quantity_variance'], 100)
        self.assertEqual(c['price_variance']+c['quantity_variance']+c['activity_variance'], c['diff'])


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.data = sample('tax_input_sample'); self.out = tax.calculate(self.data)
        self.registry = read_json(ROOT/'references/policy-registry.json')

    def verified_fixture(self):
        p = self.registry['policies'][0]
        p.update(verification_status='verified', document_number='TEST-ONLY', article='TEST',
                 official_url='https://test.gov.cn/test', reviewed_at='2026-11-01', reviewer='TEST', evidence_sha256='a'*64)
        self.data['context']['qualifications'] = {'additional_deduction_eligible': {'qualified': True, 'evidence': 'TEST'}}

    def test_demo_never_verified(self):
        self.assertEqual(validate_tax(self.data, self.out, self.registry)['status'], 'unverified')

    def test_matching_locally_reviewed_record(self):
        self.verified_fixture()
        self.assertEqual(validate_tax(self.data, self.out, self.registry)['status'], 'verified')

    def test_expiry_qualification_and_parameter_changes_block(self):
        self.verified_fixture()
        for key, value in [('effective_to', '2026-02-15'), ('official_url', 'https://evil.gov.cn.example.com'),
                           ('evidence_sha256', 'bad')]:
            with self.subTest(key=key):
                r = copy.deepcopy(self.registry); r['policies'][0][key] = value
                self.assertEqual(validate_tax(self.data, self.out, r)['status'], 'unverified')
        changed = copy.deepcopy(self.registry)
        changed['policies'][0]['parameters']['vat']['output_rate'] = '.09'
        self.assertEqual(validate_tax(self.data, self.out, changed)['status'], 'unverified')
        self.data['context']['qualifications'] = {}
        self.assertEqual(validate_tax(self.data, self.out, self.registry)['status'], 'unverified')


class IntegrationTests(unittest.TestCase):
    def test_original_samples_cli_json_and_markdown(self):
        pairs = [('fin_ratios','fin_data_sample'), ('zscore_eva','zscore_eva_sample'),
                 ('variance_decompose','variance_input_sample'), ('reconcile_check','reconcile_input_sample'), ('tax_calc','tax_input_sample')]
        for name, filename in pairs:
            for mode in ([], ['--md']):
                with self.subTest(script=name, mode=mode):
                    p = subprocess.run([sys.executable, '-B', str(ROOT/'scripts'/f'{name}.py'), '-i',
                        str(ROOT/'assets/samples'/f'{filename}.json'), *mode], capture_output=True, text=True, encoding='utf-8',
                        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
                    self.assertEqual(p.returncode, 0, p.stderr)
                    if not mode: json.loads(p.stdout)

    def test_cli_invalid_and_unverified_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'empty.json'; p.write_text('{}')
            for script, args in [('reconcile_check', ['-i', str(p)]), ('tax_calc', ['-i', str(p)]),
                    ('tax_calc', ['-i', str(ROOT/'assets/samples/tax_input_sample.json'), '--mode', 'review'])]:
                proc = subprocess.run([sys.executable, '-B', str(ROOT/'scripts'/f'{script}.py'), *args], capture_output=True)
                self.assertNotEqual(proc.returncode, 0)

    def test_template_columns_and_adjustments(self):
        with (ROOT/'assets/templates/汇算清缴调整表.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        self.assertTrue(all(len(row) == len(rows[0]) for row in rows))
        self.assertEqual(sum(number(row[4]) for row in rows[1:12]), number(rows[12][4]))

    def test_multirow_header_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'input.csv'
            p.write_text('科目编码,科目名称,期初余额,,本期发生,,期末余额,\n,,借方,贷方,借方,贷方,借方,贷方\n1002,银行,1,,1,,2,\n1002,银行,1,,1,,2,\n', encoding='utf-8')
            out = ingest(p)
            self.assertEqual(out['header_row'], 2); self.assertFalse(out['ready'])
            self.assertEqual(out['records'][0]['provenance']['closing_debit']['cell'], 'G3')

    def test_month_close_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = execute(ROOT/'assets/samples/month_close/workflow.json', Path(tmp)/'one')
            two = execute(ROOT/'assets/samples/month_close/workflow.json', Path(tmp)/'two')
            self.assertEqual(one['status'], 'ready_for_review'); self.assertEqual(one['run_id'], two['run_id'])
            statements = read_json(Path(tmp)/'one/statements.json')
            self.assertEqual(number(statements['balance']['total_assets']), 213000)
            self.assertEqual(number(statements['income']['net_profit']), 21000)
            self.assertEqual(number(statements['cashflow']['operating_cash_flow']), 30000)
            self.assertEqual(read_json(Path(tmp)/'one/checks.json')['passed'], 9)
            with self.assertRaises(ValueError): execute(ROOT/'assets/samples/month_close/workflow.json', Path(tmp)/'one')
            for filename, digest in one['artifacts'].items():
                self.assertEqual(hashlib.sha256((Path(tmp)/'one'/filename).read_bytes()).hexdigest(), digest)

    def test_wrong_enterprise_and_missing_review_block_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = ROOT/'assets/samples/month_close'
            config = read_json(base/'workflow.json')
            for key in ('trial_balance', 'support', 'mapping', 'bank'): config[key] = str((base/config[key]).resolve())
            support = read_json(base/'support.json'); support['context']['company_id'] = 'OTHER'
            sp = Path(tmp)/'support.json'; sp.write_text(dumps(support), encoding='utf-8'); config['support'] = str(sp)
            cp = Path(tmp)/'config.json'; cp.write_text(dumps(config), encoding='utf-8')
            out = execute(cp, Path(tmp)/'wrong')
            self.assertEqual(out['status'], 'blocked'); self.assertFalse((Path(tmp)/'wrong/analysis.json').exists())
            support['context']['company_id'] = 'DEMO-COMPANY'; support.pop('mapping_review')
            sp.write_text(dumps(support), encoding='utf-8')
            out = execute(cp, Path(tmp)/'pending')
            self.assertEqual(out['status'], 'blocked'); self.assertFalse((Path(tmp)/'pending/analysis.json').exists())

    def test_bank_period_and_unbalanced_trial_balance(self):
        out = ingest(ROOT/'assets/samples/银行流水_sample.csv', profile='bank', period_start='2026-02-01', period_end='2026-02-28')
        self.assertFalse(out['ready']); self.assertTrue(out['errors'])
        data = ingest(ROOT/'assets/samples/科目余额表_sample.csv')
        support = read_json(ROOT/'assets/samples/month_close/support.json')
        with self.assertRaises(ValueError): build(data, read_json(ROOT/'references/account-mapping.json'), support['context'], support)

    def test_bad_header_produces_blocked_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = ROOT/'assets/samples/month_close'
            config = read_json(base/'workflow.json')
            for key in ('trial_balance', 'support', 'mapping', 'bank'): config[key] = str((base/config[key]).resolve())
            bad = Path(tmp)/'bad.csv'; bad.write_text('unknown\nwrong\n', encoding='utf-8')
            config['trial_balance'] = str(bad)
            cp = Path(tmp)/'config.json'; cp.write_text(dumps(config), encoding='utf-8')
            out = execute(cp, Path(tmp)/'run')
            self.assertEqual(out['status'], 'blocked')
            self.assertTrue((Path(tmp)/'run/report.md').exists())
            self.assertFalse((Path(tmp)/'run/analysis.json').exists())

    def test_independent_source_control_mismatch_blocks(self):
        base = ROOT/'assets/samples/month_close'
        support = read_json(base/'support.json')
        support['statement_controls']['total_assets'] += 1
        statements = build(ingest(base/'trial_balance.csv'), read_json(ROOT/'references/account-mapping.json'), support['context'], support)
        out = rc.run(statements['reconciliation_input'])
        self.assertEqual(out['results'][6]['status'], '未通过')


if __name__ == '__main__':
    unittest.main()
