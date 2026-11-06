"""Normalize CSV/TSV or optional XLSX exports and retain per-cell provenance."""
import argparse
import csv
import hashlib
import io
from datetime import date, datetime
from pathlib import Path
from common import ZERO, cli, dumps, emit, money, number

PROFILES = {
    'trial_balance': {
        'account_code': ['科目编码', '科目代码'], 'account_name': ['科目名称'],
        'opening_debit': ['期初借方', '期初余额借方'], 'opening_credit': ['期初贷方', '期初余额贷方'],
        'debit': ['本期借方', '本期发生借方'], 'credit': ['本期贷方', '本期发生贷方'],
        'closing_debit': ['期末借方', '期末余额借方'], 'closing_credit': ['期末贷方', '期末余额贷方']},
    'bank': {'date': ['日期', '交易日期'], 'voucher_id': ['凭证号'], 'summary': ['摘要'],
             'counterparty': ['对方单位'], 'incoming': ['收入金额', '收入'], 'outgoing': ['支出金额', '支出'],
             'balance': ['余额'], 'bank_account': ['银行账号'], 'cashflow_category': ['现金流分类']},
    'invoices': {'type': ['类型'], 'invoice_id': ['发票号码', '发票号'], 'date': ['日期', '开票日期'],
                 'counterparty': ['对方单位'], 'rate': ['税率'], 'amount': ['金额不含税', '不含税金额'],
                 'tax': ['税额'], 'total': ['价税合计'], 'status': ['状态'], 'note': ['备注']}}
NUMERIC = {'opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit',
           'incoming', 'outgoing', 'balance', 'rate', 'amount', 'tax', 'total'}
ZERO_BLANK = {'opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit', 'incoming', 'outgoing'}
REQUIRED = {'trial_balance': {'account_code', 'account_name', 'opening_debit', 'opening_credit', 'debit', 'credit', 'closing_debit', 'closing_credit'},
            'bank': {'date', 'incoming', 'outgoing', 'bank_account'},
            'invoices': {'type', 'invoice_id', 'date', 'amount', 'tax', 'total', 'status'}}


