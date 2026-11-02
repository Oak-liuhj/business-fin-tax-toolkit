# 企业财税专家包 · business-fin-tax

面向企业财务与税务日常工作的技能包，覆盖八大场景，适配会计、财务经理、税务经理、审计经理四类角色。

## 包含什么

| 命令别名 | 子技能 | 能力 |
|---|---|---|
| `/财务分析` | `skills/fin-analysis` | 杜邦、偿债、运营、盈利、现金流、Z-Score、EVA 全面诊断 |
| `/做凭证` | `skills/bookkeeping-voucher` | 银行流水/费用单据 → CAS 记账凭证（含外币、研发、年末结转） |
| `/预算分析` | `skills/budget-variance` | 量价结构差异分解、弹性预算、标准成本差异 |
| `/增值税管理` | `skills/vat-management` | 税负测算、进销项匹配、出口退税、加计抵减、申报底稿 |
| `/汇算清缴` | `skills/cit-settlement` | 纳税调整、扣除限额校验、股权激励/资产损失/境外所得 |
| `/内部审计` | `skills/internal-audit` | 审计程序、工作底稿、数据分析审计、SOX/IFRS 适配 |
| `/财务报表编制` | `skills/statement-prep` | CAS 三表编制、期间对比、勾稽验证、合并、附注框架 |
| `/月结检查清单` | `skills/month-end-close` | 10 步关账、进度追踪、制造业成本核算、年度关账 |
| （内部参考） | `references/entry-templates.md` | 标准分录模板库与编制规范 |

知识底座：`references/cas-basics.md`、`statement-mapping.md`、`vat-rules.md`、`cit-limits.md`、`audit-programs-sox.md`。

工具：`scripts/` 下 5 个 Python 脚本（仅标准库，无需安装依赖）：

| 脚本 | 作用 |
|---|---|
| `fin_ratios.py` | 盈利/偿债/运营/现金流比率 + 杜邦三因子与五因子 |
| `zscore_eva.py` | Altman Z-Score（三版本可选）+ EVA（CAPM 或直接给 WACC） |
| `variance_decompose.py` | 收入量价结构三因素、成本价量差异、费用弹性预算 |
| `reconcile_check.py` | 报表九项勾稽校验，未通过返回非零退出码 |
| `tax_calc.py` | 增值税、附加税费、出口免抵退、加计抵减、企业所得税限额与应纳税额 |

样例数据在 `assets/samples/`，输出模板在 `assets/templates/`，自测记录见 `SELFTEST.md`。

## 目录结构

```
business-fin-tax-toolkit/
├── SKILL.md                     # 主入口：角色路由、命令别名表、五步流程、三条红线
├── README.md
├── SELFTEST.md                  # 自测记录与待执行命令
├── LICENSE                      # Apache-2.0
├── references/                  # 知识底座（6 份）
│   ├── cas-basics.md            # CAS 准则口径
│   ├── entry-templates.md       # 标准分录模板库（凭证参考）
│   ├── statement-mapping.md     # 科目 → 报表行映射
│   ├── vat-rules.md             # 增值税规则与风险指标
│   ├── cit-limits.md            # 企税扣除限额与优惠
│   └── audit-programs-sox.md    # 六大循环审计程序 + SOX 404
├── skills/                      # 子技能（8 个，统一四段式）
│   ├── fin-analysis/SKILL.md
│   ├── bookkeeping-voucher/SKILL.md
│   ├── budget-variance/SKILL.md
│   ├── vat-management/SKILL.md
│   ├── cit-settlement/SKILL.md
│   ├── internal-audit/SKILL.md
│   ├── statement-prep/SKILL.md
│   └── month-end-close/SKILL.md
├── scripts/                     # 5 个脚本，仅标准库
│   ├── fin_ratios.py
│   ├── zscore_eva.py
│   ├── variance_decompose.py
│   ├── reconcile_check.py
│   └── tax_calc.py
└── assets/
    ├── samples/                 # 9 份虚构样例
    └── templates/               # 6 份输出模板
```

## 安装

把本目录放到 Agent 的 skills 目录：

```bash
cp -r business-fin-tax ~/.dsh/skills/
```

各 Agent 的 skills 目录不同，按实际环境放置；DSH 下重启会话或新开会话即可识别。

## 使用

直接用自然语言说，或打命令别名：

```
/财务分析 我上传了资产负债表和利润表
/做凭证 这是本月的银行流水
/预算分析 预算和实际都在这个表里
/增值税管理 这是进销项明细
/汇算清缴 这是科目余额表
/内部审计 范围是采购到付款流程
/财务报表编制 科目余额表在附件
/月结检查清单 制造业，本月要出合并报表
```

**说明**：上述 `/xxx` 是技能触发别名，不是 DSH 原生斜杠命令。写成自然语言效果相同。

## 设计原则

1. **假设显式化**——WACC、退税率、加计抵减比例等参数必须写明来源，无依据不出数。
2. **不做合规背书**——税务与会计政策只给测算、风险等级和复核建议。
3. **勾稽优先**——报表不平先修平，再谈分析。

## 样例数据

`assets/samples/` 全部为虚构数据，仅用于跑通流程：

| 文件 | 内容 | 配套脚本 |
|---|---|---|
| `科目余额表_sample.csv` | 42 个科目，资产 12000 万 = 负债 6800 万 + 权益 5200 万 | 报表编制 |
| `银行流水_sample.csv` | 10 笔收支 | 做凭证 |
| `进销项_sample.csv` | 销项 5 张（含出口 0% 与作废）、进项 6 张（含不得抵扣） | 增值税管理 |
| `预算vs实际_sample.csv` | 3 个产品 + 3 项成本 + 费用 | 预算分析 |
| `fin_data_sample.json` | 两期完整三表关键科目 | `fin_ratios.py` |
| `zscore_eva_sample.json` | Z-Score 与 EVA 入参（含 CAPM 六参数） | `zscore_eva.py` |
| `variance_input_sample.json` | 量价结构分解入参 | `variance_decompose.py` |
| `reconcile_input_sample.json` | 勾稽校验入参 | `reconcile_check.py` |
| `tax_input_sample.json` | 增值税/附加/免抵退/加计/企税入参 | `tax_calc.py` |

输出模板在 `assets/templates/`：财务分析报告、预算差异分析、审计发现报告、月结检查表、凭证导入表、汇算清缴调整表。

## 自测

见 `SELFTEST.md`。**注意**：当前开发机 `pwsh` 崩溃（`0xC0000142`），脚本尚未真实执行，仅有静态检查记录，首次运行后须更新该文件。

## 版本

0.1.0 · 首版：八大子技能 + 6 份知识底座 + 5 个脚本 + 9 份样例 + 6 份模板。税率与限额为机制说明，实务须核对当期文件。

## 许可

Apache License 2.0，见 [LICENSE](LICENSE)。