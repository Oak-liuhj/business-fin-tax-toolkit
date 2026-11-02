#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Altman Z-Score 与 EVA 计算器（纯标准库）。

三个 Z 版本系数不可混用：
  1968 上市公司制造业   : 1.2X1+1.4X2+3.3X3+0.6X4+1.0X5   >2.99 安全 / <1.81 危险
  1983 非上市 Z'        : 0.717X1+0.847X2+3.107X3+0.420X4+0.998X5  >2.90 / <1.23
  新兴市场/非制造业 Z'' : 6.56X1+3.26X2+6.72X3+1.05X4       >2.60 / <1.10

EVA: NOPAT = EBIT*(1-t); IC = 有息负债+权益-超额现金; EVA = NOPAT - WACC*IC
WACC 全部参数必须显式给出，缺失则拒绝计算（不猜）。

用法:
  python zscore_eva.py --example
  python zscore_eva.py -i input.json [--md]
"""

import argparse
import json
import sys


def num(d, k):
    v = (d or {}).get(k)
    return float(v) if isinstance(v, (int, float)) else None


def safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def zscore(b, version="listed_1968"):
    ta = num(b, "total_assets")
    if ta is None or ta == 0:
        return {"error": "缺少 total_assets，无法计算 Z-Score"}
    wc = num(b, "working_capital")
    if wc is None:
        ca, cl = num(b, "current_assets"), num(b, "current_liabilities")
        wc = (ca - cl) if (ca is not None and cl is not None) else None
    re_ = num(b, "retained_earnings")
    ebit = num(b, "ebit")
    tl = num(b, "total_liabilities")
    rev = num(b, "revenue")
    eq_book = num(b, "total_equity")
    eq_mv = num(b, "market_cap")

    x1 = safe_div(wc, ta)
    x2 = safe_div(re_, ta)
    x3 = safe_div(ebit, ta)
    x5 = safe_div(rev, ta)

    missing = [n for n, v in (("X1", x1), ("X2", x2), ("X3", x3), ("X5", x5)) if v is None]
    if missing:
        return {"error": "缺少计算所需字段: " + ", ".join(missing)}

    res = {"version": version, "x1_wc_ta": round(x1, 4), "x2_re_ta": round(x2, 4),
           "x3_ebit_ta": round(x3, 4), "x5_rev_ta": round(x5, 4)}

    if version == "listed_1968":
        if eq_mv is None or tl is None:
            return {"error": "1968 版需 market_cap 与 total_liabilities"}
        x4 = safe_div(eq_mv, tl)
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        safe, distress = 2.99, 1.81
        res["x4_eq_mv_tl"] = round(x4, 4)
    elif version == "private_1983":
        if eq_book is None or tl is None:
            return {"error": "Z' 版需 total_equity(账面) 与 total_liabilities"}
        x4 = safe_div(eq_book, tl)
        z = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5
        safe, distress = 2.90, 1.23
        res["x4_book_eq_tl"] = round(x4, 4)
    elif version == "emerging_z2":
        if eq_book is None or tl is None:
            return {"error": "Z'' 版需 total_equity(账面) 与 total_liabilities"}
        x4 = safe_div(eq_book, tl)
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        safe, distress = 2.60, 1.10
        res["x4_book_eq_tl"] = round(x4, 4)
    else:
        return {"error": f"未知版本 {version}"}

    res["z_score"] = round(z, 4)
    res["zone"] = "安全区" if z > safe else ("危险区" if z < distress else "灰色区")
    res["thresholds"] = {"safe_above": safe, "distress_below": distress}
    res["caveat"] = "模型基于美国制造业样本，对中国新经济企业判别力有限，仅作参考信号，不作为破产预测结论。"
    return res


def eva(d):
    ebit = num(d, "ebit")
    tax = num(d, "tax_rate")
    debt = num(d, "interest_bearing_debt")
    eq = num(d, "total_equity")
    excess_cash = num(d, "excess_cash") or 0.0
    wacc = num(d, "wacc")

    if ebit is None or tax is None:
        return {"error": "缺少 ebit 或 tax_rate"}
    if wacc is None:
        params = {k: d.get(k) for k in ("rf", "beta", "erp", "cost_of_debt", "debt_ratio", "tax_rate")}
        if all(v is not None for v in params.values()):
            rf, beta, erp = float(params["rf"]), float(params["beta"]), float(params["erp"])
            rd, dr, t = float(params["cost_of_debt"]), float(params["debt_ratio"]), float(params["tax_rate"])
            re_ = rf + beta * erp
            wacc = (1 - dr) * re_ + dr * rd * (1 - t)
            computed = {"re": round(re_, 4), "wacc": round(wacc, 4),
                        "inputs": {k: params[k] for k in params}}
        else:
            return {"error": "WACC 未给出且 CAPM 参数不全（需 rf/beta/erp/cost_of_debt/debt_ratio/tax_rate），拒绝计算",
                    "required": ["wacc"] }
    else:
        computed = {"wacc": round(wacc, 4)}

    if debt is None or eq is None:
        return {"error": "缺少 interest_bearing_debt 或 total_equity，无法计算投入资本"}

    nopat = ebit * (1 - tax)
    ic = debt + eq - excess_cash
    capital_charge = wacc * ic
    value = nopat - capital_charge
    return {
        "nopat": round(nopat, 2), "invested_capital": round(ic, 2),
        "wacc": computed["wacc"], "capital_charge": round(capital_charge, 2),
        "eva": round(value, 2),
        "verdict": "创造价值 (EVA>0)" if value > 0 else ("毁灭价值 (EVA<0)" if value < 0 else "价值中性"),
        "wacc_detail": computed,
        "note": "投入资本含超额现金调整；超额现金若未提供按 0 处理。",
    }


EXAMPLE = {
    "company": "示例制造有限公司", "period": "2026年度", "unit": "元",
    "zscore_input": {
        "total_assets": 120000000, "working_capital": 18000000,
        "retained_earnings": 26000000, "ebit": 16000000,
        "total_liabilities": 68000000, "revenue": 180000000,
        "total_equity": 52000000, "market_cap": 90000000,
    },
    "eva_input": {"ebit": 16000000, "tax_rate": 0.25, "interest_bearing_debt": 30000000,
                  "total_equity": 52000000, "excess_cash": 2000000,
                  "rf": 0.025, "beta": 1.1, "erp": 0.06,
                  "cost_of_debt": 0.045, "debt_ratio": 0.35},
}


def main():
    ap = argparse.ArgumentParser(description="Z-Score 与 EVA")
    ap.add_argument("-i", "--input")
    ap.add_argument("--example", action="store_true")
    ap.add_argument("--version", default="private_1983",
                    choices=["listed_1968", "private_1983", "emerging_z2"])
    ap.add_argument("--md", action="store_true")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()

    if a.example:
        print(json.dumps(EXAMPLE, ensure_ascii=False, indent=2))
        return 0
    if not a.input:
        ap.print_help()
        return 2

    with open(a.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    z = zscore(data.get("zscore_input", {}), a.version)
    e = eva(data.get("eva_input", {}))
    out = {"company": data.get("company", ""), "period": data.get("period", ""),
           "zscore": z, "eva": e}

    if a.md:
        lines = [f"# Z-Score 与 EVA · {out['company']}", "", "## Z-Score 财务预警", ""]
        if "error" in z:
            lines.append(f"- 无法计算：{z['error']}")
        else:
            lines += [f"- 版本：{z['version']}", f"- 得分：{z['z_score']}", f"- 区间：{z['zone']}",
                      f"- 阈值：>{z['thresholds']['safe_above']} 安全，<{z['thresholds']['distress_below']} 危险",
                      f"- 局限：{z['caveat']}"]
        lines += ["", "## EVA 价值创造", ""]
        if "error" in e:
            lines.append(f"- 无法计算：{e['error']}")
        else:
            lines += [f"- NOPAT：{e['nopat']}", f"- 投入资本：{e['invested_capital']}",
                      f"- WACC：{e['wacc']}", f"- 资本成本：{e['capital_charge']}",
                      f"- EVA：{e['eva']}（{e['verdict']}）"]
        text = "\n".join(lines)
    else:
        text = json.dumps(out, ensure_ascii=False, indent=2)

    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {a.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())