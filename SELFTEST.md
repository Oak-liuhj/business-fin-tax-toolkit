# business-fin-tax · 自测记录

> 建立时间：2026-11-02。最近一次自测：2026-11-02。本文件记录每次自测的时间、环境、结果与遗留问题，作为交付证据。

## 环境

- 开发机：Windows。`pwsh` 在 DSH 沙箱内全部进程启动失败（`3221225794` / `0xC0000142`），本次自测改走批准通道执行。
- 解释器：Python 3.13.17（系统 PATH 中的 `python`），控制台编码 `PYTHONIOENCODING=utf-8`。
- WSL 未安装 Linux 发行版，`skillhub` CLI 无法在本机执行，发布需在 Mac/Linux/WSL 侧完成。

## 真实执行记录（2026-11-02）

| 项目 | 命令 | 结果 |
|---|---|---|
| 语法检查 | `python -m py_compile scripts/*.py` | 5/5 通过 |
| 内置示例 | `python scripts/<脚本>.py --example` | 5/5 `exit 0`，输出 JSON 结构完整 |
| 样例端到端 | `python scripts/<脚本>.py -i assets/samples/<样例>.json` | 5/5 `exit 0` |
| 勾稽校验 | `reconcile_check.py -i reconcile_input_sample.json` | `total_checks=9`、`failed=0`、`conclusion=全部通过` |
| 财务比率 | `fin_ratios.py -i fin_data_sample.json` | 毛利率 0.2667，杜邦三/五因子正常输出 |
| Z-Score | `zscore_eva.py -i zscore_eva_sample.json` | 版本判定 `private_1983`，X1 0.0875 与手算一致 |
| 差异分解 | `variance_decompose.py -i variance_input_sample.json` | 预算 3,460,000 / 实际 3,132,600，量价结构分解正常 |
| 税负测算 | `tax_calc.py -i tax_input_sample.json` | 销项 278,200、进项 204,000、应纳 74,200；应退 18,000（上限 120,000）；应纳税所得额 7,998,000 |

## 复现命令

```bash
cd scripts
python fin_ratios.py         -i ../assets/samples/fin_data_sample.json      --md
python zscore_eva.py         -i ../assets/samples/zscore_eva_sample.json    --md
python variance_decompose.py -i ../assets/samples/variance_input_sample.json --md
python reconcile_check.py    -i ../assets/samples/reconcile_input_sample.json --md   # 退出码 0 = 九项全通过
python tax_calc.py           -i ../assets/samples/tax_input_sample.json     --md
python -m compileall .
```

Linux/macOS 下把 `python` 换成 `python3`。

## 静态检查记录（2026-11-02）

| 检查项 | 方法 | 结果 |
|---|---|---|
| frontmatter 必填字段 | 逐个文件核对 slug / version / displayName / summary / description / name | 通过 |
| 子技能 slug 唯一性 | 与根 slug 前缀区分 | 通过 |
| references 交叉引用 | 检查 `skills/*/SKILL.md` 中引用的 references 文件均存在 | 通过 |
| 样例数据与脚本入参一致 | 字段名逐个对照脚本 `--example` 输出 | 通过 |
| 脚本仅用标准库 | import 仅有 argparse/json/sys | 通过 |
| 算术一致性 | 科目余额表样例：资产 12000 万 = 负债 6800 万 + 权益 5200 万；利润表净利润 1020 万 | 通过 |

## 手算校验（与脚本结果对照）

| 项目 | 手算 | 结果 |
|---|---|---|
| 勾稽第 2 项 | 未分配利润 1420 万 − 400 万 = 1020 万 = 净利润 | 通过（修正前样例为 600 万，与净利润不符，已改） |
| 勾稽第 3、4、6、7、9 项 | 现金 800→900 万、净增加 100 万；所得税 235+5=240 万；流动资产明细 8 项合计 4950 万；权益 5200 万 | 通过 |
| 增值税 | 销项 214 万 ×13% = 27.82 万；27.82 − 20.4 = 7.42 万 = 附加税基数 | 通过（修正前销项段与附加段口径不一致，已改） |
| 加计抵减 | 20.4 万 ×5% = 1.02 万；7.42 − 1.02 = 6.40 万 | 通过 |
| 出口免抵退 | 不得抵扣 = 120 万 ×(13%−10%) = 3.6 万；留抵 1.8 万；应退 = min(1.8, 12) = 1.8 万；免抵额 10.2 万 | 通过 |
| 企业所得税 | 调增 24+24+28+48.8+15 = 139.8 万；1260 + 139.8 − 600 = 799.8 万；×25% = 199.95 万 | 通过（脚本输出应纳税所得额 7,998,000 一致） |
| 预算收入 | 预算 346 万、实际 313.26 万，与弹性预算费用基数一致 | 通过 |

## 遗留风险

1. 脚本只在 Windows + Python 3.13 下用包内样例跑通；其他 Python 版本、其他输入（负值、缺字段、超长小数）尚未覆盖。
2. 税率、扣除比例、加计抵减比例均为**机制说明**，实际使用必须核对当期有效文件；包内已多处以"待核当期文件"标注。
3. CAS 与 IFRS 差异表为要点级，做正式 IFRS 报告仍需查阅准则原文。
4. `skillhub publish --dry-run` 未执行：本机无 Linux 环境（WSL 无发行版）且未安装 CLI，需在 Mac/Linux/WSL 侧补跑。