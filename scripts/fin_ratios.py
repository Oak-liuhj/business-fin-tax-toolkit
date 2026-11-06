#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财务比率与杜邦分析计算器（纯标准库，无第三方依赖）。

用法:
    python fin_ratios.py --example            # 输出示例输入
    python fin_ratios.py -i input.json        # 生成 JSON 结果
    python fin_ratios.py -i input.json --md   # 输出 Markdown 表格

输入 JSON 结构（缺项自动跳过，不报错）:
{
  "company": "示例公司",
  "period": "2026年度",
  "unit": "元",
  "current": {
    "balance": {"total_assets":..., "current_assets":..., ...},
    "income": {...},
    "cashflow": {...}
  },
  "prior": { "balance": {...}, "income": {...}, "cashflow": {...} }
}
键名见 --example 输出。
}
"""

import argparse
import json
import sys
from common import cli, dumps, field, money, read_json

# ---------------------------------------------------------------- 工具函数


def g(d, key):
    """安全取数，非数字返回 None。"""
    if not isinstance(d, dict):
        return None
    v = field(d, key)
    return None if v is None else float(v)


def avg(cur, pri, key):
    """平均余额 = (期初 + 期末) / 2；任一缺失均不替代。"""
    a, b = g(cur, key), g(pri, key)
    if a is not None and b is not None:
        return (a + b) / 2.0
    return None


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def r(x, n=2):
    return None if x is None else round(x, n)


# ---------------------------------------------------------------- 计算主体


def compute(data):
    cur = data.get("current", {}) or {}
    pri = data.get("prior", {}) or {}
    cb, ci, cc = cur.get("balance", {}) or {}, cur.get("income", {}) or {}, cur.get("cashflow", {}) or {}
    pb, pi, pc = pri.get("balance", {}) or {}, pri.get("income", {}) or {}, pri.get("cashflow", {}) or {}

    days = field(data, "period_days", 365, minimum=1, maximum=366)
    if "period_days" not in data and any(token in str(data.get("period", "")) for token in ("月", "Q", "季度")):
        raise ValueError("月度/季度分析必须显式提供 period_days")
    year_days = field(data, "year_days", 365, minimum=360, maximum=366)
    annualize = data.get("annualize", False)
    if not isinstance(annualize, bool):
        raise ValueError("annualize 必须为布尔值")
    revenue = g(ci, "revenue")
    cogs = g(ci, "cogs")
    gross = (revenue - cogs) if (revenue is not None and cogs is not None) else None
    ebit = g(ci, "ebit")
    pretax = g(ci, "profit_before_tax")
    net = g(ci, "net_profit")
    interest = g(ci, "interest_expense") or 0.0
    dep, amort = g(ci, "depreciation"), g(ci, "amortization")
    da = dep + amort if dep is not None and amort is not None else None

    out = {"company": data.get("company", ""), "period": data.get("period", ""), "unit": data.get("unit", ""),
           "metrics": {}, "dupont": {}, "warning": [], "period_days": days, "annualize": annualize, "assumptions": []}

    M = out["metrics"]
    if not pri.get("balance"):
        out["assumptions"].append("缺少期初余额，平均余额相关指标不计算；未用期末余额代替")
    if "period_days" not in data:
        out["assumptions"].append("未传 period_days，按年度365天计算")

    # ---- 盈利
    M["gross_margin"] = r(div(gross, revenue), 4)
    M["operating_margin"] = r(div(ebit, revenue), 4)
    M["net_margin"] = r(div(net, revenue), 4)
    M["roa"] = r(div(net, avg(cb, pb, "total_assets")), 4)
    M["roe"] = r(div(net, avg(cb, pb, "total_equity")), 4)
    expense_items = {}
    for k in ("selling_expense", "admin_expense", "rd_expense", "finance_expense"):
        expense_items[k] = r(div(g(ci, k), revenue), 4)
    M["expense_ratio"] = expense_items

    # ---- 偿债
    ca, cl = g(cb, "current_assets"), g(cb, "current_liabilities")
    M["current_ratio"] = r(div(ca, cl), 2)
    inv = g(cb, "inventory")
    M["quick_ratio"] = r(div((ca - inv) if ca is not None and inv is not None else None, cl), 2)
    M["cash_ratio"] = r(div(g(cb, "cash"), cl), 2)
    M["debt_ratio"] = r(div(g(cb, "total_liabilities"), g(cb, "total_assets")), 4)
    M["interest_coverage"] = r(div(ebit, interest), 2) if interest else None
    ebitda = ebit + da if ebit is not None and da is not None else None
    # Stock debt must be compared with annual EBITDA, not an unlabelled month's EBITDA.
    annual_ebitda = ebitda*float(year_days/days) if ebitda is not None and annualize else ebitda
    M["debt_to_ebitda"] = r(div(g(cb, "interest_bearing_debt"), annual_ebitda), 2) if days >= 360 or annualize else None

    # ---- 运营
    ar_avg, inv_avg, ap_avg = avg(cb, pb, "accounts_receivable"), avg(cb, pb, "inventory"), avg(cb, pb, "accounts_payable")
    ar_to = div(revenue, ar_avg)
    inv_to = div(cogs, inv_avg)
    ap_to = div(cogs, ap_avg)
    ta_to = div(revenue, avg(cb, pb, "total_assets"))
    M["ar_turnover"] = r(ar_to, 2)
    M["dso"] = r(div(float(days), ar_to), 1)
    M["inventory_turnover"] = r(inv_to, 2)
    M["dio"] = r(div(float(days), inv_to), 1)
    M["ap_turnover"] = r(ap_to, 2)
    M["dpo"] = r(div(float(days), ap_to), 1)
    M["asset_turnover"] = r(ta_to, 4)
    M["ccc"] = None
    if M["dso"] is not None and M["dio"] is not None and M["dpo"] is not None:
        M["ccc"] = r(M["dso"] + M["dio"] - M["dpo"], 1)

    # ---- 现金流
    ocf = g(cc, "operating_cash_flow")
    capex = g(cc, "capex")
    M["ocf_to_net_profit"] = r(div(ocf, net), 2)
    M["cash_to_revenue"] = r(div(g(cc, "cash_from_sales"), revenue), 2)
    M["free_cash_flow"] = money(field(cc, "operating_cash_flow") - field(cc, "capex")) if (ocf is not None and capex is not None) else None

    # ---- 杜邦
    eq_avg = avg(cb, pb, "total_equity")
    ta_avg = avg(cb, pb, "total_assets")
    out["dupont"] = {
        "roe": M["roe"],
        "net_margin": M["net_margin"],
        "asset_turnover": M["asset_turnover"],
        "equity_multiplier": r(div(ta_avg, eq_avg), 4),
        "check_roe": r(div(net, revenue) * div(revenue, ta_avg) * div(ta_avg, eq_avg), 4)
        if M["net_margin"] is not None and M["asset_turnover"] is not None and eq_avg and ta_avg else None,
    }
    if ebit is not None and pretax is not None and net is not None and revenue and ta_avg and eq_avg:
        out["dupont_5"] = {
            "tax_burden": r(div(net, pretax), 4),
            "interest_burden": r(div(pretax, ebit), 4),
            "ebit_margin": r(div(ebit, revenue), 4),
            "asset_turnover": r(div(revenue, ta_avg), 4),
            "equity_multiplier": r(div(ta_avg, eq_avg), 4),
        }

    out["annualized"] = {k: None if M[k] is None else r(M[k]*float(year_days/days), 4)
                         for k in ("roa", "roe", "asset_turnover", "ar_turnover", "inventory_turnover", "ap_turnover")} if annualize else {}
    out["unavailable_metrics"] = [k for k, v in M.items() if v is None]
    if not any((cb, ci, cc, pb)):
        raise ValueError("输入不足，无法计算任何财务指标")
    out["status"] = "partial" if out["unavailable_metrics"] else "complete"
    thresholds = {"current_ratio_min": 1, "interest_coverage_min": 3, "debt_ratio_max": .7,
                  "ocf_to_net_profit_min": 1, "ccc_max": 120, "gross_margin_min": .15}
    overrides = data.get("thresholds") or {}
    for key in overrides:
        if key not in thresholds:
            raise ValueError(f"未知预警阈值：{key}")
        thresholds[key] = float(field(overrides, key, required=True, minimum=0))
    out["thresholds"] = thresholds
    out["threshold_basis"] = data.get("threshold_basis") or "经验阈值，仅作线索；须结合行业与业务周期复核"
    # ---- 预警
    W = out["warning"]
    if M["current_ratio"] is not None and M["current_ratio"] < thresholds["current_ratio_min"]:
        W.append("流动比率低于已选阈值，需复核短期偿付")
    if M["interest_coverage"] is not None and M["interest_coverage"] < thresholds["interest_coverage_min"]:
        W.append("利息保障倍数低于已选阈值，需复核付息安排")
    if M["debt_ratio"] is not None and M["debt_ratio"] > thresholds["debt_ratio_max"]:
        W.append("资产负债率高于已选阈值，需结合行业评估杠杆")
    if M["ocf_to_net_profit"] is not None and net is not None and net > 0 and M["ocf_to_net_profit"] < thresholds["ocf_to_net_profit_min"]:
        W.append("正利润下净现比低于已选阈值，需核对营运资金和非现金损益")
    if M["ccc"] is not None and M["ccc"] > thresholds["ccc_max"]:
        W.append("现金转换周期高于已选阈值，需分析营运资金占用")
    if M["free_cash_flow"] is not None and M["free_cash_flow"] < 0:
        W.append("自由现金流为负，需结合期初现金与投资周期评估资金需求")
    if M["gross_margin"] is not None and M["gross_margin"] < thresholds["gross_margin_min"]:
        W.append("毛利率低于已选阈值，需核实行业特性与成本")
    return out


# ---------------------------------------------------------------- 输出


def to_markdown(res):
    lines = [f"# 财务比率结果 · {res.get('company') or ''} {res.get('period') or ''}", ""]
    m = res["metrics"]
    rows = [
        ("毛利率", m.get("gross_margin")), ("营业利润率", m.get("operating_margin")),
        ("净利率", m.get("net_margin")), ("ROA", m.get("roa")), ("ROE", m.get("roe")),
        ("流动比率", m.get("current_ratio")), ("速动比率", m.get("quick_ratio")),
        ("现金比率", m.get("cash_ratio")), ("资产负债率", m.get("debt_ratio")),
        ("利息保障倍数", m.get("interest_coverage")), ("有息负债/EBITDA", m.get("debt_to_ebitda")),
        ("应收周转率", m.get("ar_turnover")), ("DSO(天)", m.get("dso")),
        ("存货周转率", m.get("inventory_turnover")), ("DIO(天)", m.get("dio")),
        ("应付周转率", m.get("ap_turnover")), ("DPO(天)", m.get("dpo")),
        ("现金转换周期(天)", m.get("ccc")), ("总资产周转率", m.get("asset_turnover")),
        ("净现比", m.get("ocf_to_net_profit")), ("收现比", m.get("cash_to_revenue")),
        ("自由现金流", m.get("free_cash_flow")),
    ]
    lines += ["| 指标 | 数值 |", "|---|---|"]
    for k, v in rows:
        lines.append(f"| {k} | {'—' if v is None else v} |")
    d = res.get("dupont") or {}
    if d:
        lines += ["", "## 杜邦分解", "",
                  "ROE = 净利率 × 总资产周转率 × 权益乘数 = "
                  f"{d.get('net_margin')} × {d.get('asset_turnover')} × {d.get('equity_multiplier')}"
                  f" = {d.get('check_roe')}", ""]
    lines += ["", "预警依据：" + res.get("threshold_basis", ""), "```json", dumps(res.get("thresholds", {})), "```"]
    if res.get("warning"):
        lines += ["## 预警", ""] + [f"- {w}" for w in res["warning"]]
    lines += ["", "## 口径与缺项", "", f"期间天数：{res['period_days']}；年化：{res['annualize']}"]
    lines += [f"- {w}" for w in res.get("assumptions", [])]
    lines += [f"- 无法计算：{', '.join(res.get('unavailable_metrics', []))}"]
    if res.get("annualized"):
        lines += ["", "## 年化指标", "", "```json", dumps(res["annualized"]), "```"]
    return "\n".join(lines)


EXAMPLE = {
    "company": "示例制造有限公司", "period": "2026年度", "unit": "元",
    "current": {
        "balance": {"total_assets": 120000000, "current_assets": 56000000, "inventory": 22000000,
                    "accounts_receivable": 18000000, "accounts_payable": 15000000, "cash": 9000000,
                    "current_liabilities": 38000000, "total_liabilities": 68000000,
                    "total_equity": 52000000, "interest_bearing_debt": 30000000},
        "income": {"revenue": 180000000, "cogs": 132000000, "ebit": 16000000,
                   "interest_expense": 2400000, "profit_before_tax": 13600000, "net_profit": 10200000,
                   "depreciation": 7000000, "amortization": 1000000,
                   "selling_expense": 12000000, "admin_expense": 14000000,
                   "rd_expense": 6000000, "finance_expense": 2800000},
        "cashflow": {"operating_cash_flow": 14800000, "capex": 9000000,
                     "cash_from_sales": 172000000},
    },
    "prior": {
        "balance": {"total_assets": 112000000, "current_assets": 52000000, "inventory": 20000000,
                    "accounts_receivable": 16000000, "accounts_payable": 14000000, "cash": 8000000,
                    "current_liabilities": 35000000, "total_liabilities": 62000000,
                    "total_equity": 50000000, "interest_bearing_debt": 26000000},
        "income": {"revenue": 165000000, "cogs": 119000000, "ebit": 15000000,
                   "interest_expense": 2200000, "profit_before_tax": 12800000, "net_profit": 9600000,
                   "depreciation": 6500000, "amortization": 1000000},
        "cashflow": {"operating_cash_flow": 12500000, "capex": 8000000, "cash_from_sales": 158000000},
    },
}


def main():
    ap = argparse.ArgumentParser(description="财务比率与杜邦分析")
    ap.add_argument("-i", "--input", help="输入 JSON 文件路径")
    ap.add_argument("--example", action="store_true", help="打印示例输入 JSON")
    ap.add_argument("--md", action="store_true", help="以 Markdown 输出")
    ap.add_argument("-o", "--output", help="结果写入文件")
    a = ap.parse_args()

    if a.example:
        print(dumps(EXAMPLE))
        return 0
    if not a.input:
        ap.print_help()
        return 2
    data = read_json(a.input)
    res = compute(data)
    text = to_markdown(res) if a.md else dumps(res)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {a.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(cli(main))