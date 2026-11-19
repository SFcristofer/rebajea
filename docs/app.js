const up=document.body.dataset.up,$=s=>document.querySelector(s),
 fmt=n=>'$'+Math.round(n).toLocaleString('es-MX'),
 esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
 norm=s=>s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');
let idx;
const load=()=>idx||(idx=fetch(up+'search.json').then(r=>r.json()).then(d=>(d.forEach(x=>(x.s=norm(x.n+' '+x.c),x.sn=norm(x.n),x.sc=norm(x.c))),d)));
// relevancia: el nombre empieza con el término (3) + la categoría lo contiene (2); a igualdad, más ahorro en pesos
const find=q=>{const w=norm(q).split(/\s+/).filter(Boolean);return load().then(d=>w.length?d.filter(x=>w.every(t=>x.s.includes(t))).map(x=>[(x.sn.startsWith(w[0])?3:0)+(x.sc.includes(w[0])?2:0),x]).sort((a,b)=>b[0]-a[0]||(b[1].t-b[1].p)-(a[1].t-a[1].p)).map((a,o)=>(a[1].o=o,a[1])):[])};
const card=x=>{const hot=x.d>=60&&!x.f,deal=x.d>=3,cl=x.f?' flash':hot?' hot':'';return `<div class="card${cl}" data-id="${esc(x.id)}">`+
 (deal?`<span class="badge${cl}">${x.f?'⚡ ':hot?'🔥 ':''}-${Math.round(x.d)}%</span>`:'')+`<button class="fav${favs().includes(x.id)?' on':''}" type="button" aria-label="Guardar en favoritos" data-id="${esc(x.id)}">${favs().includes(x.id)?'♥':'♡'}</button>`+
 `<div class="img">${x.i?`<img src="${esc(x.i)}" alt="${esc(x.n)}" loading="lazy">`:''}</div><div class="body"><span class="cat">${esc(x.c)}</span><h3><a class="st" href="${esc(x.l)}" target="_blank" rel="sponsored noopener">${esc(x.n)}</a></h3>`+
 `<p class="price"><strong>${fmt(x.p)}</strong><small>MXN</small>${deal?` <s>${fmt(x.t)}</s>`:''}</p>`+
 (deal?`<div class="bar"><i style="width:${Math.min(x.d,100)}%"></i></div><p class="save">Ahorras ${fmt(x.t-x.p)}</p>`:'')+
 `<p class="trend">${esc(x.g||'')}</p><p class="rep">✓ ${esc(x.r)}</p>${x.u?`<a class="hl" href="${up}${x.u}">📈 Ver historial de precio</a>`:''}<span class="go">Ver oferta →</span></div></div>`};
// favoritos: ids guardados en este navegador
function favs(){try{return JSON.parse(localStorage.fav||'[]')}catch(e){return[]}}
// buscador de la barra: sugerencias en vivo; Enter abre buscar/?q=
const q=$('#q'),sug=$('#sug');
q.oninput=()=>find(q.value.trim()).then(r=>{sug.hidden=!r.length;
 sug.innerHTML=r.slice(0,6).map(x=>`<a href="${esc(x.l)}" target="_blank" rel="sponsored noopener"><img src="${esc(x.i)}" alt=""><span>${esc(x.n)}</span><b>${fmt(x.p)}</b></a>`).join('')+
 `<a class="sg-all" href="${up}buscar/?q=${encodeURIComponent(q.value.trim())}">Ver los ${r.length} resultados →</a>`});
addEventListener('click',e=>{if(!e.target.closest('.sb'))sug.hidden=true});
// página de resultados: filtro por categoría y orden
const res=$('#res');
if(res){const term=new URLSearchParams(location.search).get('q')||'';q.value=term;$('#rq').textContent=term;
 const SORT={r:(a,b)=>a.o-b.o,d:(a,b)=>b.d-a.d,p:(a,b)=>a.p-b.p,a:(a,b)=>(b.t-b.p)-(a.t-a.p)};
 find(term).then(all=>{let r=all,n=0,cat='';const more=$('#more'),cf=$('#cf'),so=$('#so'),
  show=()=>{res.insertAdjacentHTML('beforeend',r.slice(n,n+24).map(card).join(''));n+=24;more.hidden=n>=r.length},
  draw=()=>{r=all.filter(x=>!cat||x.c===cat).sort(SORT[so.value]);n=0;res.innerHTML='';
   $('#cnt').textContent=r.length+(r.length==1?' resultado':' resultados');show()};
  const cats=Object.entries(all.reduce((m,x)=>(m[x.c]=(m[x.c]||0)+1,m),{})).sort((a,b)=>b[1]-a[1]).slice(0,6);
  if(cats.length>1)cf.innerHTML=[['','Todas']].concat(cats).map(([c,k])=>`<button class="chip${c?'':' on'}" data-c="${esc(c)}">${c?esc(c)+' · '+k:'Todas'}</button>`).join('');
  else $('.tools').hidden=true;
  cf.onclick=e=>{const b=e.target.closest('.chip');if(!b)return;cat=b.dataset.c;cf.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c===b));draw()};
  so.onchange=draw;$('#none').hidden=r.length>0;more.onclick=show;draw()})}
