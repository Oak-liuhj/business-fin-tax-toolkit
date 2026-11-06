// Optional XLSX adapter. Core Python workflow remains dependency-free.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
if (args.length !== 2) throw new Error('用法：node scripts/export_workbook.mjs <运行目录> <新输出.xlsx>');
const [runDir, outputFile] = args.map(v => path.resolve(v));
await fs.access(outputFile).then(() => { throw new Error('输出已存在，请指定新文件'); }, e => { if (e.code !== 'ENOENT') throw e; });
const loader = createRequire(process.env.FIN_TAX_NODE_MODULES ? path.join(process.env.FIN_TAX_NODE_MODULES, '..', 'fin-tax-loader.cjs') : import.meta.url);
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(loader.resolve('@oai/artifact-tool')).href);
const read = async name => JSON.parse(await fs.readFile(path.join(runDir, name), 'utf8'));
const manifest = await read('manifest.json');
if (manifest.status !== 'ready_for_review') throw new Error('运行尚未完成自动校验与前置复核，不能导出分析底稿');
for (const [name, digest] of Object.entries(manifest.artifacts)) {
  if (crypto.createHash('sha256').update(await fs.readFile(path.join(runDir, name))).digest('hex') !== digest)
    throw new Error(`运行文件已变化：${name}；请重跑流程`);
}
const normalized = await read('normalized.json'), bankData = await read('bank_normalized.json');
const statements = await read('statements.json'), support = await read('inputs/support.json');
const wb = Workbook.create();
const sheets = Object.fromEntries(['月结结果', '报表计算', '科目余额表', '银行流水', '参数与复核'].map(name => [name, wb.worksheets.add(name)]));
const moneyFmt = '#,##0.00;(#,##0.00);"-"';
const num = value => {
  if (value === null || value === undefined || value === '') throw new Error('Excel 输入缺失');
  const n = Number(value);
  if (!Number.isFinite(n) || Math.abs(n) > 1e12) throw new Error('Excel 精度边界：金额超出1万亿元，保留精确JSON并另行选定缩放单位');
  return n;
};
const literal = value => typeof value === 'string' && /^[=+@]/.test(value) ? "'" + value : value;
function init(sheet, title, lastRow, lastCol) {
  sheet.showGridLines = false;
  const area = sheet.getRange(`A1:${lastCol}${lastRow}`);
  area.format.font = { name: 'Arial', size: 10, color: '#172B4D' };
  area.format.rowHeight = 24;
  area.format.verticalAlignment = 'center';
  area.format.columnWidth = 18;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange(`A2:${lastCol}2`).format.rowHeight = 30;
  sheet.getRange('A2').format.font = {name: 'Arial', size: 14, bold: true};
}
function header(sheet, range) {
  sheet.getRange(range).format = { fill: '#243D60', font: {name: 'Arial', size: 10, bold: true, color: '#FFFFFF'},
    horizontalAlignment: 'center', rowHeight: 28 };
}
function formula(sheet, address, text) {
  sheet.getRange(address).formulas = [[text]];
  sheet.getRange(address).format.font.color = text.includes('!') ? '#167044' : '#172B4D';
}
const tb = sheets['科目余额表'];
init(tb, '末级科目余额表（元）', normalized.records.length+5, 'N');
tb.getRange('A4:N4').values = [['科目编码','科目名称','期初借方','期初贷方','本期借方','本期贷方','期末借方','期末贷方','映射项目','科目性质','期初净额','本期净发生','期末净额','来源行']];
header(tb, 'A4:N4');
const codeRules = new Map();
for (const [key, references] of Object.entries(statements.lineage))
  for (const ref of references) codeRules.set(ref.account_code, [key, statements.buckets[key].nature]);
