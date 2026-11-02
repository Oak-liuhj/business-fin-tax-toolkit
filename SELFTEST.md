# business-fin-tax · 自测记录

> 建立时间：2026-11-02。本文件记录每次自测的时间、环境、结果与遗留问题，作为交付证据。

## 环境限制

当前机器 `pwsh` 全部进程启动失败（错误码 `3221225794` / `0xC0000142`），批准通道同样失败。
因此 **Python 脚本无法在本机执行**，只能用静态检查（语法通读、逻辑走查、样例数据口径核对）。

恢复方式（任一）：
1. 重启机器或修复 pwsh；
2. 在 WSL / Linux 下运行 `python3 business-fin-tax/scripts/<脚本>.py -i <样例>`；
3. 在任意装有 Python 3.8+ 的环境执行下述命令。

## 待执行命令清单

```bash
cd business-fin-tax/scripts
python3 fin_ratios.py        -i ../assets/samples/fin_data_sample.json      --md
python3 zscore_eva.py        -i ../assets/samples/zscore_eva_sample.json    --md
python3 variance_decompose.py -i ../assets/samples/variance_input_sample.json --md
python3 reconcile_check.py   -i ../assets/samples/reconcile_input_sample.json --md
python3 tax_calc.py          -i ../assets/samples/tax_input_sample.json     --md
python3 -m compileall .      # 语法检查
```

预期：
- `reconcile_check.py` 应返回 0（九项全通过）；若返回 1 说明样例数据本身不勾稽，需修样例。
- 其余脚本应输出 Markdown 表格且无异常。

## 静态检查记录（2026-11-02）

| 检查项 | 方法 | 结果 |
|---|---|---|
| frontmatter 必填字段 | 逐个文件核对 slug / version / displayName / summary / description / name | 通过 |
| 子技能 slug 唯一性 | 与根 slug 前缀区分 | 通过 |
| references 交叉引用 | 检查 `skills/*/SKILL.md` 中引用的 references 文件均存在 | 通过 |
| 样例数据与脚本入参一致 | 字段名逐个对照脚本 `--example` 输出 | 通过 |
| 脚本仅用标准库 | import 仅有 argparse/json/sys | 通过 |
| 算术一致性 | 科目余额表样例：资产 12000 万 = 负债 6800 万 + 权益 5200 万；利润表净利润 1020 万 | 通过 |

## 手算校验（无 Python 环境下的替代验证）

| 项目 | 手算 | 结果 |
|---|---|---|
| 勾稽第 2 项 | 未分配利润 1420 万 − 400 万 = 1020 万 = 净利润 | 通过（修正前样例为 600 万，与净利润不符，已改） |
| 勾稽第 3、4、6、7、9 项 | 现金 800→900 万、净增加 100 万；所得税 235+5=240 万；流动资产明细 8 项合计 4950 万；权益 5200 万 | 通过 |
| 增值税 | 销项 214 万 ×13% = 27.82 万；27.82 − 20.4 = 7.42 万 = 附加税基数 | 通过（修正前销项段与附加段口径不一致，已改） |
| 加计抵减 | 20.4 万 ×5% = 1.02 万；7.42 − 1.02 = 6.40 万 | 通过 |
| 出口免抵退 | 不得抵扣 = 120 万 ×(13%−10%) = 3.6 万；留抵 1.8 万；应退 = min(1.8, 12) = 1.8 万；免抵额 10.2 万 | 通过 |
| 企业所得税 | 调增 24+24+28+48.8+15 = 139.8 万；1260 + 139.8 − 600 = 799.8 万；×25% = 199.95 万 | 通过 |
| 预算收入 | 预算 346 万、实际 313.26 万，与弹性预算费用基数一致 | 通过 |

## 遗留风险

1. 脚本**未经真实执行**，可能存在运行期错误（如类型边界、文件路径）。首次运行后须更新本文件。
2. 税率、扣除比例、加计抵减比例均为**机制说明**，实际使用必须核对当期有效文件；包内已多处以"待核当期文件"标注。
3. CAS 与 IFRS 差异表为要点级，做正式 IFRS 报告仍需查阅准则原文。