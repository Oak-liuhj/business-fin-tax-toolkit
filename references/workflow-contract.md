# 月结工作流与交付边界

## 执行入口

在包根目录运行：

```powershell
python -B scripts/close_workflow.py -i assets/samples/month_close/workflow.json -o outputs/my-month-close
```

输出目录必须是新目录，已有结果不会被覆盖。样例全部虚构；真实使用时复制整个样例目录，修改企业标识、所属期、文件路径及实际复核证据。

## 共享上下文

`workflow.json.context` 与 `support.json.context` 的 company_id、ledger_id、period_start、period_end、currency、unit 必须一致。报告名称另用 company/period。输入导入单位使用 input_unit，标准化底稿统一为元。

当前自动编表范围为 CAS、单体、CNY、损益未结转、末级科目。IFRS、合并、已结转账套、外币及跨账户内部划转需独立底稿，不强行套用此流程。

## 输入与实际计算

1. `trial_balance`：期初借贷、本期借贷和期末借贷完整；按行滚动及三组总计试算。父子科目并存、未知映射、异常余额方向会阻止编表。
2. `mapping`：按科目编码最长前缀映射，不能仅凭名称相似归类。包内为通用示例；企业自定义编码应复制修改。尤其须复核 6603/6604 等企业编码与名称，不能直接沿用旧样例标签。
3. `bank`：每笔需现金流分类（销售收款、供应商付款、职工付款、税费付款、经营收款/付款、投资收款/付款、筹资收款/付款）及余额；按逐账户期初余额重算余额连续性和现金流。
4. `support`：独立的源报表控制总额statement_controls（资产/负债/收入/净利润）、上期已报三项总计、总账折旧摊销、当期/递延所得税费用、权益变动表、补充资料净利润/折旧摊销及资金/利润桥接。科目余额表不足以还原全部现金流，不能用差额补齐。
5. 前置复核：mapping_review 需 reviewer/evidence/mapping_sha256；cashflow_review 需 reviewer/evidence/bank_sha256。程序核对证据字段与当前文件摘要，不验证人员真实身份；宿主负责身份与授权。

## 状态及退出码

- `blocked` / exit 2：输入、勾稽或前置复核不完整；输出报告、异常和待办，不生成分析。
- `ready_for_review` / exit 0：导入、编表、九项比较及前置复核均通过，生成待最终复核的分析。
- 最终复核始终保留为 pending。此工具不自动声称已关账、不改变 ERP 权限、不执行锁账或申报。

输出包括原始输入快照、normalized.json、bank_normalized.json、statements.json、checks.json/md、analysis.json/md、provenance.json、manifest.json、report.md。出现错误时不存在的后续阶段文件代表尚未完成，而非已通过。

每个运行编号由输入摘要、版本及 Python 源码摘要确定；同一输入和代码可重复计算。manifest 保存各产物 SHA256，provenance 保留来源行、原始值、科目映射及计算口径。辅助底稿用原文件 SHA256 加 JSON 指针追溯。

## 可选 Excel 交付

```powershell
# 使用具备 @oai/artifact-tool 的 Node 环境；Codex 可通过运行时依赖发现工具取得路径。
node scripts/export_workbook.mjs outputs/my-month-close outputs/my-month-close.xlsx
```

若模块不在默认搜索路径，FIN_TAX_NODE_MODULES 指向其 node_modules 目录。该依赖仅用于可选导出，Python 核心不依赖 Node。

工作簿含月结结果、报表计算、科目余额表、银行流水、参数与复核五页。核心金额和指标以公式连接，来源行和复核输入可见。导出器会核对运行文件摘要，执行现金流输入变动重算、复核缺证检查及九项 Excel 检查，并渲染各页。

Excel 原生浮点运算不替代 Decimal 底稿。导出金额超过 1 万亿元时主动拒绝，需另选单位；JSON 保留精确十进制。Excel 内修改后应重跑 Python 校验并保留新版本。Excel 检查与 Python 九项检查的覆盖对象有差异，不能据 Excel 修改后的“通过”跳过流水连续性、映射和来源审查。

## 能力成熟度

| 场景 | 当前自动化与边界 |
|---|---|
| 财务分析 | 比率、杜邦、Z-Score/EVA计算；完整结论由工作流勾稽门槛控制 |
| 凭证编制 | 指引与 CSV 模板；不具备银行流水自动判断经济实质、ERP过账能力 |
| 预算分析 | 三因素、弹性预算、成本价格/效率/活动量分解 |
| 增值税管理 | Decimal辅助测算、抵减及附加联动；票账税匹配仍需专项整理 |
| 汇算清缴 | 限额、有效结转余额、损益调节计算；不自动认定优惠资格 |
| 内部审计 | 程序与发现指引；抽样方案、证据与缺陷定级需项目判断 |
| 报表编制 | 所述受限范围的余额表、利润表与银行分类现金流底稿；非完整法定报送包 |
| 月结 | 可执行的导入—校验—报表—分析—待复核链路；ERP锁账由授权宿主执行 |
