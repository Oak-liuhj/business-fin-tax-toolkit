# 数据与计算接口

## 统一约定

- 金额使用 Decimal、40位运算精度、人民币分按 ROUND_HALF_UP。JSON 中 Decimal 序列化为字符串，避免跨语言丢分；不得将“数字字符串”等同无效值或零。
- 支持 `1,234.50`、`(1,234.50)`、`13%`。布尔值、NaN/Infinity、错误千分位及无法识别字符会报错；同名 JSON 字段重复亦报错。
- 缺失与零分开。借贷表/流水的单边金额空白按零解释，并逐格记录 normalizations；其他缺失金额不自动补零。
- 独立税费模块中未列出的费用/可选调整按未发生处理，常见比例为试算默认，参数原样回显。review 模式必须由政策登记覆盖这些参数；不能将省略的企业事项当成经过调查的零。
- 财务指标输出是浮点比率；货币金额使用十进制。周转天数使用 period_days；月/季必须给天数，平均余额缺期初不改用期末。annualize=true 才额外输出年化指标。

## 数据导入

```powershell
python -B scripts/data_ingest.py -i 文件.csv --profile trial_balance --unit 元 -o normalized.json
python -B scripts/data_ingest.py -i 流水.xlsx --profile bank --unit 元 --sheet 银行 --period-start 2026-01-01 --period-end 2026-01-31
```

CSV/TSV 支持 UTF-8/BOM，解码失败才尝试 GB18030；XLSX 读取需安装 requirements-optional.txt。多页 XLSX 必须指定 sheet；公式输入不使用可能失效的缓存，要求导出冻结值并保留原底稿。不支持旧 XLS、OCR及自动还原未提供的数据。

前30行定位表头，支持已合并的上下两层借贷表头及 header-row 手动定位。profile 可为 trial_balance/bank/invoices；标准字段与中文别名见 scripts/data_ingest.py 的 PROFILES。

万元按10000转换为元；单位/币种混用、越期交易、重复科目/发票标识或完全重复流水均输出异常，保留来源，不自动去重。跨期汇总必须先明确范围，不能忽略越期行后继续发布。

## 勾稽输入扩展

- `ledger.depreciation_amortization`：总账实际本期计提额，不能仅凭累计余额变动推断。
- `prior_closing.total_assets/total_liabilities/total_equity`：上期已报值，分别与本期期初比较。
- `bridges.profit_distribution/reserve_transfer`：正数表示减少未分配利润；prior_adjustment 正数增加利润。
- 现金口径：现金等价物余额 = 货币资金 − restricted_cash + cash_equivalents_extra。
- `equity_change.closing_total` 与 balance.total_equity 比较，不能靠重复输入一个孤立的 balance_total_equity 冒充独立取数。

通过、未通过、缺数据、待人工复核分别统计；只有九项实际比较全部通过才 ready_for_analysis=true。exit 0=全部通过；exit 1=实际比较失败；exit 2=数据不足/待复核/非法输入。

## 税费与跨年台账

tax_calc.py 的 --part all 仅计算实际提供的模块，未提供模块不按零生成。--part vat 同时处理已提供的加计抵减；附加税基随抵减后一般计税+简易计税+消费税联动。独立 --part surcharge 需显式 base。

附加的实际缴纳与应纳差异、已核定免抵额、退税扣减等通过 `surcharge.adjustments` 的具名正负金额列示；不能将独立出口试算自动并入同一所属期税基。默认计算是情景测算，不替代实际缴纳与地区减免规则。

公益捐赠限额不低于零；业务招待费收入基数为零时限额为零；亏损使用不超过弥补前正所得。可传审定后的 loss_carryforward/prior_carryforwards，或 `cit.carryforward_ledger` + `cit.tax_year`，两者不可并用。

台账每条需 id、kind、origin_year、expiry_year、amount、used_by_year、qualified、policy_id、evidence。到期年必须由已审核政策给出。kind 支持 loss、advertising、education、donation、foreign_credit、temporary_difference；前四项接入企税计算，境外抵免和递延税暂只登记展示。资格未确认的余额不扣除，累计使用不得超过原额。使用后人工登记本年消耗并复核，本脚本不原地改台账。

## 预算分解

纯量差=(实际总销量−预算总销量)×预算加权均价；结构差=Σ(实际销量−预算销量)×(预算单价−预算均价)；价差=Σ(实际单价−预算单价)×实际销量。三项相加等于总差异；销量单位不具可比性时应分组分析。

成本输入 standard_qty_for_actual_output 后，用量/效率差异以实际产出应耗数量为基准，另列产出活动量差异；不提供时仅为静态预算数量差异。不要把增加产量产生的耗用一概解释为低效率。