normalized.records.forEach((record, i) => {
  const v = record.values, row = i+5, [key,nature] = codeRules.get(v.account_code);
  const inputs = ['opening_debit','opening_credit','debit','credit','closing_debit','closing_credit'].map(k => num(v[k]));
  tb.getRange(`A${row}:N${row}`).values = [[literal(v.account_code),literal(v.account_name),...inputs,key,nature,null,null,null,
    `${path.basename(manifest.sources.trial_balance.file)} / ${record.provenance.account_code.cell}`]];
  formula(tb,`K${row}`,`=C${row}-D${row}`); formula(tb,`L${row}`,`=E${row}-F${row}`); formula(tb,`M${row}`,`=G${row}-H${row}`);
});
const tbEnd = normalized.records.length+4;
tb.getRange(`C5:H${tbEnd}`).format.font.color = '#2456A6';
tb.getRange(`C5:M${tbEnd}`).setNumberFormat(moneyFmt);
tb.getRange(`A4:A${tbEnd}`).format.columnWidth = 14;
tb.getRange(`B4:B${tbEnd}`).format.columnWidth = 24;
tb.getRange(`I4:J${tbEnd}`).format.columnWidth = 28;
tb.getRange(`N4:N${tbEnd}`).format.columnWidth = 38;
tb.freezePanes.freezeRows(4);

const bank = sheets['银行流水'];
init(bank, '已复核分类的银行流水（元）', bankData.records.length+5, 'I');
bank.getRange('A4:I4').values = [['日期','银行账号','现金流分类','收入','支出','余额','净收支','活动分类','来源行']];
header(bank, 'A4:I4');
bankData.records.forEach((record, i) => {
  const v=record.values, row=i+5;
  const category = /^(销售|供应商|职工|税费|经营)/.test(v.cashflow_category) ? '经营' : v.cashflow_category.slice(0,2);
  bank.getRange(`A${row}:I${row}`).values = [[new Date(v.date+'T00:00:00Z'),literal(v.bank_account),literal(v.cashflow_category),num(v.incoming),num(v.outgoing),num(v.balance),null,category,
    `${path.basename(manifest.sources.bank.file)} / ${record.provenance.date.cell}`]];
  formula(bank,`G${row}`,`=D${row}-E${row}`);
});
const bankEnd=bankData.records.length+4;
bank.getRange(`A5:A${bankEnd}`).setNumberFormat('yyyy-mm-dd');
bank.getRange(`D5:G${bankEnd}`).setNumberFormat(moneyFmt);
bank.getRange(`D5:F${bankEnd}`).format.font.color='#2456A6';
bank.getRange(`B4:C${bankEnd}`).format.columnWidth=24;
bank.getRange(`I4:I${bankEnd}`).format.columnWidth=38;
bank.freezePanes.freezeRows(4);

const params=sheets['参数与复核'];
init(params,'输入参数与独立复核（元）',33,'H');
params.getRange('A4:C4').values=[['参数','数值或复核人','底稿位置']];header(params,'A4:C4');
const days = (Date.parse(manifest.context.period_end)-Date.parse(manifest.context.period_start))/86400000+1;
const entries=[['期间天数',days,'workflow.json / context'],
 ['上期资产',num(support.prior_closing.total_assets),'support.json / prior_closing/total_assets'],
 ['上期负债',num(support.prior_closing.total_liabilities),'support.json / prior_closing/total_liabilities'],
 ['上期权益',num(support.prior_closing.total_equity),'support.json / prior_closing/total_equity'],
 ['总账折旧摊销',num(support.ledger.depreciation_amortization),'support.json / ledger'],
 ['当期所得税',num(support.income.current_tax),'support.json / income/current_tax'],
 ['递延所得税费用',num(support.income.deferred_tax),'support.json / income/deferred_tax'],
 ['权益变动表期末',num(support.equity_change.closing_total),'support.json / equity_change'],
 ['银行期初余额',Object.values(support.bank_opening_balances).reduce((a,v)=>a+num(v),0),'support.json / bank_opening_balances'],
 ['现金流补充资料净利润',num(support.cashflow.net_profit),'support.json / cashflow/net_profit'],
 ['现金流补充资料折旧摊销',num(support.cashflow.depreciation_amortization),'support.json / cashflow'],
 ['最终复核人',null,'填写复核记录；运行状态仍需重新核验'],
 ['最终复核证据',null,'填写证据编号；不触发ERP锁账'],
 ['映射复核人',support.mapping_review.reviewer,'support.json / mapping_review'],
 ['现金流分类复核人',support.cashflow_review.reviewer,'support.json / cashflow_review'],
 ['比较容差',0.01,'本底稿计算容差'],
 ['利润分配',num(support.bridges?.profit_distribution??0),'support.json / bridges/profit_distribution'],
 ['盈余公积提取',num(support.bridges?.reserve_transfer??0),'support.json / bridges/reserve_transfer'],
 ['前期调整',num(support.bridges?.prior_adjustment??0),'support.json / bridges/prior_adjustment'],
 ['受限货币资金',num(support.bridges?.restricted_cash??0),'support.json / bridges/restricted_cash'],
 ['其他现金等价物',num(support.bridges?.cash_equivalents_extra??0),'support.json / bridges/cash_equivalents_extra'],
 ['源资产控制总额',num(support.statement_controls.total_assets),'support.json / statement_controls/total_assets'],
 ['源负债控制总额',num(support.statement_controls.total_liabilities),'support.json / statement_controls/total_liabilities'],
 ['源收入控制总额',num(support.statement_controls.revenue),'support.json / statement_controls/revenue'],
 ['源净利润控制总额',num(support.statement_controls.net_profit),'support.json / statement_controls/net_profit']];
