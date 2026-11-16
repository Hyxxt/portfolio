export function check(answer,groups,forbidden=[]){
 const normal=String(answer).toLowerCase().replace(/\s+/g,'');
 const tests=groups.map(group=>({alternatives:group,matched:group.some(s=>normal.includes(s.toLowerCase().replace(/\s+/g,'')))}));
 const violations=forbidden.filter(s=>normal.includes(s.toLowerCase().replace(/\s+/g,'')));
 return {tests,coverage:tests.length?tests.filter(x=>x.matched).length/tests.length:null,violations,pass:tests.length>0&&tests.every(x=>x.matched)&&!violations.length};
}
export function validateCases(data){
 if(!Array.isArray(data)||data.length===0||data.length>200)throw new Error('需要 1–200 条用例组成的 JSON 数组');
 return data.map((c,i)=>{
  if(!c.id||typeof c.question!=='string'||typeof c.answerA!=='string'||typeof c.answerB!=='string'||!Array.isArray(c.groups)||!c.groups.length||!c.groups.every(g=>Array.isArray(g)&&g.length&&g.every(s=>typeof s==='string'&&s.trim())))throw new Error(`第 ${i+1} 条用例结构不完整`);
  if(c.forbidden&&!Array.isArray(c.forbidden))throw new Error('forbidden 必须为字符串数组');if(c.forbidden&&!c.forbidden.every(s=>typeof s==='string'))throw new Error('forbidden 必须为字符串数组');return {...c,id:String(c.id),category:String(c.category||'自定义'),groups:c.groups,forbidden:c.forbidden||[]};
 });
}
export function aggregate(cases){return ['A','B'].map(v=>{const r=cases.map(c=>check(c['answer'+v],c.groups,c.forbidden));return {variant:v,count:r.length,passed:r.filter(x=>x.pass).length,coverage:r.length?r.reduce((a,c)=>a+(c.coverage??0),0)/r.length:0,violationCount:r.reduce((a,c)=>a+c.violations.length,0)};});}
