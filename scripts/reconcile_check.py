#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报表勾稽校验（纯标准库）：九项检查，逐项给出通过/差额/提示。

用法:
  python reconcile_check.py --example
  python reconcile_check.py -i input.json [--md]

输入 JSON（缺项的检查自动跳过并标注）:
{
  "period": "2026年度",
  "balance": {"total_assets":..., "total_liabilities":..., "total_equity":...,
              "cash":..., "opening_total_assets":..., "opening_total_liabilities":...,
              "opening_total_equity":..., "undistributed_profit":..., "opening_undistributed_profit":...},
  "income": {"net_profit":..., "income_tax":..., "current_tax":..., "deferred_tax":...},
  "cashflow": {"net_increase":..., "opening_cash":..., "closing_cash":...,
               "operating_cash_flow":..., "net_profit":..., "depreciation_amortization":...},
  "detail": {"line_items": {"资产总计": [100, 40, 60], ...}},   # 可选：小计=明细之和
  "equity_change": {"closing_total":..., "balance_total_equity":...}   # 可选
}
"""

import argparse
import json
import sys

TOL = 0.01  # 允许的四舍五入误差


def n(d, k):
    v = (d or {}).get(k)
    return float(v) if isinstance(v, (int, float)) else None


def check(no, name, ok, detail, hint=""):
    return {"no": no, "item": name, "status": "通过" if ok else "未通过",
            "detail": detail, "hint": hint if not ok else ""}


def run(data):
    b = data.get("balance") or {}
    inc = data.get("income") or {}
    cf = data.get("cashflow") or {}
    res = []

    # 1 资产 = 负债 + 权益
    ta, tl, te = n(b, "total_assets"), n(b, "total_liabilities"), n(b, "total_equity")
    if None not in (ta, tl, te):
        diff = ta - (tl + te)
        res.append(check(1, "资产 = 负债 + 所有者权益", abs(diff) <= TOL,
                         f"资产 {ta:.2f}，负债+权益 {tl + te:.2f}，差额 {diff:.2f}",
                         "检查是否存在未结转损益、科目归类错误或漏记凭证"))
    else:
        res.append(check(1, "资产 = 负债 + 所有者权益", True, "字段不全，跳过"))

    # 2 净利润 ↔ 未分配利润变动
    npf = n(inc, "net_profit")
    upd, o_upd = n(b, "undistributed_profit"), n(b, "opening_undistributed_profit")
    if None not in (npf, upd, o_upd):
        diff = (upd - o_upd) - npf
        res.append(check(2, "净利润 ↔ 未分配利润变动", abs(diff) <= TOL,
                         f"未分配利润变动 {upd - o_upd:.2f}，净利润 {npf:.2f}，差额 {diff:.2f}",
                         "差额应仅为利润分配、盈余公积提取或以前年度调整；否则检查结转"))
    else:
        res.append(check(2, "净利润 ↔ 未分配利润变动", True, "字段不全，跳过"))

    # 3 现金净增加额 ↔ 货币资金变动
    ni, oc, cc_ = n(cf, "net_increase"), n(cf, "opening_cash"), n(cf, "closing_cash")
    cash = n(b, "cash")
    if ni is not None and None not in (oc, cc_):
        diff = (ni - (cc_ - oc))
        ok = abs(diff) <= TOL
        extra = ""
        if cash is not None and abs(cc_ - cash) > TOL:
            ok = False
            extra = f"；期末现金 {cc_:.2f} 与资产负债表货币资金 {cash:.2f} 不符"
        res.append(check(3, "现金净增加额 ↔ 货币资金变动", ok,
                         f"净增加 {ni:.2f}，期初 {oc:.2f} → 期末 {cc_:.2f}，差额 {diff:.2f}{extra}",
                         "核对受限资金口径与现金等价物定义"))
    else:
        res.append(check(3, "现金净增加额 ↔ 货币资金变动", True, "字段不全，跳过"))

    # 4 现金流量表起点净利润 = 利润表净利润
    cf_np = n(cf, "net_profit")
    if cf_np is not None and npf is not None:
        diff = cf_np - npf
        res.append(check(4, "现金流表起点净利润 = 利润表净利润", abs(diff) <= TOL,
                         f"现金流 {cf_np:.2f}，利润表 {npf:.2f}，差额 {diff:.2f}", "间接法起点取数错误"))
    else:
        res.append(check(4, "现金流表起点净利润 = 利润表净利润", True, "字段不全，跳过"))

    # 5 折旧摊销（有则比对，无则提示手工核对）
    da = n(cf, "depreciation_amortization")
    if da is not None:
        res.append(check(5, "折旧摊销与累计折旧/摊销发生额", True,
                         f"表中折旧摊销 {da:.2f}；需与累计折旧/摊销本期贷方发生额（剔除处置转出）人工核对",
                         ""))
    else:
        res.append(check(5, "折旧摊销与累计折旧/摊销发生额", True, "未提供，跳过"))

    # 6 所得税 = 当期 + 递延
    it, ct, dt = n(inc, "income_tax"), n(inc, "current_tax"), n(inc, "deferred_tax")
    if None not in (it, ct, dt):
        diff = it - (ct + dt)
        res.append(check(6, "所得税费用 = 当期所得税 + 递延所得税", abs(diff) <= TOL,
                         f"所得税费用 {it:.2f}，当期 {ct:.2f} + 递延 {dt:.2f}，差额 {diff:.2f}",
                         "检查递延所得税资产/负债变动是否全部计入所得税费用"))
    else:
        res.append(check(6, "所得税费用 = 当期 + 递延", True, "字段不全，跳过"))

    # 7 小计 = 明细之和
    items = (data.get("detail") or {}).get("line_items") or {}
    if items:
        bad = []
        for name, vals in items.items():
            if not isinstance(vals, list) or len(vals) < 2:
                continue
            total = float(vals[0])
            rest = sum(float(x) for x in vals[1:])
            if abs(total - rest) > TOL:
                bad.append(f"{name}: 小计 {total:.2f} ≠ 明细之和 {rest:.2f}")
        res.append(check(7, "各小计 = 明细之和", not bad,
                         "全部一致" if not bad else "；".join(bad), "逐栏核对明细列"))
    else:
        res.append(check(7, "各小计 = 明细之和", True, "未提供明细，跳过"))

    # 8 本期期初 = 上期期末
    o_ta = n(b, "opening_total_assets")
    if o_ta is not None and ta is not None:
        res.append(check(8, "本期期初 = 上期期末", True,
                         f"本期期初资产 {o_ta:.2f}；需与上期已报资产负债表期末数人工比对", ""))
    else:
        res.append(check(8, "本期期初 = 上期期末", True, "未提供上期数，跳过"))

    # 9 权益变动表 ↔ 资产负债表
    ec = data.get("equity_change") or {}
    ect, bte = n(ec, "closing_total"), n(ec, "balance_total_equity")
    if None not in (ect, bte):
        diff = ect - bte
        res.append(check(9, "所有者权益变动表 = 资产负债表权益", abs(diff) <= TOL,
                         f"变动表 {ect:.2f}，资产负债表 {bte:.2f}，差额 {diff:.2f}", "检查各栏合计"))
    else:
        res.append(check(9, "所有者权益变动表 = 资产负债表权益", True, "字段不全，跳过"))

    failed = [x for x in res if x["status"] == "未通过"]
    return {"period": data.get("period", ""), "total_checks": len(res),
            "failed": len(failed), "conclusion": "全部通过" if not failed else f"{len(failed)} 项未通过，不得出分析结论",
            "results": res}


EXAMPLE = {
    "period": "2026年度",
    "balance": {"total_assets": 120000000, "total_liabilities": 68000000, "total_equity": 52000000,
                "cash": 9000000, "opening_total_assets": 112000000,
                "undistributed_profit": 22000000, "opening_undistributed_profit": 11800000},
    "income": {"net_profit": 10200000, "income_tax": 3400000, "current_tax": 3200000, "deferred_tax": 200000},
    "cashflow": {"net_increase": 1000000, "opening_cash": 8000000, "closing_cash": 9000000,
                 "operating_cash_flow": 14800000, "net_profit": 10200000,
                 "depreciation_amortization": 8000000},
    "detail": {"line_items": {"流动资产合计": [56000000, 9000000, 18000000, 22000000, 7000000]}},
    "equity_change": {"closing_total": 52000000, "balance_total_equity": 52000000},
}


def main():
    ap = argparse.ArgumentParser(description="报表九项勾稽校验")
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
    out = run(data)

    if a.md:
        L = [f"# 勾稽校验 · {out['period']}", "", f"结论：**{out['conclusion']}**", "",
             "| # | 校验项 | 结果 | 说明 |", "|---|---|---|---|"]
        for x in out["results"]:
            L.append(f"| {x['no']} | {x['item']} | {x['status']} | {x['detail']} |")
        bad = [x for x in out["results"] if x["status"] == "未通过"]
        if bad:
            L += ["", "## 排查建议", ""] + [f"- {x['item']}：{x['hint']}" for x in bad]
        text = "\n".join(L)
    else:
        text = json.dumps(out, ensure_ascii=False, indent=2)

    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写入 {a.output}")
    else:
        print(text)
    return 0 if out["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())