params.getRange('A5:C29').values=entries;
params.getRange('A4:A29').format.columnWidth=30;params.getRange('B4:B29').format.columnWidth=26;
params.getRange('C4:C29').format.columnWidth=60;params.getRange('D1:D33').format.columnWidth=3;
params.getRange('B5:B20').format.font.color='#2456A6';
params.getRange('B6:B15').setNumberFormat(moneyFmt);
params.getRange('B16:B17').format.fill='#FFF2CC';
params.getRange('F4:H4').values=[['独立检查','差额','状态']];header(params,'F4:H4');
params.getRange('F4:F24').format.columnWidth=30;params.getRange('G4:H24').format.columnWidth=20;

const build=sheets['报表计算'];
init(build,`${manifest.context.period} 报表与指标计算（元）`,43,'D');
build.getRange('A4:C4').values=[['项目','本期期末或本期','期初']];header(build,'A4:C4');
const labels={5:'货币资金',6:'应收账款',7:'存货',8:'固定资产净额',9:'资产合计',10:'负债合计',11:'权益（未加本期损益）',12:'未结转净利润',13:'权益合计',14:'未分配利润',16:'营业收入',17:'营业成本',18:'其他费用（不含所得税）',19:'其他收入',20:'利润总额',21:'净利润',22:'所得税费用',24:'经营活动现金净额',25:'投资活动现金净额',26:'筹资活动现金净额',27:'现金净增加额',28:'期初现金',29:'期末现金',31:'应收周转天数',32:'毛利率',33:'本期ROE'};
for (const [r,label] of Object.entries(labels)) build.getRange(`A${r}`).values=[[label]];
const sumField=(field,col)=>`SUMIF('科目余额表'!$I$5:$I$${tbEnd},"${field}",'科目余额表'!$${col}$5:$${col}$${tbEnd})`;
const sumNature=(nature,col)=>`SUMIF('科目余额表'!$J$5:$J$${tbEnd},"${nature}",'科目余额表'!$${col}$5:$${col}$${tbEnd})`;
for(const [col,raw] of [['B','M'],['C','K']]){
 for(const [row,key] of [[5,'cash'],[6,'accounts_receivable'],[7,'inventory']]) formula(build,`${col}${row}`,`=${sumField(key,raw)}`);
 formula(build,`${col}8`,`=${sumField('fixed_assets_gross',raw)}+${sumField('accumulated_depreciation',raw)}`);
 formula(build,`${col}9`,`=${sumNature('asset',raw)}+${sumNature('contra_asset',raw)}`);
 formula(build,`${col}10`,`=-${sumNature('liability',raw)}`);
 formula(build,`${col}11`,`=-${sumNature('equity',raw)}`);
 formula(build,`${col}12`,col==='B'?'=B21':'=0');
 formula(build,`${col}13`,`=${col}11+${col}12`);
 formula(build,`${col}14`,`=-${sumField('retained_profit',raw)}+${col}12`);
}
formula(build,'B16',`=-${sumField('revenue','L')}`);
formula(build,'B17',`=${sumField('cogs','L')}`);
formula(build,'B18',`=${sumNature('expense','L')}-B17-B22`);
formula(build,'B19',`=-${sumNature('income','L')}-B16`);
formula(build,'B20','=B16-B17-B18+B19');formula(build,'B21','=B20-B22');formula(build,'B22',`=${sumField('income_tax','L')}`);
for(const [row,category] of [[24,'经营'],[25,'投资'],[26,'筹资']]) formula(build,`B${row}`,`=SUMIF('银行流水'!$H$5:$H$${bankEnd},"${category}",'银行流水'!$G$5:$G$${bankEnd})`);
formula(build,'B27','=SUM(B24:B26)');formula(build,'B28',"='参数与复核'!B13");formula(build,'B29','=B28+B27');
formula(build,'B31',`=IF(B16=0,"无法计算",(B6+C6)/2/B16*'参数与复核'!B5)`);
formula(build,'B32','=IF(B16=0,"无法计算",(B16-B17)/B16)');formula(build,'B33','=IF((B13+C13)=0,"无法计算",B21/((B13+C13)/2))');
build.getRange('A4:A43').format.columnWidth=32;build.getRange('B4:C43').format.columnWidth=24;
build.getRange('B5:C29').setNumberFormat(moneyFmt);build.getRange('B31').setNumberFormat('0.0');build.getRange('B32:B33').setNumberFormat('0.0%');
build.getRange('A32:B33').format.font.italic=true;
for(const row of [9,13,20,21,27,29]) build.getRange(`A${row}:C${row}`).format.font.bold=true;

