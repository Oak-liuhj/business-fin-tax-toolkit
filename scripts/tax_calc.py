#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""税费测算（纯标准库）：增值税、附加税费、出口免抵退、加计抵减、企业所得税限额与应纳税额。

所有税率与比例来自入参（默认值为常见档位），**输出会原样回显所用参数**，
便于核对是否与当期有效文件一致。本工具只做测算，不构成申报依据。

用法:
  python tax_calc.py --example
  python tax_calc.py -i input.json [--md]
"""

import argparse
import json
import sys

DEFAULT_VAT_RATES = {"goods": 0.13, "transport_build": 0.09, "service": 0.06, "export": 0.0}


def f(v, d=0.0):
    return float(v) if isinstance(v, (int, float)) else d


# ------------------------------------------------------------ 增值税


def vat(d):
    """d: output_tax 或 sales 与 rate；input_tax；transfers；simple；carryforward_credit"""
    rate = f(d.get("output_rate"), 0.13)
    if "output_tax" in d:
        out_tax = f(d.get("output_tax"))
        sales_ex = f(d.get("sales_excl_tax"))
    else:
        sales_ex = f(d.get("sales_excl_tax"))
        out_tax = sales_ex * rate

    in_tax = f(d.get("input_tax"))
    transfer = f(d.get("input_transfer_out"))       # 不得抵扣/转出
    carry = f(d.get("opening_credit"))              # 上期留抵
    simple_sales = f(d.get("simple_sales_excl_tax"))
    simple_rate = f(d.get("simple_rate"), 0.03)
    surcharge_base_extra = f(d.get("consumption_tax"))

    net_input = in_tax - transfer
    general_payable = out_tax - net_input - carry
    credit_carry = 0.0
    if general_payable < 0:
        credit_carry = -general_payable
        general_payable = 0.0

    simple_payable = simple_sales * simple_rate
    total = general_payable + simple_payable
    return {
        "output_tax": round(out_tax, 2), "input_tax": round(in_tax, 2),
        "input_transfer_out": round(transfer, 2), "net_input": round(net_input, 2),
        "opening_credit": round(carry, 2),
        "general_payable": round(general_payable, 2),
        "closing_credit": round(credit_carry, 2),
        "simple_payable": round(simple_payable, 2),
        "total_payable": round(total, 2),
        "vat_burden_rate": round(total / sales_ex, 4) if sales_ex else None,
        "surcharge_base": round(total + surcharge_base_extra, 2),
        "params_used": {"output_rate": rate, "simple_rate": simple_rate},
        "note": "留抵不得抵减简易计税应纳税额；附加税费基数为实缴增值税+消费税。",
    }


def surcharges(d):
    base = f(d.get("base"))
    rates = {"city": f(d.get("city_rate"), 0.07), "edu": f(d.get("edu_rate"), 0.03),
             "local_edu": f(d.get("local_edu_rate"), 0.02)}
    items = {k: round(base * v, 2) for k, v in rates.items()}
    total = sum(items.values())
    return {"base": round(base, 2), "items": items, "total": round(total, 2),
            "params_used": {f"{k}_rate": v for k, v in rates.items()},
            "note": "城建税税率按纳税人所在地 7%/5%/1% 分档，此处取入参或默认 7%。"}


# ------------------------------------------------------------ 出口免抵退


def export_refund(d):
    """生产企业免抵退。出口额按人民币离岸价。"""
    fob = f(d.get("fob_rmb"))
    levy = f(d.get("levy_rate"), 0.13)
    refund_rate = f(d.get("refund_rate"))            # 必填，来自当期退税率文库
    dom_out = f(d.get("domestic_output_tax"))
    in_tax = f(d.get("input_tax"))
    carry = f(d.get("opening_credit"))

    if "refund_rate" not in d:
        return {"error": "缺少 refund_rate（退税率），须核对当期出口退税率文库后传入，拒绝默认取值"}

    no_deduct = fob * (levy - refund_rate)
    current_payable = dom_out - (in_tax - no_deduct) - carry
    refund_cap = fob * refund_rate
    closing_credit = max(0.0, -current_payable)
    refund = min(closing_credit, refund_cap)
    exempt_offset = refund_cap - refund
    return {
        "fob_rmb": round(fob, 2),
        "non_deductible": round(no_deduct, 2),
        "current_tax_payable": round(max(current_payable, 0.0), 2),
        "closing_credit": round(closing_credit, 2),
        "refund_cap": round(refund_cap, 2),
        "refund": round(refund, 2),
        "exempt_offset": round(exempt_offset, 2),
        "params_used": {"levy_rate": levy, "refund_rate": refund_rate},
        "note": "退税率须核对当期文库；申报有期限，逾期视同内销征税。",
    }


# ------------------------------------------------------------ 加计抵减


def super_deduction(d, vat_payable):
    ratio = d.get("ratio")
    if ratio is None:
        return {"error": "缺少 ratio（加计抵减比例），须核对当期政策文件确认比例与有效期",
                "hint": "可传 ratio 试算，并在输出中标注为假设"}
    ratio = float(ratio)
    cur_input = f(d.get("current_deductible_input"))
    opening_bal = f(d.get("opening_balance"))
    decrease = f(d.get("current_decrease"))
    accrued = cur_input * ratio
    available = opening_bal + accrued - decrease
    used = min(max(vat_payable, 0.0), available)
    return {
        "ratio": ratio, "accrued": round(accrued, 2), "available": round(available, 2),
        "used": round(used, 2), "remaining_balance": round(available - used, 2),
        "payable_after": round(max(vat_payable - used, 0.0), 2),
        "note": "加计抵减只抵减一般计税应纳税额，不改变进项税额本身，需单独核算。",
    }


# ------------------------------------------------------------ 企业所得税


def cit(d):
    profit = f(d.get("accounting_profit"))
    revenue = f(d.get("revenue"))
    salary = f(d.get("salary_total"))

    ent = f(d.get("entertainment_expense"))
    ent_limit = min(ent * 0.6, revenue * 0.005) if revenue else ent * 0.6
    ent_add = max(0.0, ent - ent_limit)

    ad = f(d.get("advertising_expense"))
    ad_ratio = f(d.get("advertising_ratio"), 0.15)
    ad_limit = revenue * ad_ratio
    ad_add = max(0.0, ad - ad_limit)
    ad_carry = ad_add  # 结转以后年度

    wel = f(d.get("welfare_expense"))
    wel_limit = salary * 0.14
    wel_add = max(0.0, wel - wel_limit)

    edu = f(d.get("education_expense"))
    edu_limit = salary * 0.08
    edu_add = max(0.0, edu - edu_limit)
    edu_carry = edu_add

    don = f(d.get("donation"))
    don_limit = profit * 0.12
    don_add = max(0.0, don - don_limit)

    rd = f(d.get("rd_expense"))
    rd_ratio = f(d.get("rd_super_ratio"), 1.0)
    rd_deduction = rd * rd_ratio

    other_add = f(d.get("other_add"))       # 滞纳金、罚款、准备金等
    other_less = f(d.get("other_less"))     # 国债利息、股息等
    loss_cf = f(d.get("loss_carryforward"))
    rate = f(d.get("tax_rate"), 0.25)

    adds = ent_add + ad_add + wel_add + edu_add + don_add + other_add
    taxable = profit + adds - other_less - rd_deduction - loss_cf
    taxable = max(taxable, 0.0)
    tax = taxable * rate

    return {
        "accounting_profit": round(profit, 2),
        "limits": {
            "entertainment": {"actual": ent, "limit": round(ent_limit, 2), "add_back": round(ent_add, 2)},
            "advertising": {"actual": ad, "limit": round(ad_limit, 2), "add_back": round(ad_add, 2),
                            "carryforward": round(ad_carry, 2)},
            "welfare": {"actual": wel, "limit": round(wel_limit, 2), "add_back": round(wel_add, 2)},
            "education": {"actual": edu, "limit": round(edu_limit, 2), "add_back": round(edu_add, 2),
                          "carryforward": round(edu_carry, 2)},
            "donation": {"actual": don, "limit": round(don_limit, 2), "add_back": round(don_add, 2)},
        },
        "rd_super_deduction": round(rd_deduction, 2),
        "total_add_back": round(adds, 2),
        "taxable_income": round(taxable, 2),
        "tax_rate": rate,
        "tax_payable": round(tax, 2),
        "effective_rate": round(tax / profit, 4) if profit else None,
        "params_used": {"advertising_ratio": ad_ratio, "rd_super_ratio": rd_ratio, "tax_rate": rate},
        "caveats": [
            "招待费取『发生额60%』与『收入5‰』孰低，超支为永久性差异。",
            "广告费、职工教育经费超支可结转以后年度，勿一次性永久调增。",
            "研发加计比例与技术先进型等优惠须核对当期文件，且确认不在负面清单行业。",
            "本测算不含递延所得税与会计-税务时间性差异台账。",
        ],
    }


EXAMPLE = {
    "unit": "元", "period": "2026年度",
    "vat": {"sales_excl_tax": 10000000, "output_rate": 0.13,
            "input_tax": 900000, "input_transfer_out": 50000, "opening_credit": 20000,
            "simple_sales_excl_tax": 500000, "simple_rate": 0.03},
    "surcharge": {"base": 400000, "city_rate": 0.07, "edu_rate": 0.03, "local_edu_rate": 0.02},
    "export": {"fob_rmb": 5000000, "levy_rate": 0.13, "refund_rate": 0.10,
               "domestic_output_tax": 800000, "input_tax": 600000, "opening_credit": 0},
    "super_deduction": {"ratio": 0.05, "current_deductible_input": 900000,
                        "opening_balance": 10000, "current_decrease": 0},
    "cit": {"accounting_profit": 13600000, "revenue": 180000000, "salary_total": 24000000,
            "entertainment_expense": 600000, "advertising_expense": 20000000,
            "welfare_expense": 3600000, "education_expense": 2200000,
            "donation": 2000000, "rd_expense": 6000000, "rd_super_ratio": 1.0,
            "other_add": 150000, "other_less": 80000, "loss_carryforward": 0, "tax_rate": 0.25},
}


def main():
    ap = argparse.ArgumentParser(description="税费测算")
    ap.add_argument("-i", "--input")
    ap.add_argument("--example", action="store_true")
    ap.add_argument("--part", choices=["all", "vat", "surcharge", "export", "cit"], default="all")
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

    out = {}
    if a.part in ("all", "vat"):
        out["vat"] = vat(data.get("vat") or {})
    if a.part in ("all", "surcharge"):
        out["surcharge"] = surcharges(data.get("surcharge") or {})
    if a.part in ("all", "export"):
        out["export"] = export_refund(data.get("export") or {})
    if a.part in ("all", "cit"):
        vat_payable = (out.get("vat") or {}).get("general_payable") or 0.0
        sd = data.get("super_deduction")
        if sd:
            out["super_deduction"] = super_deduction(sd, vat_payable)
        out["cit"] = cit(data.get("cit") or {})

    if a.md:
        L = ["# 税费测算结果", ""]
        v = out.get("vat")
        if v:
            L += ["## 增值税", "", f"- 销项 {v['output_tax']} / 进项 {v['input_tax']} / 转出 {v['input_transfer_out']}",
                  f"- 一般计税应纳 {v['general_payable']}，期末留抵 {v['closing_credit']}",
                  f"- 简易计税应纳 {v['simple_payable']}", f"- 合计应纳 {v['total_payable']}",
                  f"- 税负率 {v['vat_burden_rate']}", f"- 附加税费基数 {v['surcharge_base']}", ""]
        s = out.get("surcharge")
        if s:
            L += ["## 附加税费", "", f"- 基数 {s['base']}，合计 {s['total']}",
                  f"- 明细 {s['items']}", ""]
        e = out.get("export")
        if e:
            if "error" in e:
                L += ["## 出口退税", "", f"- 无法计算：{e['error']}", ""]
            else:
                L += ["## 出口退税（免抵退）", "", f"- 不得免征和抵扣 {e['non_deductible']}",
                      f"- 当期应纳 {e['current_tax_payable']}，期末留抵 {e['closing_credit']}",
                      f"- 免抵退税额 {e['refund_cap']}，应退 {e['refund']}，免抵 {e['exempt_offset']}", ""]
        c = out.get("cit")
        if c:
            L += ["## 企业所得税", "", f"- 会计利润 {c['accounting_profit']}",
                  f"- 调增合计 {c['total_add_back']}", f"- 研发加计 {c['rd_super_deduction']}",
                  f"- 应纳税所得额 {c['taxable_income']}", f"- 税率 {c['tax_rate']}，应纳税额 {c['tax_payable']}",
                  "", "注意："]
            L += [f"- {x}" for x in c["caveats"]]
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