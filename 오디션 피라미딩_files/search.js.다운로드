/* 사이트 안 검색 — 원본은 scripts/build_search_index.py 의 JS 문자열이다. 여기를 고치지 않는다(다음 회차에 덮인다).
   찾는 범위: 아카이브와 원자료 화면. 색인(search-index.json)은 검색 창을 처음 열 때 한 번 받는다.
   검색어는 브라우저 밖으로 나가지 않는다. */
(function(){
  if(window.__srch) return; window.__srch=1;
  var IDX=null, loading=null, cur=-1, items=[];
  function nf(s){return (s||'').normalize('NFC').toLowerCase();}
  function esc(s){return s.replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function load(){
    if(IDX) return Promise.resolve(IDX);
    if(loading) return loading;
    loading=fetch('search-index.json',{cache:'no-cache'}).then(function(r){if(!r.ok) throw r.status; return r.json();}).then(function(d){
      d.p.forEach(function(p){p.s.forEach(function(x){x.n=nf(x[1]+' '+x[2]); x.z=x.n.replace(/\s+/g,'');}); p.n=nf(p.t+' '+p.m); p.z=p.n.replace(/\s+/g,'');});
      IDX=d; return d;});
    return loading;
  }
  var bg=document.createElement('div'); bg.className='srch-bg';
  var box=document.createElement('div'); box.className='srch-box'; box.setAttribute('role','dialog'); box.setAttribute('aria-label','아카이브·원자료 검색');
  box.innerHTML='<div class="srch-top"><input class="srch-in" type="search" placeholder="아카이브·원자료에서 찾기 — 예: 하이일드 OAS" aria-label="검색어" autocomplete="off"><button class="srch-x" type="button">닫기</button></div>'+
    '<div class="srch-meta" aria-live="polite"></div><ul class="srch-r"></ul>';
  document.body.appendChild(bg); document.body.appendChild(box);
  var inp=box.querySelector('.srch-in'), meta=box.querySelector('.srch-meta'), ul=box.querySelector('.srch-r');
  function open(){bg.classList.add('on'); box.classList.add('on'); inp.focus(); inp.select(); last=null;
    meta.textContent=IDX?'':'색인을 받는 중…'; load().then(function(){if(!inp.value) meta.textContent='아카이브 '+IDX.na+'편 · 원자료 '+IDX.nd+'장에서 찾는다'; else run();}).catch(function(){meta.textContent='색인을 받지 못했다. 잠시 뒤 다시 열어 보십시오.';});}
  function close(){bg.classList.remove('on'); box.classList.remove('on');}
  function hit(n,z,t){return n.indexOf(t)>=0||z.indexOf(t.replace(/\s+/g,''))>=0;}
  function snip(raw,terms){
    var low=nf(raw), at=-1, len=0;
    for(var i=0;i<terms.length;i++){var k=low.indexOf(terms[i]); if(k>=0&&(at<0||k<at)){at=k;len=terms[i].length;}}
    var a=Math.max(0,at-40), b=Math.min(raw.length,(at<0?0:at)+len+90);
    var s=(a>0?'…':'')+raw.slice(a,b)+(b<raw.length?'…':'');
    return mark(s,terms);
  }
  function mark(s,terms){
    var e=esc(s);
    terms.forEach(function(t){ if(t.length<1) return; var re=new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'); e=e.replace(re,function(m){return '<mark>'+m+'</mark>';}); });
    return e;
  }
  function run(){
    var q=nf(inp.value).trim(); ul.innerHTML=''; cur=-1; items=[];
    if(!IDX) return; if(!q){meta.textContent='아카이브 '+IDX.na+'편 · 원자료 '+IDX.nd+'장에서 찾는다'; return;}
    var terms=q.split(/\s+/).filter(Boolean), res=[];
    IDX.p.forEach(function(p,pi){
      var best=null;
      p.s.forEach(function(x,si){
        var ok=terms.every(function(t){return hit(x.n+' '+p.n, x.z+p.z, t);});
        if(!ok) return;
        var sc=0; terms.forEach(function(t){ if(hit(p.n,p.z,t)) sc+=8; if(hit(nf(x[1]),nf(x[1]).replace(/\s+/g,''),t)) sc+=5; var c=x.n.split(t).length-1; sc+=Math.min(c,6); });
        if(p.k==='아카이브') sc+=1;
        res.push({p:p,x:x,sc:sc,pi:pi});
      });
    });
    res.sort(function(a,b){return b.sc-a.sc||a.pi-b.pi;});
    var per={}, out=[];
    res.forEach(function(r){var k=r.p.f; per[k]=(per[k]||0)+1; if(per[k]<=3&&out.length<40) out.push(r);});
    var np=Object.keys(per).length;
    meta.textContent=out.length?('글 '+np+'편 · 절 '+res.length+'곳'+(res.length>out.length?' · 위에서 '+out.length+'곳만 보인다':'')):'찾지 못했다. 낱말을 줄이거나 띄어쓰기를 바꿔 보십시오.';
    out.forEach(function(r){
      var li=document.createElement('li'), a=document.createElement('a');
      a.href=r.p.f+(r.x[0]?'#'+encodeURIComponent(r.x[0]):'');
      var head=(r.x[0]&&r.x[1]!==r.p.t)?'<div class="srch-h">'+mark(r.x[1],terms)+'</div>':'';
      a.innerHTML='<div class="srch-t"><span class="srch-k">'+r.p.k+'</span>'+mark(r.p.m,terms)+'</div>'+head+'<div class="srch-s">'+snip(r.x[2],terms)+'</div>';
      a.addEventListener('click',function(){var h=a.getAttribute('href'); if(h.split('#')[0]===location.pathname.split('/').pop()){close();}});
      li.appendChild(a); ul.appendChild(li); items.push(a);
    });
  }
  var tm=null, last=null;
  function later(){clearTimeout(tm); tm=setTimeout(function(){ if(inp.value===last&&IDX) return; load().then(function(){last=inp.value; run();}); },120);}
  /* 한글 입력기는 조합 중에 input 을 늦게 내거나 건너뛰는 브라우저가 있다 — 조합 끝·키 뗌에서도 다시 찾는다 */
  inp.addEventListener('input',later); inp.addEventListener('compositionend',later); inp.addEventListener('keyup',function(e){ if(e.key!=='ArrowDown'&&e.key!=='ArrowUp'&&e.key!=='Enter') later(); });
  inp.addEventListener('keydown',function(e){
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){ if(!items.length) return; e.preventDefault();
      if(cur>=0) items[cur].classList.remove('cur'); cur=(cur+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;
      items[cur].classList.add('cur'); items[cur].scrollIntoView({block:'nearest'}); }
    else if(e.key==='Enter'){ var a=items[cur>=0?cur:0]; if(a){e.preventDefault(); if(a.getAttribute('href').split('#')[0]===location.pathname.split('/').pop()) close(); location.href=a.href;} }
  });
  box.querySelector('.srch-x').addEventListener('click',close); bg.addEventListener('click',close);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&box.classList.contains('on')){close(); return;}
    var t=e.target, typing=t&&(t.tagName==='INPUT'||t.tagName==='TEXTAREA'||t.isContentEditable);
    if(!typing&&(e.key==='/'||((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'))){e.preventDefault(); open();}
  });
  /* 우하단 돋보기와 상단 메뉴 «검색»(rebuild_nav 가 심는다) 둘 다 같은 창을 연다 */
  document.querySelectorAll('.srch-btn, .srch-nav').forEach(function(b){b.addEventListener('click',function(e){e.preventDefault(); open();});});
  if(location.hash==='#search'){ history.replaceState(null,'',location.pathname+location.search); open(); }
  inp.addEventListener('focus',function(){load();},{once:true});
})();
