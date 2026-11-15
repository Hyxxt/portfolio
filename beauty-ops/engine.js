(function(root){
'use strict';
const products=[
 {id:'lotion',name:'轻润保湿乳',category:'保湿乳液',size:'50ml',price:129,cost:36,stock:900,keywords:['保湿乳液','轻润肤感','日常护肤'],facts:['50ml','保湿','日常护肤'],current:{exposure:128000,clicks:4608,visitors:4200,buyers:168,paid:21672,refund:1300,ad:6200},previous:{exposure:110000,clicks:4400,visitors:4000,buyers:180,paid:23220,refund:1100,ad:5600}},
 {id:'cleanser',name:'绵密洁面泡沫',category:'洁面泡沫',size:'150ml',price:89,cost:25,stock:650,keywords:['洁面泡沫','绵密泡沫','日常清洁'],facts:['150ml','清洁','泡沫'],current:{exposure:90000,clicks:4050,visitors:3600,buyers:198,paid:17622,refund:700,ad:3500},previous:{exposure:85000,clicks:3400,visitors:3100,buyers:155,paid:13795,refund:800,ad:3200}},
 {id:'cream',name:'柔润保湿面霜',category:'保湿面霜',size:'50g',price:159,cost:48,stock:420,keywords:['保湿面霜','柔润质地','晚间护肤'],facts:['50g','保湿','面霜'],current:{exposure:76000,clicks:2280,visitors:2100,buyers:63,paid:10017,refund:1200,ad:3900},previous:{exposure:70000,clicks:2520,visitors:2300,buyers:92,paid:14628,refund:900,ad:3500}}
];
const ratio=(a,b)=>b>0?a/b:null;
function metrics(d){return {ctr:ratio(d.clicks,d.exposure),cvr:ratio(d.buyers,d.visitors),aov:ratio(d.paid,d.buyers),roas:ratio(d.paid,d.ad),refundRate:ratio(d.refund,d.paid),net:d.paid-d.refund};}
function total(list,period='current'){return list.reduce((a,p)=>{Object.keys(a).forEach(k=>a[k]+=p[period][k]);return a;},{exposure:0,clicks:0,visitors:0,buyers:0,paid:0,refund:0,ad:0});}
function campaign(p,{discount,coupon,orders,budget,refundRate,feeRate,shipping}){
 const values=[discount,coupon,orders,budget,refundRate,feeRate,shipping];
 if(values.some(v=>!Number.isFinite(v))||discount<=0||discount>1||coupon<0||orders<1||!Number.isInteger(orders)||budget<0||refundRate<0||refundRate>1||feeRate<0||feeRate>1||shipping<0)throw Error('请检查输入范围；订单量必须为正整数。');
 const price=Math.round((p.price*discount-coupon)*100)/100;
 if(price<=0)throw Error('优惠后成交价必须大于0。');
 const revenue=price*orders,refund=revenue*refundRate,net=revenue-refund;
 // Conservative scenario: costs and outbound shipping incurred on all placed orders, no returned-goods recovery.
 const variable=p.cost*orders+shipping*orders+net*feeRate;
 const contribution=net-variable-budget;
 const perOrder=price*(1-refundRate)*(1-feeRate)-p.cost-shipping;
 return {price,revenue,refund,net,contribution,margin:ratio(contribution,net),breakeven:perOrder>0?Math.ceil(budget/perOrder):null,stockRisk:orders>p.stock};
}
function review(text){const terms=['根治','治疗','药用','100%','零过敏','全网第一','永久','美白','祛斑'];return terms.filter(w=>text.includes(w));}
function copy(p,tone){const line=tone==='场景型'?'把日常护肤，留给轻松的自己。':'每天的基础护理，从这一瓶开始。';return {title:`澄光 ${p.category} ${p.size} ${p.keywords[1]} ${p.keywords[2]}`,body:`${line}\n${p.name} · ${p.size}\n${p.facts.join(' / ')}\n产品资料为演示设定；实际发布前核对包装、备案与功效依据。`,prompt:`虚构品牌澄光的${p.name}，${p.size}，鼠尾草绿与奶油白配色，柔和自然光，真实包装比例，突出${p.keywords[1]}的视觉感受；画面左侧留标题区。保留产品原始包装信息，不增加未经证实的功效文字。`};}
const api={products,metrics,total,campaign,review,copy};if(typeof module!=='undefined')module.exports=api;root.Beauty=api;
})(typeof window==='undefined'?globalThis:window);
