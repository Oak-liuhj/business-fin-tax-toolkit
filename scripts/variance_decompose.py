#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预算差异分解器（纯标准库）：收入量价结构三因素、成本价量差异、费用弹性预算。

用法:
  python variance_decompose.py --example
  python variance_decompose.py -i input.json [--md]

输入 JSON:
{
  "period": "2026Q1", "unit": "元",
  "revenue": {
    "items": [
      {"name":"A产品","budget_qty":1000,"budget_price":100,"actual_qty":900,"actual_price":105}
    ]
  },
  "cost": {
    "items": [
      {"name":"原材料X","budget_qty":500,"budget_price":20,"actual_qty":520,"actual_price":21}
    ]
  },
  "expense": {
    "fixed_budget": 500000, "variable_rate_budget": 0.05,
    "revenue_budget": 1000000, "revenue_actual": 950000, "expense_actual": 560000
  }
}
"""

import argparse
import json
import sys


def f(v, default=0.0):
    return float(v) if isinstance(v, (int, float)) else default


def decompose_revenue(items):
    """量差、价差、结构差（以预算加权均价为基准）。"""
    total_qty_b = sum(f(i.get("budget_qty")) for i in items)
    total_qty_a = sum(f(i.get("actual_qty")) for i in items)
    rev_b = sum(f(i.get("budget_qty")) * f(i.get("budget_price")) for i in items)
    rev_a = sum(f(i.get("actual_qty")) * f(i.get("actual_price")) for i in items)

    wavg_b = (rev_b / total_qty_b) if total_qty_b else 0.0

    rows, vol, price, mix = [], 0.0, 0.0, 0.0
    for i in items:
        qb, pb, qa, pa = f(i.get("budget_qty")), f(i.get("budget_price")), \
            f(i.get("actual_qty")), f(i.get("actual_price"))
        v_i = (qa - qb) * pb
        p_i = (pa - pb) * qa
        m_i = (qa - qb) * (pb - wavg_b)
        vol += v_i
        price += p_i
        mix += m_i
        rows.append({"name": i.get("name", ""), "revenue_budget": round(qb * pb, 2),
                     "revenue_actual": round(qa * pa, 2),
                     "diff": round(qa * pa - qb * pb, 2),
                     "volume": round(v_i, 2), "price": round(p_i, 2), "mix": round(m_i, 2)})

    total_diff = rev_a - rev_b
    return {
        "total_budget": round(rev_b, 2), "total_actual": round(rev_a, 2),
        "total_diff": round(total_diff, 2),
        "diff_pct": round(total_diff / rev_b, 4) if rev_b else None,
        "volume_effect": round(vol, 2), "price_effect": round(price, 2),
        "mix_effect": round(mix, 2),
        "check_residual": round(total_diff - (vol + price), 2),
        "note": "结构差以预算加权均价为基准，价格效应取实际销量为权；量差+价差=总差异，结构差含于其中，勿重复相加。",
        "rows": rows,
    }


def decompose_cost(items):
    rows, total_diff = [], 0.0
    for i in items:
        qb, pb, qa, pa = f(i.get("budget_qty")), f(i.get("budget_price")), \
            f(i.get("actual_qty")), f(i.get("actual_price"))
        price_v = (pa - pb) * qa          # 价格差异
        qty_v = (qa - qb) * pb            # 用量差异
        diff = qa * pa - qb * pb
        total_diff += diff
        rows.append({"name": i.get("name", ""), "cost_budget": round(qb * pb, 2),
                     "cost_actual": round(qa * pa, 2), "diff": round(diff, 2),
                     "price_variance": round(price_v, 2), "quantity_variance": round(qty_v, 2),
                     "flag": "U (不利)" if diff > 0 else ("F (有利)" if diff < 0 else "—")}) 
    return {"total_diff": round(total_diff, 2), "rows": rows,
            "note": "成本类差异超预算为不利(U)，低于预算为有利(F)。"}


def decompose_expense(e):
    fb = f(e.get("fixed_budget"))
    vr = f(e.get("variable_rate_budget"))
    rb = f(e.get("revenue_budget"))
    ra = f(e.get("revenue_actual"))
    ea = f(e.get("expense_actual"))
    base_budget = fb + vr * rb
    flex_budget = fb + vr * ra
    volume_effect = flex_budget - base_budget      # 随收入变动的部分
    spending = ea - flex_budget                    # 真实超支
    total = ea - base_budget
    return {
        "budget_static": round(base_budget, 2), "flex_budget": round(flex_budget, 2),
        "actual": round(ea, 2), "total_diff": round(total, 2),
        "volume_effect": round(volume_effect, 2), "spending_variance": round(spending, 2),
        "flag": "U (不利)" if total > 0 else ("F (有利)" if total < 0 else "—"),
        "note": "spending_variance 才是真实可控差异；volume_effect 是收入变动带来的合理增减。",
    }


EXAMPLE = {
    "period": "2026Q1", "unit": "元",
    "revenue": {"items": [
        {"name": "A产品", "budget_qty": 1000, "budget_price": 100, "actual_qty": 900, "actual_price": 105},
        {"name": "B产品", "budget_qty": 500, "budget_price": 200, "actual_qty": 620, "actual_price": 185},
    ]},
    "cost": {"items": [
        {"name": "原材料X", "budget_qty": 500, "budget_price": 20, "actual_qty": 520, "actual_price": 21},
        {"name": "直接人工", "budget_qty": 800, "budget_price": 30, "actual_qty": 860, "actual_price": 31},
    ]},
    "expense": {"fixed_budget": 500000, "variable_rate_budget": 0.05,
                "revenue_budget": 200000, "revenue_actual": 209200, "expense_actual": 553000},
}


def main():
    ap = argparse.ArgumentParser(description="预算差异分解")
    ap.add_argument("-i", "--input")
    ap.add_argument("--example", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()

    if a.example:
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=2))
        return 0
    if not a.input:
        ap.print_help()
        return 2

    with open(a.input, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    rev = decompose_revenue((data.get("revenue") or {}).get("items") or [])
    cost = decompose_cost((data.get("cost") or {}).get("items") or [])
    exp = decompose_expense(data.get("expense") or {})
    out = {"period": data.get("period", ""), "unit": data.get("unit", ""),
           "revenue": rev, "cost": cost, "expense": exp}

    if a.md:
        L = [f"# 预算差异分解 · {out['period']}", "", "## 收入", "",
             "| 产品 | 预算 | 实际 | 差异 | 量差 | 价差 | 结构差 |", "|---|---|---|---|---|---|---|"]
        for x in rev["rows"]:
            L.append(f"| {x['name']} | {x['revenue_budget']} | {x['revenue_actual']} | {x['diff']} | "
                     f"{x['volume']} | {x['price']} | {x['mix']} |")
        L += ["", f"合计差异 {rev['total_diff']}（量差 {rev['volume_effect']}，价差 {rev['price_effect']}，"
                  f"结构差 {rev['mix_effect']}）", "", "## 成本", "",
              "| 项目 | 预算 | 实际 | 差异 | 价格差异 | 用量差异 | 有利/不利 |", "|---|---|---|---|---|---|---|"]
        for x in cost["rows"]:
            L.append(f"| {x['name']} | {x['cost_budget']} | {x['cost_actual']} | {x['diff']} | "
                     f"{x['price_variance']} | {x['quantity_variance']} | {x['flag']} |")
        L += ["", "## 费用（弹性预算）", "",
              f"- 原预算 {exp['budget_static']}", f"- 弹性预算 {exp['flex_budget']}",
              f"- 实际 {exp['actual']}", f"- 总差异 {exp['total_diff']}（{exp['flag']}）",
              f"- 其中收入量影响 {exp['volume_effect']}，真实可控差异 {exp['spending_variance']}"]
        text = "\n".join(L)
    else:
        text = json.dumps(out, ensure_ascii=False, indent=2)

    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写入 {a.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())