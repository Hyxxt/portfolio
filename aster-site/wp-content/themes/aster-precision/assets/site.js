(()=>{
 const $=s=>document.querySelector(s);const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let shortlist=[];try{const x=JSON.parse(localStorage.getItem('aster-shortlist')||'[]');if(Array.isArray(x))shortlist=x.filter(p=>p&&typeof p.sku==='string'&&typeof p.name==='string').slice(0,10);}catch{}
 function toast(s){const el=$('#toast');if(!el)return;el.textContent=s;el.classList.add('show');clearTimeout(window.asterToast);window.asterToast=setTimeout(()=>el.classList.remove('show'),3500);}
 function update(){document.querySelectorAll('.shortlist-count').forEach(e=>e.textContent=shortlist.length);if($('#shortlist-items')){$('#shortlist-items').innerHTML=shortlist.length?shortlist.map((p,i)=>`<div class="shortlist-row"><div>${esc(p.name)}<small>${esc(p.sku)}</small></div><button data-remove="${i}" aria-label="Remove ${esc(p.name)}">Remove ×</button></div>`).join(''):'<p class="shortlist-empty">No components selected yet.<br>Browse the catalog to add a starting point.</p>';document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{shortlist.splice(Number(b.dataset.remove),1);persist();});}if($('#form-shortlist'))$('#form-shortlist').innerHTML=shortlist.length?shortlist.map(p=>`<div class="shortlist-form-row"><span>${esc(p.name)}</span><small>${esc(p.sku)}</small></div>`).join('')+'<p class="shortlist-form-note">Concept references only. Describe your own drawing requirements below.</p>':'<p class="shortlist-form-note">A custom part? No shortlist needed. Describe the requirements below.</p>';if($('#rfq-items'))$('#rfq-items').value=JSON.stringify(shortlist.map(p=>({sku:p.sku})));}
 function persist(){try{localStorage.setItem('aster-shortlist',JSON.stringify(shortlist));}catch{toast('Browser storage unavailable. Keep this page open while preparing your RFQ.');}update();}
 document.querySelectorAll('.add-rfq').forEach(b=>b.onclick=()=>{if(shortlist.some(p=>p.sku===b.dataset.sku)){toast('This component is already in your RFQ shortlist.');return;}if(shortlist.length>=10){toast('Your shortlist can contain up to 10 components.');return;}shortlist.push({sku:b.dataset.sku,name:b.dataset.name});persist();toast('Added to your RFQ shortlist.');});
 document.querySelectorAll('.shortlist-toggle').forEach(b=>b.onclick=()=>$('#shortlist-dialog').showModal());if($('.close-dialog'))$('.close-dialog').onclick=()=>$('#shortlist-dialog').close();if($('.menu-toggle'))$('.menu-toggle').onclick=()=>{const open=$('#main-nav').classList.toggle('open');$('.menu-toggle').setAttribute('aria-expanded',String(open));};
 let family='all',query='';function filter(){let count=0;document.querySelectorAll('#catalog-grid .product-card').forEach(card=>{const show=(family==='all'||card.dataset.family===family)&&card.dataset.search.includes(query);card.hidden=!show;if(show)count++;});if($('#result-count'))$('#result-count').textContent=`${count} illustrative component${count===1?'':'s'}`;if($('#empty-catalog'))$('#empty-catalog').hidden=count>0;}
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{family=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b));});filter();});if($('#catalog-search'))$('#catalog-search').oninput=e=>{query=e.target.value.trim().toLowerCase();filter();};
 const API_BASE=(document.querySelector('meta[name="aster-api-base"]')?.content||'').replace(/\/$/,'');
 if(document.querySelector('meta[name="aster-static-preview"]')){
  document.querySelectorAll('[data-wp-demo]').forEach(a=>{a.href='/wordpress-demo/?view=admin';a.textContent='WordPress live demo ↗';});
  const form=$('#rfq-form');
  if(form)form.addEventListener('submit',async e=>{
   e.preventDefault();
   if(!form.reportValidity())return;
   const f=new FormData(form);
   const payload={};
   for(const k of ['name','email','company','country','quantity','message','website','items'])payload[k]=String(f.get(k)||'');
   payload.consent=f.get('consent')==='1';
   try{payload.items=JSON.parse(payload.items||'[]');}catch{payload.items=[];}
   const btn=form.querySelector('button[type="submit"]');
   const original=btn?btn.innerHTML:'';
   if(btn){btn.disabled=true;btn.textContent='Submitting…';}
   const old=form.querySelector('.rfq-result');if(old)old.remove();
   try{
    const r=await fetch((API_BASE||'')+'/api/rfq',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(90000)});
    const data=await r.json().catch(()=>({}));
    if(!r.ok){const msg=data.errors?Object.values(data.errors).join(' '):(data.message||'Submission failed.');throw new Error(msg);}
    const box=document.createElement('div');box.className='rfq-result';box.setAttribute('role','status');
    const strong=document.createElement('strong');strong.textContent='Demo RFQ saved';
    const p=document.createElement('p');p.textContent=`Reference: ${data.reference}. The site owner can review it in the demo admin dashboard. No real quotation or supplier response will follow.`;
    box.append(strong,p);form.append(box);
    form.reset();
    try{localStorage.removeItem('aster-shortlist');}catch{}
    shortlist=[];persist();
    box.scrollIntoView({behavior:'smooth',block:'center'});
   }catch(err){
    const box=document.createElement('div');box.className='rfq-result error';box.setAttribute('role','alert');box.textContent='Could not submit: '+err.message;form.append(box);
   }finally{
    if(btn){btn.disabled=false;btn.innerHTML=original;}
   }
  });
 }
 update();
})();
