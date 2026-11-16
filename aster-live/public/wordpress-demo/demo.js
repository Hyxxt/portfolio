const $=s=>document.querySelector(s);const status=s=>$('#status').textContent=s;
const slow=setTimeout(()=>{status('WordPress is taking longer to start. You can use the hosted WordPress preview below, or keep this page open. Edge was verified for this interactive demo.');$('#error').style.display='block';},60000);
try{
 const blueprintText=await fetch('/blueprint.json').then(r=>r.text());
 // Keep the blueprint resources self-contained: its URLs use the canonical
 // Maozi domain. Resolve them to the current origin so preview/deployment
 // domains also load the theme/plugin zips from this copy rather than remotely.
 const blueprint=JSON.parse(blueprintText.split('https://asterprecision-10n3k3ol.maozi.io').join(location.origin));
 const official=new URL('https://playground.wordpress.net/');official.searchParams.set('blueprint-url',location.origin+'/blueprint.json');$('#official').href=official.href;
 const {startPlaygroundWeb}=await import('https://playground.wordpress.net/client/index.js');
 const client=await startPlaygroundWeb({iframe:$('#wp'),remoteUrl:'https://playground.wordpress.net/remote.html',blueprint});
 await client.isReady();
 clearTimeout(slow);$('#error').style.display='none';
 status('WordPress is ready. Native products, technical fields and RFQ inbox are editable. Use fictional data only; this isolated session can reset on reload. No email is sent.');
 document.querySelectorAll('header button').forEach(b=>b.disabled=false);
 $('#front').onclick=()=>client.goTo('/');$('#admin').onclick=()=>client.goTo('/wp-admin/');$('#inbox').onclick=()=>client.goTo('/wp-admin/edit.php?post_type=aster_rfq');
 $('#backup').textContent='Export content';$('#backup').onclick=()=>client.goTo('/wp-admin/export.php');
 const view=new URLSearchParams(location.search).get('view');
 const pending=sessionStorage.getItem('aster-pending-rfq');
 if(view==='rfq'&&pending){
  const payload=JSON.parse(pending);const encoded=btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(payload))));
  const result=await client.run({code:`<?php require '/wordpress/wp-load.php'; $input=json_decode(base64_decode('${encoded}'),true);$r=aster_create_rfq($input);echo wp_json_encode(is_wp_error($r)?array('error'=>$r->get_error_message()):$r);`});
  const r=JSON.parse(result.text);if(r.error)throw new Error(r.error);sessionStorage.removeItem('aster-pending-rfq');$('#receipt').textContent=`Demo RFQ ${r.reference} was validated and saved as a private WordPress record. Open “RFQ inbox” to inspect it. No email was sent.`;$('#receipt').style.display='block';await client.goTo('/wp-admin/edit.php?post_type=aster_rfq');
 }else if(view==='admin')await client.goTo('/wp-admin/');
 else if(view==='rfq')await client.goTo('/request-quote/');
}catch(e){clearTimeout(slow);status('WordPress could not start. The hosted preview and public catalog remain available below.');$('#error').style.display='block';$('#wp').style.display='none';$('#error-message').textContent=e.message||String(e);}
