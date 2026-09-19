const up=document.body.dataset.up,$=s=>document.querySelector(s),
 fmt=n=>'$'+Math.round(n).toLocaleString('es-MX'),
 esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
 norm=s=>s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');
let idx;
const load=()=>idx||(idx=fetch(up+'search.json').then(r=>r.json()).then(d=>(d.forEach(x=>x.s=norm(x.n+' '+x.c)),d)));
const find=q=>{const w=norm(q).split(/\s+/).filter(Boolean);return load().then(d=>w.length?d.filter(x=>w.every(t=>x.s.includes(t))):[])};
const card=x=>{const hot=x.d>=30,deal=x.d>=1;return `<a class="card${hot?' hot':''}" href="${esc(x.l)}" target="_blank" rel="sponsored noopener">`+
 (deal?`<span class="badge${hot?' hot':''}">${hot?'🔥 ':''}-${Math.round(x.d)}%</span>`:'')+
 `<div class="img">${x.i?`<img src="${esc(x.i)}" alt="${esc(x.n)}" loading="lazy">`:''}</div><div class="body"><span class="cat">${esc(x.c.split(',')[0])}</span><h3>${esc(x.n)}</h3>`+
 `<p class="price"><strong>${fmt(x.p)}</strong>${deal?` <s>${fmt(x.t)}</s>`:''} <small>MXN</small></p>`+
 (deal?`<div class="bar"><i style="width:${Math.min(x.d,100)}%"></i></div><p class="save">Ahorras ${fmt(x.t-x.p)}</p>`:'')+
 `<p class="rep">✓ ${esc(x.r)}</p><span class="go">Ver oferta →</span></div></a>`};
// buscador de la barra: sugerencias en vivo; Enter abre buscar/?q=
const q=$('#q'),sug=$('#sug');
q.oninput=()=>find(q.value.trim()).then(r=>{sug.hidden=!r.length;
 sug.innerHTML=r.slice(0,6).map(x=>`<a href="${esc(x.l)}" target="_blank" rel="sponsored noopener"><img src="${esc(x.i)}" alt=""><span>${esc(x.n)}</span><b>${fmt(x.p)}</b></a>`).join('')+
 `<a class="sg-all" href="${up}buscar/?q=${encodeURIComponent(q.value.trim())}">Ver los ${r.length} resultados →</a>`});
addEventListener('click',e=>{if(!e.target.closest('.sb'))sug.hidden=true});
// página de resultados
const res=$('#res');
if(res){const term=new URLSearchParams(location.search).get('q')||'';q.value=term;$('#rq').textContent=term;
 find(term).then(r=>{let n=0;const more=$('#more'),show=()=>{res.insertAdjacentHTML('beforeend',r.slice(n,n+24).map(card).join(''));n+=24;more.hidden=n>=r.length};
  $('#none').hidden=r.length>0;more.onclick=show;show()})}
// flechas de los carruseles
document.querySelectorAll('.rail').forEach(r=>{const f=r.querySelector('.feat');
 r.querySelectorAll('.nv').forEach(b=>b.onclick=()=>f.scrollBy({left:(b.classList.contains('l')?-1:1)*f.clientWidth*.8,behavior:'smooth'}))});