// flechas de los carruseles
document.querySelectorAll('.rail').forEach(r=>{const f=r.querySelector('.feat');
 r.querySelectorAll('.nv').forEach(b=>b.onclick=()=>f.scrollBy({left:(b.classList.contains('l')?-1:1)*f.clientWidth*.8,behavior:'smooth'}))});
// cuenta regresiva a la próxima actualización (status.json lo genera generate_site.py)
(()=>{const u=$('#reloj');if(!u)return;let s,k=0;
 const set=j=>{s={n:new Date(j.next),u:new Date(j.updated)};u.hidden=false;tick()};
 const load=()=>fetch(up+'status.json',{cache:'no-store'}).then(r=>r.json()).then(j=>{sessionStorage.upd=JSON.stringify(j);set(j)}).catch(()=>{});
 const p=n=>String(n).padStart(2,'0');
 const tick=()=>{const d=Math.round((s.n-Date.now())/1e3),m=Math.round((Date.now()-s.u)/6e4);
  if(d<=0){u.className='reloj go';u.innerHTML='<span class="lv"><i></i>EN VIVO</span><span class="tx">Actualizando precios… vuelve en unos minutos</span>';if(++k%60==0)load();return}
  const pc=Math.min(100,Math.max(0,(Date.now()-s.u)/(s.n-s.u)*100));
  u.className='reloj';u.innerHTML='<span class="lv"><i></i>EN VIVO</span><span class="tx">Próxima actualización de precios en</span>'+
   '<span class="dg"><b>'+p(Math.floor(d/3600))+'</b><em>:</em><b>'+p(Math.floor(d%3600/60))+'</b><em>:</em><b>'+p(d%60)+'</b></span>'+
   '<span class="ag">Actualizado hace '+(m<60?m+' min':Math.floor(m/60)+' h')+'</span><div class="pg"><u style="width:'+pc+'%"></u></div>'};
 try{set(JSON.parse(sessionStorage.upd))}catch(e){}
 load();setInterval(()=>s&&tick(),1e3)})();
(()=>{const f=()=>document.querySelectorAll('.ago[data-t]').forEach(e=>{const m=Math.max(0,(Date.now()-Date.parse(e.dataset.t))/6e4|0);
 e.textContent='Detectado hace '+(m<60?m+' min':m<1440?(m/60|0)+' h':(m/1440|0)+(m<2880?' día':' días'))});f();setInterval(f,6e4)})();
const markFav=()=>{const f=favs();document.querySelectorAll('.fav').forEach(b=>{const on=f.includes(b.dataset.id);b.classList.toggle('on',on);b.textContent=on?'♥':'♡';b.setAttribute('aria-pressed',on)})};
markFav();
document.addEventListener('click',e=>{const b=e.target.closest('.fav');if(!b)return;e.preventDefault();e.stopPropagation();
 let f=favs();const id=b.dataset.id;f=f.includes(id)?f.filter(x=>x!==id):[id].concat(f);localStorage.fav=JSON.stringify(f);markFav();drawFav()},true);
const fl=$('#fav');
function drawFav(){if(!fl)return;const f=favs();load().then(d=>{const m=new Map(d.map(x=>[x.id,x])),r=f.map(id=>m.get(id)).filter(Boolean);
 fl.innerHTML=r.map(card).join('');$('#fnone').hidden=r.length>0})}
drawFav();
// filtros reales sobre la lista completa (no solo la página actual)
(()=>{const t=$('.flt'),lst=$('#lst');if(!t||!lst)return;const k=t.dataset.k,mx=+t.dataset.m||0,orig=lst.innerHTML,more=$('#fmore'),pgr=$('#pgr'),
 fp=$('#fp'),fd=$('#fd'),ff=$('#ff'),fo=$('#fo'),fc=$('#fc');let r=[],n=0;
 const inK=x=>k==='ofertas'?x.d>=3:k==='relampago'?x.f&&x.d>=3:k.startsWith('c:')?x.c===k.slice(2):(x.k||[]).includes(k);
 const S={p:(a,b)=>a.p-b.p,d:(a,b)=>b.d-a.d,a:(a,b)=>(b.t-b.p)-(a.t-a.p)};
 const show=()=>{lst.insertAdjacentHTML('beforeend',r.slice(n,n+24).map(card).join(''));n+=24;more.hidden=n>=r.length};
 const run=()=>{const p=+fp.value||0,d=+fd.value||0,f=ff.checked,o=fo.value;
  if(!p&&!d&&!f&&!o){lst.innerHTML=orig;more.hidden=true;pgr.hidden=false;fc.textContent='';markFav();return}
  load().then(all=>{r=all.filter(x=>inK(x)&&(!mx||x.p<mx)&&(!p||x.p<=p)&&x.d>=d&&(!f||x.f));if(o)r.sort(S[o]);
   n=0;lst.innerHTML='';pgr.hidden=true;fc.textContent=r.length+(r.length==1?' producto':' productos');show()})};
 [fp,fd,ff,fo].forEach(e=>e.onchange=run);more.onclick=show})();