def source_info(path):
    path = Path(path).resolve()
    return {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def column_name(index):
    out = ''
    while index:
        index, rem = divmod(index-1, 26); out = chr(65+rem)+out
    return out


def read_rows(path, sheet=None):
    path = Path(path)
    if path.suffix.lower() in ('.csv', '.tsv'):
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('gb18030')
        return list(csv.reader(io.StringIO(text), delimiter='\t' if path.suffix.lower() == '.tsv' else ',')), 'CSV', set()
    if path.suffix.lower() != '.xlsx':
        raise ValueError('仅支持 CSV、TSV 和 XLSX（旧版 XLS 请先另存）')
    try:
        import openpyxl
    except ImportError:
        raise ValueError('读取 XLSX 需可选 openpyxl 依赖，或先从 ERP/Excel 导出 CSV') from None
    book = openpyxl.load_workbook(path, data_only=False)
    if sheet is None and len(book.worksheets) != 1:
        book.close(); raise ValueError('多工作表 XLSX 必须指定 --sheet，避免选错账表')
    ws = book[sheet] if sheet else book.worksheets[0]
    rows = [[c.value for c in row] for row in ws.iter_rows()]
    formulas = {(c.row, c.column) for row in ws.iter_rows() for c in row if c.data_type == 'f'}
    for merged in ws.merged_cells.ranges:
        value = ws.cell(merged.min_row, merged.min_col).value
        for row in range(merged.min_row, merged.max_row+1):
            for col in range(merged.min_col, merged.max_col+1):
                rows[row-1][col-1] = value
    name = ws.title; book.close()
    return rows, name, formulas


def ingest(path, profile='trial_balance', unit='元', sheet=None, header_row=None, period_start=None, period_end=None):
    if profile not in PROFILES or unit not in ('元', '万元'):
        raise ValueError('不支持的数据类型或金额单位')
    rows, sheet_name, formulas = read_rows(path, sheet)
    source = source_info(path)
    aliases = {alias.replace(' ', ''): key for key, names in PROFILES[profile].items() for alias in [key]+names}
    aliases.update({'单位': 'unit', '币种': 'currency'})
    mapping, header = None, None
    candidates = [header_row-1] if header_row is not None else range(min(len(rows), 30))
    for index in candidates:
        if not 0 <= index < len(rows):
            raise ValueError('表头行超出文件范围')
        mapped = {j: aliases[str(v).strip().replace(' ', '')] for j, v in enumerate(rows[index])
                  if str(v).strip().replace(' ', '') in aliases}
        if index > 0:
            parent = ''
            for j, value in enumerate(rows[index]):
                upper = rows[index-1][j] if j < len(rows[index-1]) else None
                parent = str(upper).strip() if upper is not None and str(upper).strip() else parent
                joined = (parent+str(value).strip()).replace(' ', '')
                if joined in aliases and j not in mapped:
                    mapped[j] = aliases[joined]
        if REQUIRED[profile] <= set(mapped.values()):
            if len(set(mapped.values())) != len(mapped):
                raise ValueError('表头存在重复字段，需明确各列含义')
            mapping, header = mapped, index; break
    if mapping is None:
        raise ValueError(f'无法定位 {profile} 表头，需字段：{sorted(REQUIRED[profile])}')
    errors, records, seen = [], [], {}
    multiplier = number(10000 if unit == '万元' else 1)
    for index, row in enumerate(rows[header+1:], header+2):
        if all(v is None or not str(v).strip() for v in row):
            continue
        record, provenance, normalizations = {}, {}, []
        try:
            if len(row) != len(rows[header]):
                raise ValueError('列数与表头不一致')
            for col, key in mapping.items():
                raw = row[col]
                if (index, col+1) in formulas:
                    raise ValueError(f'{key} 含公式，须提供已计算并冻结的值及原始底稿')
                cell = f'{column_name(col+1)}{index}'
                provenance[key] = {'file_sha256': source['sha256'], 'sheet': sheet_name,
                                   'cell': cell, 'row': index, 'raw': str(raw) if raw is not None else None}
                if key in NUMERIC:
                    blank = raw is None or str(raw).strip() == ''
                    if blank and key in ZERO_BLANK:
                        value = ZERO
                        normalizations.append(f'{cell}: 借贷/收支空单边按零解释')
                    else:
                        value = number(raw, key)
                    record[key] = value if key == 'rate' else money(value*multiplier)
                    if key != 'balance' and key != 'rate' and record[key] < 0:
                        raise ValueError(f'{key} 为负；红字/反向金额须先确定导出规则')
                elif key == 'date':
                    value = raw.date() if isinstance(raw, datetime) else raw
                    value = str(value).replace('/', '-')
                    parsed = datetime.strptime(value, '%Y-%m-%d').date()
                    if period_start and parsed < date.fromisoformat(period_start) or period_end and parsed > date.fromisoformat(period_end):
                        raise ValueError(f'交易日期 {parsed} 不在所属期')
                    record[key] = parsed.isoformat()
                else:
                    record[key] = '' if raw is None else str(raw).strip()
            if any(not record.get(k) for k in REQUIRED[profile]-NUMERIC):
                raise ValueError('必填标识字段为空')
            if record.get('unit', unit) != unit or record.get('currency', 'CNY') != 'CNY':
                raise ValueError('存在单位或币种混用，请分币种/单位导出')
            if profile == 'invoices' and abs(record['amount']+record['tax']-record['total']) > number('0.01'):
                raise ValueError('发票金额+税额与价税合计不符')
            fingerprint = record['account_code'] if profile == 'trial_balance' else (
                f"{record['type']}:{record['invoice_id']}" if profile == 'invoices' else dumps(record))
            if fingerprint in seen:
                raise ValueError(f'重复标识/记录，与第 {seen[fingerprint]} 行冲突；需核实，未自动删除')
            seen[fingerprint] = index
            records.append({'id': f"{source['sha256'][:12]}:{sheet_name}:{index}",
                            'values': record, 'provenance': provenance, 'normalizations': normalizations})
        except (ValueError, TypeError) as exc:
            errors.append({'row': index, 'error': str(exc)})
    if not records:
        errors.append({'error': '无有效明细数据'})
    return {'schema_version': '0.2.0', 'profile': profile, 'unit': '元', 'input_unit': unit,
            'source': source, 'sheet': sheet_name, 'header_row': header+1,
            'records': records, 'errors': errors, 'ready': not errors}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-i', '--input', required=True); ap.add_argument('-o', '--output')
    ap.add_argument('--profile', choices=list(PROFILES), default='trial_balance')
    ap.add_argument('--unit', choices=['元', '万元'], required=True)
    ap.add_argument('--sheet'); ap.add_argument('--header-row', type=int)
    ap.add_argument('--period-start'); ap.add_argument('--period-end')
    a = ap.parse_args()
    out = ingest(a.input, a.profile, a.unit, a.sheet, a.header_row, a.period_start, a.period_end)
    emit(out, a.output); return 0 if out['ready'] else 2


if __name__ == '__main__':
    import sys
    sys.exit(cli(main))
