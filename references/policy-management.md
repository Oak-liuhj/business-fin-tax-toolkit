# 政策登记与核验

包内 policy-registry.json 全部是未核验示例，不包含已确认的现行政策。

## 使用模式

```powershell
python -B scripts/tax_calc.py -i assets/samples/tax_input_sample.json --mode simulation
python -B scripts/tax_calc.py -i 企业税费.json --mode review --registry 企业政策登记.json
```

simulation 输出试算及全部政策缺口；review 在政策/参数/资格未通过时仍显示测算底稿和缺口，但 exit 2，不能由宿主作为已核验结果发布。不能只检查是否生成文件。

## 核验步骤

1. 从财政部、国家税务总局或对应政府官方站点查原文、修订和废止情况；保留适用年度及过渡条款。
2. 将原文归档，计算 SHA256，填写 document_title、document_number、article、official_url、effective_from/to、reviewed_at、reviewer、evidence_sha256。每条登记可覆盖同一业务所需的一组文件，但需逐项列清来源与条款，复杂事项宜拆成独立登记版本。
3. applicability 填 region/industry/taxpayer_type 的允许值列表；通用适用用 ["*"]。required_qualifications 填资格标识；企业 context.qualifications 对应条目必须有 qualified=true 与 evidence。
4. parameters 按 vat/surcharge/export/super_deduction/cit 填代码实际使用的参数；policy_bindings 为每个实际使用模块绑定唯一政策 id。代码默认值同样必须被已核验参数覆盖。
5. 人工确认后 verification_status=verified；变更政策、金额口径或资格材料时新建版本并重新审核，不直接覆盖旧交付中的登记快照。

程序校验完整字段、官方 HTTPS 域名、摘要格式、日期覆盖、地区/行业/身份、资格证据及参数一致性。它不能证明填写的法律结论、归档文件内容及复核人身份真实，也不会联网核验政策；verified 仅表示本地人工登记满足规则。源文真实性与人员授权由企业复核和宿主负责。

## 应优先重新核验的旧知识

references/vat-rules.md、cit-limits.md 中的加计抵减对象、出口逾期后果、资产损失申报形式、研发与小微优惠等存在年度与条件差异。旧叙述仅供定位问题，不能代替登记中的有效文件。未取得原文时保留 unverified，并输出需要核验的条款，不编造文号或宣称已经更新到现行政策。