const auditRows=[['资产负债平衡',"='报表计算'!B9-'报表计算'!B10-'报表计算'!B13"],
 ['未分配利润桥接',"='报表计算'!B14-'报表计算'!C14-'报表计算'!B21+B21+B22-B23"],
 ['期末现金与货币资金',"='报表计算'!B29-('报表计算'!B5-B24+B25)"],
 ['净利润与现金流补充资料',"='报表计算'!B21-B14"],
 ['折旧摊销与总账', '=B15-B9'],
 ['所得税费用分解',"='报表计算'!B22-B10-B11"],
 ['源报表控制及试算',`=MAX(ABS(SUM('科目余额表'!E5:E${tbEnd})-SUM('科目余额表'!F5:F${tbEnd})),ABS('报表计算'!B9-B26),ABS('报表计算'!B10-B27),ABS('报表计算'!B16-B28),ABS('报表计算'!B21-B29))`],
 ['期初三项总计与上期',"=MAX(ABS('报表计算'!C9-B6),ABS('报表计算'!C10-B7),ABS('报表计算'!C13-B8))"],
 ['权益与权益变动表',"='报表计算'!B13-B12"]];
for(let i=0;i<auditRows.length;i++){
 const row=i+5;params.getRange(`F${row}`).values=[[auditRows[i][0]]];formula(params,`G${row}`,auditRows[i][1]);
 formula(params,`H${row}`,`=IF(ABS(G${row})<=$B$20,"通过","未通过")`);
}
params.getRange('G5:G13').setNumberFormat('0.00');params.getRange('G5:G13').format.font.color='#172B4D';
params.getRange('H5:H13').conditionalFormats.add('containsText',{text:'未通过',format:{fill:'#FDE9E7',font:{color:'#A61C00',bold:true}}});

