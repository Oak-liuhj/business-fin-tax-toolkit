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
from common import ZERO, cli, dumps, field, money, number, read_json


def f(v, default=None):
    return number(v)


def decompose_revenue(items):
    """量差、价差、结构差（以预算加权均价为基准）。"""
    total_qty_b = sum(f(i.get("budget_qty")) for i in items)
    total_qty_a = sum(f(i.get("actual_qty")) for i in items)
    rev_b = sum(f(i.get("budget_qty")) * f(i.get("budget_price")) for i in items)
    rev_a = sum(f(i.get("actual_qty")) * f(i.get("actual_price")) for i in items)

    if total_qty_b == 0 and total_qty_a != 0:
        raise ValueError("预算销量为零，需补充新品量价结构分解基准")
    wavg_b = (rev_b / total_qty_b) if total_qty_b else ZERO

    rows, vol, price, mix = [], ZERO, ZERO, ZERO
    for i in items:
        qb, pb, qa, pa = f(i.get("budget_qty")), f(i.get("budget_price")), \
            f(i.get("actual_qty")), f(i.get("actual_price"))
        v_i = (qa - qb) * wavg_b
        p_i = (pa - pb) * qa
        m_i = (qa - qb) * (pb - wavg_b)
        vol += v_i
        price += p_i
        mix += m_i
        rows.append({"name": i.get("name", ""), "revenue_budget": money(qb * pb),
                     "revenue_actual": money(qa * pa),
                     "diff": money(qa * pa - qb * pb),
                     "volume": money(v_i), "price": money(p_i), "mix": money(m_i)})

    total_diff = rev_a - rev_b
    return {
        "total_budget": money(rev_b), "total_actual": money(rev_a),
        "total_diff": money(total_diff),
        "diff_pct": round(total_diff / rev_b, 4) if rev_b else None,
        "volume_effect": money(vol), "price_effect": money(price),
        "mix_effect": money(mix),
        "check_residual": money(total_diff - (vol + price + mix)),
        "note": "结构差以预算加权均价为基准，价格效应取实际销量为权；纯量差+价差+结构差=总差异；产品销量必须具有可比单位。",
        "rows": rows,
    }


def decompose_cost(items):
    rows, total_diff = [], ZERO
    for i in items:
        qb, pb, qa, pa = f(i.get("budget_qty")), f(i.get("budget_price")), \
            f(i.get("actual_qty")), f(i.get("actual_price"))
        price_v = (pa - pb) * qa          # 价格差异
        standard = f(i.get("standard_qty_for_actual_output", qb))
        qty_v = (qa - standard) * pb
        activity_v = (standard - qb) * pb            # 用量差异
        diff = qa * pa - qb * pb
        total_diff += diff
        rows.append({"name": i.get("name", ""), "cost_budget": money(qb * pb),
                     "cost_actual": money(qa * pa), "diff": money(diff),
                     "price_variance": money(price_v), "quantity_variance": money(qty_v), "activity_variance": money(activity_v),
                     "basis": "实际产出标准耗用" if "standard_qty_for_actual_output" in i else "静态预算差异，不能单独解释为效率",
                     "flag": "U (不利)" if diff > 0 else ("F (有利)" if diff < 0 else "—")}) 
    return {"total_diff": money(total_diff), "rows": rows,
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
        "budget_static": money(base_budget), "flex_budget": money(flex_budget),
        "actual": money(ea), "total_diff": money(total),
        "volume_effect": money(volume_effect), "spending_variance": money(spending),
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
        print(dumps(EXAMPLE))
        return 0
    if not a.input:
        ap.print_help()
        return 2

    data = read_json(a.input)

    if not any(data.get(k) for k in ("revenue", "cost", "expense")):
        raise ValueError("缺少预算分析数据")
    rev = decompose_revenue(data["revenue"]["items"]) if data.get("revenue") else None
    cost = decompose_cost(data["cost"]["items"]) if data.get("cost") else None
    exp = decompose_expense(data["expense"]) if data.get("expense") else None
    out = {"period": data.get("period", ""), "unit": data.get("unit", ""),
           "revenue": rev, "cost": cost, "expense": exp}

    if a.md:
        L = [f"# 预算差异分解 · {out['period']}", ""]
        if rev is not None:
            L += ["## 收入", "", "| 产品 | 预算 | 实际 | 差异 | 纯量差 | 价差 | 结构差 |",
                  "|---|---|---|---|---|---|---|"]
            for x in rev["rows"]:
                L.append(f"| {x['name']} | {x['revenue_budget']} | {x['revenue_actual']} | {x['diff']} | "
                         f"{x['volume']} | {x['price']} | {x['mix']} |")
            L += ["", f"合计差异：{rev['total_diff']}；残差：{rev['check_residual']}", rev["note"]]
        if cost is not None:
            L += ["", "## 成本", "", "```json", dumps(cost), "```"]
        if exp is not None:
            L += ["", "## 费用（弹性预算）", "", "```json", dumps(exp), "```"]
        text = "\n".join(L)
    else:
        text = dumps(out)

    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写入 {a.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(cli(main))