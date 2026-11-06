"""Shared numeric, JSON and CLI contract (stdlib only)."""
import json
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from pathlib import Path

getcontext().prec = 40
ZERO = Decimal(0)
CENT = Decimal('0.01')
VERSION = '0.2.0'


def number(value, field='value', optional=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError(f'缺少数值字段：{field}')
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f'{field} 必须为有限数值')
    text = str(value).strip().replace('，', ',').replace('−', '-').replace('（', '(').replace('）', ')')
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    percent = text.endswith('%')
    text = text[:-1] if percent else text
    if ',' in text and not re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?', text):
        raise ValueError(f'{field} 千分位格式错误：{value}')
    try:
        result = Decimal(text.replace(',', ''))
    except InvalidOperation:
        raise ValueError(f'{field} 无法识别为数值：{value}') from None
    if not result.is_finite() or abs(result) > Decimal('1e28'):
        raise ValueError(f'{field} 超出有限数值范围')
    return result / 100 if percent else result


def field(data, key, default=None, required=False, minimum=None, maximum=None):
    if not isinstance(data, dict):
        raise ValueError(f'{key} 的父节点必须为对象')
    value = number(data.get(key, default), key, optional=not required)
    if value is not None and ((minimum is not None and value < number(minimum)) or
                              (maximum is not None and value > number(maximum))):
        raise ValueError(f'{key} 超出范围 [{minimum}, {maximum}]')
    return value


def money(value):
    return number(value).quantize(CENT, rounding=ROUND_HALF_UP)


def read_json(path):
    def invalid(value):
        raise ValueError(f'JSON 禁止非有限数值：{value}')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f'JSON 重复字段：{key}')
            out[key] = value
        return out
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_float=Decimal,
                       parse_constant=invalid, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('JSON 根节点必须为对象')
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False,
                      default=lambda x: str(x) if isinstance(x, Decimal) else _unsupported(x))


def _unsupported(value):
    raise TypeError(f'无法序列化 {type(value).__name__}')


def emit(value, output=None, markdown=None):
    text = markdown if markdown is not None else dumps(value)
    if output:
        Path(output).write_text(text, encoding='utf-8')
    else:
        print(text)


def cli(main):
    try:
        return main()
    except (ValueError, TypeError, KeyError, OSError, InvalidOperation) as exc:
        print(dumps({'status': 'error', 'error': str(exc)}), file=sys.stderr)
        return 2
