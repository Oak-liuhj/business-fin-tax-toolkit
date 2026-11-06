# 企业财税专家套件 · business-fin-tax

面向会计、财务经理、税务经理与审计经理的技能包。提供八类任务手册、知识参考、计算脚本和可执行月结底稿流程。

版本 **0.2.0**：修复计算/校验缺陷，增加政策登记、来源追溯、跨年台账与“月结—报表—分析”工作流。Python 核心仅使用标准库，支持 Python 3.11+。

## 八类场景

| 触发别名 | 子技能 | 当前能力 |
|---|---|---|
| `/财务分析` | fin-analysis | 财务比率、杜邦、Z-Score、EVA；期间口径与缺项显式输出 |
| `/做凭证` | bookkeeping-voucher | 分录指引及待复核CSV模板，支持来源与附件整理 |
| `/预算分析` | budget-variance | 收入纯量差/价差/结构差、弹性预算、成本活动量/效率差异 |
| `/增值税管理` | vat-management | 一般/简易计税、加计抵减、附加联动、简化出口退税试算 |
| `/汇算清缴` | cit-settlement | 扣除限额、亏损弥补、结转余额与调整底稿 |
| `/内部审计` | internal-audit | 审计程序、发现结构、内控与数据异常检查指引 |
| `/财务报表编制` | statement-prep | 受限范围内的CAS单体报表草稿与九项实际比较 |
| `/月结检查清单` | month-end-close | 数据导入、试算、报表、勾稽、分析与待复核状态 |

上述别名为自然语言触发词，不是DSH原生斜杠命令。能力成熟度及适用范围见 [工作流说明](references/workflow-contract.md)。

## 快速运行

在本项目目录执行，输出目录使用新名称：

```powershell
python -B scripts/close_workflow.py -i assets/samples/month_close/workflow.json -o outputs/my-month-close
```

样例全部虚构。自动验证预期：资产213,000元、负债42,000元、权益171,000元、净利润21,000元、经营现金净额30,000元，九项比较通过，状态 `ready_for_review`。最终复核仍待完成，不代表ERP已锁账。

真实使用时复制 `assets/samples/month_close/`，替换余额表、带现金流分类的银行流水、上期数据与辅助底稿，设置企业和账套标识，并记录当前科目映射与流水文件的复核证据/SHA256。详细字段见 [数据接口](references/data-contract.md)。

## 计算及校验

```powershell
python -B scripts/fin_ratios.py -i assets/samples/fin_data_sample.json --md
python -B scripts/zscore_eva.py -i assets/samples/zscore_eva_sample.json --md
python -B scripts/variance_decompose.py -i assets/samples/variance_input_sample.json --md
python -B scripts/reconcile_check.py -i assets/samples/reconcile_input_sample.json --md
python -B scripts/tax_calc.py -i assets/samples/tax_input_sample.json --mode simulation --md
python -B scripts/carryforward_ledger.py -i assets/samples/carryforward_ledger_sample.json --year 2026
```

税费示例中的增值税74,200元经加计抵减10,200元后为64,000元，联动附加税基64,000元、示例附加7,680元；企税应纳税所得额7,998,000元。出口部分是独立情景，不自动并入同一税基。

### 结果约定

- 金额使用 Decimal，分按 ROUND_HALF_UP；JSON中的十进制金额为字符串，保留精度。比率为数字或十进制字符串，调用方应按字段含义解析。
- 缺失、零、失败与待人工复核不同；空数据不会判定为通过。勾稽 exit 0=九项全部通过，exit 1=有实际失败，exit 2=缺数据/待复核/非法输入。
- 月/季分析显式传 period_days；平均余额缺期初时不以期末代替。年化结果单列，不将月度EBITDA直接用于年度债务倍数。
- 五个原计算脚本仍支持 `--example`、`-i`、`--md`、`-o`。`--example` 输出输入样例，不等于执行计算。

## 政策登记

[policy-registry.json](references/policy-registry.json) 是**未核验示例**。税费脚本默认 simulation，输出试算与政策缺口；review 模式要求本地登记中的人工核验、官方来源、条款、有效期、适用条件、资格证据和实际参数匹配：

```powershell
python -B scripts/tax_calc.py -i 企业税费.json --mode review --registry 企业政策登记.json
```

未核验时 exit 2，仍保留底稿与问题。程序不联网确认法规、不认证复核人身份，也不进行申报。登记流程见 [政策管理](references/policy-management.md)。

## 导入和追溯

```powershell
python -B scripts/data_ingest.py -i assets/samples/科目余额表_sample.csv --profile trial_balance --unit 元 -o normalized.json
```

支持CSV/TSV、表头定位、两层借贷表头、千分位/括号负数、万元换算、重复/越期/币种检查；每格保留文件SHA256、工作表、行号、原始值和标准化说明。XLSX读取为可选功能：`python -m pip install -r requirements-optional.txt`，多页文件必须指定 `--sheet`。

**旧的 `科目余额表_sample.csv` 本身存在期初/发生/期末不一致和试算问题。** 保留它作为异常检出用例，不再宣称可直接生成平衡三表；完整工作流使用 `month_close/` 内新建的独立平衡样例。各独立计算器样例也不默认属于同一家企业同一套账。

## Excel 底稿

具备 `@oai/artifact-tool` 的 Node 环境可执行：

```powershell
node scripts/export_workbook.mjs outputs/my-month-close outputs/my-month-close.xlsx
```

可用 FIN_TAX_NODE_MODULES 指定模块目录。工作簿包含五页、可重算公式、来源行、独立检查及最终复核输入。导出器会验证输入变动确实影响现金流、缺少证据时复核状态不完成，并渲染各页。Python流程不依赖Excel导出器。

## 安装到 Agent

将整个目录复制到宿主支持的skills目录，保留相对路径。DSH可使用 `~/.dsh/skills/business-fin-tax/`；各宿主安装位置和技能发现方式不同。

本包保留既有DSH frontmatter扩展字段（slug/displayName/version/summary）。Codex标准技能校验器不接受这些顶层字段；若发布至仅接受Codex字段的宿主，应将扩展字段移至metadata或制作适配副本，不修改共享包的宿主约定。

## 验证

```powershell
python -B -m unittest discover -s tests -v
```

测试覆盖已发现的边界缺陷、原脚本JSON/Markdown、政策拒绝放行、导入和模板、月结正向流程、错误企业/缺复核阻断、产物摘要及重复计算。当前实测环境和结果见 [SELFTEST.md](SELFTEST.md)。为保持既有SkillHub导入兼容，仓库不包含隐藏配置文件；可在目标环境运行上述命令，Windows/Linux及Python版本的实际覆盖以SELFTEST记录为准。

知识页中的税率、门槛及申报形式仍须按所属期完成原文核验。IFRS、合并、优惠资格认定、正式报送包和ERP写入仍需专项处理，不将知识指引表述为已自动实现。

Apache-2.0，见 [LICENSE.md](LICENSE.md)。