const summary=sheets['月结结果'];init(summary,`${manifest.context.company} 月结底稿`,19,'D');summary.tabColor='#243D60';
summary.getRange('A3').values=[[`${manifest.context.period}，CNY，元${manifest.context.demo ? '；虚构样例' : ''}`]];
summary.getRange('A5:B5').values=[['项目','金额或状态']];header(summary,'A5:B5');
const summaryRows=[[6,'资产合计',9],[7,'负债合计',10],[8,'权益合计',13],[9,'营业收入',16],[10,'净利润',21],[11,'经营现金净额',24],[12,'现金净增加额',27]];
for(const [row,label,sourceRow] of summaryRows){summary.getRange(`A${row}`).values=[[label]];formula(summary,`B${row}`,`='报表计算'!B${sourceRow}`);}
summary.getRange('A14').values=[['最终复核']];
formula(summary,'B14',`=IF(OR('参数与复核'!B16="",'参数与复核'!B17=""),"待补复核人或证据","已填记录，需重跑校验")`);
summary.getRange('A16').values=[['底稿内修改会重算公式；修改后应重新运行Python校验并保留新版本。']];
summary.getRange('A4:A19').format.columnWidth=32;summary.getRange('B4:B19').format.columnWidth=32;
summary.getRange('B6:B12').setNumberFormat(moneyFmt);summary.getRange('B6:B14').format.font.color='#172B4D';
summary.getRange('A16:D16').format.rowHeight=32;summary.getRange('A16:D16').format.columnWidth=32;

// Verify values and a meaningful input change in the calculation engine; restore before export.
wb.recalculate();
function cell(sheet,address){return sheets[sheet].getRange(address).values[0][0];}
for(const [address,expected] of [['B9',num(statements.balance.total_assets)],['B13',num(statements.balance.total_equity)],['B21',num(statements.income.net_profit)],['B24',num(statements.cashflow.operating_cash_flow)]])
 if(Math.abs(cell('报表计算',address)-expected)>0.01) throw new Error(`独立计算不一致：${address}`);
const before=cell('报表计算','B24'),original=cell('银行流水','D5');bank.getRange('D5').values=[[original+1000]];wb.recalculate();
if(Math.abs(cell('报表计算','B24')-before-1000)>0.01 || cell('参数与复核','H7')!=='未通过') throw new Error('流水修改未传递至现金流或现金勾稽');
bank.getRange('D5').values=[[original]];params.getRange('B16').values=[['TEST-ONLY']];wb.recalculate();
if(cell('月结结果','B14')!=='待补复核人或证据') throw new Error('复核证据缺失时错误放行');
params.getRange('B16').values=[[null]];wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},maxChars:2000});
if(/#(?:REF!|DIV\/0!|VALUE!|NAME\?|NUM!|NULL!|SPILL!|CALC!)/.test(errors.ndjson)) throw new Error('存在公式错误：'+errors.ndjson);
for(let row=5;row<=13;row++) if(cell('参数与复核',`H${row}`)!=='通过') throw new Error(`导出校验未通过：${row}`);
await fs.mkdir(path.dirname(outputFile),{recursive:true});
const previews=[];
for(const [name,range] of [['月结结果','A1:D19'],['报表计算','A1:C34'],['科目余额表',`A1:N${tbEnd}`],['银行流水',`A1:I${bankEnd}`],['参数与复核','A1:H30']]){
 const image=await wb.render({sheetName:name,range,scale:1,format:'png'});
 const preview=outputFile.replace(/\.xlsx$/i,`-${name}.png`);await fs.writeFile(preview,new Uint8Array(await image.arrayBuffer()));previews.push(preview);
}
await (await SpreadsheetFile.exportXlsx(wb)).save(outputFile);
await fs.writeFile(outputFile.replace(/\.xlsx$/i,'-verification.json'),JSON.stringify({run_id:manifest.run_id,
 calculated_totals:{assets:cell('报表计算','B9'),net_profit:cell('报表计算','B21'),operating_cash:cell('报表计算','B24')},
 input_change_test:'passed',missing_review_test:'passed',checks:9,formula_scan:errors.ndjson,
 xlsx_sha256:crypto.createHash('sha256').update(await fs.readFile(outputFile)).digest('hex'),previews},null,2));
console.log(JSON.stringify({output:outputFile,checks:9,previews},null,2));
