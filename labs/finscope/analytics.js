export const fields=['company','industry','year','quarter','revenue','net_profit','operating_cash_flow','assets','liabilities'];
export function parseCSV(text){
 const rows=[];let row=[],field='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===','&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(x=>x.trim()))rows.push(row);row=[];field='';}else field+=c;}
 if(quoted)throw new Error('CSV 引号未闭合');if(field||row.length){row.push(field);rows.push(row);}if(rows.length<2)throw new Error('CSV 至少需要表头和一行数据');
 const header=rows.shift().map(s=>s.replace(/^\uFEFF/,'').trim());if(fields.some(f=>!header.includes(f)))throw new Error('缺少必要列：'+fields.filter(f=>!header.includes(f)).join(', '));
 const data=rows.map((row,i)=>{if(row.length!==header.length)throw new Error(`第 ${i+2} 行列数与表头不一致`);const d=Object.fromEntries(fields.map(f=>[f,row[header.indexOf(f)].trim()]));
  if(!d.company||!d.industry)throw new Error(`第 ${i+2} 行缺少公司或行业`);
  for(const f of fields.slice(2)){if(d[f]===''||!Number.isFinite(Number(d[f])))throw new Error(`第 ${i+2} 行 ${f} 不是有效数值`);d[f]=Number(d[f]);}
  if(!Number.isInteger(d.year)||d.year<1900||d.year>2200||![1,2,3,4].includes(d.quarter)||d.revenue<=0||d.assets<=0||d.liabilities<0)throw new Error(`第 ${i+2} 行年份、季度或金额不符合口径`);return d;
 });const keys=data.map(d=>`${d.company}|${d.year}|${d.quarter}`);if(new Set(keys).size!==keys.length)throw new Error('存在重复的公司 / 年份 / 季度');return data;
}
export function summarize(rows){
 const sum=k=>rows.reduce((a,d)=>a+d[k],0);const last=new Map();for(const d of rows){const old=last.get(d.company);if(!old||d.year*4+d.quarter>old.year*4+old.quarter)last.set(d.company,d);}
 const balance=[...last.values()];const assets=balance.reduce((a,d)=>a+d.assets,0),liabilities=balance.reduce((a,d)=>a+d.liabilities,0);
 const revenue=sum('revenue'),profit=sum('net_profit'),cash=sum('operating_cash_flow');
 return {revenue,profit,cash,margin:revenue?profit/revenue:null,cashRatio:profit>0?cash/profit:null,gap:profit-cash,debt:assets?liabilities/assets:null,count:new Set(rows.map(d=>d.company)).size};
}
export function companySummary(rows){return [...new Set(rows.map(d=>d.company))].map(company=>{const r=rows.filter(d=>d.company===company);return {company,industry:r[0].industry,...summarize(r)};}).sort((a,b)=>b.revenue-a.revenue);}
export function csv(rows){return fields.join(',')+'\n'+rows.map(d=>fields.map(f=>'"'+String(d[f]).replace(/"/g,'""')+'"').join(',')).join('\n');}
